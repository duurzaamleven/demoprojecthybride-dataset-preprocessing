# SPDX-License-Identifier: EUPL-1.2
"""Cumulatieve tellers differentiëren naar intervalgemiddeld vermogen (ontwerp-preprocessing.md §2.2,
correctie in ontwerp-intervalsemantiek.md §2).

De momentane kolommen (``p_thermal_system``, ``heatpump_power``, ``boiler_power``, de DSMR-
vermogens) zijn steekproeven op één moment; ze middelen tot een kwartiergemiddelde is fysisch
onjuist (§2.2). Wat wél klopt: de cumulatieve tellers (``e_consumed_*``/``e_delivered_*``,
``v_gas_consumed``, ``heatpump_energy``, ``boiler_energy``, ``e_thermal_system``) differentiëren
over het ECHTE interval tussen twee opeenvolgende aflezingen VAN DEZELFDE WONING. "Het echte
interval" is essentieel: een ontbrekend kwartier (§5, ``ontbrekend__bool``) betekent dat de
volgende teller-aflezing een langere periode overspant dan 15 minuten, en die langere periode moet
in de deler terechtkomen -- 900 s aannemen zou het vermogen daar stelselmatig laten overschatten.

**Voorwaarts, niet achterwaarts (ontwerp-intervalsemantiek.md §2).** De waarde op rij *Q* beschrijft
per contract het interval ``[tijdstip_start(Q), tijdstip_start(Q) + 900 s)`` -- dus wat er gebeurt
NA dit kwartier-begin, niet ervoor. Het vermogen op rij *Q* is daarom ``teller(Q+1) - teller(Q)``,
gedeeld door de werkelijke tijd tot die VOLGENDE aflezing. Een achterwaarts verschil
(``teller(Q) - teller(Q-1)``) zou een waarde uit het VORIGE interval onder de naam van dit interval
wegschrijven -- precies de trapeziumtoets in ontwerp-intervalsemantiek.md §2 die dit aan het licht
bracht (vijftien van de vijftien vergelijkingen per woning wezen dezelfde kant op). Gevolg: de
LAATSTE rij van elke woning krijgt NaN (er is geen volgende aflezing om het interval mee af te
sluiten), niet de eerste.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: kWh -> J. Zelfde constante als IM3's ``im3_preprocessing.intervals.J_PER_KWH``.
J_PER_KWH = 3_600_000.0
#: GJ -> J (variable-dictionary.md: e_thermal_system ×10^9).
GJ_NAAR_J = 1e9

#: De vijf sentinelwaarden van het DSMR-initialisatietelegram (ontwerp-teller-artefacten.md §2/§3).
#:
#: **Herkomst: eerste rij van ``dsmr.csv`` in ``data/raw/dph-dataset.zip``, woning ``-ORiFQC6``,
#: 2022-02-07T11:10:58.** Dat is de plek waar deze vijf waarden voor het eerst zijn afgelezen; die
#: rij heeft ook ``u_L1=u_L2=u_L3=0,0 V`` bij ``i_L1=i_L2=i_L3=4 A`` (fysisch onmogelijk, vier
#: ampère bij nul volt), wat bevestigt dat dit een initialisatietelegram is en geen meting.
#:
#: Alle vijf registers moeten TEGELIJK op deze waarde staan om als sentinel te gelden (de strikte
#: handtekening, §4.1): één register alleen is geen bewijs (§3, §9 -- twee echte metingen,
#: ``df79ygat`` en ``A0JoUuz-``, lopen toevallig door 8969,994 kWh heen op ``e_import_laag_cum__kWh``
#: met de andere vier registers op heldere, onderling verschillende waarden). Gemeten op de
#: volledige ``dsmr.csv`` (7.866.691 rijen, 174 woningen): de strikte handtekening geeft 1896 rijen,
#: 167 woningen, 0 vals-positieven.
INITIALISATIETELEGRAM_SENTINEL: dict[str, float] = {
    "e_import_laag_cum__kWh": 8969.994,
    "e_import_hoog_cum__kWh": 8789.167,
    "e_export_laag_cum__kWh": 3433.300,
    "e_export_hoog_cum__kWh": 8299.146,
    "g_gebruik_cum__m3": 5059.199,
}

#: Boven deze stand geldt een teller als "ooit echt gelopen" (ontwerp-preprocessing-minuut.md §5).
#: Dat onderscheidt een foutieve uitlezing van exact 0,0 van een teruglevertelller die legitiem op
#: 0 blijft staan. Gedeeld door het minuutpad en het kwartierpad -- zie de docstring van
#: :func:`markeer_nulmetingen`.
TELLER_ONTWAAKT_BOVEN = 1.0


def is_initialisatietelegram(measurements: pd.DataFrame) -> pd.Series:
    """True waar ALLE VIJF sentinelregisters van :data:`INITIALISATIETELEGRAM_SENTINEL` TEGELIJK op
    hun sentinelwaarde staan (ontwerp §3/§4.1): de handtekening van een DSMR-initialisatietelegram,
    niet van een echte meting, op elke positie in de reeks (niet alleen de eerste rij -- ``OMa7vZ0x``
    en ``uQLTOCT9`` laten zien dat hij ook middenin de reeks kan staan en kan terugkeren).

    ``measurements`` moet de vijf kolommen van :data:`INITIALISATIETELEGRAM_SENTINEL` bevatten.
    Exacte gelijkheid (geen tolerantie): op de volledige ``dsmr.csv`` geeft dat precies de 1896
    rijen/167 woningen uit §3 -- de vijf waarden komen letterlijk, ongewijzigd uit de bron
    (``bron.py``/``tabellen.py`` zijn doorgeefluiken, ze ronden niet af).
    """
    handtekening = pd.Series(True, index=measurements.index)
    for kolom, waarde in INITIALISATIETELEGRAM_SENTINEL.items():
        handtekening &= measurements[kolom] == waarde
    return handtekening.fillna(False)

# Fysische bovengrenzen op het intervalgemiddelde vermogen (W), voor teller_sprong__bool (ontwerp
# §5: "een sprong die fysisch onmogelijk is binnen één kwartier").
#
# **Gekozen op de gemeten verdeling** (analyse B7, ontwerp §8, gemeten 05-09-2026 over 174
# woningen). Een drempel moet het fysisch onmogelijke vangen, niet alleen het absurde (megawatts).
# Per teller de mediane p99,99 van het intervalgemiddelde vermogen, naast de drempel:
#
#   teller             mediane p99,99   p99,99 bij de 99e-percentielwoning   drempel
#   e_net__W                  6,5 kW                            20,4 kW       40 kW
#   g_gebruik__W             27,9 kW                           466   MW      100 kW
#   p_warmtepomp__W           1,6 kW                             3,7 kW       10 kW
#   p_ketel__W               56    W                           138,8 kW        1 kW
#   q_geleverd__W            12,1 kW                            31,5 kW       50 kW
#
# De gascijfers zijn berekend met de werkelijke calorische waarde per uur (gaskwaliteit.py).
#
# Per teller de fysische onderbouwing:
SPRONG_DREMPEL__W: dict[str, float] = {
    # 40 kW ligt boven elke huishoudelijke aansluiting: 3x25 A geeft 17,25 kW, 3x35 A 24 kW,
    # 3x50 A 34 kW. De 99e-percentielwoning haalt 20,4 kW, dus er is ruimte zonder valse alarmen.
    "e_net__W": 40_000.0,
    # ~10 m3/h bij de calorische waarden die in deze dataset voorkomen (35,4-36,0 MJ/m3). Een
    # G6-huisaansluiting laat ongeveer 6 m3/h door (~60 kW), dus dit is ruim maar niet absurd; de
    # mediane woning komt niet boven 27,9 kW.
    "g_gebruik__W": 100_000.0,
    # Geen enkele gezonde woning komt boven 3,7 kW: dit zijn hybride warmtepompen voor een
    # woning, geen industriële units. 10 kW houdt een factor 2,7 marge op de zwaarste woning.
    "p_warmtepomp__W": 10_000.0,
    # Dit is het ELEKTRISCHE verbruik van de ketel -- pomp, ventilator, regeling -- niet het gas.
    # De mediane woning komt niet boven 56 W; een drempel van 10 kW zou daar bijna tweehonderd keer
    # boven liggen en niets vangen. 1 kW is ruim vijf keer het maximum van een gezonde ketel.
    "p_ketel__W": 1_000.0,
    # Warmteafgifte van een hybride opstelling, ketel meegerekend. De 99e-percentielwoning haalt
    # 31,5 kW; 50 kW laat die ruimte en vangt de rest.
    "q_geleverd__W": 50_000.0,
}


def differentieer_teller(
    waarde: pd.Series,
    tijdstip_start: pd.Series,
    home_id: pd.Series,
    eenheid_naar_J: float | pd.Series = 1.0,
) -> pd.DataFrame:
    """Differentieer één cumulatieve teller naar intervalgemiddeld vermogen (W), per woning.

    De drie reeksen moeten dezelfde index delen; volgorde maakt niet uit, deze functie sorteert
    zelf op (``home_id``, ``tijdstip_start``) vóór het differentiëren en zet het resultaat terug
    in de oorspronkelijke volgorde.

    ``eenheid_naar_J`` mag een **Series op dezelfde index** zijn in plaats van een constante, voor
    een teller waarvan de omrekenfactor zelf per rij verschilt. Dat is er precies één: gas, waar de
    calorische waarde per uur wordt gepubliceerd (:mod:`dph_preprocessing.gaskwaliteit`). De factor
    wordt dan uitgelijnd op de gesorteerde volgorde en hoort bij de rij waar het interval BEGINT,
    net als ``delta`` en ``delta_t__s`` zelf.

    Retourneert een DataFrame (zelfde index als ``waarde``) met, VOORWAARTS bepaald (module-
    docstring, ontwerp-intervalsemantiek.md §2) zodat rij *Q* het interval
    ``[tijdstip_start(Q), tijdstip_start(Q) + 900 s)`` beschrijft:

    - ``delta``: het verschil met de VOLGENDE aflezing VAN DEZELFDE WONING, in de eenheid van
      ``waarde`` (``teller(Q+1) - teller(Q)``).
    - ``delta_t__s``: de WERKELIJKE tijd tot die volgende aflezing (kan > 900 s zijn bij een
      ontbrekend kwartier), niet aangenomen.
    - ``vermogen__W``: ``delta * eenheid_naar_J / delta_t__s``.

    De LAATSTE rij van elke woning krijgt overal NaN: er is geen volgende teller om het interval
    mee af te sluiten, en dat is geen 0 (ontwerp §3: nul is een waarde, geen ontbrekende).
    """
    werk = pd.DataFrame(
        {"home_id__str": home_id.to_numpy(), "waarde": waarde.to_numpy(), "tijdstip_start": tijdstip_start.to_numpy()},
        index=waarde.index,
    )
    volgorde = werk.sort_values(["home_id__str", "tijdstip_start"]).index
    gesorteerd = werk.loc[volgorde]

    grouped = gesorteerd.groupby("home_id__str", sort=False)
    # shift(-1) i.p.v. diff(): de waarde/tijd van de VOLGENDE rij binnen dezelfde groep, dus
    # delta/delta_t__s horen bij het interval [tijdstip_start(Q), volgende tijdstip_start). Een
    # groupby-shift respecteert groepsgrenzen vanzelf: de laatste rij van elke woning krijgt NaN.
    volgende_waarde = grouped["waarde"].shift(-1)
    volgende_tijd = grouped["tijdstip_start"].shift(-1)
    delta = volgende_waarde - gesorteerd["waarde"]
    delta_t_s = (volgende_tijd - gesorteerd["tijdstip_start"]).dt.total_seconds()
    # Bij een per-rij factor expliciet herindexeren op de gesorteerde volgorde. Pandas zou hier
    # vanzelf op index uitlijnen (delta's index is een permutatie van de oorspronkelijke), maar
    # expliciet is het één regel en dan hangt de uitkomst niet aan dat gedrag.
    factor = eenheid_naar_J.reindex(volgorde) if isinstance(eenheid_naar_J, pd.Series) else eenheid_naar_J
    vermogen = ((delta * factor) / delta_t_s).astype("float32")

    resultaat = pd.DataFrame({"delta": delta, "delta_t__s": delta_t_s, "vermogen__W": vermogen})
    return resultaat.reindex(waarde.index)


def teller_terug_masker(delta: pd.Series) -> pd.Series:
    """True waar een teller daalt (ontwerp §5: meteruitval of -vervanging).

    Nullable ``boolean``: bij de eerste rij van een woning (of een teller die zelf ontbreekt) is
    "is dit teruggelopen" niet te beantwoorden, en dat is ``pd.NA``, niet automatisch False.
    """
    return (delta < 0).astype("boolean").mask(delta.isna())


def teller_gestegen_masker(delta: pd.Series) -> pd.Series:
    """True waar een teller STIJGT (positieve delta) in dit interval.

    Bestaat specifiek voor ``teruglevering__bool`` (ontwerp §5/§8 B3): een stijging van een
    EXPORTteller in een kwartier betekent dat er toen zonnestroom is teruggeleverd. Zelfde
    nullable-``boolean``-behandeling als :func:`teller_terug_masker`.
    """
    return (delta > 0).astype("boolean").mask(delta.isna())


def teller_sprong_masker(vermogen__W: pd.Series, drempel__W: float) -> pd.Series:
    """True waar het intervalgemiddelde vermogen boven ``drempel__W`` ligt (ontwerp §5).

    Zelfde nullable-``boolean``-behandeling als :func:`teller_terug_masker`.
    """
    return (vermogen__W.abs() > drempel__W).astype("boolean").mask(vermogen__W.isna())


def markeer_nulmetingen(
    stand: pd.Series,
    home_id: pd.Series | None = None,
    tijdstip_start: pd.Series | None = None,
) -> pd.Series:
    """True waar de stand exact 0,0 is terwijl deze teller EERDER al boven
    :data:`TELLER_ONTWAAKT_BOVEN` stond (lopend maximum, geshift met 1 zodat de rij zelf niet
    meetelt) -- ontwerp-teller-artefacten.md §4.2, "uitval met herstel".

    **Gedeeld door het minuutpad** (``minuut.py``, ontwerp-preprocessing-minuut.md §5) **en het
    kwartierpad**, zodat er geen twee losse implementaties zijn die uit elkaar kunnen groeien
    (ontwerp-teller-artefacten.md §12 stap 3). Dat is bewust ANDERS dan
    :func:`differentieer_teller`/``minuut.differentieer_snel``:
    díe twee zijn wél gesplitst, maar met een gemeten reden (de gedeelde DataFrame-route kostte 2,7 s
    per teller per locatie, zie ``minuut.differentieer_snel``'s docstring). Voor deze functie -- één
    vectorized ``cummax``/``shift`` per aanroep, geen hot path -- is die reden er niet, dus blijft
    hij één implementatie.

    "Eerder" en niet "ooit", en dat verschil is een echte valkuil. Vragen of de teller *ergens in de
    reeks* boven 1 komt, nult ook de legitieme beginperiode van een teller die bij nul begint en pas
    later gaat lopen (``e_warmtepomp_cum__kWh``, ``q_geleverd_cum__J``: die staan bij het begin van
    de meetperiode gewoon op 0,0). Een lopend maximum vraagt wat het moet vragen: valt de stand
    *terug* naar nul.

    Zonder ``home_id`` (het minuutpad, dat altijd al één locatie tegelijk aanlevert, in tijdsorde)
    wordt de hele reeks als één woning behandeld. Met ``home_id`` ÉN ``tijdstip_start`` (het
    kwartierpad, dat alle woningen in één kolom aanlevert) wordt het lopende maximum PER WONING
    opgebouwd op haar eigen chronologische volgorde: intern gesorteerd op (``home_id``,
    ``tijdstip_start``) en teruggezet op de oorspronkelijke index -- hetzelfde patroon als
    :func:`differentieer_teller` hierboven.
    """
    if home_id is None:
        eerder_hoogste = stand.cummax().shift(1)
        gevlagd = (stand == 0.0) & (eerder_hoogste > TELLER_ONTWAAKT_BOVEN)
        return gevlagd.fillna(False).astype(bool)

    if tijdstip_start is None:
        raise ValueError("tijdstip_start is verplicht samen met home_id (chronologische volgorde per woning)")
    werk = pd.DataFrame(
        {"home_id__str": home_id.to_numpy(), "stand": stand.to_numpy(), "tijdstip_start": tijdstip_start.to_numpy()},
        index=stand.index,
    )
    volgorde = werk.sort_values(["home_id__str", "tijdstip_start"]).index
    gesorteerd = werk.loc[volgorde]
    gevlagd_gesorteerd = gesorteerd.groupby("home_id__str", sort=False)["stand"].transform(
        lambda s: markeer_nulmetingen(s)
    )
    return gevlagd_gesorteerd.reindex(stand.index).astype(bool)


def verwerk_bronteller(
    waarde: pd.Series,
    tijdstip_start: pd.Series,
    home_id: pd.Series,
    eenheid_naar_J: float | pd.Series = 1.0,
) -> dict[str, object]:
    """Eén brontteller door de kwartierpad-ingrepen van ontwerp-teller-artefacten.md §4.2/§4.3:
    nulmeting eruit vóór het differentiëren, dan differentiëren, dan het ene interval van een echte
    wissel op ``NaN``.

    **De sentinel (§4.1) hoort hier NIET bij.** Die maskeert de aanroeper al op de rauwe DSMR-
    kolommen, VOORDAT deze functie het cummax-criterium van :func:`markeer_nulmetingen` ziet (§5:
    die volgorde is dwingend -- de sentinelwaarde 3433,300 ligt ruim boven
    :data:`TELLER_ONTWAAKT_BOVEN`, en telt hij mee in het lopende maximum, dan explodeert het aantal
    nulmeting-treffers op ``e_export_laag_cum__kWh`` van 361 naar 542.507).

    Retourneert een dict met:

    - ``"schoon"``: de stand na nulmeting-maskering. Dit is wat in ``measurements.parquet`` komt te
      staan voor deze teller (de sentinel-maskering, als van toepassing, zit al in ``waarde``).
    - ``"gedifferentieerd"``: het resultaat van :func:`differentieer_teller` op ``"schoon"``, met
      het ene wissel-interval (§4.3) daarna alsnog op ``NaN`` in ``delta``/``vermogen__W`` -- niet
      in ``delta_t__s``, want de intervalduur zelf is geen afgeleide grootheid en verdwijnen zou het
      gat onzichtbaar maken voor wie ``delta_t__s`` los gebruikt.
    - ``"nulmeting__bool"``, ``"wissel__bool"``: de twee per-teller vlaggen (nullable ``boolean``),
      voor de OR naar de rijvlaggen ``teller_nulmeting__bool``/``teller_wissel__bool`` (§7).
    """
    nulmeting = markeer_nulmetingen(waarde, home_id=home_id, tijdstip_start=tijdstip_start)
    schoon = waarde.where(~nulmeting)
    gedifferentieerd = differentieer_teller(schoon, tijdstip_start, home_id, eenheid_naar_J)

    daalt = (gedifferentieerd["delta"] < 0.0).fillna(False)

    # "Landt de daling in een nulmeting?" -- in dezelfde chronologische volgorde per woning als
    # differentieer_teller zelf gebruikt (sort_values + shift), anders wordt op een dataset met
    # meerdere woningen de verkeerde "volgende" rij vergeleken.
    werk = pd.DataFrame(
        {
            "home_id__str": home_id.to_numpy(),
            "nulmeting": nulmeting.to_numpy(),
            "tijdstip_start": tijdstip_start.to_numpy(),
        },
        index=waarde.index,
    )
    volgorde = werk.sort_values(["home_id__str", "tijdstip_start"]).index
    gesorteerd = werk.loc[volgorde]
    volgende_is_nulmeting = (
        gesorteerd.groupby("home_id__str", sort=False)["nulmeting"]
        .shift(-1)
        .fillna(False)
        .astype(bool)
        .reindex(waarde.index)
    )

    # Een daling die niet in een nulmeting landt is een echte breuk (meter vervangen of teruggezet):
    # de nulmeting hierboven herstelt zich later, dit niet (ontwerp §4.3).
    wissel = daalt & ~volgende_is_nulmeting
    gedifferentieerd = gedifferentieerd.copy()
    gedifferentieerd.loc[wissel, ["delta", "vermogen__W"]] = np.nan

    return {
        "schoon": schoon,
        "gedifferentieerd": gedifferentieerd,
        "nulmeting__bool": nulmeting.astype("boolean"),
        "wissel__bool": wissel.astype("boolean"),
    }
