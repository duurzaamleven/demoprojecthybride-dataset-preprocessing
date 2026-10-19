# SPDX-License-Identifier: EUPL-1.2
"""De vijf tabellen (homes/measurements/weer/quality/derived) opbouwen, conform
``docs/variable-dictionary.md`` (ontwerp-preprocessing.md §4).

**Rijspil van measurements/quality/derived (interpretatiekeuze, niet letterlijk in het ontwerp
vastgelegd -- zie het eindrapport van deze implementatie):** anders dan bij IM3 (één CSV per
woning) levert deze dataset één CSV per meetbron, met vier bronnen die een cumulatieve teller
dragen (``dsmr``, ``kamstrup``, ``heatpump``, ``boiler`` -- exact :data:`~dph_preprocessing.
quality.COP_BRONNEN`). De rijenverzameling van ``measurements``/``quality``/``derived`` is de UNIE
van de door deze vier bronnen waargenomen kwartieren per woning (via een outer-merge), aangevuld
met een volledig kwartierrooster in ``quality`` (:func:`~dph_preprocessing.quality.bouw_tijdas`) zodat
een kwartier zonder ENKELE van de vier bronnen zichtbaar blijft als ``ontbrekend__bool``-rij in
plaats van gewoon te ontbreken uit de tabel. ``room.csv`` (binnentemperatuur) en de weerkoppeling
worden op diezelfde rijenspil GEKOPPELD (left-join): een kwartier waarin uitsluitend ``room.csv``
iets meet, maar geen van de vier telelrbronnen, komt dus NIET als eigen rij terug.
"""

from __future__ import annotations

import logging

import pandas as pd

from . import gaskwaliteit
from .quality import COP_BRONNEN, bouw_tijdas, bron_incompleet_masker, or_vlaggen, scheef_masker
from .tellers import (
    GJ_NAAR_J,
    INITIALISATIETELEGRAM_SENTINEL,
    J_PER_KWH,
    SPRONG_DREMPEL__W,
    differentieer_teller,
    is_initialisatietelegram,
    teller_gestegen_masker,
    teller_sprong_masker,
    verwerk_bronteller,
)
from .timestamps import resolve_timestamps

log = logging.getLogger(__name__)

KW_NAAR_W = 1000.0
LH_NAAR_DM3S = 1.0 / 3600.0
#: J/cm² per uur -> W/m²: 1 J/cm² = 10^4 J/m², gedeeld door 3600 s. De waarde is een GEMIDDELDE
#: INSTRALING over dat uur, dus een flow -- geen energietotaal. Deel hier niet door 1000 en noem het
#: veld niet ``ghi__kWh_m_2``: voor een uurwaarde is die naam numeriek nog te verdedigen, maar zodra
#: er over een dag gemiddeld wordt klopt hij niet meer. Zie ontwerp-intervalsemantiek.md §6.
GHI_J_CM2_UUR_NAAR_W_M2 = (100 * 100) / (60 * 60)
TIENDE_NAAR_EENHEID = 0.1


