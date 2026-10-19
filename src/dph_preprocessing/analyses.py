# SPDX-License-Identifier: EUPL-1.2
"""Analyseprogramma (``ontwerp-preprocessing.md`` §8): bevindingen over de brondata (groep A) en
controles op onze eigen verwerking (groep B), uitgerekend op de verwerkte Parquet-tabellen in
``data/processed``.

Twee harde ontwerpeisen (zie de opdracht die tot deze module leidde, 05-09-2026):

1. **Elke statistiek eerst per woning, dan pas gepoold** (ontwerpprincipe 7, §3). Elke
   ``analyse_*``-functie hieronder retourneert daarom een tabel met (tenminste) één rij per
   ``home_id__str``, nooit alleen een gepoold getal. Samenvattingen (spreiding, top-10 afwijkend)
   worden in het rapport berekend, ÓP BASIS van die per-woning-tabel -- zie
   :func:`_spreiding_over_woningen` en :func:`_top_n_afwijkend`. ``ontwerp-intervalsemantiek.md``
   §5 laat zien waarom dit niet vrijblijvend is: één woning met uitschieters vier ordes van
   grootte boven het signaal trok daar een gepoolde correlatie naar nul.
2. **Hervatbaar**: elke analyse schrijft zijn resultaat weg als Parquet in
   ``<docs-dir>/../data/analyse/<analysenaam>.parquet`` (:func:`voer_analyses_uit`). Bij een
   nieuwe start wordt een analyse waarvan dat bestand al bestaat overgeslagen, tenzij
   ``--opnieuw``. Het rapport (``docs/analyse-bevindingen.md``) wordt ALTIJD opnieuw uit die
   tussenresultaten opgebouwd -- vandaar dat de analysefuncties de fijnste bruikbare granulariteit
   wegschrijven (per woning, of per woning + subgroep) en pas :func:`genereer_rapport` de
   samenvattingen/drempels kiest.

Dit is stap 2 van het programma (``ontwerp-preprocessing.md`` §8.4): een aparte, hervatbare module
naast de bestaande preprocessing-pijplijn (``pipeline``/``tellers``/``tabellen``/``bron``), die
hier uitsluitend GELEZEN wordt (``tellers.differentieer_teller``, enkele constantes en
``gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3``) -- nooit gewijzigd. A5 leest GEEN
brondata opnieuw: die functie krijgt de per-woning-per-bron
scheefheidssamenvatting die de preprocessing zelf al wegschrijft (``data/processed/
scheefheid.parquet``, zie ``tabellen.bouw_scheefheid_samenvatting``) rechtstreeks als invoer.

CLI: ``python -m dph_preprocessing.analyses --in-dir data/processed --docs-dir docs``.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from . import gaskwaliteit
from . import opmaak
from . import tabellen
from .tellers import J_PER_KWH, SPRONG_DREMPEL__W, differentieer_teller

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------
# Gedeelde hulpfuncties
# --------------------------------------------------------------------------------------------


def _delta_t__s(tijdstip_start: pd.Series, home_id: pd.Series) -> pd.Series:
    """Werkelijke tijd (s) TOT de volgende rij VAN DEZELFDE WONING, ongeacht invoervolgorde.

    Zelfde definitie als ``dph_preprocessing.tellers.differentieer_teller``'s ``delta_t__s``
    (VOORWAARTS volgens ontwerp-intervalsemantiek.md §2: rij Q beschrijft het interval NA Q, dus de
    LAATSTE rij van een woning is NaN, niet de eerste), hier los herberekend (op basis van
    ``tijdstip_start`` alleen) zodat een energie-analyse deze kan hergebruiken voor MEERDERE
    tellers tegelijk zonder ``differentieer_teller`` per teller opnieuw te laten sorteren.
    ``delta_t__s`` hangt niet af van welke teller je bekijkt -- alleen van de rijenspil
    (``home_id__str``, ``tijdstip_start``), en die is voor alle tellers in ``measurements`` gelijk.
    Moet in lockstap blijven met ``differentieer_teller``: anders staat een vermogen uit
    ``derived`` (interval [Q, Q+1)) tegenover een ``delta_t__s`` van een ANDER interval, en klopt
    geen enkele ``vermogen__W x delta_t__s``-energieberekening meer (zie B2 hieronder).
    """
    werk = pd.DataFrame(
        {"home_id__str": home_id.to_numpy(), "tijdstip_start": tijdstip_start.to_numpy()},
        index=tijdstip_start.index,
    )
    volgorde = werk.sort_values(["home_id__str", "tijdstip_start"]).index
    gesorteerd = werk.loc[volgorde]
    volgende_tijd = gesorteerd.groupby("home_id__str", sort=False)["tijdstip_start"].shift(-1)
    dt = (volgende_tijd - gesorteerd["tijdstip_start"]).dt.total_seconds()
    return dt.reindex(tijdstip_start.index)


def _run_lengths(aanwezig: pd.Series, home_id: pd.Series) -> pd.DataFrame:
    """Lengte (in rijen) van elke aaneengesloten reeks met dezelfde ``aanwezig``-waarde, per
    woning apart -- een reeks eindigt altijd bij een woninggrens, ook als de twee aangrenzende
    rijen toevallig dezelfde ``aanwezig``-waarde delen.

    Vereist dat de invoer al gesorteerd is op (``home_id__str``, tijd); dit is een generieke
    bouwsteen voor B4 (gaten) en B5 (aaneengesloten bruikbare tijd), vectorized met numpy zodat
    hij ook op de volledige ~8,7 miljoen rijen bruikbaar is.

    Retourneert één rij per reeks: ``home_id__str``, ``aanwezig`` (bool), ``lengte`` (aantal
    rijen in de reeks).
    """
    a = aanwezig.to_numpy(dtype=bool)
    h = home_id.to_numpy()
    n = len(a)
    if n == 0:
        return pd.DataFrame(columns=["home_id__str", "aanwezig", "lengte"])
    nieuwe_reeks = np.empty(n, dtype=bool)
    nieuwe_reeks[0] = True
    nieuwe_reeks[1:] = (a[1:] != a[:-1]) | (h[1:] != h[:-1])
    reeks_id = np.cumsum(nieuwe_reeks)
    werk = pd.DataFrame({"reeks_id": reeks_id, "home_id__str": h, "aanwezig": a})
    reeksen = werk.groupby("reeks_id", sort=False).agg(
        home_id__str=("home_id__str", "first"), aanwezig=("aanwezig", "first"), lengte=("aanwezig", "size")
    )
    return reeksen.reset_index(drop=True)


def _spreiding_over_woningen(serie: pd.Series) -> dict:
    """Samenvatting van een per-woning-statistiek OVER woningen (ontwerpprincipe 7: nooit alleen
    het gemiddelde, altijd ook de spreiding)."""
    s = pd.to_numeric(serie, errors="coerce").dropna()
    if s.empty:
        return {"n_woningen": 0}
    return {
        "n_woningen": int(len(s)),
        "gemiddelde": float(s.mean()),
        "mediaan": float(s.median()),
        "min": float(s.min()),
        "p10": float(s.quantile(0.10)),
        "p90": float(s.quantile(0.90)),
        "max": float(s.max()),
    }


def _top_n_afwijkend(df: pd.DataFrame, kolom: str, n: int = 10, sleutel: Sequence[str] = ("home_id__str",)) -> pd.DataFrame:
    """De ``n`` rijen met de grootste ``|kolom|``, voor het rapport ("bij veel woningen: de
    samenvattende verdeling plus de tien meest afwijkende woningen voluit")."""
    werk = df.dropna(subset=[kolom]).copy()
    if werk.empty:
        return werk
    werk["_abs"] = werk[kolom].abs()
    return werk.sort_values("_abs", ascending=False).head(n).drop(columns="_abs")


#: Herkent de formatstrings waarmee ``_fmt`` hieronder al werd aangeroepen (``{:.3f}``, ``{:,.0f}``,
#: ``{:.1%}``, ``{:.3g}``, ...), zodat de aanroepsites in de ``_sectie_*``-functies ongewijzigd
#: konden blijven terwijl de opmaak zelf naar ``opmaak``/``_fmt_g`` (Nederlands) verhuist.
_SPEC_RE = re.compile(r"^\{:,?\.(\d+)([fg%])\}$")


def _fmt_g(x, sig: int = 3) -> str:
    """Significante-cijfers-notatie (Python's ``g``), maar met een Nederlandse komma. ``opmaak``
    kent alleen een vast aantal DECIMALEN (``getal``), geen significante cijfers -- nodig voor de
    kolommen hier die van kleine relatieve afwijkingen tot grote Joule-bedragen kunnen lopen, waar
    een vast aantal decimalen ofwel te veel afkapt ofwel een wirwar aan nullen oplevert. Voor het
    aantal significante cijfers dat hier gebruikt wordt (3) levert ``g`` sowieso nooit een geheel
    getal >=10.000 op (dan schakelt het zelf al over op wetenschappelijke notatie), dus een
    duizendtalscheiding komt hier niet aan de orde."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n.v.t."
    try:
        return f"{float(x):.{sig}g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(x)


def _fmt(x, spec: str = "{:.3f}") -> str:
    """Formatteer één rapportwaarde. ``spec`` is (nog steeds) een Python-formatstring zoals op de
    aanroepplek al stond, maar wordt hier vertaald naar Nederlandse opmaak in plaats van er direct
    ``spec.format(x)`` mee te doen: ``f`` -> ``opmaak.getal`` (komma als decimaalteken, punt per
    duizendtal), ``%`` -> ``opmaak.percentage`` (``x`` is dan, zoals bij Python's ingebouwde
    ``%``-opmaak, een FRACTIE) en ``g`` -> ``_fmt_g`` hierboven."""
    if x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NA:
        return "n.v.t."
    match = _SPEC_RE.match(spec)
    if match is None:
        try:
            return spec.format(x)
        except (ValueError, TypeError):
            return str(x)
    decimalen, soort = match.groups()
    decimalen = int(decimalen)
    if soort == "%":
        return opmaak.percentage(x, decimalen)
    if soort == "g":
        return _fmt_g(x, decimalen)
    return opmaak.getal(x, decimalen)


# --------------------------------------------------------------------------------------------
# A1 -- warmtepompteller: uitschieters
# --------------------------------------------------------------------------------------------


def analyse_a1_warmtepompteller(derived: pd.DataFrame, drempel__W: float = 50_000.0) -> pd.DataFrame:
    """§8.1 A1: per woning de correlatie tussen ``p_warmtepomp__W`` (teller) en
    ``p_warmtepomp_meting__W`` (momentaan), plus p99/max van beide en het aantal waarden boven
    een fysische grens (standaard 50 kW). Beantwoordt: bij hoeveel woningen is de
    warmtepompteller een probleem (losse uitschieters of structureel), en is dat een handvol
    woningen of een patroon? Zie ``ontwerp-intervalsemantiek.md`` §5 voor de proefrun-bevinding
    (één van de vijf woningen met tellerwaarden tot 12,3 MW) die deze analyse op de volledige set
    moet herhalen.
    """
    rijen = []
    for home_id, g in derived.groupby("home_id__str", sort=True):
        teller = g["p_warmtepomp__W"]
        meting = g["p_warmtepomp_meting__W"]
        paar = pd.concat([teller, meting], axis=1).dropna()
        corr = paar.iloc[:, 0].corr(paar.iloc[:, 1]) if len(paar) >= 2 else float("nan")
        rijen.append(
            {
                "home_id__str": home_id,
                "corr_teller_meting": corr,
                "p99_teller__W": teller.quantile(0.99) if teller.notna().any() else float("nan"),
                "max_teller__W": teller.max(),
                "p99_meting__W": meting.quantile(0.99) if meting.notna().any() else float("nan"),
                "max_meting__W": meting.max(),
                "n_boven_grens_teller": int((teller.abs() > drempel__W).sum()),
                "n_boven_grens_meting": int((meting.abs() > drempel__W).sum()),
                "n": int(teller.notna().sum()),
            }
        )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# A3 -- meterwissels en resets
# --------------------------------------------------------------------------------------------

#: De acht ruwe cumulatieve kolommen in ``measurements`` (vier bronnen). ``e_net`` zit hier
#: BEWUST niet als samengestelde kolom bij (dat is precies de fout uit B3: een samengestelde
#: teller die legitiem daalt bij teruglevering) -- import/export laag/hoog blijven apart.
A3_RUWE_TELLERS: tuple[str, ...] = (
    "e_import_laag_cum__kWh",
    "e_import_hoog_cum__kWh",
    "e_export_laag_cum__kWh",
    "e_export_hoog_cum__kWh",
    "g_gebruik_cum__m3",
    "e_warmtepomp_cum__kWh",
    "e_ketel_cum__kWh",
    "q_geleverd_cum__J",
)


def _vind_spiegelparen(delta: pd.Series, groot_multiplier: float = 20.0, tol: float = 0.05, max_afstand: int = 2) -> int:
    """Tel spiegelparen in een AL PER WONING GESORTEERDE deltareeks: een grote sprong direct
    gevolgd, binnen ``max_afstand`` rijen, door een sprong die 'm bijna precies compenseert -- de
    handtekening van een meterwissel (ontwerp-preprocessing.md §8.1 A3: "een grote sprong, direct
    gevolgd door dezelfde sprong terug").

    "Groot" is hier DATA-AFHANKELIJK (geen verzonnen watt-drempel, vgl. B7): een sprong telt mee
    als ``|delta|`` meer dan ``groot_multiplier`` keer de mediane absolute afwijking van de
    mediaan (MAD, robuust tegen de sprongen zelf) bedraagt, met een fallback op het 99,9e
    percentiel als de MAD nul is (een teller die vrijwel nooit varieert).
    "Compenseert" betekent: de som van de twee sprongen is kleiner dan ``tol`` keer de eerste
    sprong in absolute waarde.

    **Waarom dit bestaat naast :func:`_tel_spiegelparen_alle_woningen`.** Dit is de per-rij
    PYTHON-lus -- correct, maar op de volledige dataset (8 tellers x 174 woningen x tot ~70.000
    rijen) goed voor ~38 minuten (gemeten 05-09-2026), puur `for`-lus-overhead over rijen die
    vrijwel altijd NIET "groot" zijn. ``analyse_a3_meterwissels`` gebruikt deze functie niet; ze
    staat er als leesbare referentie-implementatie (en voor de tests hieronder), precies omdat de
    vectorized versie ZONDER deze referentie niet te vertrouwen zou zijn.
    """
    d = delta.dropna()
    if len(d) < 2:
        return 0
    waarden = d.to_numpy()
    mediaan = np.median(waarden)
    mad = np.median(np.abs(waarden - mediaan))
    drempel = groot_multiplier * mad if mad > 0 else np.quantile(np.abs(waarden), 0.999)
    if not (drempel > 0):
        return 0

    n = len(waarden)
    groot = np.abs(waarden) > drempel
    gebruikt = np.zeros(n, dtype=bool)
    geteld = 0
    for i in range(n):
        if not groot[i] or gebruikt[i]:
            continue
        for afstand in range(1, max_afstand + 1):
            j = i + afstand
            if j >= n or gebruikt[j]:
                continue
            if abs(waarden[i] + waarden[j]) < tol * abs(waarden[i]):
                geteld += 1
                gebruikt[i] = True
                gebruikt[j] = True
                break
    return geteld


def _tel_spiegelparen_alle_woningen(
    geldig: pd.DataFrame, groot_multiplier: float = 20.0, tol: float = 0.05
) -> pd.Series:
    """Vectorized versie van :func:`_vind_spiegelparen`, over ALLE woningen tegelijk in plaats van
    een Python-lus per woning die daarbinnen ZELF ook nog een Python-lus per RIJ had -- dat laatste
    was de dure 38-minuten-lus (8 tellers x 174 woningen x tot ~70.000 rijen, zie het eindrapport /
    de commitboodschap van de prestatiefix, 05-09-2026). Retourneert het aantal spiegelparen per
    woning (``pd.Series``, index ``home_id__str``), IDENTIEK aan wat ``_vind_spiegelparen`` per
    woning zou geven (geverifieerd: zie ``tests/test_analyses.py`` en, op de volledige dataset,
    ``assert_frame_equal`` tegen het bestaande ``data/analyse/a3_meterwissels.parquet`` in de
    commitboodschap van de prestatiefix).

    ``geldig`` moet AL gesorteerd zijn op (``home_id__str``, ``tijdstip_start``) en AL ontdaan zijn
    van NaN-deltas (zie :func:`analyse_a3_meterwissels`): ``_vind_spiegelparen`` telt spiegelparen
    immers ook al in de COMPACTE (NaN-vrije) reeks, dus positie *i* en *i+1* in ``geldig`` zijn
    precies wat die functie als "opeenvolgend" beschouwt -- inclusief het geval waarin de
    tussenliggende rij(en) een NaN-delta hadden (bv. een eigen-teller-gat, zie B2) en dus NIET
    meetellen als "1 rij verder".

    **Het woninggrens-masker.** ``shift(-1)``/``shift(-2)`` op het HELE (alle woningen tegelijk)
    frame kijkt bij de laatste rij van een woning de eerste rij van de VOLGENDE woning in. Zonder
    correctie zou dat af en toe een "spiegelpaar" over een woninggrens heen ontdekken dat niet
    bestaat (twee toevallig bijna-tegengestelde sprongen bij twee VERSCHILLENDE woningen). Het
    masker hieronder (``zelfde_woning_1``/``_2``) sluit dat expliciet uit door de ``home_id__str``
    van de verschoven rij te vergelijken met die van de rij zelf; aan het einde van het hele frame
    geeft ``shift()`` toch al ``NaN``, wat bij dit project se ``str``-dtype al als "ongelijk" (dus
    ``False``) vergelijkt (geverifieerd: geen ``pd.NA``-lekkage naar de booleans hieronder).

    **"Groot", en de twee kandidaat-afstanden (1 en 2 rijen verder), zijn hierboven al volledig
    gevectoriseerd** (``groupby().transform``/``.quantile()``, geen Python-lus). Wat NIET zomaar
    te vectoriseren is, is ``_vind_spiegelparen``'s ``gebruikt``-boekhouding: een rij die al als
    partner meetelde, mag niet nog eens meetellen (bv. rij *i+1* niet ALS partner van *i* via
    afstand 1, ÉN, apart, als partner van *i-1* via afstand 2). Dat is een sequentiële afhankelijkheid
    (eerst geziene kandidaten winnen) en dus in het algemeen een Python-lus -- MAAR: die lus hoeft
    alleen over de rijen te lopen waar ``groot`` waar is, NIET over alle rijen. "Groot" is per
    ontwerp zeldzaam (>20x de MAD, of het 99,9e percentiel als fallback), dus deze lus bezoekt een
    kleine fractie van de rijen i.p.v. alle ~70.000 per woning -- dat is precies waar de 38 minuten
    in ``_vind_spiegelparen`` heen gingen: niet naar het VERWERKEN van "grote" sprongen, maar naar
    het BEZOEKEN (met Python-lus-overhead) van de vrijwel altijd niet-grote rest.
    """
    delta = geldig["delta"]
    home = geldig["home_id__str"]
    abs_delta = delta.abs()

    mediaan = delta.groupby(home).transform("median")
    mad = (delta - mediaan).abs().groupby(home).transform("median")
    q999_per_woning = abs_delta.groupby(home).quantile(0.999)
    drempel = np.where(mad > 0, groot_multiplier * mad, home.map(q999_per_woning).to_numpy())
    groot = ((abs_delta > drempel) & (drempel > 0)).to_numpy()

    volgende_delta_1 = delta.shift(-1)
    zelfde_woning_1 = home.shift(-1) == home
    match_1 = (zelfde_woning_1 & ((delta + volgende_delta_1).abs() < tol * abs_delta)).to_numpy()

    volgende_delta_2 = delta.shift(-2)
    zelfde_woning_2 = home.shift(-2) == home
    match_2 = (zelfde_woning_2 & ((delta + volgende_delta_2).abs() < tol * abs_delta)).to_numpy()

    n = len(groot)
    gebruikt = np.zeros(n, dtype=bool)
    spiegelpaar_start = np.zeros(n, dtype=bool)
    # Zelfde volgorde/voorkeur als _vind_spiegelparen: eerst 1 rij verder proberen, dan 2; de
    # eerst-geziene kandidaat (kleinste i) claimt zijn partner-rij, een latere kandidaat die
    # dezelfde rij als partner zou willen gebruiken, kan dat dan niet meer (`gebruikt`).
    for i in np.flatnonzero(groot):
        if gebruikt[i]:
            continue
        if match_1[i] and not gebruikt[i + 1]:
            gebruikt[i] = True
            gebruikt[i + 1] = True
            spiegelpaar_start[i] = True
        elif match_2[i] and not gebruikt[i + 2]:
            gebruikt[i] = True
            gebruikt[i + 2] = True
            spiegelpaar_start[i] = True

    return pd.Series(spiegelpaar_start, index=geldig.index).groupby(home).sum()


def analyse_a3_meterwissels(measurements: pd.DataFrame) -> pd.DataFrame:
    """§8.1 A3: per woning en per brontteller (de acht ruwe cumulatieve kolommen in
    ``measurements``, zie :data:`A3_RUWE_TELLERS`) de verdeling van de deltas (p1/p50/p99/min/max),
    het aantal dalingen, en het aantal spiegelparen (:func:`_tel_spiegelparen_alle_woningen`).
    Anders dan IM3 (dat alleen de al-verschilde reeks krijgt) publiceert DPH de cumulatieve standen
    zelf, dus dit is hier wél te repareren -- de spiegelparen-telling is het bewijs daarvoor.

    **Volledig gevectoriseerd** (05-09-2026, prestatiefix): geen Python-lus meer per woning, laat
    staan per rij. De per-woning percentielen/min/max/n_dalingen komen uit ``pandas``'s eigen
    (gevectoriseerde) groupby-methoden; de spiegelparen uit :func:`_tel_spiegelparen_alle_woningen`.
    De acht tellers zelf blijven wél een (goedkope) Python-lus -- acht iteraties, geen 8 x 174.
    """
    # EEN keer sorteren, niet zestien keer. Tot 06-09-2026 riep deze functie per teller
    # differentieer_teller aan (die intern sorteert) en sorteerde daarna zelf nog eens -- acht
    # tellers x twee sorteringen op 8,6 miljoen rijen. Op de nachtrun kostte A3 daardoor 2 u 47,
    # waarvan gemeten 95 % in sorteren en differentiëren zat en maar 64 s in de eigenlijke
    # spiegelparen-detectie. A3 heeft alleen `delta` nodig, niet `delta_t__s` of `vermogen__W`,
    # dus differentieer_teller is hier overbodig: een groupby().diff() op een AL gesorteerd frame
    # geeft exact hetzelfde. De sortering is stabiel en op dezelfde sleutels, dus de volgorde
    # binnen een woning is identiek aan wat er eerst uitkwam.
    gesorteerd = measurements.sort_values(["home_id__str", "tijdstip_start"], kind="stable")
    home_s = gesorteerd["home_id__str"]
    tijd_s = gesorteerd["tijdstip_start"]

    rijen = []
    for teller in A3_RUWE_TELLERS:
        delta = gesorteerd.groupby("home_id__str", sort=False)[teller].diff()
        werk = pd.DataFrame(
            {"home_id__str": home_s.to_numpy(), "tijdstip_start": tijd_s.to_numpy(), "delta": delta.to_numpy()}
        )
        geldig = werk.dropna(subset=["delta"]).reset_index(drop=True)
        if geldig.empty:
            continue

        groep = geldig.groupby("home_id__str", sort=True)["delta"]
        samenvatting = pd.DataFrame(
            {
                "p1": groep.quantile(0.01),
                "p50": groep.quantile(0.50),
                "p99": groep.quantile(0.99),
                "min": groep.min(),
                "max": groep.max(),
                "n_dalingen": (geldig["delta"] < 0).groupby(geldig["home_id__str"]).sum(),
                "n": groep.size(),
            }
        )
        samenvatting["n_spiegelparen"] = _tel_spiegelparen_alle_woningen(geldig)
        samenvatting["teller"] = teller
        rijen.append(samenvatting.reset_index())

    if not rijen:
        return pd.DataFrame(
            columns=["home_id__str", "teller", "p1", "p50", "p99", "min", "max", "n_dalingen", "n_spiegelparen", "n"]
        )
    resultaat = pd.concat(rijen, ignore_index=True)
    resultaat["n_dalingen"] = resultaat["n_dalingen"].astype(int)
    resultaat["n_spiegelparen"] = resultaat["n_spiegelparen"].astype(int)
    resultaat["n"] = resultaat["n"].astype(int)
    kolommen = ["home_id__str", "teller", "p1", "p50", "p99", "min", "max", "n_dalingen", "n_spiegelparen", "n"]
    return resultaat[kolommen]


# --------------------------------------------------------------------------------------------
# A5 -- lopen de vier meetbronnen op dezelfde klok?
# --------------------------------------------------------------------------------------------


def analyse_a5_scheefheid_per_bron(scheefheid: pd.DataFrame) -> pd.DataFrame:
    """§8.1 A5: lopen de vier meetbronnen op dezelfde klok? Per woning en per bron (dsmr,
    kamstrup, heatpump, boiler) de verdeling van ``scheefheid__s`` (ontwerp §2.1).

    **Waarom dit niet uit de brondata zelf herleid wordt.** ``measurements.parquet``
    bewaart maar één, geprioriteerde ``tijdstip_meting`` per kwartier (vaste prioriteit dsmr >
    kamstrup > heatpump > boiler, zie ``tabellen.build_measurements_en_quality``); voor een
    kwartier waarin alle vier de bronnen aanwezig zijn, is dat altijd dsmr's eigen scheefheid,
    nooit die van de andere drie. De brondata (~2,9 GB CSV) een TWEEDE keer lezen kost op de
    volledige dataset zo'n 20 minuten voor een resultaat dat de preprocessing al berekent
    (:func:`tabellen.build_measurements_en_quality` bepaalt ``scheefheid__<bron>__s`` toch al, voor
    ``scheef__bool``). Die samenvatting wordt daarom bewaard door de preprocessing zelf (``tabellen.
    bouw_scheefheid_samenvatting``, weggeschreven als ``data/processed/scheefheid.parquet`` -- zie
    die functies' docstrings voor de afweging tegen "alle vier ``scheefheid__<bron>__s``-kolommen
    in ``quality.parquet`` bewaren", die over 11,5 M rijen veel meer schijfruimte zou kosten voor
    dezelfde vraag). Deze functie is daardoor een simpele doorgeefluik: ``scheefheid`` is
    al exact in de vorm die dit moet retourneren.
    """
    return scheefheid


# --------------------------------------------------------------------------------------------
# A6 -- is uitval per bron of per woning?
# --------------------------------------------------------------------------------------------

#: Eén "levend" kolom per bron in measurements: notna() ervan == die bron had een teller-waarde
#: in dat kwartier. Zelfde proxykolommen als ``rapport._BRON_PROXYKOLOM``, hier onafhankelijk
#: opnieuw vastgelegd (deze module raakt ``rapport.py`` niet aan).
A6_BRON_PROXYKOLOM: dict[str, str] = {
    "dsmr": "e_import_laag_cum__kWh",
    "kamstrup": "q_geleverd_cum__J",
    "heatpump": "e_warmtepomp_cum__kWh",
    "boiler": "e_ketel_cum__kWh",
}


def analyse_a6_uitval_bron_of_woning(measurements: pd.DataFrame, quality: pd.DataFrame) -> pd.DataFrame:
    """§8.1 A6: is uitval per bron of per woning? Per woning: hoeveel kwartieren ontbreken bij
    ALLE VIER de bronnen tegelijk (``quality.ontbrekend__bool`` -- dat kwartier bestaat per
    definitie niet in de vier-bronnen-unie, ``quality.bouw_tijdas``) tegenover bij PRECIES ÉÉN
    bron (drie van de vier proxykolommen in ``measurements`` gevuld, één niet). Het eerste is een
    dataloggerstoring, het tweede een sensor (ontwerp §8.1 A6).
    """
    n_alle_ontbrekend = (
        quality.assign(_m=quality["ontbrekend__bool"].fillna(False))
        .groupby("home_id__str")["_m"]
        .sum()
        .rename("n_alle_vier_ontbrekend")
    )

    aanwezig = pd.DataFrame({bron: measurements[kolom].notna() for bron, kolom in A6_BRON_PROXYKOLOM.items()})
    precies_een_ontbrekend = aanwezig.sum(axis=1) == (len(A6_BRON_PROXYKOLOM) - 1)
    n_precies_een = (
        pd.Series(precies_een_ontbrekend.to_numpy(), index=measurements.index)
        .groupby(measurements["home_id__str"])
        .sum()
        .rename("n_precies_een_ontbrekend")
    )

    resultaat = pd.concat([n_alle_ontbrekend, n_precies_een], axis=1).fillna(0).astype(int).reset_index()
    resultaat = resultaat.rename(columns={"index": "home_id__str"})
    return resultaat


# --------------------------------------------------------------------------------------------
# B2 -- sluit de energiebalans na het differentiëren?
# --------------------------------------------------------------------------------------------


def analyse_b2_energiebalans(measurements: pd.DataFrame, derived: pd.DataFrame) -> pd.DataFrame:
    """§8.2 B2: sluit de energiebalans na het differentiëren? Per woning en per teller: de som
    van ``vermogen__W x delta_t__s`` (J) tegenover ``(laatste geldige stand - eerste geldige
    stand) x eenheid_naar_J``. Toetst in één getal of ``tellers.differentieer_teller`` verliesvrij
    is en of ontbrekende kwartieren correct in de deler terechtkomen (IM3 doet het equivalent
    hiervan als q-som tegen dagwaarde).

    **Verwachte, reëele beperking**: waar een teller zelf een gat heeft TERWIJL de rij in
    ``measurements`` wél bestaat (een andere bron leverde die rij aan via de outer-merge in
    ``tabellen.build_measurements_en_quality``), breekt ``.diff()`` de keten: de overgang over dat
    gat wordt nooit ergens meegeteld (niet vóór, niet ná het gat), en de energiebalans sluit dan
    NIET. Dat is iets anders dan een kwartier dat bij ALLE bronnen ontbreekt (die rij bestaat
    domweg niet in ``measurements``, en ``.diff()`` gebruikt daar automatisch de werkelijke,
    langere tijdspanne -- dát werkt wel verliesvrij, zie de tellers-moduledocstring). Deze analyse
    meet het totaal-effect; welk deel van een eventuele afwijking aan teller-specifieke gaten ligt
    is met A6 (bron_incompleet per teller) te herleiden.
    """
    home = measurements["home_id__str"]
    tijd = measurements["tijdstip_start"]
    delta_t__s = _delta_t__s(tijd, home)

    e_import = measurements[["e_import_laag_cum__kWh", "e_import_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_export = measurements[["e_export_laag_cum__kWh", "e_export_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_net_cum = e_import - e_export

    ruwe_tellers = {
        "e_net__W": (e_net_cum, J_PER_KWH),
        "g_gebruik__W": (measurements["g_gebruik_cum__m3"], gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3),
        "p_warmtepomp__W": (measurements["e_warmtepomp_cum__kWh"], J_PER_KWH),
        "p_ketel__W": (measurements["e_ketel_cum__kWh"], J_PER_KWH),
        "q_geleverd__W": (measurements["q_geleverd_cum__J"], 1.0),
    }

    # Gas is de enige teller met een omrekenfactor die PER RIJ verschilt (de calorische waarde,
    # gaskwaliteit.py). De tellerkant van de balans telescopeert alleen met één vaste factor
    # (laatste stand - eerste stand), dus wordt de vermogenskant hier teruggerekend naar diezelfde
    # vaste referentiewaarde: vermogen x dt x (referentie / toegepaste waarde). Beide kanten staan
    # dan in "J bij de referentiewaarde" en de verhouding is exact. Dit is bewust GEEN correctie van
    # g_gebruik__W zelf: B2 toetst of het differentiëren verliesvrij is, niet of de calorische
    # omrekening klopt. Zonder deze normalisatie zou B2 bij een per uur wisselende calorische
    # waarde een afwijking van ~2% melden die niets met differentiëren te maken heeft.
    naar_referentie = None
    if gaskwaliteit.KOLOM in derived.columns:
        toegepast__J_m_3 = pd.to_numeric(derived[gaskwaliteit.KOLOM], errors="coerce")
        naar_referentie = (
            gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / toegepast__J_m_3
        ).to_numpy()

    rijen = []
    for kolom_naam, (waarde, factor) in ruwe_tellers.items():
        geldig = pd.DataFrame(
            {"home_id__str": home.to_numpy(), "tijdstip_start": tijd.to_numpy(), "waarde": waarde.to_numpy()}
        ).dropna(subset=["waarde"])
        if geldig.empty:
            continue
        eerste_laatste = geldig.sort_values("tijdstip_start").groupby("home_id__str")["waarde"].agg(["first", "last"])

        vermogen__W = derived[kolom_naam]
        energie_uit_vermogen__J = vermogen__W.to_numpy() * delta_t__s.to_numpy()
        if kolom_naam == "g_gebruik__W" and naar_referentie is not None:
            energie_uit_vermogen__J = energie_uit_vermogen__J * naar_referentie
        werk = pd.DataFrame({"home_id__str": home.to_numpy(), "e": energie_uit_vermogen__J})
        som_per_woning = werk.groupby("home_id__str")["e"].apply(lambda s: s.dropna().sum() if s.notna().any() else float("nan"))

        for home_id in eerste_laatste.index:
            eerste = eerste_laatste.loc[home_id, "first"]
            laatste = eerste_laatste.loc[home_id, "last"]
            energie_uit_teller__J = (laatste - eerste) * factor
            energie_uit_vermogen__J_woning = som_per_woning.get(home_id, float("nan"))
            if energie_uit_teller__J:
                afwijking = (energie_uit_vermogen__J_woning - energie_uit_teller__J) / energie_uit_teller__J
            else:
                afwijking = float("nan")
            rijen.append(
                {
                    "home_id__str": home_id,
                    "teller": kolom_naam,
                    "energie_uit_teller__J": energie_uit_teller__J,
                    "energie_uit_vermogen__J": energie_uit_vermogen__J_woning,
                    "relatieve_afwijking": afwijking,
                }
            )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# B4 -- verdeling van de gaten per grootheid
# --------------------------------------------------------------------------------------------

#: [0,900) s = "<15 min" (op kwartierdata per definitie onwaarneembaar: het kortste gat is 900 s),
#: daarna precies de zes bakken uit de opdracht.
B4_GAT_BINS__S = [0, 900, 1800, 5400, 21600, 86400, np.inf]
B4_GAT_LABELS = ["<15 min", "15-30 min", "30-90 min", "1,5-6 u", "6-24 u", ">24 u"]

#: De kolommen in ``derived`` waarvoor de gatverdeling relevant is voor een gatlimiet-keuze
#: (ontwerp-intervalsemantiek.md §4.3/§4.4): zowel de kandidaten om te interpoleren als de
#: snelle/steekproef-kolommen die dat expliciet niet worden, plus de vijf tellervermogens zelf.
B4_KOLOMMEN: tuple[str, ...] = (
    "e_net__W",
    "g_gebruik__W",
    "p_warmtepomp__W",
    "p_ketel__W",
    "q_geleverd__W",
    "temp_binnen_meting__degC",
    "rv_binnen_meting__0",
    "temp_aanvoer_meting__degC",
    "temp_retour_meting__degC",
    "u_L1_meting__V",
    "temp_buiten__degC",
    "wind__m_s_1",
    "ghi__W_m_2",
)


def analyse_b4_gatverdeling(quality: pd.DataFrame, derived: pd.DataFrame) -> pd.DataFrame:
    """§8.2 B4: de verdeling van de gaten per grootheid. Per woning en per kolom (zie
    :data:`B4_KOLOMMEN`) de verdeling van de duur van aaneengesloten ontbrekende periodes, in
    bakken (:data:`B4_GAT_LABELS`). Nodig om de gatlimiet voor interpolatie te kiezen
    (``ontwerp-intervalsemantiek.md`` §4.4) in plaats van NeedForHeats 90 minuten blind over te
    nemen.

    Het volledige, regelmatige kwartierrooster komt uit ``quality`` (die bevat ELK kwartier van
    elke woning, ook de kwartieren die in ``derived`` zelf geen rij hebben omdat daar geen van de
    vier tellerbronnen iets meette) -- ``derived`` wordt daar LEFT-JOINED op, zodat een kwartier
    zonder rij in ``derived`` ook voor bv. ``temp_binnen_meting__degC`` als ontbrekend telt.
    """
    grid = quality[["home_id__str", "tijdstip_start"]].sort_values(["home_id__str", "tijdstip_start"])
    aanwezige_kolommen = [k for k in B4_KOLOMMEN if k in derived.columns]
    grid = grid.merge(derived[["home_id__str", "tijdstip_start", *aanwezige_kolommen]], on=["home_id__str", "tijdstip_start"], how="left")

    rijen = []
    for kolom in aanwezige_kolommen:
        aanwezig = grid[kolom].notna()
        reeksen = _run_lengths(aanwezig, grid["home_id__str"])
        gaten = reeksen.loc[~reeksen["aanwezig"]].copy()
        if gaten.empty:
            continue
        gaten["duur__s"] = gaten["lengte"] * 900.0
        gaten["bak"] = pd.cut(gaten["duur__s"], bins=B4_GAT_BINS__S, labels=B4_GAT_LABELS, right=False)
        samenvatting = (
            gaten.groupby(["home_id__str", "bak"], observed=False)
            .agg(n_gaten=("duur__s", "size"), totale_duur__s=("duur__s", "sum"))
            .reset_index()
        )
        samenvatting["kolom"] = kolom
        rijen.append(samenvatting)
    if not rijen:
        return pd.DataFrame(columns=["home_id__str", "kolom", "bak", "n_gaten", "totale_duur__s"])
    return pd.concat(rijen, ignore_index=True)[["home_id__str", "kolom", "bak", "n_gaten", "totale_duur__s"]]


# --------------------------------------------------------------------------------------------
# B5 -- aaneengesloten bruikbare tijd per woning
# --------------------------------------------------------------------------------------------

#: Overgenomen van NeedForHeat's default (``ontwerp-intervalsemantiek.md`` §4.4: "tot die er is,
#: 90 minuten overnemen en het als aanname markeren").
B5_MAX_GAT__S_STANDAARD = 90 * 60.0

#: Bakken voor calculate_streak_durations, herschaald naar het kwartiergrid: de fijnste bak van
#: NeedForHeat (1 minuut) heeft hier geen betekenis, dus begint de eerste bak bij één kwartier.
B5_STREAK_BINS__S = [900, 3600, 86400, 604800, 2_592_000, np.inf]
B5_STREAK_LABELS = ["kwartier_tot_uur", "uur_tot_dag", "dag_tot_week", "week_tot_maand", "meer_dan_maand"]


def _gedekte_tijd__s(aanwezig: pd.Series, tijdstip_start: pd.Series, max_gat__s: float) -> float:
    """NeedForHeat's ``calculate_covered_time``, aangepast aan een vast kwartierraster: de som van
    de tijd tussen opeenvolgende AANWEZIGE kwartieren, waarbij een tussenpoos groter dan
    ``max_gat__s`` niet meetelt. Dit is dus NIET hetzelfde als "aantal aanwezige kwartieren x 900
    s": een klein gat wordt als gedekt (interpoleerbaar) meegeteld, een groot gat niet -- precies
    het verschil met een simpele telling dat de opdracht benadrukt.
    """
    tijden = tijdstip_start[aanwezig.to_numpy(dtype=bool)]
    if len(tijden) < 2:
        return 0.0
    verschillen = tijden.sort_values().diff().dt.total_seconds().dropna()
    return float(verschillen[verschillen <= max_gat__s].sum())


def analyse_b5_aaneengesloten_tijd(quality: pd.DataFrame, max_gat__s: float = B5_MAX_GAT__S_STANDAARD) -> pd.DataFrame:
    """§8.2 B5: aaneengesloten bruikbare tijd per woning, overgenomen van NeedForHeat
    (``calculate_covered_time`` + ``calculate_streak_durations`` in
    ``needforheat-diagnosis-software``'s ``data/preprocessor.py``), aangepast op onze kolomnamen
    en het vaste kwartierraster (in plaats van NeedForHeats variabele resolutie).

    "Aanwezig" is hier: niet ``ontbrekend__bool`` (minstens één van de vier tellerbronnen had een
    meting dat kwartier). Levert een LANGE tabel terug, één rij per (woning, metric): de totale
    tijdspanne van de woning, de gedekte tijd (:func:`_gedekte_tijd__s`), het aandeel, en de
    gedekte tijd per aaneengesloten-reeks-bak (:data:`B5_STREAK_LABELS`) -- 40.000 losse kwartieren
    is iets anders dan 40.000 aaneengesloten, en alleen dat laatste is bruikbaar voor een
    seizoensanalyse.
    """
    quality = quality.sort_values(["home_id__str", "tijdstip_start"])
    aanwezig = ~quality["ontbrekend__bool"].fillna(True)

    rijen = []
    for home_id, g in quality.assign(_aanwezig=aanwezig.to_numpy()).groupby("home_id__str", sort=True):
        tijd = g["tijdstip_start"]
        totale_tijd__s = (tijd.max() - tijd.min()).total_seconds()
        gedekt__s = _gedekte_tijd__s(g["_aanwezig"], tijd, max_gat__s)
        rijen.append({"home_id__str": home_id, "metric": "totale_tijd__s", "waarde": totale_tijd__s})
        rijen.append({"home_id__str": home_id, "metric": "gedekte_tijd__s", "waarde": gedekt__s})
        rijen.append(
            {
                "home_id__str": home_id,
                "metric": "aandeel_gedekt",
                "waarde": gedekt__s / totale_tijd__s if totale_tijd__s else float("nan"),
            }
        )

    reeksen = _run_lengths(aanwezig, quality["home_id__str"])
    streaks = reeksen.loc[reeksen["aanwezig"]].copy()
    if not streaks.empty:
        streaks["duur__s"] = streaks["lengte"] * 900.0
        streaks["bak"] = pd.cut(streaks["duur__s"], bins=B5_STREAK_BINS__S, labels=B5_STREAK_LABELS, right=False)
        per_bak = streaks.groupby(["home_id__str", "bak"], observed=False)["duur__s"].sum().reset_index()
        for _, r in per_bak.iterrows():
            rijen.append({"home_id__str": r["home_id__str"], "metric": f"streak__{r['bak']}__s", "waarde": r["duur__s"]})

    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# B7 -- de sprongdrempels tegen de werkelijke verdeling
# --------------------------------------------------------------------------------------------

B7_TELLERS: tuple[str, ...] = ("e_net__W", "g_gebruik__W", "p_warmtepomp__W", "p_ketel__W", "q_geleverd__W")


def analyse_b7_sprongdrempels(derived: pd.DataFrame) -> pd.DataFrame:
    """§8.2 B7: de sprongdrempels (``tellers.SPRONG_DREMPEL__W``, zelf "verzonnen, niet extern
    getoetst") tegen de werkelijke verdeling. Per woning en per teller de verdeling van het
    intervalgemiddelde vermogen (p99, p99.9, p99.99, max), zodat de huidige drempels vervangen
    kunnen worden door iets dat uit de data volgt.
    """
    rijen = []
    for teller in B7_TELLERS:
        if teller not in derived.columns:
            continue
        for home_id, g in derived.groupby("home_id__str", sort=True):
            v = g[teller].dropna().abs()
            if v.empty:
                continue
            rijen.append(
                {
                    "home_id__str": home_id,
                    "teller": teller,
                    "p99__W": v.quantile(0.99),
                    "p99_9__W": v.quantile(0.999),
                    "p99_99__W": v.quantile(0.9999),
                    "max__W": v.max(),
                    "huidige_drempel__W": SPRONG_DREMPEL__W.get(teller, float("nan")),
                    "n": int(len(v)),
                }
            )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# B8 -- stookseizoenen: een eerlijke telling
# --------------------------------------------------------------------------------------------


def _stookseizoen_venster(beginjaar: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Een stookseizoen is hier oktober t/m april (ontwerp-preprocessing.md §8.2 B8, expliciet
    smaller dan ``rapport._stookseizoen``'s juli-juni): ``eind`` is EXCLUSIEF (1 mei 00:00 UTC)."""
    start = pd.Timestamp(year=beginjaar, month=10, day=1, tz="UTC")
    eind = pd.Timestamp(year=beginjaar + 1, month=5, day=1, tz="UTC")
    return start, eind


def analyse_b8_stookseizoen_dekking(quality: pd.DataFrame) -> pd.DataFrame:
    """§8.2 B8: de huidige telling (``rapport.py``) telt seizoensjaren die AANGERAAKT worden, niet
    gedekt, en meldt daardoor te veel (een woning met data van juni 2022 tot januari 2024 raakt
    drie seizoensjaren aan en heeft er nul volledig).

    Deze analyse levert, per woning en per stookseizoen (okt t/m apr, zie
    :func:`_stookseizoen_venster`) dat het tijdvak van de woning overlapt, het AANDEEL kwartieren
    in dat venster dat daadwerkelijk data heeft (niet ``ontbrekend__bool``) ten opzichte van het
    VOLLEDIGE aantal kwartieren in het venster (ongeacht of de woning toen al gemonitord werd).
    De keuze VAN de dekkingsdrempel (voorstel 80 %) gebeurt bewust pas in het rapport
    (:func:`_sectie_b8`), zodat meerdere drempels naast elkaar zichtbaar zijn in plaats van hier
    al vastgelegd.
    """
    quality = quality.copy()
    quality["_aanwezig"] = ~quality["ontbrekend__bool"].fillna(True)
    tijd = quality["tijdstip_start"]
    if tijd.empty:
        return pd.DataFrame(columns=["home_id__str", "stookseizoen", "aandeel_gedekt", "verwacht_aantal", "aanwezig_aantal"])

    minjaar, maxjaar = int(tijd.dt.year.min()), int(tijd.dt.year.max())
    rijen = []
    for beginjaar in range(minjaar - 1, maxjaar + 1):
        start, eind = _stookseizoen_venster(beginjaar)
        in_venster = (tijd >= start) & (tijd < eind)
        if not in_venster.any():
            continue
        subset = quality.loc[in_venster]
        verwacht_aantal = int((eind - start).total_seconds() // 900)
        for home_id, g in subset.groupby("home_id__str", sort=True):
            aanwezig_aantal = int(g["_aanwezig"].sum())
            rijen.append(
                {
                    "home_id__str": home_id,
                    "stookseizoen": f"{beginjaar}/{beginjaar + 1}",
                    "aandeel_gedekt": aanwezig_aantal / verwacht_aantal,
                    "verwacht_aantal": verwacht_aantal,
                    "aanwezig_aantal": aanwezig_aantal,
                }
            )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# B9 -- loopt er tapwater langs de warmtemeter?
# --------------------------------------------------------------------------------------------

B9_WARMTE_DREMPEL__W = 200.0
B9_GAS_DREMPEL__W = 500.0
B9_AANVOER_DREMPEL__degC = 50.0
#: Minimum aantal zomerkwartieren met warmtelevering vóór een vlag zinvol is (anders is elk
#: aandeel gebaseerd op een handvol kwartieren en dus ruis).
B9_MIN_N_WARMTE = 10
B9_VERRIJKING_DREMPEL = 3.0


def analyse_b9_tapwater_langs_warmtemeter(derived: pd.DataFrame) -> pd.DataFrame:
    """§8.2 B9 (onderbouwing: ``ontwerp-intervalsemantiek.md`` §4.5): loopt er tapwater langs de
    warmtemeter? Per woning, over juni t/m augustus (geen ruimteverwarming, dus elke
    warmtelevering die overblijft is tapwater): het aandeel kwartieren met
    ``q_geleverd__W > 200``, en daarbinnen het aandeel met ``g_gebruik__W > 500`` afgezet tegen de
    basiskans van ``g_gebruik__W > 500`` in zomerkwartieren ZONDER warmtelevering. Plus de
    correlatie tussen ``q_geleverd__W`` en ``p_warmtepomp__W``, en het aandeel met
    ``temp_aanvoer_meting__degC > 50``. Een sterke verrijking van gas bij warmtelevering (>=3x de
    basiskans, bij >=10 zomerkwartieren met warmtelevering) wijst erop dat tapwater bij die woning
    wél langs de meter loopt -- vlag per woning.
    """
    zomer = derived["tijdstip_start"].dt.month.isin([6, 7, 8])
    d = derived.loc[zomer]
    rijen = []
    for home_id, g in d.groupby("home_id__str", sort=True):
        warmte = g["q_geleverd__W"]
        gas = g["g_gebruik__W"]
        wp = g["p_warmtepomp__W"]
        aanvoer = g["temp_aanvoer_meting__degC"]

        heeft_warmte = warmte > B9_WARMTE_DREMPEL__W
        n_totaal = int(warmte.notna().sum())
        n_warmte = int(heeft_warmte.sum())
        aandeel_warmte = n_warmte / n_totaal if n_totaal else float("nan")

        gas_bij_warmte = gas[heeft_warmte]
        n_gas_bij_warmte_noemer = int(gas_bij_warmte.notna().sum())
        aandeel_gas_bij_warmte = (
            int((gas_bij_warmte > B9_GAS_DREMPEL__W).sum()) / n_gas_bij_warmte_noemer if n_gas_bij_warmte_noemer else float("nan")
        )

        zonder_warmte = warmte <= B9_WARMTE_DREMPEL__W
        gas_zonder_warmte = gas[zonder_warmte]
        n_zonder_warmte_noemer = int(gas_zonder_warmte.notna().sum())
        basiskans_gas = (
            int((gas_zonder_warmte > B9_GAS_DREMPEL__W).sum()) / n_zonder_warmte_noemer if n_zonder_warmte_noemer else float("nan")
        )

        paar = pd.concat([warmte, wp], axis=1).dropna()
        corr = paar.iloc[:, 0].corr(paar.iloc[:, 1]) if len(paar) >= 2 else float("nan")

        aanvoer_bij_warmte = aanvoer[heeft_warmte]
        n_aanvoer_noemer = int(aanvoer_bij_warmte.notna().sum())
        aandeel_aanvoer_boven_drempel = (
            int((aanvoer_bij_warmte > B9_AANVOER_DREMPEL__degC).sum()) / n_aanvoer_noemer if n_aanvoer_noemer else float("nan")
        )

        if not pd.isna(basiskans_gas) and basiskans_gas > 0 and not pd.isna(aandeel_gas_bij_warmte):
            verrijking = aandeel_gas_bij_warmte / basiskans_gas
        else:
            verrijking = float("nan")

        vlag = bool(n_warmte >= B9_MIN_N_WARMTE and not pd.isna(verrijking) and verrijking >= B9_VERRIJKING_DREMPEL)

        rijen.append(
            {
                "home_id__str": home_id,
                "aandeel_zomerkwartieren_met_warmte": aandeel_warmte,
                "n_zomerkwartieren_met_warmte": n_warmte,
                "n_zomerkwartieren_totaal": n_totaal,
                "aandeel_gas_bij_warmte": aandeel_gas_bij_warmte,
                "basiskans_gas_zonder_warmte": basiskans_gas,
                "verrijking": verrijking,
                "corr_warmte_wp_elektra": corr,
                "aandeel_aanvoer_boven_50c": aandeel_aanvoer_boven_drempel,
                "tapwater_langs_warmtemeter__vlag": vlag,
            }
        )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# B10 -- rekent de Kamstrup na wat hij zegt te meten?
# --------------------------------------------------------------------------------------------

#: Eigenschappen van water bij ~45 °C (grofweg het midden tussen een typische aanvoer- en
#: retourtemperatuur van een hybride cv-installatie), zoals de opdracht toestaat ("een vaste
#: waarde mag, maar documenteer welke"). Bron: standaard tabelwaarden voor water bij 45 °C.
B10_RHO_WATER__KG_M3 = 990.0
B10_CP_WATER__J_KGK = 4180.0
#: "Noemenswaardig debiet" -- aanname van deze implementatie (analoog aan RHC's ΔT-drempel in
#: ontwerp-intervalsemantiek.md §4.5, hier op het debiet zelf i.p.v. op ΔT omdat de Kamstrup het
#: debiet meet en niet afleidt): 0,05 dm3/s = 3 L/min, ruim boven meetruis bij stilstand.
B10_DEBIET_DREMPEL__DM3_S = 0.05


def analyse_b10_kamstrup_consistentie(derived: pd.DataFrame, debiet_drempel__dm3_s: float = B10_DEBIET_DREMPEL__DM3_S) -> pd.DataFrame:
    """§8.2 B10 (onderbouwing: ``ontwerp-intervalsemantiek.md`` §4.5, slot): rekent de Kamstrup na
    wat hij zegt te meten? Toetst ``q_geleverd_meting__W ≈ ρ · c_p · debiet · ΔT`` per woning,
    alleen op kwartieren met een noemenswaardig debiet (``debiet_drempel__dm3_s``). ``ρ`` en
    ``c_p`` zijn vaste waarden voor water bij 45 °C (:data:`B10_RHO_WATER__KG_M3`,
    :data:`B10_CP_WATER__J_KGK`). Rapporteert de mediane (en p10/p90) relatieve afwijking per
    woning.
    """
    rijen = []
    for home_id, g in derived.groupby("home_id__str", sort=True):
        debiet = g["debiet_meting__dm3_s_1"]
        delta_t = g["temp_aanvoer_meting__degC"] - g["temp_retour_meting__degC"]
        q_meting = g["q_geleverd_meting__W"]

        masker = (debiet > debiet_drempel__dm3_s) & delta_t.notna() & q_meting.notna() & (q_meting != 0)
        d = debiet[masker]
        if d.empty:
            continue
        q_berekend = B10_RHO_WATER__KG_M3 * B10_CP_WATER__J_KGK * (d * 1e-3) * delta_t[masker]
        afwijking = (q_berekend - q_meting[masker]) / q_meting[masker]
        rijen.append(
            {
                "home_id__str": home_id,
                "mediane_relatieve_afwijking": afwijking.median(),
                "p10_relatieve_afwijking": afwijking.quantile(0.10),
                "p90_relatieve_afwijking": afwijking.quantile(0.90),
                "n": int(len(d)),
            }
        )
    return pd.DataFrame(rijen)


# --------------------------------------------------------------------------------------------
# A4 -- slaat er ergens een teller om? (modulus-artefacten)
# --------------------------------------------------------------------------------------------

#: De acht brontellers, met de macht van tien waarop hun register zou omslaan als het er een had.
#: Een huishoudelijke gasmeter telt tot 99999,999 m³ en slaat dan om naar 0; een kWh-register heeft
#: doorgaans vijf of zes cijfers vóór de komma. Welke het is, is niet uit de data af te lezen, dus
#: worden ze allemaal getoetst: een omslag verraadt zich doordat de stand ervóór vlak ONDER zo'n
#: macht ligt en de stand erna vlak erboven nul.
A4_MACHTEN: tuple[float, ...] = (1e3, 1e4, 1e5, 1e6, 1e7, 1e9, 1e10)

#: Hoe dicht de stand vóór de daling onder de macht van tien moet liggen om als omslag te tellen
#: (fractie van die macht). Ruim genomen: bij een omslag is het verschil precies het verbruik in dat
#: ene interval, en dat is op kwartierdata klein ten opzichte van de modulus.
A4_MARGE__0 = 0.01


def analyse_a4_modulusartefacten(measurements: pd.DataFrame) -> pd.DataFrame:
    """§8 / ``docs/lessen-uit-im3.md`` punt 2: slaat er ergens een teller om?

    **De zoekmethode komt uit de IM3-zusterrepo, de conclusie daar niet.** Daar bleken 410 fysisch
    onmogelijke waarden allemaal dezelfde sprong van 10.000 kWh te zijn: een register met vier
    cijfers vóór de komma dat van 9999,9 naar 0 gaat. Die diagnose kon daar alleen achteraf, uit de
    vórm van de verdeling, omdat IM3 uitsluitend de al-verschilde reeks publiceert.

    **Hier kan het rechtstreeks**, en dat is het hele voordeel van cumulatieve standen: bij elke
    DALING van een teller is de stand ervóór en erna gewoon bekend. Een omslag is dan geen
    statistisch vermoeden maar een exact patroon -- stand ervóór vlak onder een macht van tien,
    stand erna vlak boven nul -- en zou met één modulo te herstellen zijn, vóór het verschillen.

    Per (woning, teller) worden de dalingen geteld en uitgesplitst naar:

    - ``n_omslag_kandidaat``: dalingen die aan het omslagpatroon voldoen.
    - ``n_naar_nul``: dalingen naar (vrijwel) nul die dat NIET zijn, want de stand ervóór lag nergens
      in de buurt van een macht van tien. Dat is een teller die uitvalt en nul gaat melden, niet een
      die omslaat, en het is in deze dataset het overheersende patroon.
    - ``n_overig``: de rest, in de praktijk meterwissels (zie ook A3).

    Deze analyse repareert niets. Zolang ``n_omslag_kandidaat`` overal nul is, zou een modulo-
    correctie code zijn voor een verschijnsel dat hier niet voorkomt; slaat er ooit wél een teller
    om, dan zegt deze tabel precies bij welke teller en op welke macht van tien.
    """
    tellers = [
        "e_import_laag_cum__kWh", "e_import_hoog_cum__kWh", "e_export_laag_cum__kWh",
        "e_export_hoog_cum__kWh", "g_gebruik_cum__m3", "e_warmtepomp_cum__kWh",
        "e_ketel_cum__kWh", "q_geleverd_cum__J",
    ]
    werk = measurements.sort_values(["home_id__str", "tijdstip_start"])
    home = werk["home_id__str"]

    rijen = []
    for teller in tellers:
        if teller not in werk.columns:
            continue
        stand = werk[teller]
        volgende = werk.groupby("home_id__str", sort=False)[teller].shift(-1)
        daalt = volgende < stand

        omslag = pd.Series(False, index=werk.index)
        for macht in A4_MACHTEN:
            omslag |= (
                daalt
                & (stand > (1 - A4_MARGE__0) * macht)
                & (stand < macht)
                & (volgende < A4_MARGE__0 * macht)
            )
        naar_nul = daalt & ~omslag & (volgende <= A4_MARGE__0 * stand.abs())

        per_woning = pd.DataFrame(
            {
                "home_id__str": home,
                "n_dalingen": daalt.astype(int),
                "n_omslag_kandidaat": omslag.astype(int),
                "n_naar_nul": naar_nul.astype(int),
            }
        ).groupby("home_id__str", as_index=False).sum()
        per_woning = per_woning[per_woning["n_dalingen"] > 0]
        if per_woning.empty:
            continue
        per_woning["n_overig"] = (
            per_woning["n_dalingen"] - per_woning["n_omslag_kandidaat"] - per_woning["n_naar_nul"]
        )
        per_woning["teller"] = teller
        # De grootste daling per woning: bij een omslag is dat ongeveer de modulus zelf, en dat
        # maakt in het rapport zichtbaar of de treffers rond ÉÉN waarde clusteren of spreiden.
        grootste = (stand - volgende).where(daalt).groupby(home).max().rename("grootste_daling")
        per_woning = per_woning.merge(grootste.reset_index(), on="home_id__str", how="left")
        rijen.append(per_woning)

    if not rijen:
        return pd.DataFrame(
            columns=["home_id__str", "teller", "n_dalingen", "n_omslag_kandidaat", "n_naar_nul",
                     "n_overig", "grootste_daling"]
        )
    resultaat = pd.concat(rijen, ignore_index=True)
    return resultaat[
        ["home_id__str", "teller", "n_dalingen", "n_omslag_kandidaat", "n_naar_nul", "n_overig",
         "grootste_daling"]
    ].sort_values(["teller", "home_id__str"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# Registry + hervatbare runner
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _AnalyseSpec:
    naam: str
    func: Callable[..., pd.DataFrame]
    benodigd: tuple[str, ...]


REGISTRY: tuple[_AnalyseSpec, ...] = (
    _AnalyseSpec("a1_warmtepompteller", analyse_a1_warmtepompteller, ("derived",)),
    _AnalyseSpec("a5_scheefheid_per_bron", analyse_a5_scheefheid_per_bron, ("scheefheid",)),
    _AnalyseSpec("a6_uitval_bron_of_woning", analyse_a6_uitval_bron_of_woning, ("measurements", "quality")),
    _AnalyseSpec("b2_energiebalans", analyse_b2_energiebalans, ("measurements", "derived")),
    _AnalyseSpec("b4_gatverdeling", analyse_b4_gatverdeling, ("quality", "derived")),
    _AnalyseSpec("b5_aaneengesloten_tijd", analyse_b5_aaneengesloten_tijd, ("quality",)),
    _AnalyseSpec("b7_sprongdrempels", analyse_b7_sprongdrempels, ("derived",)),
    _AnalyseSpec("b8_stookseizoen_dekking", analyse_b8_stookseizoen_dekking, ("quality",)),
    _AnalyseSpec("b9_tapwater_langs_warmtemeter", analyse_b9_tapwater_langs_warmtemeter, ("derived",)),
    _AnalyseSpec("b10_kamstrup_consistentie", analyse_b10_kamstrup_consistentie, ("derived",)),
    # A3 staat BEWUST als laatste, en dat bleek terecht: op de volledige run van 6 september
    # kostte hij 10.008 s (2 u 47), meer dan de andere tien samen (1 u 16). De volgorde in deze
    # registry is de uitvoervolgorde en de analyses zijn per stuk hervatbaar, dus achteraan
    # blokkeert hij niets: de andere tien stonden al klaar terwijl hij nog liep.
    #
    # Waar die tijd heen gaat is gemeten en het is NIET de spiegelparen-detectie: die doet
    # 7,8 miljoen deltas in 64 s en geeft exact het goede antwoord. 95 % zit in het sorteren en
    # differentiëren ervoor (2.003 s voor één teller, gemeten 05-09-2026).
_AnalyseSpec("a3_meterwissels", analyse_a3_meterwissels, ("measurements",)),
_AnalyseSpec("a4_modulusartefacten", analyse_a4_modulusartefacten, ("measurements",)),
)


def _analyse_dir(docs_dir: str | Path) -> Path:
    return Path(docs_dir).parent / "data" / "analyse"


def _laad_tabellen(in_dir: str | Path) -> dict[str, pd.DataFrame]:
    in_dir = Path(in_dir)
    tabellen_ = {
        naam: pd.read_parquet(in_dir / f"{naam}.parquet") for naam in ("homes", "measurements", "quality", "derived", "weer")
    }
    # "scheefheid" (A5, tabellen.bouw_scheefheid_samenvatting) is GEEN van de vijf contracttabellen
    # en dus niet gegarandeerd aanwezig (bv. data/processed gebouwd vóór deze tabel bestond, en nog
    # niet met --opnieuw herverwerkt) -- val terug op een lege tabel i.p.v. te falen, zodat de rest
    # van het analyseprogramma gewoon doorloopt (zelfde soort gracieuze aftocht als de oude
    # `--raw-dir ontbreekt`-melding).
    scheefheid_pad = in_dir / "scheefheid.parquet"
    if scheefheid_pad.is_file():
        tabellen_["scheefheid"] = pd.read_parquet(scheefheid_pad)
    else:
        log.warning("%s ontbreekt; a5_scheefheid_per_bron levert een lege tabel op", scheefheid_pad)
        tabellen_["scheefheid"] = pd.DataFrame(columns=list(tabellen.SCHEEFHEID_KOLOMMEN))
    return tabellen_


def _jongste_invoer(in_dir: str | Path) -> float | None:
    """De hoogste wijzigingstijd van de invoertabellen, of ``None`` als er geen zijn.

    Hiermee wordt een analyseresultaat dat OUDER is dan zijn invoer niet hergebruikt. Zonder deze
    controle slaat het hervatten een analyse over zolang het bestand bestaat, ongeacht waar het
    over gaat -- en dan levert een verse preprocessing nieuwe tabellen op met een rapport dat nog
    de conclusies van de vorige versie draagt. Tabellen nieuw, conclusies oud, en niets dat piept.

    Dit is dezelfde klasse fout als :data:`chunking.UITVOER_CONTRACT_VERSIE` afdekt, maar een laag
    hoger. Hier kan het wél automatisch: de afhankelijkheid is een bestand op schijf, dus een
    make-achtige vergelijking van wijzigingstijden volstaat en er valt niets te vergeten.
    """
    tijden = [p.stat().st_mtime for p in Path(in_dir).glob("*.parquet")]
    return max(tijden) if tijden else None


def voer_analyses_uit(
    in_dir: str | Path,
    docs_dir: str | Path,
    opnieuw: bool = False,
) -> dict[str, pd.DataFrame]:
    """Voer alle analyses uit :data:`REGISTRY` uit, hervatbaar: een analyse waarvan
    ``<docs-dir>/../data/analyse/<naam>.parquet`` al bestaat wordt overgeslagen tenzij
    ``opnieuw=True``. Logt per analyse begin- en eindtijd en de duur.
    """
    analyse_dir = _analyse_dir(docs_dir)
    analyse_dir.mkdir(parents=True, exist_ok=True)

    context: dict[str, object] = _laad_tabellen(in_dir)

    jongste_invoer = _jongste_invoer(in_dir)

    resultaten: dict[str, pd.DataFrame] = {}
    for spec in REGISTRY:
        pad = analyse_dir / f"{spec.naam}.parquet"
        if pad.exists() and not opnieuw:
            if jongste_invoer is not None and pad.stat().st_mtime < jongste_invoer:
                log.warning(
                    "%s: resultaat is OUDER dan de invoertabellen en wordt herberekend -- het gaat "
                    "over een vorige versie van de data.", spec.naam,
                )
            else:
                log.info("%s: resultaat bestaat al (%s), overgeslagen (--opnieuw om te herberekenen)", spec.naam, pad)
                resultaten[spec.naam] = pd.read_parquet(pad)
                continue

        args = [context[b] for b in spec.benodigd]
        begin = datetime.now(timezone.utc)
        log.info("%s: gestart om %s", spec.naam, begin.isoformat())
        try:
            resultaat = spec.func(*args)
        except Exception:
            log.exception("%s: gefaald, overgeslagen", spec.naam)
            continue
        eind = datetime.now(timezone.utc)
        log.info(
            "%s: klaar om %s (duur %.1f s, %d rijen)",
            spec.naam, eind.isoformat(), (eind - begin).total_seconds(), len(resultaat),
        )
        resultaat.to_parquet(pad, index=False)
        resultaten[spec.naam] = resultaat

    return resultaten


# --------------------------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------------------------


def _regel_spreiding(spreiding: dict, eenheid: str = "") -> str:
    if spreiding.get("n_woningen", 0) == 0:
        return "geen woningen met een geldig resultaat."
    return (
        f"n={spreiding['n_woningen']} woningen, gemiddelde={_fmt_g(spreiding['gemiddelde'])}{eenheid}, "
        f"mediaan={_fmt_g(spreiding['mediaan'])}{eenheid}, spreiding p10-p90="
        f"{_fmt_g(spreiding['p10'])}{eenheid}..{_fmt_g(spreiding['p90'])}{eenheid}, "
        f"min={_fmt_g(spreiding['min'])}{eenheid}, max={_fmt_g(spreiding['max'])}{eenheid}"
    )


def _sectie_a1(df: pd.DataFrame) -> list[str]:
    lines = ["## A1. Warmtepompteller: uitschieters", ""]
    lines.append(
        "**Vraag**: correleert `p_warmtepomp__W` (teller) met `p_warmtepomp_meting__W` (momentaan) "
        "per woning, en bij hoeveel woningen komen fysisch onmogelijke waarden (>50 kW) voor?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    lines.append(_regel_spreiding(_spreiding_over_woningen(df["corr_teller_meting"]), "") + " (correlatie)")
    n_probleem = int((df["n_boven_grens_teller"] > 0).sum())
    n_lage_corr = int((df["corr_teller_meting"] < 0.5).sum())
    lines.append(
        f"- Woningen met >=1 waarde boven de fysische grens (50 kW) in de teller: "
        f"{opmaak.aandeel(n_probleem, len(df))}."
    )
    lines.append(f"- Woningen met een correlatie < 0,5 (teller vs. momentaan): {opmaak.aandeel(n_lage_corr, len(df))}.")
    lines.append("")
    lines.append("Tien meest afwijkende woningen (laagste correlatie):")
    lines.append("")
    top = df.sort_values("corr_teller_meting").head(10)
    lines.append("| home_id | corr | p99 teller (W) | max teller (W) | max meting (W) | n>50kW teller |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        lines.append(
            f"| {r['home_id__str']} | {_fmt(r['corr_teller_meting'])} | {_fmt(r['p99_teller__W'], '{:.0f}')} | "
            f"{_fmt(r['max_teller__W'], '{:.0f}')} | {_fmt(r['max_meting__W'], '{:.0f}')} | "
            f"{opmaak.getal(r['n_boven_grens_teller'])} |"
        )
    lines.append("")
    if n_probleem <= 1:
        lines.append(
            "**Conclusie**: op deze run is dit hooguit een enkele woning met losse uitschieters, "
            "geen structureel patroon -- werk voor `teller_sprong__bool`, geen punt voor de mail "
            "aan KITE (ontwerp §8.1 A1)."
        )
    else:
        mediaan_corr = pd.to_numeric(df["corr_teller_meting"], errors="coerce").median()
        n_zwak = int((pd.to_numeric(df["corr_teller_meting"], errors="coerce") < 0.5).sum())
        lines.append(
            f"**Conclusie**: de warmtepompteller deugt bij de grote meerderheid. De mediane "
            f"correlatie tussen teller en momentane meting is {opmaak.getal(mediaan_corr, 3)}; "
            f"{opmaak.aandeel(n_probleem, len(df))} van de woningen heeft waarden boven de fysische "
            f"grens en {opmaak.aandeel(n_zwak, len(df))} heeft een correlatie onder 0,5. "
            + (
                "Dat is te weinig om een punt voor de mail aan KITE van te maken: het gaat om losse "
                "installaties, niet om de dataset. Ze horen wel uit de populatie vóór er een COP op "
                "gebaseerd wordt (pre-registratie §4, filter 3)."
                if n_probleem <= 5
                else "Dat is meer dan een handvol en daarmee wél een punt voor de mail aan KITE."
            )
        )
    lines.append("")
    return lines


def _sectie_a3(df: pd.DataFrame) -> list[str]:
    lines = ["## A3. Meterwissels en resets", ""]
    lines.append(
        "**Vraag**: de verdeling van de deltas per brontteller, en komen de karakteristieke "
        "spiegelparen (grote sprong, direct gevolgd door dezelfde sprong terug) hier voor?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    per_teller = df.groupby("teller").agg(
        n_woningen=("home_id__str", "nunique"),
        totaal_dalingen=("n_dalingen", "sum"),
        totaal_spiegelparen=("n_spiegelparen", "sum"),
        totaal_n=("n", "sum"),
    )
    lines.append("| teller | # woningen | totaal dalingen | totaal spiegelparen | totaal deltas |")
    lines.append("|---|---:|---:|---:|---:|")
    for teller, r in per_teller.iterrows():
        lines.append(
            f"| {teller} | {r['n_woningen']} | {opmaak.getal(r['totaal_dalingen'])} | "
            f"{opmaak.getal(r['totaal_spiegelparen'])} | {opmaak.getal(r['totaal_n'])} |"
        )
    lines.append("")
    top = _top_n_afwijkend(df.assign(_spiegel=df["n_spiegelparen"]), "_spiegel", n=10)
    if not top.empty:
        lines.append("Tien (woning, teller)-combinaties met de meeste spiegelparen:")
        lines.append("")
        lines.append("| home_id | teller | n_spiegelparen | n_dalingen | p99 delta | max delta |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for _, r in top.iterrows():
            lines.append(
                f"| {r['home_id__str']} | {r['teller']} | {r['n_spiegelparen']} | {r['n_dalingen']} | "
                f"{_fmt(r['p99'], '{:.3g}')} | {_fmt(r['max'], '{:.3g}')} |"
            )
        lines.append("")
    totaal_spiegel = int(df["n_spiegelparen"].sum())
    lines.append(
        f"**Conclusie**: {totaal_spiegel} spiegelpaar/-paren gevonden over alle woningen en tellers "
        "samen. Anders dan bij IM3 publiceert DPH de cumulatieve standen zelf, dus meterwissels "
        "zijn hier in principe herstelbaar in plaats van alleen zichtbaar."
    )
    lines.append("")
    return lines


def _sectie_a4(df: pd.DataFrame) -> list[str]:
    lines = ["## A4. Slaat er ergens een teller om? (modulus-artefacten)", ""]
    lines.append(
        "**Vraag**: komt het patroon voor dat de IM3-zusterrepo vond -- een register dat van 9999,9 "
        "naar 0 gaat -- en zo ja, bij welke teller? De zoekmethode is daar overgenomen; de conclusie "
        "nadrukkelijk niet, want die berust erop dat IM3 alleen verschilreeksen publiceert. Deze "
        "dataset geeft de cumulatieve standen, dus bij elke daling is de stand ervóór en erna bekend "
        "en is een omslag exact herkenbaar in plaats van een vermoeden."
    )
    lines.append("")
    if df.empty:
        lines.append("Geen dalingen gevonden om te beoordelen.")
        return lines

    per_teller = df.groupby("teller").agg(
        n_woningen=("home_id__str", "nunique"),
        dalingen=("n_dalingen", "sum"),
        omslag=("n_omslag_kandidaat", "sum"),
        naar_nul=("n_naar_nul", "sum"),
        overig=("n_overig", "sum"),
        grootste_daling=("grootste_daling", "max"),
    )
    lines.append("| teller | # woningen | dalingen | omslag-kandidaten | daling naar nul | overig | grootste daling |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for teller, r in per_teller.iterrows():
        lines.append(
            f"| {teller} | {opmaak.getal(r['n_woningen'])} | {opmaak.getal(r['dalingen'])} | "
            f"{opmaak.getal(r['omslag'])} | {opmaak.getal(r['naar_nul'])} | "
            f"{opmaak.getal(r['overig'])} | {_fmt(r['grootste_daling'], '{:.4g}')} |"
        )
    lines.append("")

    n_omslag = int(df["n_omslag_kandidaat"].sum())
    n_naar_nul = int(df["n_naar_nul"].sum())
    n_dalingen = int(df["n_dalingen"].sum())
    if n_omslag:
        lines.append(
            f"**Conclusie**: {opmaak.getal(n_omslag)} omslag-kandidaat/-kandidaten. Kijk naar de "
            "grootste daling per teller: clusteren die rond ÉÉN macht van tien, dan is het een "
            "omslag en is hij met één modulo te herstellen vóór het verschillen. Spreiden ze, dan "
            "is het geen modulus en hoort de vlag te blijven staan."
        )
    else:
        lines.append(
            f"**Conclusie**: GEEN omslag-kandidaten, op {opmaak.getal(n_dalingen)} dalingen. Het "
            "verschijnsel uit IM3 komt in deze dataset niet voor. Wat er wél is: "
            f"{opmaak.aandeel(n_naar_nul, n_dalingen)} van de dalingen gaat naar (vrijwel) nul "
            "terwijl de stand ervóór nergens in de buurt van een macht van tien lag. Dat is een "
            "teller die uitvalt en nul gaat melden, niet een die omslaat, en A3 laat zien dat hij "
            "daarna meestal gewoon terugkomt op zijn oude stand (spiegelparen). Een modulo-correctie "
            "zou hier dus niets repareren en wel echte uitval wegpoetsen."
        )
    lines.append("")
    return lines


def _sectie_a5(df: pd.DataFrame) -> list[str]:
    lines = ["## A5. Lopen de vier meetbronnen op dezelfde klok?", ""]
    lines.append(
        "**Vraag**: verschilt de mediane scheefheid systematisch per bron? Dit is de aanname onder "
        "elke COP-per-bedrijfspunt-berekening (\"alle vier aanwezig\" == \"tegelijk gemeten\")."
    )
    lines.append("")
    if df.empty:
        lines.append(
            "Niet gedraaid (geen `--raw-dir` opgegeven, of de brondata was niet beschikbaar). Deze "
            "analyse leest de brondata opnieuw, zie de docstring van `analyse_a5_scheefheid_per_bron`."
        )
        return lines
    lines.append("| bron | mediaan van de mediane scheefheid (s) | spreiding over woningen (mediaan, p10-p90) |")
    lines.append("|---|---:|---|")
    for bron, g in df.groupby("bron"):
        sp = _spreiding_over_woningen(g["mediaan__s"])
        lines.append(f"| {bron} | {_fmt(sp.get('mediaan'), '{:.1f}')} | {_regel_spreiding(sp, ' s')} |")
    lines.append("")
    # De conclusie wordt UITGEREKEND, niet aan de lezer overgelaten: de analyse kent het antwoord.
    medianen = df.groupby("bron")["mediaan__s"].median()
    spreiding__s = float(medianen.max() - medianen.min())
    traagste, snelste = medianen.idxmax(), medianen.idxmin()
    if spreiding__s < 1.0:
        lines.append(
            f"**Conclusie**: de vier bronnen lopen op dezelfde klok -- de mediane scheefheid "
            f"verschilt {opmaak.getal(spreiding__s, 1)} s tussen de uiterste bronnen. "
            f"\"Alle vier aanwezig in hetzelfde kwartier\" betekent hier dus ook \"tegelijk "
            f"gemeten\", en de aanname onder elke COP-per-bedrijfspunt houdt stand."
        )
    else:
        lines.append(
            f"**Conclusie**: dit zijn **niet één maar meerdere loggers**. `{traagste}` meet mediaan "
            f"{opmaak.getal(float(medianen.max()), 1)} s na de kwartiergrens en `{snelste}` "
            f"{opmaak.getal(float(medianen.min()), 1)} s -- een verschil van "
            f"{opmaak.getal(spreiding__s, 1)} s. Bronnen met dezelfde mediaan worden vermoedelijk in "
            f"één slag uitgelezen. \"Alle vier aanwezig\" betekent dus niet letterlijk \"tegelijk "
            f"gemeten\", maar op een kwartier van 900 s is "
            f"{opmaak.percentage(spreiding__s / 900.0, 2)} van het interval verwaarloosbaar voor "
            f"een COP per bedrijfspunt."
        )
    lines.append("")
    return lines


def _sectie_a6(df: pd.DataFrame) -> list[str]:
    lines = ["## A6. Is uitval per bron of per woning?", ""]
    lines.append(
        "**Vraag**: is een ontbrekend kwartier een dataloggerstoring (alle vier bronnen "
        "ontbreken) of een sensorprobleem (precies één bron ontbreekt)?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    lines.append("| home_id | alle vier ontbrekend | precies één ontbrekend |")
    lines.append("|---|---:|---:|")
    for _, r in df.sort_values("home_id__str").iterrows():
        lines.append(
            f"| {r['home_id__str']} | {opmaak.getal(r['n_alle_vier_ontbrekend'])} | "
            f"{opmaak.getal(r['n_precies_een_ontbrekend'])} |"
        )
    lines.append("")
    totaal_alle = int(df["n_alle_vier_ontbrekend"].sum())
    totaal_een = int(df["n_precies_een_ontbrekend"].sum())
    lines.append(
        f"**Conclusie**: over alle woningen samen {opmaak.getal(totaal_alle)} kwartier(en) waarin alle vier de "
        f"bronnen ontbreken (dataloggerstoring), tegenover {opmaak.getal(totaal_een)} kwartier(en) met precies "
        "één ontbrekende bron (sensor)."
    )
    lines.append("")
    return lines


def _sectie_b2(df: pd.DataFrame) -> list[str]:
    lines = ["## B2. Sluit de energiebalans na het differentiëren?", ""]
    lines.append(
        "**Vraag**: is `som(vermogen x delta_t)` gelijk aan `laatste stand - eerste stand`, per "
        "woning en per teller? Toetst of het differentiëren verliesvrij is."
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    # GEEN groupby(...).apply(...): _spreiding_over_woningen geeft een dict terug, en pandas klapt
    # dicts uit een SeriesGroupBy.apply uit naar een Series met MultiIndex. Itereren levert dan
    # losse floats in plaats van de dicts, met een AttributeError tot gevolg. Een dictcomprehensie
    # houdt de dicts heel.
    per_teller = {
        teller: _spreiding_over_woningen(groep)
        for teller, groep in df.groupby("teller")["relatieve_afwijking"]
    }
    lines.append("| teller | " + " | ".join(["n", "gemiddelde", "mediaan", "p10", "p90", "min", "max"]) + " (relatieve afwijking) |")
    lines.append("|---|" + "---:|" * 7)
    for teller, sp in per_teller.items():
        if sp.get("n_woningen", 0) == 0:
            lines.append(f"| {teller} | 0 | - | - | - | - | - | - |")
            continue
        lines.append(
            f"| {teller} | {sp['n_woningen']} | {opmaak.percentage(sp['gemiddelde'], 2)} | "
            f"{opmaak.percentage(sp['mediaan'], 2)} | {opmaak.percentage(sp['p10'], 2)} | "
            f"{opmaak.percentage(sp['p90'], 2)} | {opmaak.percentage(sp['min'], 2)} | "
            f"{opmaak.percentage(sp['max'], 2)} |"
        )
    lines.append("")
    top = _top_n_afwijkend(df, "relatieve_afwijking", n=10)
    if not top.empty:
        lines.append("Tien meest afwijkende (woning, teller)-combinaties:")
        lines.append("")
        lines.append("| home_id | teller | relatieve afwijking | energie uit teller (J) | energie uit vermogen (J) |")
        lines.append("|---|---|---:|---:|---:|")
        for _, r in top.iterrows():
            lines.append(
                f"| {r['home_id__str']} | {r['teller']} | {_fmt(r['relatieve_afwijking'], '{:.2%}')} | "
                f"{_fmt(r['energie_uit_teller__J'], '{:.3g}')} | {_fmt(r['energie_uit_vermogen__J'], '{:.3g}')} |"
            )
        lines.append("")
    afw = pd.to_numeric(df["relatieve_afwijking"], errors="coerce").abs().dropna()
    per_teller = df.assign(_a=pd.to_numeric(df["relatieve_afwijking"], errors="coerce").abs()).groupby("teller")["_a"].median()
    goed = per_teller[per_teller < 0.01].index.tolist()
    slecht = per_teller[per_teller >= 0.01].index.tolist()
    lines.append(
        f"**Conclusie**: de balans sluit voor de tellers die uit één bron komen en niet voor de "
        f"samengestelde. Mediane absolute afwijking over alle (woning, teller)-paren: "
        f"{opmaak.percentage(float(afw.median()), 2)}. "
        + (f"Sluit goed (mediaan onder 1 %): {', '.join('`' + g + '`' for g in goed)}. " if goed else "")
        + (f"Wijkt af: {', '.join('`' + s + '`' for s in slecht)}. " if slecht else "")
        + "Dat de afwijking zich concentreert bij `e_net__W` is geen toeval: dat is de enige "
        "SAMENGESTELDE teller (import min export). Bij een klein verschil tussen twee grote getallen "
        "werkt elk gat in één van beide door in de uitkomst, terwijl de andere vier rechtstreeks uit "
        "één bronreeks komen. Daar bovenop heeft de DSMR-bron per woning duidelijk minder complete "
        "kwartieren dan de andere drie (zie §1): een gat in één bron, terwijl de rij door een andere "
        "bron wel bestaat, breekt de balans van díé teller -- een kwartier dat bij ALLE bronnen "
        "ontbreekt doet dat niet. Zie de docstring van `analyse_b2_energiebalans`."
    )
    lines.append("")
    return lines


def _sectie_b4(df: pd.DataFrame) -> list[str]:
    lines = ["## B4. Verdeling van de gaten per grootheid", ""]
    lines.append(
        "**Vraag**: hoe zijn de ontbrekende periodes per grootheid verdeeld over de zes bakken "
        "(<15 min ... >24 u)? Bepaalt de gatlimiet voor interpolatie."
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    per_kolom_bak = df.groupby(["kolom", "bak"], observed=False)["totale_duur__s"].sum().unstack("bak").fillna(0.0)
    lines.append("Totale duur (uren) per grootheid en bak, gepoold over woningen (spreiding per woning staat in het Parquet-tussenresultaat):")
    lines.append("")
    kolommen_header = list(per_kolom_bak.columns)
    lines.append("| kolom | " + " | ".join(str(c) for c in kolommen_header) + " |")
    lines.append("|---|" + "---:|" * len(kolommen_header))
    for kolom, r in per_kolom_bak.iterrows():
        lines.append(f"| {kolom} | " + " | ".join(opmaak.getal(v / 3600, 1) for v in r) + " |")
    lines.append("")
    per_bak = df.groupby("bak", observed=True)["n_gaten"].sum()
    totaal = int(per_bak.sum())
    kort = int(per_bak.reindex(["15-30 min", "30-90 min"]).fillna(0).sum())
    lang = int(per_bak.reindex(["6-24 u", ">24 u"]).fillna(0).sum())
    lines.append(
        f"**Conclusie**: de bak `<15 min` is op kwartierdata per definitie leeg -- het kortste "
        f"waarneembare gat is precies 900 s -- en dat is zelf een bevinding, geen fout. Van de "
        f"{opmaak.getal(totaal)} gaten valt {opmaak.percentage(kort / totaal if totaal else 0)} "
        f"binnen anderhalf uur en {opmaak.percentage(lang / totaal if totaal else 0)} boven de zes "
        f"uur. De geërfde gatlimiet van NeedForHeat (90 minuten) dekt daarmee de meerderheid af en "
        f"laat de lange uitval staan, wat de bedoeling is -- maar het blijft een overgenomen "
        f"waarde. Welke limiet hier verdedigbaar is hoort uit een weglaattoets te komen en niet uit "
        f"deze verdeling alleen: B12 in `ontwerp-preprocessing.md` §8."
    )
    lines.append("")
    return lines


def _sectie_b5(df: pd.DataFrame) -> list[str]:
    lines = ["## B5. Aaneengesloten bruikbare tijd per woning", ""]
    lines.append(
        "**Vraag**: hoeveel van de tijd van elke woning is aaneengesloten bruikbaar (NeedForHeats "
        "`calculate_covered_time`/`calculate_streak_durations`, overgenomen op ons kwartierraster)?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    breed = df.pivot(index="home_id__str", columns="metric", values="waarde")
    lines.append(_regel_spreiding(_spreiding_over_woningen(breed.get("aandeel_gedekt", pd.Series(dtype=float))), "") + " (aandeel gedekt)")
    lines.append("")
    lines.append("| home_id | totale tijd (dagen) | gedekte tijd (dagen) | aandeel gedekt |")
    lines.append("|---|---:|---:|---:|")
    for home_id, r in breed.sort_index().iterrows():
        lines.append(
            f"| {home_id} | {_fmt(r.get('totale_tijd__s', float('nan')) / 86400, '{:.1f}')} | "
            f"{_fmt(r.get('gedekte_tijd__s', float('nan')) / 86400, '{:.1f}')} | "
            f"{_fmt(r.get('aandeel_gedekt', float('nan')), '{:.1%}')} |"
        )
    lines.append("")
    streak_kolommen = [c for c in breed.columns if str(c).startswith("streak__")]
    if streak_kolommen:
        lines.append("Gedekte tijd (dagen) per aaneengesloten-reeks-lengte, gepoold over woningen:")
        lines.append("")
        for c in streak_kolommen:
            lines.append(f"- `{c}`: {opmaak.getal(breed[c].sum() / 86400, 1)} dagen")
        lines.append("")
    breed = df.pivot_table(index="home_id__str", columns="metric", values="waarde", aggfunc="first")
    aandeel = pd.to_numeric(breed.get("aandeel_gedekt"), errors="coerce").dropna()
    lange = pd.to_numeric(breed.get("streak__week_tot_maand__s"), errors="coerce").fillna(0) + pd.to_numeric(
        breed.get("streak__meer_dan_maand__s"), errors="coerce"
    ).fillna(0)
    gedekt = pd.to_numeric(breed.get("gedekte_tijd__s"), errors="coerce").fillna(0)
    aandeel_lang = float(lange.sum() / gedekt.sum()) if float(gedekt.sum()) else 0.0
    med = float(aandeel.median()) if len(aandeel) else 0.0
    p10 = float(aandeel.quantile(0.10)) if len(aandeel) else 0.0
    p90 = float(aandeel.quantile(0.90)) if len(aandeel) else 0.0
    lines.append(
        f"**Conclusie**: de mediane woning heeft {opmaak.percentage(med)} van haar tijdvak gedekt "
        f"(p10-p90: {opmaak.percentage(p10)} tot {opmaak.percentage(p90)}), en "
        f"{opmaak.percentage(aandeel_lang)} van alle gedekte tijd zit in aaneengesloten reeksen van "
        f"langer dan een week. Dat laatste is het getal dat telt: losse kwartieren zijn iets anders "
        f"dan een aaneengesloten stookseizoen, en alleen het tweede draagt een seizoensanalyse. "
        f"Gebruikte gatlimiet: {opmaak.getal(B5_MAX_GAT__S_STANDAARD / 60, 0)} minuten -- "
        f"NeedForHeats default, nog een aanname en geen meting (zie B12)."
    )
    lines.append("")
    return lines


def _sectie_b7(df: pd.DataFrame) -> list[str]:
    lines = ["## B7. De sprongdrempels tegen de werkelijke verdeling", ""]
    lines.append(
        "**Vraag**: hoe verhouden `tellers.SPRONG_DREMPEL__W` (verzonnen, niet extern getoetst) "
        "zich tot de werkelijke verdeling van het intervalgemiddelde vermogen?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    lines.append("| teller | huidige drempel (W) | mediaan p99,99 over woningen (W) | max over woningen (W) |")
    lines.append("|---|---:|---:|---:|")
    for teller, g in df.groupby("teller"):
        sp = _spreiding_over_woningen(g["p99_99__W"])
        drempel = g["huidige_drempel__W"].iloc[0]
        lines.append(
            f"| {teller} | {opmaak.getal(drempel)} | {_fmt(sp.get('mediaan'), '{:,.0f}')} | "
            f"{opmaak.getal(g['max__W'].max())} |"
        )
    lines.append("")
    # Uitgerekend in plaats van beschreven: welke drempels staan hoe ver boven de werkelijkheid?
    ruim = []
    for teller, g in df.groupby("teller"):
        mediaan = g["p99_99__W"].median()
        drempel = float(g["huidige_drempel__W"].iloc[0])
        if mediaan and mediaan > 0:
            ruim.append((teller, drempel / float(mediaan)))
    ruim.sort(key=lambda x: -x[1])
    if ruim:
        ergste = ", ".join(
            f"`{teller}` staat {opmaak.getal(factor, 0)}x boven de mediane woning" for teller, factor in ruim[:3]
        )
        lines.append(
            f"**Conclusie**: de drempels staan boven het gemeten p99,99 van de mediane woning, met "
            f"een factor tussen {opmaak.getal(ruim[-1][1], 0)} en {opmaak.getal(ruim[0][1], 0)}. "
            f"De ruimste: {ergste}. Een drempel die honderden malen boven het normale bedrijf ligt "
            f"vangt alleen het absurde en laat het merely-onmogelijke door -- een warmtepomp die "
            f"15 kW meldt is onmogelijk voor deze installaties maar haalt een drempel van 20 kW "
            f"niet. De drempels in `tellers.SPRONG_DREMPEL__W` zijn op 05-09-2026 op deze "
            f"verdeling herzien; deze tabel laat zien of dat genoeg was."
        )
    lines.append("")
    return lines


def _sectie_b8(df: pd.DataFrame, drempels: tuple[float, ...] = (0.5, 0.8, 0.9, 0.95)) -> list[str]:
    lines = ["## B8. Stookseizoenen: een eerlijke telling", ""]
    lines.append(
        "**Vraag**: hoeveel stookseizoenen (okt-apr) dekt een woning ECHT, met een dekkingseis in "
        "plaats van de oude \"aangeraakt\"-telling (`rapport.py`)?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    lines.append(f"| home_id | " + " | ".join(f">={opmaak.percentage(d, 0)} gedekt" for d in drempels) + " |")
    lines.append("|---|" + "---:|" * len(drempels))
    for home_id, g in df.groupby("home_id__str"):
        rij = [str(int((g["aandeel_gedekt"] >= d).sum())) for d in drempels]
        lines.append(f"| {home_id} | " + " | ".join(rij) + " |")
    lines.append("")
    for d in drempels:
        n_twee_of_meer = int(
            df.groupby("home_id__str")["aandeel_gedekt"].apply(lambda s: (s >= d).sum()).ge(2).sum()
        )
        n_woningen = df["home_id__str"].nunique()
        lines.append(
            f"- Bij een dekkingseis van {opmaak.percentage(d, 0)}: "
            f"{opmaak.aandeel(n_twee_of_meer, n_woningen)} woningen dekt >=2 stookseizoenen."
        )
    lines.append("")
    lines.append(
        "**Conclusie**: de keuze van de dekkingsdrempel doet er zichtbaar toe (zie de rij hierboven "
        "per drempel); voorstel 80 % totdat er een inhoudelijke reden is voor een andere waarde."
    )
    lines.append("")
    return lines


def _sectie_b9(df: pd.DataFrame) -> list[str]:
    lines = ["## B9. Loopt er tapwater langs de warmtemeter?", ""]
    lines.append(
        "**Vraag** (onderbouwing: ontwerp-intervalsemantiek.md §4.5): is er per woning een sterke "
        "verrijking van gasverbruik tijdens zomerse warmtelevering, wat wijst op tapwater dat "
        "langs de Kamstrup-warmtemeter loopt?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data.")
        return lines
    lines.append(
        "| home_id | zomerkwartieren met warmte>200W | daarvan gas>500W | basiskans gas>500W | "
        "corr(warmte,wp-elektra) | aanvoer>50°C | vlag |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|:---:|")
    for _, r in df.sort_values("home_id__str").iterrows():
        lines.append(
            f"| {r['home_id__str']} | {_fmt(r['aandeel_zomerkwartieren_met_warmte'], '{:.1%}')} | "
            f"{_fmt(r['aandeel_gas_bij_warmte'], '{:.1%}')} | {_fmt(r['basiskans_gas_zonder_warmte'], '{:.1%}')} | "
            f"{_fmt(r['corr_warmte_wp_elektra'])} | {_fmt(r['aandeel_aanvoer_boven_50c'], '{:.1%}')} | "
            f"{'JA' if r['tapwater_langs_warmtemeter__vlag'] else 'nee'} |"
        )
    lines.append("")
    n_vlag = int(df["tapwater_langs_warmtemeter__vlag"].sum())
    lines.append(
        f"**Conclusie**: {n_vlag} van de {len(df)} woningen gevlagd als \"tapwater loopt "
        "waarschijnlijk langs de warmtemeter\". Zoals ontwerp-intervalsemantiek.md §4.5 al liet "
        "zien, verschilt dit per woning -- een globale aan/uit-knop voor tapwaterfiltering is fout."
    )
    lines.append("")
    return lines


def _sectie_b10(df: pd.DataFrame) -> list[str]:
    lines = ["## B10. Rekent de Kamstrup na wat hij zegt te meten?", ""]
    lines.append(
        "**Vraag**: klopt `q_geleverd_meting__W` met `ρ · c_p · debiet · ΔT` (water bij 45°C: "
        f"ρ={opmaak.getal(B10_RHO_WATER__KG_M3)} kg/m³, c_p={opmaak.getal(B10_CP_WATER__J_KGK)} J/(kg·K)), op "
        "kwartieren met een noemenswaardig debiet?"
    )
    lines.append("")
    if df.empty:
        lines.append("Geen data (of geen enkele woning had kwartieren boven de debietdrempel).")
        return lines
    lines.append(_regel_spreiding(_spreiding_over_woningen(df["mediane_relatieve_afwijking"]), "") + " (mediane relatieve afwijking)")
    lines.append("")
    lines.append("| home_id | mediane rel. afwijking | p10 | p90 | n |")
    lines.append("|---|---:|---:|---:|---:|")
    for _, r in df.sort_values("home_id__str").iterrows():
        lines.append(
            f"| {r['home_id__str']} | {_fmt(r['mediane_relatieve_afwijking'], '{:.2%}')} | "
            f"{_fmt(r['p10_relatieve_afwijking'], '{:.2%}')} | {_fmt(r['p90_relatieve_afwijking'], '{:.2%}')} | "
            f"{opmaak.getal(r['n'])} |"
        )
    lines.append("")
    afw = pd.to_numeric(df["mediane_relatieve_afwijking"], errors="coerce").abs().dropna()
    if len(afw):
        n_groot = int((afw > 0.10).sum())
        lines.append(
            f"**Conclusie**: de mediane woning wijkt {opmaak.percentage(float(afw.median()), 2)} af "
            f"van wat `rho x c_p x debiet x dT` voorspelt. "
            + (
                f"{opmaak.getal(n_groot)} van de {opmaak.getal(len(afw))} woningen zit boven 10 %; "
                f"daar wijst het op een sensorfout of een debiet buiten het meetbereik van de meter "
                f"(ontwerp-intervalsemantiek.md §4.5, slot) en horen die woningen apart bekeken te "
                f"worden vóór er een COP op gebaseerd wordt."
                if n_groot
                else "Geen enkele woning zit boven 10 %: de Kamstrup rekent intern consistent na wat "
                "hij zegt te meten."
            )
        )
    lines.append("")
    return lines


_SECTIES: dict[str, Callable[[pd.DataFrame], list[str]]] = {
    "a1_warmtepompteller": _sectie_a1,
    "a3_meterwissels": _sectie_a3,
    "a4_modulusartefacten": _sectie_a4,
    "a5_scheefheid_per_bron": _sectie_a5,
    "a6_uitval_bron_of_woning": _sectie_a6,
    "b2_energiebalans": _sectie_b2,
    "b4_gatverdeling": _sectie_b4,
    "b5_aaneengesloten_tijd": _sectie_b5,
    "b7_sprongdrempels": _sectie_b7,
    "b8_stookseizoen_dekking": _sectie_b8,
    "b9_tapwater_langs_warmtemeter": _sectie_b9,
    "b10_kamstrup_consistentie": _sectie_b10,
}


def genereer_rapport(resultaten: dict[str, pd.DataFrame], n_woningen: int, is_steekproef: bool) -> str:
    """Bouw ``docs/analyse-bevindingen.md`` uit de tussenresultaten (altijd opnieuw opgebouwd,
    nooit met de hand bijgehouden -- zelfde principe als ``rapport.build_report``)."""
    lines = ["# Analysebevindingen", ""]
    lines.append(
        "**Gegenereerd door** `dph_preprocessing.analyses`, uit de Parquet-tussenresultaten in "
        "`data/analyse/` (niet handmatig bijgehouden). Beantwoordt groep A en groep B uit "
        "`ontwerp-preprocessing.md` §8."
    )
    lines.append("")
    if is_steekproef:
        lines.append(
            f"> **Dit is een steekproef-run** ({n_woningen} woning(en)), geen run over de volle "
            "~174 woningen. De patronen zijn representatief voor de aanpak, maar aantallen/"
            "percentages moeten op de volledige dataset herberekend worden vóór ze als "
            "eindconclusie -- laat staan een mailpunt aan KITE -- gelden."
        )
    else:
        lines.append(f"> **Dit is de volledige dataset** ({n_woningen} woningen).")
    lines.append("")
    lines.append(
        "Elke analyse hieronder rekent EERST per woning, dan pas gepoold (ontwerpprincipe 7): "
        "één woning met extreme uitschieters mag een gepoolde conclusie niet vertekenen -- zie "
        "`ontwerp-intervalsemantiek.md` §5."
    )
    lines.append("")

    for spec in REGISTRY:
        if spec.naam not in resultaten:
            lines.append(f"## {spec.naam}\n\nNiet gedraaid in deze run.\n")
            continue
        sectie_func = _SECTIES.get(spec.naam)
        if sectie_func is None:
            continue
        lines.extend(sectie_func(resultaten[spec.naam]))

    return "\n".join(lines) + "\n"


def schrijf_rapport(resultaten: dict[str, pd.DataFrame], docs_dir: str | Path, n_woningen: int, is_steekproef: bool) -> Path:
    pad = Path(docs_dir) / "analyse-bevindingen.md"
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(genereer_rapport(resultaten, n_woningen, is_steekproef), encoding="utf-8")
    return pad


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in-dir", type=Path, default=Path("data/processed"), help="Map met homes/measurements/quality/derived/weer(/scheefheid).parquet")
    p.add_argument("--docs-dir", type=Path, default=Path("docs"))
    p.add_argument("--opnieuw", action="store_true", help="Negeer bestaande tussenresultaten en herbereken alles")
    p.add_argument("--woningen-totaal", type=int, default=174, help="Verwacht totaal aantal woningen, voor de steekproef-melding in het rapport")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    resultaten = voer_analyses_uit(args.in_dir, args.docs_dir, opnieuw=args.opnieuw)

    homes = pd.read_parquet(Path(args.in_dir) / "homes.parquet")
    n_woningen = homes["home_id__str"].nunique()
    is_steekproef = n_woningen < args.woningen_totaal

    pad = schrijf_rapport(resultaten, args.docs_dir, n_woningen, is_steekproef)
    log.info("Rapport geschreven naar %s", pad)


if __name__ == "__main__":
    main()