def _dedupliceer_op_kwartier(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Bij een (zeldzame) dubbele meting binnen hetzelfde kwartier van dezelfde bron: houd de
    LAATSTE (dichtst bij het einde van het kwartier -- de meest representatieve stand voor een
    cumulatieve teller). ``metadata.csv`` zegt expliciet "One sample per 15 minutes is included in
    this dataset", dus dit zou zelden/nooit moeten voorkomen; als het toch gebeurt is het een
    telbare bevinding, geen fout. Retourneert ook het aantal getroffen rijen, voor het rapport.
    """
    dubbel = df.duplicated(["home_id__str", "tijdstip_start"], keep=False)
    n_dubbel = int(dubbel.sum())
    schoon = df.sort_values("tijdstip_meting").drop_duplicates(
        ["home_id__str", "tijdstip_start"], keep="last"
    )
    return schoon, n_dubbel


#: Kolommen van :func:`bouw_scheefheid_samenvatting` -- ook de vaste vorm van
#: ``data/processed/scheefheid.parquet`` en van ``analyses.analyse_a5_scheefheid_per_bron``'s
#: uitvoer, die dit ongewijzigd doorgeeft.
SCHEEFHEID_KOLOMMEN: tuple[str, ...] = ("home_id__str", "bron", "mediaan__s", "p95__s", "max__s", "n")


def bouw_scheefheid_samenvatting(resolved_per_bron: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per woning en per bron de samenvatting (mediaan/p95/max/n) van ``scheefheid__s``, uit
    AL ``resolveer_domein``'de DataFrames (sleutel van ``resolved_per_bron`` is de bronnaam zonder
    ``.csv``, bv. ``"dsmr"``).

    **Waarom dit een eigen, apart bewaarde tabel is (i.p.v. de scheefheid gewoon in
    ``measurements`` te laten staan).** :func:`build_measurements_en_quality` berekent de
    scheefheid per bron toch al (nodig voor ``scheef__bool``), maar gooit 'm daarna weg: de
    outer-merge naar de rijenspil van ``measurements`` houdt maar ÉÉN ``tijdstip_meting`` (dus ook
    maar één scheefheid) per kwartier over, met een vaste prioriteit dsmr > kamstrup > heatpump >
    boiler -- voor een kwartier waarin alle vier de bronnen aanwezig zijn is dat altijd dsmr's
    scheefheid, nooit die van de andere drie (zie ``analyses.analyse_a5_scheefheid_per_bron``'s
    docstring). Deze
    samenvatting bewaart precies genoeg om die vraag ("lopen de vier bronnen op dezelfde klok?")
    achteraf te beantwoorden, zonder de volledige scheefheid-samples (11,5 M rijen, één per
    ``measurements``-rij x 4 bronnen) te hoeven bewaren: één rij per (woning, bron) -- voor de
    volledige dataset 174 x 4 = 696 rijen, een fractie van de brondata. Wie ooit de VOLLEDIGE
    verdeling nodig heeft (niet alleen mediaan/p95/max) moet nog steeds de brondata lezen; voor de
    per-woning-vraag die A5 stelt is dat niet nodig.

    Wordt aangeroepen vanuit ``pipeline._verwerk_en_schrijf_chunk`` op de resolved-frames die daar
    toch al in geheugen staan (geen extra I/O), en resultaat per chunk weggeschreven als
    ``data/processed/parts/scheefheid/chunk_<nnn>.parquet`` -- zie ``chunking.PARTS_TABELLEN``'s
    module-docstring voor waarom dit BEWUST geen verplicht deel van de vijf contracttabellen is.
    """
    rijen = []
    for bron_naam, resolved in resolved_per_bron.items():
        for home_id, g in resolved.groupby("home_id__str", sort=True):
            s = g["scheefheid__s"].dropna()
            if s.empty:
                continue
            rijen.append(
                {
                    "home_id__str": home_id,
                    "bron": bron_naam,
                    "mediaan__s": s.median(),
                    "p95__s": s.quantile(0.95),
                    "max__s": s.max(),
                    "n": int(len(s)),
                }
            )
    if not rijen:
        return pd.DataFrame(columns=list(SCHEEFHEID_KOLOMMEN))
    return pd.DataFrame(rijen)[list(SCHEEFHEID_KOLOMMEN)]


def resolveer_domein(raw: pd.DataFrame) -> pd.DataFrame:
    """Voeg ``tijdstip_start``/``tijdstip_meting``/``scheefheid__s`` toe aan een ruwe, per-domein
    DataFrame (na filtering in :mod:`dph_preprocessing.bron`), en dedupliceer op
    (``home_id__str``, ``tijdstip_start``). De ruwe ``timestamp``-kolom wordt vervangen.
    """
    werk = raw.copy()
    tijden = resolve_timestamps(werk["timestamp"])
    werk["tijdstip_start"] = tijden["tijdstip_start"].to_numpy()
    werk["tijdstip_meting"] = tijden["tijdstip_meting"].to_numpy()
    werk["scheefheid__s"] = tijden["scheefheid__s"].to_numpy()
    werk = werk.drop(columns=["timestamp"])
    schoon, n_dubbel = _dedupliceer_op_kwartier(werk)
    if n_dubbel:
        log.warning(
            "%d rij(en) delen een kwartier met een andere meting van dezelfde bron; laatste gehouden",
            n_dubbel,
        )
    return schoon


# --- homes ---------------------------------------------------------------------------------

_HOMES_CAT = {
    "house_type": "woningtype__cat",
    "construction_year": "bouwjaar_klasse__cat",
    "surface": "oppervlak_klasse__cat",
    "energylabel": "energielabel__cat",
    "number_of_inhabitants": "bewoners__cat",
    "ownership": "eigendom__cat",
}
_HOMES_NUM__KWH_OF_M3 = {
    "gas_before_2": "gas_voor_2__m3",
    "gas_before_1": "gas_voor_1__m3",
    "electricity_before_2": "elektra_voor_2__kWh",
    "electricity_before_1": "elektra_voor_1__kWh",
}
_HOMES_BOOL = {
    "has_low_heat_floor_heating": "heeft_vloerverwarming__bool",
    "has_high_heat_radiator_heating": "heeft_radiatoren__bool",
    "has_gas_furnace": "heeft_gasfornuis__bool",
    "has_double_paned_glass": "heeft_dubbelglas__bool",
    "has_roofinsulation": "heeft_dakisolatie__bool",
    "has_wallinsulation": "heeft_muurisolatie__bool",
    "has_floorinsulation": "heeft_vloerisolatie__bool",
}


def build_homes(homes_ruw: pd.DataFrame) -> pd.DataFrame:
    """``household.csv`` (sleutel ``participant_id``) -> ``homes`` (sleutel ``home_id__str``).

    ``wrong_elec_measurement`` (bron: metadata.csv, niet in `docs/variable-dictionary.md` zelf
    gedocumenteerd -- de betekenis komt uit `notebooks/README.md` van het analysepakket) wordt hier
    meegenomen als ``elektrameting_verdacht__cat``: ``"0"`` = de elektriciteitsmeting van de
    warmtepomp is bruikbaar, ``"1"`` = onbruikbaar, ``"2"`` = tijdens het project gerepareerd
    (ontwerp §8, A2). Als STRING-categorie, niet als getal: het zijn drie labels, geen schaal
    waarop opgeteld/gemiddeld mag worden.
    """
    homes = pd.DataFrame({"home_id__str": homes_ruw["participant_id"].astype(str)})
    for ruw, naam in _HOMES_CAT.items():
        homes[naam] = homes_ruw[ruw].astype("category")
    for ruw, naam in _HOMES_NUM__KWH_OF_M3.items():
        homes[naam] = homes_ruw[ruw].astype("float32")
    for ruw, naam in _HOMES_BOOL.items():
        # Nullable boolean: has_* zijn 0/1-int in de bron (geen NaN aangetroffen, 26-aug-2026),
        # maar nullable voorkomt een stille cast-fout mocht dat ooit toch gebeuren.
        homes[naam] = homes_ruw[ruw].astype("boolean")
    homes["elektrameting_verdacht__cat"] = (
        homes_ruw["wrong_elec_measurement"].astype("int64").astype(str).astype("category")
    )
    return homes.sort_values("home_id__str").reset_index(drop=True)


# --- measurements + quality + vermogens (voor derived) --------------------------------------

_DSMR_TELLERS = {
    "e_consumed_low": "e_import_laag_cum__kWh",
    "e_consumed_high": "e_import_hoog_cum__kWh",
    "e_delivered_low": "e_export_laag_cum__kWh",
    "e_delivered_high": "e_export_hoog_cum__kWh",
    "v_gas_consumed": "g_gebruik_cum__m3",
}
_KAMSTRUP_TELLER = {"e_thermal_system": "e_thermal_system__GJ"}
_HEATPUMP_TELLER = {"heatpump_energy": "e_warmtepomp_cum__kWh"}
_BOILER_TELLER = {"boiler_energy": "e_ketel_cum__kWh"}


def build_measurements_en_quality(
    dsmr_r: pd.DataFrame,
    kamstrup_r: pd.DataFrame,
    heatpump_r: pd.DataFrame,
    boiler_r: pd.DataFrame,
    gas_hhv: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Bouw ``measurements``, ``quality`` en een intern ``vermogens``-hulptabel (voor ``derived``)
    uit de vier al-``resolveer_domein``'de tellerbronnen.

    Retourneert ``(measurements, quality, vermogens)``. ``vermogens`` is geen van de vijf
    contract-tabellen; het draagt ``e_net__W``/``g_gebruik__W``/``p_warmtepomp__W``/
    ``p_ketel__W``/``q_geleverd__W`` door naar :func:`build_derived`, zodat de teller-differentiatie
    niet twee keer gebeurt, plus de toegepaste calorische gaswaarde en haar herkomst.

    ``gas_hhv``: de per-uur opgehaalde calorische waarde uit
    :func:`~dph_preprocessing.gaskwaliteit.fetch_actual_gas_hhv`. ``None`` of leeg betekent dat
    ``g_gebruik__W`` overal op :data:`~dph_preprocessing.gaskwaliteit.
    GAS_CALORISCHE_WAARDE_FALLBACK__J_M3` terugvalt; dat is dan geen stille aanname, want
    ``gas_hhv_bron__cat`` legt het per rij vast en het rapport telt het.

    **``teller_terug__bool`` gaat over de ECHTE bronttellers, niet over ``e_net`` (ontwerp §8,
    B3).** ``e_net = e_import - e_export`` is een SAMENGESTELDE teller die legitiem kan dalen
    (teruglevering van zonnestroom verhoogt de exportteller, en dus daalt het verschil). Gemeten
    op de steekproef: alle 39.612 dalingen van ``e_net`` vielen samen met een stijging van de
    exportteller diezelfde kwartier -- de oude, over ``e_net`` meegetelde vlag was dus vrijwel
    zuiver een zonneschijnindicator, geen meteruitval-indicator. De vlag wordt hier bepaald over de
    acht echte bronttellers (``e_import_laag/hoog_cum__kWh``, ``e_export_laag/hoog_cum__kWh``,
    ``g_gebruik_cum__m3``, ``e_warmtepomp_cum__kWh``, ``e_ketel_cum__kWh``, ``q_geleverd_cum__J``) en pas daarna
    OR-gecombineerd; ``teruglevering__bool`` maakt de weggelaten informatie (een exportteller die
    stijgt) apart bruikbaar in plaats van hem te laten verdwijnen.
    """
    kolommen_per_bron = {
        "dsmr": (dsmr_r, _DSMR_TELLERS),
        "kamstrup": (kamstrup_r, _KAMSTRUP_TELLER),
        "heatpump": (heatpump_r, _HEATPUMP_TELLER),
        "boiler": (boiler_r, _BOILER_TELLER),
    }

    frames = {}
    for naam, (raw, tellers) in kolommen_per_bron.items():
        basis = ["home_id__str", "tijdstip_start", "tijdstip_meting", "scheefheid__s"]
        df = raw[basis + list(tellers)].rename(columns=tellers)
        df = df.rename(
            columns={
                "tijdstip_meting": f"tijdstip_meting__{naam}",
                "scheefheid__s": f"scheefheid__{naam}__s",
            }
        )
        frames[naam] = df

    measurements = frames["dsmr"]
    for naam in ("kamstrup", "heatpump", "boiler"):
        measurements = measurements.merge(frames[naam], on=["home_id__str", "tijdstip_start"], how="outer")

    measurements["q_geleverd_cum__J"] = (measurements["e_thermal_system__GJ"] * GJ_NAAR_J).astype("float32")
    measurements = measurements.drop(columns=["e_thermal_system__GJ"])

    aanwezig = {naam: measurements[f"tijdstip_meting__{naam}"].notna() for naam in COP_BRONNEN}

    # Eén tijdstip_meting-kolom in de output (het ontwerp noemt geen regel voor het geval meerdere
    # bronnen in hetzelfde kwartier vallen met een verschillende werkelijke meettijd): vaste
    # prioriteit dsmr > kamstrup > heatpump > boiler, als eerste-beschikbare i.p.v. bv. het
    # gemiddelde, zodat de uitkomst reproduceerbaar en uit te leggen is. Zie het eindrapport.
    tijdstip_meting = measurements["tijdstip_meting__dsmr"]
    for naam in ("kamstrup", "heatpump", "boiler"):
        tijdstip_meting = tijdstip_meting.combine_first(measurements[f"tijdstip_meting__{naam}"])
    measurements["tijdstip_meting"] = tijdstip_meting

    scheef__bool = or_vlaggen(*[scheef_masker(measurements[f"scheefheid__{n}__s"]) for n in COP_BRONNEN])
    bron_incompleet__bool = bron_incompleet_masker(*[aanwezig[n] for n in COP_BRONNEN])

    # --- drie teller-artefacten wegmaskeren, in de DWINGENDE volgorde van ontwerp-teller-
    # artefacten.md §5: eerst de sentinel (§4.1) op NaN, dan pas het cummax-criterium van §4.2.
    # Omgedraaid telt de sentinelwaarde 3433,300 (ruim boven TELLER_ONTWAAKT_BOVEN) mee in het
    # lopende maximum en explodeert het aantal nulmeting-treffers op e_export_laag_cum__kWh van 361
    # naar 542.507 (regressietoets: test_tabellen.py).
    teller_initialisatie__bool = is_initialisatietelegram(measurements)
    for kolom in INITIALISATIETELEGRAM_SENTINEL:
        measurements[kolom] = measurements[kolom].mask(teller_initialisatie__bool)

    # De calorische waarde is de ENIGE omrekenfactor die per rij verschilt (gaskwaliteit.py): van
    # m3 naar J hangt af van de kwaliteit van het gas op dat moment, en die wordt per uur
    # gepubliceerd. Vandaar een Series waar de andere vier tellers een constante hebben.
    gas_hhv_per_rij = gaskwaliteit.koppel_gas_hhv(measurements["tijdstip_start"], gas_hhv)

    # --- §4.2/§4.3 per brontteller: nulmeting eruit, differentiëren, het ene wissel-interval eruit
    # (tellers.verwerk_bronteller). Acht bronttellers, zelfde acht als teller_terug__bool altijd al
    # bestreek (ontwerp §8 B3): e_net blijft hierbuiten, want die mag legitiem dalen.
    _BRONTELLER_FACTOREN: dict[str, float | pd.Series] = {
        "e_import_laag_cum__kWh": 1.0,
        "e_import_hoog_cum__kWh": 1.0,
        "e_export_laag_cum__kWh": 1.0,
        "e_export_hoog_cum__kWh": 1.0,
        "g_gebruik_cum__m3": gas_hhv_per_rij[gaskwaliteit.KOLOM],
        "e_warmtepomp_cum__kWh": J_PER_KWH,
        "e_ketel_cum__kWh": J_PER_KWH,
        "q_geleverd_cum__J": 1.0,
    }
    verwerkt = {
        naam: verwerk_bronteller(
            measurements[naam], measurements["tijdstip_start"], measurements["home_id__str"], factor
        )
        for naam, factor in _BRONTELLER_FACTOREN.items()
    }
    # De schone stand (sentinel- én nulmeting-gemaskeerd) IS de uitvoer: measurements_out leest
    # verderop rechtstreeks uit measurements, dus deze toewijzing is wat er in measurements.parquet
    # terechtkomt (ontwerp §7).
    for naam, v in verwerkt.items():
        measurements[naam] = v["schoon"]

    teller_nulmeting__bool = or_vlaggen(*[v["nulmeting__bool"] for v in verwerkt.values()])
    teller_wissel__bool = or_vlaggen(*[v["wissel__bool"] for v in verwerkt.values()])
    # §7: teller_terug__bool is geen zelfstandige berekening, maar de OR van de twee hierboven. Een
    # overgang van of naar een initialisatietelegram telt daardoor niet als daling.
    teller_terug__bool = or_vlaggen(teller_nulmeting__bool, teller_wissel__bool)

    teruglevering__bool = or_vlaggen(
        *[
            teller_gestegen_masker(verwerkt[naam]["gedifferentieerd"]["delta"])
            for naam in ("e_export_laag_cum__kWh", "e_export_hoog_cum__kWh")
        ]
    )

    # e_net: samengesteld (import - export), mag legitiem dalen bij teruglevering van zonnestroom en
    # telt daarom niet mee in teller_terug__bool (ontwerp §8 B3). Gebouwd op de kolommen hierboven,
    # die al sentinel- én nulmeting-gemaskeerd zijn (dezelfde toewijzing als net), zodat er
    # geen sentinel- of nulmeting-garbage in de samenstelling lekt.
    e_import__kWh = measurements[["e_import_laag_cum__kWh", "e_import_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_export__kWh = measurements[["e_export_laag_cum__kWh", "e_export_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_net_cum__kWh = e_import__kWh - e_export__kWh
    e_net_gedifferentieerd = differentieer_teller(
        e_net_cum__kWh, measurements["tijdstip_start"], measurements["home_id__str"], J_PER_KWH
    )

    # De vijf vermogens die naar derived/quality gaan: e_net (hierboven) plus de vier bronttellers
    # die ook een eigen __W-kolom hebben (de vier DSMR-subtellers hebben dat niet, ze gaan alleen in
    # e_net en de teller_terug/teruglevering-vlaggen op).
    _VERMOGENSNAAM = {
        "g_gebruik_cum__m3": "g_gebruik__W",
        "e_warmtepomp_cum__kWh": "p_warmtepomp__W",
        "e_ketel_cum__kWh": "p_ketel__W",
        "q_geleverd_cum__J": "q_geleverd__W",
    }
    vermogens_per_kolom = {
        vermogen_naam: verwerkt[bronteller]["gedifferentieerd"]["vermogen__W"]
        for bronteller, vermogen_naam in _VERMOGENSNAAM.items()
    }
    vermogens_per_kolom["e_net__W"] = e_net_gedifferentieerd["vermogen__W"]

    teller_sprong__bool = or_vlaggen(
        *[
            teller_sprong_masker(vermogen__W, SPRONG_DREMPEL__W[naam])
            for naam, vermogen__W in vermogens_per_kolom.items()
        ]
    )

    vermogens = pd.DataFrame(
        {
            "home_id__str": measurements["home_id__str"],
            "tijdstip_start": measurements["tijdstip_start"],
            **vermogens_per_kolom,
            # De TOEGEPASTE calorische waarde en haar herkomst gaan mee naar derived: zonder die
            # twee kolommen is g_gebruik__W een getal waarvan de omrekening niet meer na te rekenen
            # is, en dan ziet een terugval op de vaste waarde er precies zo uit als een geslaagde
            # ophaal (ontwerpprincipe 3, en docs/lessen-uit-im3.md punt 2).
            gaskwaliteit.KOLOM: gas_hhv_per_rij[gaskwaliteit.KOLOM],
            gaskwaliteit.BRON_KOLOM: gas_hhv_per_rij[gaskwaliteit.BRON_KOLOM],
        }
    )

    # --- quality: volledig kwartierrooster + vlaggen ---
    gezien = measurements[["home_id__str", "tijdstip_start"]]
    tijdas = bouw_tijdas(gezien)
    quality = tijdas.merge(gezien.assign(_gezien=True), on=["home_id__str", "tijdstip_start"], how="left")
    quality["ontbrekend__bool"] = quality["_gezien"].isna().astype("boolean")
    quality = quality.drop(columns=["_gezien"])

    vlaggen = pd.DataFrame(
        {
            "home_id__str": measurements["home_id__str"],
            "tijdstip_start": measurements["tijdstip_start"],
            "scheef__bool": scheef__bool,
            "teller_initialisatie__bool": teller_initialisatie__bool,
            "teller_nulmeting__bool": teller_nulmeting__bool,
            "teller_wissel__bool": teller_wissel__bool,
            "teller_terug__bool": teller_terug__bool,
            "teruglevering__bool": teruglevering__bool,
            "teller_sprong__bool": teller_sprong__bool,
            "bron_incompleet__bool": bron_incompleet__bool,
        }
    )
    quality = quality.merge(vlaggen, on=["home_id__str", "tijdstip_start"], how="left")
    for kolom in (
        "scheef__bool", "teller_initialisatie__bool", "teller_nulmeting__bool", "teller_wissel__bool",
        "teller_terug__bool", "teruglevering__bool", "teller_sprong__bool", "bron_incompleet__bool",
    ):
        quality[kolom] = quality[kolom].astype("boolean")
    quality = quality.sort_values(["home_id__str", "tijdstip_start"]).reset_index(drop=True)

    measurements_out = measurements[
        [
            "home_id__str", "tijdstip_start", "tijdstip_meting",
            "e_import_laag_cum__kWh", "e_import_hoog_cum__kWh", "e_export_laag_cum__kWh", "e_export_hoog_cum__kWh",
            "g_gebruik_cum__m3", "e_warmtepomp_cum__kWh", "e_ketel_cum__kWh", "q_geleverd_cum__J",
        ]
    ].sort_values(["home_id__str", "tijdstip_start"]).reset_index(drop=True)

    return measurements_out, quality, vermogens


# --- weer ------------------------------------------------------------------------------------

_KNMI_VELDEN = {
    "T": ("temp_buiten__degC", TIENDE_NAAR_EENHEID),
    "FH": ("wind__m_s_1", TIENDE_NAAR_EENHEID),
    "Q": ("ghi__W_m_2", GHI_J_CM2_UUR_NAAR_W_M2),
}


def build_weer(knmi_r: pd.DataFrame) -> pd.DataFrame:
    """``knmi.csv`` -> ``weer`` (sleutel ``weerstation_nr``, ``tijdstip_start``), met alleen de
    drie grootheden die IM3 ook heeft (ontwerp §4, variable-dictionary "weer"). De overige twintig
    KNMI-velden gaan bewust niet mee.

    Meerdere woningen op hetzelfde station leveren dezelfde reeks; ``.first()`` na groeperen op
    (station, tijdstip) normaliseert dat weg (zelfde aanpak als IM3's
    ``im3_preprocessing.weer.extract_im3_weather``).
    """
    werk = knmi_r.rename(columns={"station_code": "weerstation_nr"}).copy()
    # De KNMI-uurreeks is EIND-gelabeld: HH=1 is het uur 00:00-01:00. Die tijdstempel als
    # tijdstip_start overnemen gaf elke meting het weer van het uur ervóór. Bewezen op 05-09-2026
    # door juni 2023 onafhankelijk op te halen (dutch_weather.knmi, de route van de
    # IM3-zusterrepo) en per station te vergelijken bij drie verschuivingen: onze reeks een uur
    # eerder leggen gaf een mediane afwijking van 3,8e-07 K -- de afrondgrens van float32, dus
    # exact nul, op alle 23 vergelijkbare stations. Gelijk gelegd was het 0,6 tot 0,9 K.
    # Zie ontwerp-intervalsemantiek.md §3.
    werk["tijdstip_start"] = werk["tijdstip_start"] - pd.Timedelta(hours=1)
    for ruw, (naam, factor) in _KNMI_VELDEN.items():
        werk[naam] = (werk[ruw] * factor).astype("float32")
    werk["weerstation_nr"] = werk["weerstation_nr"].astype("int32")

    kolommen = ["weerstation_nr", "tijdstip_start"] + [naam for naam, _ in _KNMI_VELDEN.values()]
    weer = (
        werk[kolommen]
        .groupby(["weerstation_nr", "tijdstip_start"], as_index=False)
        .first()
        .sort_values(["weerstation_nr", "tijdstip_start"])
        .reset_index(drop=True)
    )
    return weer


def home_station_mapping(knmi_r: pd.DataFrame) -> pd.DataFrame:
    """``home_id__str`` -> ``weerstation_nr``, afgeleid uit de knmi-rijen van die woning zelf
    (household.csv/``homes`` heeft in deze dataset GEEN weerstation-kolom, anders dan bij IM3 --
    zie het eindrapport). Bij (zeldzame) wisseling van dichtstbijzijnd station binnen de looptijd
    van een woning wordt het meest voorkomende station gebruikt.
    """
    tellingen = (
        knmi_r.groupby(["home_id__str", "station_code"]).size().rename("n").reset_index()
    )
    gekozen = tellingen.sort_values("n", ascending=False).drop_duplicates("home_id__str")
    return gekozen[["home_id__str", "station_code"]].rename(columns={"station_code": "weerstation_nr"})


# --- derived ----------------------------------------------------------------------------------

_DSMR_MOMENTAAN_V_A = {
    "u_L1": "u_L1_meting__V", "u_L2": "u_L2_meting__V", "u_L3": "u_L3_meting__V",
    "i_L1": "i_L1_meting__A", "i_L2": "i_L2_meting__A", "i_L3": "i_L3_meting__A",
}
_DSMR_MOMENTAAN_KW_NAAR_W = {
    "p_consumed_L1": "p_import_L1_meting__W", "p_consumed_L2": "p_import_L2_meting__W", "p_consumed_L3": "p_import_L3_meting__W",
    "p_delivered_L1": "p_export_L1_meting__W", "p_delivered_L2": "p_export_L2_meting__W", "p_delivered_L3": "p_export_L3_meting__W",
}


def build_derived(
    vermogens: pd.DataFrame,
    dsmr_r: pd.DataFrame,
    kamstrup_r: pd.DataFrame,
    heatpump_r: pd.DataFrame,
    boiler_r: pd.DataFrame,
    room_r: pd.DataFrame,
    weer: pd.DataFrame,
    home_station: pd.DataFrame,
) -> pd.DataFrame:
    """``derived`` = ``vermogens`` (uit :func:`build_measurements_en_quality`) + de momentane
    steekproeven van alle vier tellerbronnen + ``room.csv`` + gekoppeld weer, allemaal LEFT-JOINED
    op de rijenspil van ``vermogens`` (zie module-docstring voor de rijspil-keuze).
    """
    derived = vermogens.copy()

    # dsmr: momentane spanningen/stromen/vermogens
    dsmr_mom = dsmr_r[["home_id__str", "tijdstip_start", *_DSMR_MOMENTAAN_V_A, *_DSMR_MOMENTAAN_KW_NAAR_W]].copy()
    for ruw, naam in _DSMR_MOMENTAAN_V_A.items():
        dsmr_mom[naam] = dsmr_mom.pop(ruw).astype("float32")
    for ruw, naam in _DSMR_MOMENTAAN_KW_NAAR_W.items():
        dsmr_mom[naam] = (dsmr_mom.pop(ruw) * KW_NAAR_W).astype("float32")
    derived = derived.merge(dsmr_mom, on=["home_id__str", "tijdstip_start"], how="left")

    # kamstrup: momentane temperaturen/debiet/vermogen
    kamstrup_mom = kamstrup_r[["home_id__str", "tijdstip_start", "t_supply", "t_return", "f_system", "p_thermal_system"]].copy()
    kamstrup_mom["temp_aanvoer_meting__degC"] = kamstrup_mom.pop("t_supply").astype("float32")
    kamstrup_mom["temp_retour_meting__degC"] = kamstrup_mom.pop("t_return").astype("float32")
    kamstrup_mom["debiet_meting__dm3_s_1"] = (kamstrup_mom.pop("f_system") * LH_NAAR_DM3S).astype("float32")
    kamstrup_mom["q_geleverd_meting__W"] = (kamstrup_mom.pop("p_thermal_system") * KW_NAAR_W).astype("float32")
    derived = derived.merge(kamstrup_mom, on=["home_id__str", "tijdstip_start"], how="left")

    # heatpump/boiler: momentaan vermogen (al in W, geen schaling -- zie bron.py's hernoeming)
    heatpump_mom = heatpump_r[["home_id__str", "tijdstip_start", "heatpump_power"]].rename(
        columns={"heatpump_power": "p_warmtepomp_meting__W"}
    )
    heatpump_mom["p_warmtepomp_meting__W"] = heatpump_mom["p_warmtepomp_meting__W"].astype("float32")
    derived = derived.merge(heatpump_mom, on=["home_id__str", "tijdstip_start"], how="left")

    boiler_mom = boiler_r[["home_id__str", "tijdstip_start", "boiler_power"]].rename(
        columns={"boiler_power": "p_ketel_meting__W"}
    )
    boiler_mom["p_ketel_meting__W"] = boiler_mom["p_ketel_meting__W"].astype("float32")
    derived = derived.merge(boiler_mom, on=["home_id__str", "tijdstip_start"], how="left")

    # room: binnentemperatuur/vochtigheid
    room_mom = room_r[["home_id__str", "tijdstip_start", "temperature", "humidity"]].copy()
    room_mom["temp_binnen_meting__degC"] = room_mom.pop("temperature").astype("float32")
    room_mom["rv_binnen_meting__0"] = (room_mom.pop("humidity") * 0.01).astype("float32")
    derived = derived.merge(room_mom, on=["home_id__str", "tijdstip_start"], how="left")

    # weer: gekoppeld via het eigen station van de woning + het uur waarin het kwartier valt.
    # DPH kent, anders dan IM3, geen q/h/d/m-onderscheid (alles is kwartier), dus geen interpolatie
    # nodig: het uur waarin tijdstip_start valt heeft altijd een KNMI-uurwaarde (of niet, en dan
    # blijft de weerkolom NaN).
    derived = derived.merge(home_station, on="home_id__str", how="left")
    derived["_uur"] = derived["tijdstip_start"].dt.floor("h")
    weer_hernoemd = weer.rename(columns={"tijdstip_start": "_uur"})
    derived = derived.merge(weer_hernoemd, on=["weerstation_nr", "_uur"], how="left")
    derived = derived.drop(columns=["_uur", "weerstation_nr"])

    return derived.sort_values(["home_id__str", "tijdstip_start"]).reset_index(drop=True)
