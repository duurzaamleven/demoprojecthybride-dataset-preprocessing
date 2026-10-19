# SPDX-License-Identifier: EUPL-1.2
"""Preprocessing van de per-minuut-extractie (``ontwerp-preprocessing-minuut.md``).

Tweede invoerpad naast :mod:`dph_preprocessing.pipeline`. Dat pad leest ``dph-dataset.zip`` en
levert een kwartierrooster; dit pad leest de 174 gecompacteerde parquet-bestanden van de
per-minuut-extractie en houdt het minuutrooster vast.

Wat de twee delen: de naamgevingsconventie uit ``docs/variable-dictionary.md`` en de semantiek van
:func:`dph_preprocessing.tellers.differentieer_teller`, die hier in :func:`differentieer_snel` op
numpy is overgedaan en tegen het origineel wordt getoetst. Verder niets, en dat is opzet: het
kwartierpad rekent met ``floor("15min")`` en met drempels die op kwartiergemiddeld vermogen zijn
gemeten, en geen van beide klopt op een minuutrooster (ontwerp §2 en §4).

**Eén pas.** De NAS levert 2,8 MB/s, dus één leesslag over de 7,90 GB kost ongeveer 48 minuten.
Alles wat deze module oplevert, inclusief de per-locatiekenmerken van ontwerp §8, komt daarom uit
diezelfde ene pas; er is geen tweede leesronde over de brondata.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .minuut_dekking import bouw_dekking_tabel
from .tellers import TELLER_ONTWAAKT_BOVEN, markeer_nulmetingen
from .timestamps import TZ_UITVOER, naar_lokale_tijdzone_arrow

log = logging.getLogger(__name__)

BRON_STANDAARD = "//hoftenas/backup/energiedata/DPH-per-minuut/measurements_per_minuut"
DOEL_STANDAARD = "//hoftenas/backup/energiedata/DPH-per-minuut-verwerkt"

J_PER_KWH = 3_600_000.0
GJ_NAAR_J = 1_000_000_000.0
KW_NAAR_W = 1000.0
LH_NAAR_DM3S = 1.0 / 3600.0
PROCENT_NAAR_FRACTIE = 0.01

#: Versie van het uitvoercontract van dit pad: kolomnamen, eenheden, tijdzone en de semantiek van de
#: waarden. **Hoog dit op zodra de uitvoer van vorm of betekenis verandert.** Een hervatting slaat
#: elke locatie over waarvan het bestand al bestaat; zonder deze versie zou een run met nieuwe code
#: de oude bestanden stil laten staan en er nieuwe naast zetten. Handmatig om dezelfde reden als
#: :data:`dph_preprocessing.chunking.UITVOER_CONTRACT_VERSIE`, en apart daarvan omdat de twee paden
#: los van elkaar veranderen.
MINUUT_CONTRACT_VERSIE = "2026-09-24-lokale-tijd"

#: Het bestandje in de uitvoermap waarin :data:`MINUUT_CONTRACT_VERSIE` staat.
CONTRACT_BESTAND = "contract.json"

#: Een gat langer dan dit is uitval en geen hapering (ontwerp §7). De verkenning vond dat 92,7 %
#: van alle ontbrekende minuten in gaten van deze orde zit, tegen 0,44 % in gaten tot 5 minuten.
UITVAL_DREMPEL__min = 24 * 60

#: De acht echte brontellers: bronkolom (zonder ``_eerste``/``_laatste``) -> (uitvoernaam, factor
#: naar de eenheid in die naam). ``e_net`` staat hier bewust NIET bij: dat is een samenstelling van
#: vier van deze tellers en mag legitiem dalen, dus terugsprongen horen per BRONteller bepaald te
#: worden en niet op het saldo (ontwerp §5, en §8 B3 van het kwartierontwerp).
TELLERS: dict[str, tuple[str, float]] = {
    "dsmr_e_consumed_low": ("e_import_laag_cum__kWh", 1.0),
    "dsmr_e_consumed_high": ("e_import_hoog_cum__kWh", 1.0),
    "dsmr_e_delivered_low": ("e_export_laag_cum__kWh", 1.0),
    "dsmr_e_delivered_high": ("e_export_hoog_cum__kWh", 1.0),
    "dsmr_v_gas_consumed": ("g_gebruik_cum__m3", 1.0),
    "heatpump_energy": ("e_warmtepomp_cum__kWh", 1.0),
    "boiler_energy": ("e_ketel_cum__kWh", 1.0),
    "kamstrup_e_thermal_system": ("q_geleverd_cum__J", GJ_NAAR_J),
}

EXPORT_TELLERS = ("e_export_laag_cum__kWh", "e_export_hoog_cum__kWh")

#: Momentane kolommen: bronnaam -> (uitvoernaam, factor). Deze krijgen GEEN ``_meting__``, want in
#: de minuutdata zijn het intervalgemiddelden over 12 (groep 1), 6 (groep 2) of 2 (groep 3)
#: metingen en niet de momentane steekproef die dat achtervoegsel in het kwartierpad aanduidt
#: (ontwerp §3).
MOMENTAAN: dict[str, tuple[str, float]] = {
    "kamstrup_t_supply": ("temp_aanvoer__degC", 1.0),
    "kamstrup_t_return": ("temp_retour__degC", 1.0),
    "kamstrup_p_thermal_system": ("q_geleverd_gemeten__W", KW_NAAR_W),
    "kamstrup_f_system": ("debiet__dm3_s_1", LH_NAAR_DM3S),
    "heatpump_power": ("p_warmtepomp_gemeten__W", 1.0),
    "heatpump_voltage": ("u_warmtepomp__V", 1.0),
    "heatpump_current": ("i_warmtepomp__A", 1.0),
    "boiler_power": ("p_ketel_gemeten__W", 1.0),
    "boiler_voltage": ("u_ketel__V", 1.0),
    "boiler_current": ("i_ketel__A", 1.0),
    "dsmr_u_L1": ("u_L1__V", 1.0),
    "dsmr_u_L2": ("u_L2__V", 1.0),
    "dsmr_u_L3": ("u_L3__V", 1.0),
    "dsmr_i_L1": ("i_L1__A", 1.0),
    "dsmr_i_L2": ("i_L2__A", 1.0),
    "dsmr_i_L3": ("i_L3__A", 1.0),
    "dsmr_p_consumed_L1": ("p_import_L1__W", KW_NAAR_W),
    "dsmr_p_consumed_L2": ("p_import_L2__W", KW_NAAR_W),
    "dsmr_p_consumed_L3": ("p_import_L3__W", KW_NAAR_W),
    "dsmr_p_delivered_L1": ("p_export_L1__W", KW_NAAR_W),
    "dsmr_p_delivered_L2": ("p_export_L2__W", KW_NAAR_W),
    "dsmr_p_delivered_L3": ("p_export_L3__W", KW_NAAR_W),
    "sonoff_temperature": ("temp_binnen__degC", 1.0),
    "sonoff_humidity": ("rv_binnen__0", PROCENT_NAAR_FRACTIE),
    "heatpump_power_min": ("p_warmtepomp_gemeten_min__W", 1.0),
    "heatpump_power_max": ("p_warmtepomp_gemeten_max__W", 1.0),
    "boiler_power_min": ("p_ketel_gemeten_min__W", 1.0),
    "boiler_power_max": ("p_ketel_gemeten_max__W", 1.0),
    "kamstrup_p_thermal_system_min": ("q_geleverd_gemeten_min__W", KW_NAAR_W),
    "kamstrup_p_thermal_system_max": ("q_geleverd_gemeten_max__W", KW_NAAR_W),
}

#: Kolommen waar een uitlezing van exact 0,0 *afwezig* betekent en niet *onplausibel*.
#:
#: De drie DSMR-spanningen melden op meters die geen spanning rapporteren een harde 0,0 in plaats
#: van niets, op alle drie de fasen tegelijk en op precies dezelfde minuten. Gemeten op negen
#: locaties en 6,1 miljoen minuten: 29,2 % van alle minuten heeft zo'n nul, en dat is 98 % van
#: alles wat `onplausibel__bool` markeerde. Zonder deze uitzondering staat de vlag op 29,8 % en
#: markeert hij vooral welke meter geen spanning levert; mét deze uitzondering op 0,7 %, en dan
#: markeert hij wat hij hoort te markeren.
#:
#: Dit is dezelfde redenering als :func:`markeer_nulmetingen` voor de tellers, waar een exacte 0,0
#: ook als foutieve uitlezing geldt en niet als meting. Hier is hij sterker: een netspanning van
#: precies 0 V bestaat niet zolang de meter communiceert, dus de nul is een sentinel.
#:
#: **Bewust alleen de drie DSMR-fasen.** `u_warmtepomp__V` en `u_ketel__V` komen van een ander
#: toestel en overschreden in de meting geen enkele keer hun grens; ze hier opnemen zou een
#: toekomstige échte nul verbergen zonder dat er vandaag een probleem is.
NUL_IS_AFWEZIG: frozenset[str] = frozenset({"u_L1__V", "u_L2__V", "u_L3__V"})

#: Fysische grenzen per grootheid (ontwerp §6). Buiten bereik wordt NaN plus een vlag, niet
#: afgekapt: afkappen verzint een getal en weglaten maakt het defect onvindbaar. De ondergrens op
#: de warmtekolommen is bewust niet 0, want licht negatief bij stilstand is een nulpuntseffect.
GRENZEN: dict[str, tuple[float, float]] = {
    "p_warmtepomp_gemeten__W": (-100.0, 15_000.0),
    "p_warmtepomp_gemeten_min__W": (-100.0, 15_000.0),
    "p_warmtepomp_gemeten_max__W": (-100.0, 15_000.0),
    "p_ketel_gemeten__W": (-100.0, 5_000.0),
    "p_ketel_gemeten_min__W": (-100.0, 5_000.0),
    "p_ketel_gemeten_max__W": (-100.0, 5_000.0),
    "q_geleverd_gemeten__W": (-2_000.0, 60_000.0),
    "q_geleverd_gemeten_min__W": (-2_000.0, 60_000.0),
    "q_geleverd_gemeten_max__W": (-2_000.0, 60_000.0),
    "temp_aanvoer__degC": (-10.0, 100.0),
    "temp_retour__degC": (-10.0, 100.0),
    "temp_binnen__degC": (-10.0, 60.0),
    "rv_binnen__0": (0.0, 1.0),
    "u_L1__V": (150.0, 300.0),
    "u_L2__V": (150.0, 300.0),
    "u_L3__V": (150.0, 300.0),
    "u_warmtepomp__V": (150.0, 300.0),
    "u_ketel__V": (150.0, 300.0),
    "debiet__dm3_s_1": (-1.0, 10.0),
}

OVERNEMEN = (
    "n_g1", "n_g2", "n_g3",
    "offset_eerste_g1__ms", "offset_eerste_g2__ms", "offset_eerste_g3__ms",
    "offset_laatste_g1__ms", "offset_laatste_g2__ms", "offset_laatste_g3__ms",
)


def _types_mapper(arrow_type: pa.DataType):
    """Voorkomt dat ``to_pandas`` de ``uint16``-kolommen van :data:`OVERNEMEN` naar ``float64``
    verbreedt (geheugenontwerp §2, §5.5).

    Zonder deze mapper verbreedt pandas een integerkolom met ontbrekende waarden naar ``float64``:
    zes van de negen ``uint16``-kolommen kwamen zo standaard 36 byte per rij duurder uit dan nodig,
    en welke zes dat waren hing af van welke batch de ontbrekende waarde toevallig bevatte. Met deze
    mapper komt zo'n kolom altijd terug als pandas' eigen nullable ``UInt16``, met of zonder
    ontbrekende waarden en onafhankelijk van de batchindeling, en die converteert bij het schrijven
    weer terug naar ``pa.uint16()`` met een validity-bitmap in plaats van naar ``float64``.
    """
    if pa.types.is_uint16(arrow_type):
        return pd.UInt16Dtype()
    return None

#: Drempels voor de warmtemeterproef (ontwerp §8), overgenomen uit §1.2 van de verkenning.
WP_UIT_ONDER__W = 200.0
KETEL_AAN_BOVEN__W = 20.0
STREAK__min = 10
WARMTE_AAN_FRACTIE_VAN_MAX = 0.02
BEREIK_SYSTEEM_BOVEN = 0.15
BEREIK_WARMTEPOMP_ONDER = 0.01


@dataclass
class Uitkomst:
    """Wat één locatie oplevert: de tabel, zijn gaten, en de kenmerken voor ``homes_minuut``.

    ``metingen`` is een DataFrame uit :func:`verwerk_locatie` en een ``pa.Table`` uit
    :func:`verwerk_locatie_streamend`; beide gaan zo naar :func:`schrijf_atomisch`.
    """

    home_id: str
    metingen: pd.DataFrame | pa.Table
    gaten: pd.DataFrame
    kenmerken: dict = field(default_factory=dict)


# --- tellers ---------------------------------------------------------------------------------


def _telt_als_onplausibel(naam: str, waarde: np.ndarray, buiten: np.ndarray) -> np.ndarray:
    """Welke buiten-bereikwaarden mogen ``onplausibel__bool`` zetten.

    De waarde zelf gaat hoe dan ook op ``NaN``; dit bepaalt alleen of de vlag afgaat. Voor de
    kolommen in :data:`NUL_IS_AFWEZIG` telt een uitlezing van exact 0,0 niet mee, want daar is de
    nul een sentinel voor "niet gerapporteerd" en geen foute meting. Zie de toelichting bij die
    constante voor de meting waarop dat berust.
    """
    if naam not in NUL_IS_AFWEZIG:
        return buiten
    return buiten & (waarde != 0.0)


def differentieer_snel(stand: np.ndarray, tijd__ns: np.ndarray, factor: float) -> dict[str, np.ndarray]:
    """Dezelfde bewerking als :func:`~dph_preprocessing.tellers.differentieer_teller`, maar op numpy.

    **Waarom er een tweede implementatie is.** De gedeelde functie bleek de helft van de rekentijd
    op te eten: ze bouwt per aanroep een DataFrame met ``tijdstip_start.to_numpy()``, en op een
    tijdzone-bewuste kolom levert dat een object-array die pandas element voor element vult. Bij
    46.474 rijen kostte dat 2,7 s per teller, negen tellers per locatie, en over de hele set kwam
    dat op ruim achttien uur. Dat past niet in één nacht.

    Hier kan het goedkoper omdat deze pas één locatie tegelijk verwerkt en de rijen al op tijd
    gesorteerd zijn: geen groupby, geen sortering, en rekenen op int64-nanoseconden. De semantiek
    is identiek en ``test_minuut.py`` toetst dat ook tegen de gedeelde functie, zodat de twee niet
    uit elkaar kunnen lopen: vooruit differentiëren, delen door de WERKELIJKE verstreken tijd, en
    ``NaN`` op de laatste rij omdat daar geen volgend interval is.
    """
    n = stand.size
    delta = np.full(n, np.nan)
    duur__s = np.full(n, np.nan)
    if n >= 2:
        delta[:-1] = stand[1:] - stand[:-1]
        duur__s[:-1] = (tijd__ns[1:] - tijd__ns[:-1]) / 1e9
    # Twee rijen op dezelfde minuut zouden delen door nul geven. De extractie groepeert per minuut
    # en levert ze dus niet, maar oneindig vermogen in de uitvoer is een te dure manier om daar
    # achter te komen.
    duur__s[duur__s <= 0] = np.nan
    return {"delta": delta, "delta_t__s": duur__s, "vermogen__W": delta * factor / duur__s}


def verwerk_teller(
    stand: pd.Series,
    tijd__ns: np.ndarray,
    factor_naar_J: float,
) -> tuple[pd.Series, dict[str, np.ndarray], pd.Series]:
    """Eén brontteller: nulmetingen eruit, dan vooruit differentiëren.

    Retourneert de opgeschoonde stand, het resultaat van :func:`differentieer_snel`, en de
    nulmetingvlag. De nulmeting gaat op ``NaN`` vóór het differentiëren, zodat er GEEN enorme
    negatieve piek gevolgd door een enorme positieve piek ontstaat.

    **Dit is geen bridging, en dat is eerder ten onrechte anders opgeschreven geweest** (gecorrigeerd
    na ontwerp-teller-artefacten.md §10, reviewpunt A1): ``differentieer_snel`` werkt positioneel
    (``delta[:-1] = stand[1:] - stand[:-1]``), dus een gemaskeerde (``NaN``) rij levert gewoon ``NaN``
    op voor het interval ervoor ÉN de rij zelf -- er wordt niets overgeslagen naar de eerstvolgende
    geldige aflezing, en er is dus ook geen vermogenswaarde die een langer interval beschrijft. Het
    verschil met de rauwe, ongemaskeerde reeks is dat de valse piek vervangen wordt door ``NaN``, niet
    dat hij vervangen wordt door een correct gemiddelde over een langer interval.
    """
    nulmeting = markeer_nulmetingen(stand)
    schoon = stand.where(~nulmeting)
    afgeleid = differentieer_snel(schoon.to_numpy(dtype="float64"), tijd__ns, factor_naar_J)
    return schoon, afgeleid, nulmeting


# --- gaten -----------------------------------------------------------------------------------


def bouw_gaten(tijdstip_start: pd.Series, home_id: str) -> pd.DataFrame:
    """De gaten in de tijdas van één locatie, met hun soort (ontwerp §7).

    Een gat is elk verschil van meer dan één minuut tussen twee opeenvolgende aanwezige minuten.
    ``soort`` is ``uitval`` boven 24 uur en anders ``hapering``; dat onderscheid bestaat omdat 92,7
    % van het gemis in de lange gaten zit en die horen uit de noemer, terwijl de korte
    overbrugbaar zijn.
    """
    if len(tijdstip_start) < 2:
        return pd.DataFrame(
            {"home_id__str": pd.Series(dtype="string"), "begin": pd.Series(dtype="datetime64[ms, UTC]"),
             "eind": pd.Series(dtype="datetime64[ms, UTC]"), "duur__min": pd.Series(dtype="int64"),
             "soort": pd.Series(dtype="string")}
        )
    verschil__min = tijdstip_start.diff().dt.total_seconds().div(60.0)
    is_gat = verschil__min > 1.0
    if not is_gat.any():
        return bouw_gaten(tijdstip_start.iloc[:1], home_id)
    eind = tijdstip_start[is_gat]
    duur = verschil__min[is_gat] - 1.0
    begin = eind - pd.to_timedelta(duur, unit="m")
    gaten = pd.DataFrame(
        {
            "home_id__str": home_id,
            "begin": begin.to_numpy(),
            "eind": eind.to_numpy(),
            "duur__min": duur.round().astype("int64").to_numpy(),
        }
    )
    gaten["soort"] = np.where(gaten["duur__min"] > UITVAL_DREMPEL__min, "uitval", "hapering")
    gaten["home_id__str"] = gaten["home_id__str"].astype("string")
    gaten["soort"] = gaten["soort"].astype("string")
    return gaten.reset_index(drop=True)


# --- de warmtemeterproef ----------------------------------------------------------------------


def _streaks(masker: np.ndarray, lengte: int) -> np.ndarray:
    """True op elke positie die binnen een aaneengesloten reeks van >= ``lengte`` True's valt.

    Via de randen van de reeksen en niet per positie: een Python-lus over alle minuten zou hier
    ruim 100 miljoen iteraties kosten over de hele set. Nu loopt hij alleen over de gevonden lange
    reeksen, en dat zijn er per locatie hooguit enkele duizenden.
    """
    if masker.size == 0:
        return masker
    rand = np.diff(np.concatenate(([0], masker.astype(np.int8), [0])))
    begin = np.flatnonzero(rand == 1)
    eind = np.flatnonzero(rand == -1)
    lang = (eind - begin) >= lengte
    uit = np.zeros(masker.size, dtype=bool)
    for b, e in zip(begin[lang], eind[lang]):
        uit[b:e] = True
    return uit


def bepaal_warmtemeter_bereik(df: pd.DataFrame) -> dict:
    """Meet de Kamstrup het hele systeem of alleen de warmtepomp? (ontwerp §8, verkenning §1.2)

    De proef: zoek reeksen van minstens tien aaneengesloten minuten waarin de warmtepomp onder 200
    W zit terwijl de ketel elektrisch aan staat, en kijk in welk deel van die minuten de
    warmtemeter tóch levert. Levert hij daar, dan zit hij achter beide toestellen.

    De controle (beide uit) hoort vrijwel nul te geven en de referentie (warmtepomp aan) hoog; die
    twee staan erbij zodat een onzinnige uitkomst zichzelf verraadt in plaats van als classificatie
    door te lopen.
    """
    wp = df.get("p_warmtepomp_gemeten__W")
    ketel = df.get("p_ketel_gemeten__W")
    warmte = df.get("q_geleverd_gemeten__W")
    leeg = {"bereik_n": 0, "bereik_fractie": np.nan, "bereik_controle": np.nan,
            "bereik_referentie": np.nan, "warmtemeter_bereik__cat": "onbeslist"}
    if wp is None or ketel is None or warmte is None:
        return leeg
    warmte_max = float(np.nanmax(warmte.to_numpy())) if warmte.notna().any() else np.nan
    if not np.isfinite(warmte_max) or warmte_max <= 0:
        return leeg
    drempel = warmte_max * WARMTE_AAN_FRACTIE_VAN_MAX

    wp_uit = (wp < WP_UIT_ONDER__W).fillna(False).to_numpy()
    wp_aan = (wp >= WP_UIT_ONDER__W).fillna(False).to_numpy()
    ketel_aan = (ketel > KETEL_AAN_BOVEN__W).fillna(False).to_numpy()
    ketel_uit = (ketel <= KETEL_AAN_BOVEN__W).fillna(False).to_numpy()
    warmte_aan = (warmte > drempel).fillna(False).to_numpy()

    proef = _streaks(wp_uit & ketel_aan, STREAK__min)
    controle = _streaks(wp_uit & ketel_uit, STREAK__min)
    n = int(proef.sum())
    if n == 0:
        return leeg
    fractie = float(warmte_aan[proef].mean())
    uit = {
        "bereik_n": n,
        "bereik_fractie": fractie,
        "bereik_controle": float(warmte_aan[controle].mean()) if controle.any() else np.nan,
        "bereik_referentie": float(warmte_aan[wp_aan].mean()) if wp_aan.any() else np.nan,
    }
    if fractie > BEREIK_SYSTEEM_BOVEN:
        uit["warmtemeter_bereik__cat"] = "systeem"
    elif fractie < BEREIK_WARMTEPOMP_ONDER:
        uit["warmtemeter_bereik__cat"] = "warmtepomp"
    else:
        uit["warmtemeter_bereik__cat"] = "onbeslist"
    return uit


def _raster_kenmerken(grenzen: dict[str, tuple[float, float]]) -> dict:
    """``raster_<kort>__W`` en ``raster_breuk_<kort>__bool`` per teller, voor ``homes_minuut``.

    Geheugenontwerp §5.5 en §6.7: het float32-raster van de bron is fijn genoeg voor de meter bij
    lage standen, maar bij de standen die deze meters na 2,5 jaar hebben bereikt is hij bij een
    aantal tellers grover dan de metertik zelf, en dat vertaalt zich rechtstreeks in een trap op het
    afgeleide vermogen. De rekenregels zelf staan in :mod:`dph_preprocessing.minuut_raster` en worden
    hier hergebruikt, niet opnieuw geschreven; alleen de invoer verschilt: daar komt ``stand_min``/
    ``stand_max`` uit de parquet-footer van alle 174 bestanden zonder een rij te lezen, hier komt hij
    uit de stand die deze locatie tijdens DEZE pas al aan het lezen is.

    ``<kort>`` is de tellernaam zonder zijn eigen eenheid (``e_import_laag_cum__kWh`` wordt
    ``e_import_laag_cum``), zodat de nieuwe kolom zelf weer één ``__eenheid``-achtervoegsel krijgt in
    plaats van twee. Circulaire import: deze module wordt door :mod:`minuut_raster` op moduleniveau
    geïmporteerd, dus die kant op moet het hier een lokale import zijn (zelfde reden als bij
    :func:`_schrijf_kwaliteitsrapport`).
    """
    from dph_preprocessing.minuut_raster import beoordeel_teller

    kenmerken: dict = {}
    for bron, (stand_min, stand_max) in grenzen.items():
        if not (math.isfinite(stand_min) and math.isfinite(stand_max)):
            continue
        naam, _ = TELLERS[bron]
        kort = naam.split("__")[0]
        post = beoordeel_teller(bron, stand_min, stand_max)
        kenmerken[f"raster_{kort}__W"] = post["raster__W"]
        kenmerken[f"raster_breuk_{kort}__bool"] = post["raster_breuk__bool"]
    return kenmerken


# --- de hoofdbewerking ------------------------------------------------------------------------


def verwerk_locatie(ruw: pd.DataFrame, home_id: str) -> Uitkomst:
    """Van één ruwe minuuttabel naar de verwerkte tabel, de gaten en de kenmerken."""
    ruw = ruw.sort_values("tijdstip_start").reset_index(drop=True)
    tijdstip_start = ruw["tijdstip_start"]
    # int64-nanoseconden, één keer. Elke afgeleide rekent hierop verder; zie differentieer_snel
    # voor wat het kost om dit per teller opnieuw uit een tijdzone-bewuste kolom te halen.
    tijd__ns = tijdstip_start.to_numpy(dtype="datetime64[ns]").astype("int64")

    uit = pd.DataFrame({"home_id__str": pd.Series(home_id, index=ruw.index, dtype="string"),
                        "tijdstip_start": tijdstip_start})

    # 1. Momentane kolommen: omrekenen en op plausibiliteit toetsen (ontwerp §3, §6).
    onplausibel = np.zeros(len(ruw), dtype=bool)
    for bron, (naam, factor) in MOMENTAAN.items():
        if bron not in ruw.columns:
            continue
        waarde = ruw.pop(bron).to_numpy(dtype="float64") * factor
        if naam in GRENZEN:
            onder, boven = GRENZEN[naam]
            # Een NaN is niet onplausibel maar afwezig; np.nan vergelijkt sowieso als False, en
            # dat is hier precies het gewenste gedrag.
            buiten = (waarde < onder) | (waarde > boven)
            onplausibel |= _telt_als_onplausibel(naam, waarde, buiten)
            waarde = np.where(buiten, np.nan, waarde)
        uit[naam] = waarde.astype("float32")

    # 2. Tellers: nulmetingen eruit, vooruit differentiëren (ontwerp §4, §5).
    nulmeting = np.zeros(len(ruw), dtype=bool)
    terug = np.zeros(len(ruw), dtype=bool)
    wissel = np.zeros(len(ruw), dtype=bool)
    teruglevering = np.zeros(len(ruw), dtype=bool)
    standen: dict[str, pd.Series] = {}
    tellerstats: dict[str, dict] = {}
    # Voor raster_<naam>__W en raster_breuk_<naam>__bool (geheugenontwerp §5.5, §6.6, §6.7): de
    # RUWE stand vóór het schoonmaken, want het float32-raster wordt bepaald door de spanwijdte die
    # de teller in de bron doorloopt, en dat is precies wat de footer-gebaseerde scan in
    # minuut_raster.py ook meet (die kent onze nulmeting-opschoning niet). ONTWAAKT_BOVEN in
    # beoordeel_teller vangt een eventuele foutieve 0 in het minimum toch al op.
    raster_grenzen: dict[str, tuple[float, float]] = {}

    for bron, (naam, factor_naar_J) in TELLERS.items():
        kolom = f"{bron}_eerste"
        if kolom not in ruw.columns:
            continue
        stand = ruw.pop(kolom).astype("float64")
        if stand.notna().any():
            raster_grenzen[bron] = (float(stand.min()), float(stand.max()))
        schoon, afgeleid, nul = verwerk_teller(stand, tijd__ns, factor_naar_J)
        standen[naam] = schoon
        nul_np = nul.to_numpy()
        nulmeting |= nul_np
        daalt = afgeleid["delta"] < 0.0
        terug |= daalt
        # Een daling die niet naar 0 loopt is een echte breuk: de teller is vervangen of
        # teruggezet. De nulmeting hierboven is dat niet, want die herstelt zich (ontwerp §5).
        volgende_is_nul = np.concatenate([nul_np[1:], [False]])
        wissel_hier = daalt & ~volgende_is_nul
        wissel |= wissel_hier
        # A2 (ontwerp-teller-artefacten.md §10): dit interval hoort net als in het kwartierpad
        # (§4.3) op NaN, niet de stand. Anders blijft het onmogelijke interval staan in
        # g_gebruik__m3_s_1/q_geleverd__W/p_warmtepomp__W/p_ketel__W (bij woning W5J0QUUq
        # bijvoorbeeld q_geleverd__W = -100.000,7).
        if wissel_hier.any():
            afgeleid["delta"] = np.where(wissel_hier, np.nan, afgeleid["delta"])
            afgeleid["vermogen__W"] = np.where(wissel_hier, np.nan, afgeleid["vermogen__W"])
        if naam in EXPORT_TELLERS:
            teruglevering |= afgeleid["delta"] > 0.0
        uit[naam] = schoon.astype("float32")
        tellerstats[naam] = {
            "n_geldig": int(schoon.notna().sum()),
            "n_nulmeting": int(nul_np.sum()),
            "n_terug": int(daalt.sum()),
        }
        if naam == "g_gebruik_cum__m3":
            uit["g_gebruik__m3_s_1"] = afgeleid["vermogen__W"].astype("float32")
        elif naam == "q_geleverd_cum__J":
            uit["q_geleverd__W"] = afgeleid["vermogen__W"].astype("float32")
        elif naam == "e_warmtepomp_cum__kWh":
            uit["p_warmtepomp__W"] = (afgeleid["delta"] * J_PER_KWH / afgeleid["delta_t__s"]).astype("float32")
        elif naam == "e_ketel_cum__kWh":
            uit["p_ketel__W"] = (afgeleid["delta"] * J_PER_KWH / afgeleid["delta_t__s"]).astype("float32")

    # 3. Het elektrasaldo is een samenstelling en mag dalen; daarom pas hier en niet als brontteller.
    invoer = [standen[n] for n in ("e_import_laag_cum__kWh", "e_import_hoog_cum__kWh") if n in standen]
    uitvoer = [standen[n] for n in EXPORT_TELLERS if n in standen]
    duur__s = np.full(len(ruw), np.nan)
    if len(ruw) >= 2:
        duur__s[:-1] = (tijd__ns[1:] - tijd__ns[:-1]) / 1e9
    if invoer:
        saldo = sum(invoer[1:], invoer[0])
        for reeks in uitvoer:
            saldo = saldo - reeks
        net = differentieer_snel(saldo.to_numpy(dtype="float64"), tijd__ns, J_PER_KWH)
        uit["e_net_cum__kWh"] = saldo.astype("float32")
        uit["e_net__W"] = net["vermogen__W"].astype("float32")
    uit["delta_t__s"] = duur__s.astype("float32")

    # 4. Dekking en offsets ongewijzigd mee (R7: n is het dekkingsgewicht van het gemiddelde).
    for kolom in OVERNEMEN:
        if kolom in ruw.columns:
            uit[kolom] = ruw[kolom]

    # 5. Vlaggen. Nullable boolean, net als in het kwartierpad.
    uit["teller_nulmeting__bool"] = pd.array(nulmeting, dtype="boolean")
    uit["teller_terug__bool"] = pd.array(terug, dtype="boolean")
    uit["teller_wissel__bool"] = pd.array(wissel, dtype="boolean")
    uit["teruglevering__bool"] = pd.array(teruglevering, dtype="boolean")
    uit["onplausibel__bool"] = pd.array(onplausibel, dtype="boolean")
    gat_na = (uit["delta_t__s"] > 60.0).fillna(False)
    uit["gat_na__bool"] = pd.array(gat_na.to_numpy(), dtype="boolean")
    uitval_na = (uit["delta_t__s"] > UITVAL_DREMPEL__min * 60.0).fillna(False)
    uit["uitval_na__bool"] = pd.array(uitval_na.to_numpy(), dtype="boolean")

    gaten = bouw_gaten(tijdstip_start, home_id)

    # 6. Kenmerken voor homes_minuut (ontwerp §8). Deze komen uit dezelfde pas, want een tweede
    #    leesslag over de brondata kost 48 minuten.
    span__min = 0.0
    if len(tijdstip_start) >= 2:
        span__min = (tijdstip_start.iloc[-1] - tijdstip_start.iloc[0]).total_seconds() / 60.0 + 1.0
    wp_kolom = uit.get("p_warmtepomp_gemeten__W")
    wp_max = float(np.nanmax(wp_kolom.to_numpy())) if wp_kolom is not None and wp_kolom.notna().any() else np.nan
    kenmerken = {
        "home_id__str": home_id,
        "n_minuten": int(len(uit)),
        "eerste_minuut": tijdstip_start.iloc[0] if len(uit) else pd.NaT,
        "laatste_minuut": tijdstip_start.iloc[-1] if len(uit) else pd.NaT,
        "bezetting__0": float(len(uit) / span__min) if span__min > 0 else np.nan,
        "grootste_gat__min": int(gaten["duur__min"].max()) if len(gaten) else 0,
        "n_gaten": int(len(gaten)),
        "n_uitval": int((gaten["soort"] == "uitval").sum()) if len(gaten) else 0,
        "warmtepompkanaal_dood__bool": bool(np.isfinite(wp_max) and wp_max <= WP_UIT_ONDER__W),
        "p_warmtepomp_max__W": wp_max,
        "n_onplausibel": int(onplausibel.sum()),
        "n_teller_terug": int(terug.sum()),
        "n_teller_nulmeting": int(nulmeting.sum()),
        "n_teller_wissel": int(wissel.sum()),
    }
    kenmerken.update(bepaal_warmtemeter_bereik(uit))
    kenmerken.update(_raster_kenmerken(raster_grenzen))
    # R3: dekking per KOLOM, niet per meetgroep. n_g2 > 0 zegt niets over een gevulde dsmr-waarde.
    for naam in list(MOMENTAAN.values()):
        kolom = naam[0]
        if kolom in uit.columns:
            kenmerken[f"dekking_{kolom}"] = float(uit[kolom].notna().mean()) if len(uit) else np.nan
    for naam in tellerstats:
        kenmerken[f"dekking_{naam}"] = float(tellerstats[naam]["n_geldig"] / len(uit)) if len(uit) else np.nan

    return Uitkomst(home_id=home_id, metingen=uit, gaten=gaten, kenmerken=kenmerken)


# --- het streamende pad -------------------------------------------------------------------------
#
# Waarom dit er naast staat en niet in verwerk_locatie (ontwerp-preprocessing-minuut-geheugen.md).
# De piek van verwerk_locatie is 8,5 keer het dataframe, omdat de arrow-tabel, de pandas-kopie, de
# kopie van sort_values, de float64-standen en de from_pandas-kopie bij het schrijven allemaal
# tegelijk bestaan. Op het grootste bestand is dat 2,1 tot 2,4 GB, en dat past niet op een machine
# met 7,8 GB die al vol staat. Hieronder wordt de invoer per batch gelezen en verwerkt, met tussen
# de batches alleen een handjevol draagwaarden en één rij vooruitkijk.
#
# verwerk_locatie blijft bestaan als referentie-implementatie: test_minuut.py toetst hém, en
# test_minuut_streamend.py toetst dat dit pad er rij voor rij hetzelfde uit krijgt.

#: Rijen per leesbatch. De bron heeft row groups van ~100.000 rijen (geheugenontwerp §3), dus een
#: batch valt vrijwel samen met een row group en pyarrow hoeft niets dubbel te decomprimeren.
BATCH_RIJEN = 100_000


class NietStreambaar(RuntimeError):
    """Deze locatie voldoet niet aan de aannames van het streamende pad.

    :func:`run` vangt dit op en doet de locatie alsnog via :func:`verwerk_locatie`. De footer van
    alle 174 bestanden zegt dat dat nooit nodig is (geheugenontwerp §3), maar een stille verkeerde
    uitkomst is duurder dan een terugvalpad dat blijft staan.
    """


def _nodige_kolommen(namen: list[str]) -> list[str]:
    """De 48 van de 57 bronkolommen die dit pad werkelijk gebruikt (geheugenontwerp §4.1).

    De acht ``*_laatste``-varianten worden nergens gelezen en ``location_id`` staat al in de
    bestandsnaam; ze overslaan scheelt 17 % van de float-payload zonder dat er iets aan de uitkomst
    verandert.
    """
    aanwezig = set(namen)
    nodig = ["tijdstip_start"]
    nodig += [kolom for kolom in MOMENTAAN if kolom in aanwezig]
    nodig += [f"{bron}_eerste" for bron in TELLERS if f"{bron}_eerste" in aanwezig]
    nodig += [kolom for kolom in OVERNEMEN if kolom in aanwezig]
    return nodig


class _Streamend:
    """Draagtoestand tussen de batches van één locatie (geheugenontwerp §4.2).

    Alles wat :func:`verwerk_locatie` uit het volledige frame haalt komt hier uit een handjevol
    scalars plus één rij vooruitkijk. Die vooruitkijk is er omdat vooruit differentiëren de opvolger
    nodig heeft: ``delta[i] = stand[i+1] - stand[i]``, dus de laatste rij van een batch is pas af als
    de volgende binnen is. Die rij schuift door en wordt aan het begin van de volgende batch opnieuw
    meegerekend; alleen de rijen daarvóór zijn definitief.

    Eén ding wordt wél over de hele locatie vastgehouden: de drie kolommen van de warmtemeterproef
    (§4.3). Die proef kan niet streamen, want zijn drempel is 2 % van het locatiemaximum en zijn
    reeksen van tien minuten lopen over batchgrenzen heen. Als float32 kost dat 12 byte per rij, dus
    14 MB op het grootste bestand, en daarna draait :func:`bepaal_warmtemeter_bereik` er ongewijzigd
    op.
    """

    #: De drie kolommen waarvan de hele locatie wordt vastgehouden (§4.3).
    PROEFKOLOMMEN = ("p_warmtepomp_gemeten__W", "p_ketel_gemeten__W", "q_geleverd_gemeten__W")

    def __init__(self, home_id: str, namen: list[str]) -> None:
        aanwezig = set(namen)
        self.home_id = home_id
        self.momentaan = [(bron, *MOMENTAAN[bron]) for bron in MOMENTAAN if bron in aanwezig]
        self.tellers = [
            (f"{bron}_eerste", *TELLERS[bron]) for bron in TELLERS if f"{bron}_eerste" in aanwezig
        ]
        self.overnemen = [kolom for kolom in OVERNEMEN if kolom in aanwezig]

        self.blokken: list[pa.Table] = []
        self.gaten: list[pd.DataFrame] = []
        self.proef: dict[str, list[np.ndarray]] = {naam: [] for naam in self.PROEFKOLOMMEN}

        # Draagwaarden per teller voor markeer_nulmetingen. "lopend_max" is het maximum van de RUWE
        # stand vóór het blok; daarmee wordt de cummax van het blok tot de cummax van de hele reeks
        # gemaakt. "vorige_cummax" is de waarde die shift(1) op de eerste rij van het blok hoort te
        # zetten, en die mag NaN zijn: cummax laat NaN staan waar de stand NaN is, en een vergelijking
        # met NaN is False. Dat onderscheid bewaart de semantiek "stond hij EERDER al boven 1".
        self.lopend_max: dict[str, float] = {naam: -np.inf for _, naam, _ in self.tellers}
        self.vorige_cummax: dict[str, float] = {naam: np.nan for _, naam, _ in self.tellers}
        # Het lopende minimum van de RUWE stand, voor raster_<naam>__W en raster_breuk_<naam>__bool
        # (§5.5, §6.6). Een eventuele foutieve 0 hierin doet niets af aan de uitkomst: beoordeel_teller
        # klemt het minimum toch al op ONTWAAKT_BOVEN.
        self.lopend_min: dict[str, float] = {naam: np.inf for _, naam, _ in self.tellers}

        self.n_rijen = 0
        self.eerste_minuut: pd.Timestamp | None = None
        self.laatste_minuut: pd.Timestamp | None = None
        self.n_onplausibel = 0
        self.n_terug = 0
        self.n_nulmeting = 0
        self.n_wissel = 0
        self.wp_max = -np.inf
        self.notna: dict[str, int] = {}
        self.n_geldig: dict[str, int] = {naam: 0 for _, naam, _ in self.tellers}

    # -- één blok ------------------------------------------------------------------------------

    def blok(self, blok: pd.DataFrame, flush: bool) -> None:
        """Verwerk één blok. Definitief zijn alle rijen behalve de laatste, tenzij ``flush``.

        Het blok is de nieuwe batch met de doorgeschoven rij van de vorige ervoor geplakt. Door pas
        ná het berekenen af te snijden hoeft geen enkele bewerking te weten dat ze in een batch
        draait: de randeffecten van de stencils (de ``NaN`` op de laatste delta, de ``False`` in
        ``volgende_is_nul``) vallen precies op de rij die toch wordt weggesneden.
        """
        n = len(blok)
        if n == 0:
            return
        # k = het aantal definitieve rijen van dit blok.
        k = n if flush else n - 1

        tijdstip_start = blok["tijdstip_start"]
        tijd__ns = tijdstip_start.to_numpy(dtype="datetime64[ns]").astype("int64")

        uit = pd.DataFrame(
            {
                "home_id__str": pd.Series(self.home_id, index=blok.index, dtype="string"),
                "tijdstip_start": tijdstip_start,
            }
        )

        # 1. Momentane kolommen: omrekenen en op plausibiliteit toetsen (ontwerp §3, §6).
        onplausibel = np.zeros(n, dtype=bool)
        for bron, naam, factor in self.momentaan:
            waarde = blok[bron].to_numpy(dtype="float64") * factor
            if naam in GRENZEN:
                onder, boven = GRENZEN[naam]
                buiten = (waarde < onder) | (waarde > boven)
                onplausibel |= _telt_als_onplausibel(naam, waarde, buiten)
                waarde = np.where(buiten, np.nan, waarde)
            uit[naam] = waarde.astype("float32")

        # 2. Tellers: nulmetingen eruit, vooruit differentiëren (ontwerp §4, §5).
        nulmeting = np.zeros(n, dtype=bool)
        terug = np.zeros(n, dtype=bool)
        wissel = np.zeros(n, dtype=bool)
        teruglevering = np.zeros(n, dtype=bool)
        standen: dict[str, pd.Series] = {}

        for kolom, naam, factor_naar_J in self.tellers:
            stand = blok[kolom].astype("float64")
            nul = self._nulmetingen(stand, naam, k)
            schoon = stand.where(~nul)
            afgeleid = differentieer_snel(schoon.to_numpy(dtype="float64"), tijd__ns, factor_naar_J)
            standen[naam] = schoon
            nul_np = nul.to_numpy()
            nulmeting |= nul_np
            daalt = afgeleid["delta"] < 0.0
            terug |= daalt
            volgende_is_nul = np.concatenate([nul_np[1:], [False]])
            wissel_hier = daalt & ~volgende_is_nul
            wissel |= wissel_hier
            # A2 (ontwerp-teller-artefacten.md §10): zelfde maskering als in het batchpad hierboven
            # en als 4.3 in het kwartierpad -- het ene interval op NaN, niet de stand.
            if wissel_hier.any():
                afgeleid["delta"] = np.where(wissel_hier, np.nan, afgeleid["delta"])
                afgeleid["vermogen__W"] = np.where(wissel_hier, np.nan, afgeleid["vermogen__W"])
            if naam in EXPORT_TELLERS:
                teruglevering |= afgeleid["delta"] > 0.0
            uit[naam] = schoon.astype("float32")
            self.n_geldig[naam] += int(schoon.iloc[:k].notna().sum())
            if naam == "g_gebruik_cum__m3":
                uit["g_gebruik__m3_s_1"] = afgeleid["vermogen__W"].astype("float32")
            elif naam == "q_geleverd_cum__J":
                uit["q_geleverd__W"] = afgeleid["vermogen__W"].astype("float32")
            elif naam == "e_warmtepomp_cum__kWh":
                uit["p_warmtepomp__W"] = (afgeleid["delta"] * J_PER_KWH / afgeleid["delta_t__s"]).astype("float32")
            elif naam == "e_ketel_cum__kWh":
                uit["p_ketel__W"] = (afgeleid["delta"] * J_PER_KWH / afgeleid["delta_t__s"]).astype("float32")

        # 3. Het elektrasaldo is een samenstelling en mag dalen; daarom pas hier en niet als
        #    brontteller. De float64 blijft: §5.4 van het geheugenontwerp laat zien dat de som van
        #    vier tellers tot boven 19.000 kWh loopt en dat float64 daar de trap op e_net__W
        #    halveert. Per blok kost dat niets meer, want de reeks is nu 100.000 rijen en geen
        #    miljoen.
        invoer = [standen[n_] for n_ in ("e_import_laag_cum__kWh", "e_import_hoog_cum__kWh") if n_ in standen]
        uitvoer = [standen[n_] for n_ in EXPORT_TELLERS if n_ in standen]
        duur__s = np.full(n, np.nan)
        if n >= 2:
            duur__s[:-1] = (tijd__ns[1:] - tijd__ns[:-1]) / 1e9
        if invoer:
            saldo = sum(invoer[1:], invoer[0])
            for reeks in uitvoer:
                saldo = saldo - reeks
            net = differentieer_snel(saldo.to_numpy(dtype="float64"), tijd__ns, J_PER_KWH)
            uit["e_net_cum__kWh"] = saldo.astype("float32")
            uit["e_net__W"] = net["vermogen__W"].astype("float32")
        uit["delta_t__s"] = duur__s.astype("float32")

        # 4. Dekking en offsets ongewijzigd mee (R7: n is het dekkingsgewicht van het gemiddelde).
        for kolom in self.overnemen:
            uit[kolom] = blok[kolom]

        # 5. Vlaggen. Nullable boolean, net als in het kwartierpad.
        uit["teller_nulmeting__bool"] = pd.array(nulmeting, dtype="boolean")
        uit["teller_terug__bool"] = pd.array(terug, dtype="boolean")
        uit["teller_wissel__bool"] = pd.array(wissel, dtype="boolean")
        uit["teruglevering__bool"] = pd.array(teruglevering, dtype="boolean")
        uit["onplausibel__bool"] = pd.array(onplausibel, dtype="boolean")
        gat_na = (uit["delta_t__s"] > 60.0).fillna(False)
        uit["gat_na__bool"] = pd.array(gat_na.to_numpy(), dtype="boolean")
        uitval_na = (uit["delta_t__s"] > UITVAL_DREMPEL__min * 60.0).fillna(False)
        uit["uitval_na__bool"] = pd.array(uitval_na.to_numpy(), dtype="boolean")

        # De gaten komen uit het HELE blok en niet uit het definitieve deel. Een gat hoort bij de
        # latere van twee rijen (``diff`` kijkt achteruit), dus rij 0 van het blok is de
        # doorgeschoven rij en die is vorige ronde al beoordeeld. Zo wordt elke rij precies één keer
        # gewogen: bij aankomst, op index >= 1.
        gaten = bouw_gaten(tijdstip_start, self.home_id)
        if len(gaten):
            self.gaten.append(gaten)

        if k == 0:
            return

        definitief = uit.iloc[:k]
        self.blokken.append(pa.Table.from_pandas(definitief, preserve_index=False))

        for naam in self.PROEFKOLOMMEN:
            if naam in definitief.columns:
                self.proef[naam].append(definitief[naam].to_numpy(dtype="float32"))

        if self.eerste_minuut is None:
            self.eerste_minuut = tijdstip_start.iloc[0]
        self.laatste_minuut = tijdstip_start.iloc[k - 1]
        self.n_rijen += k
        self.n_onplausibel += int(onplausibel[:k].sum())
        self.n_terug += int(terug[:k].sum())
        self.n_nulmeting += int(nulmeting[:k].sum())
        self.n_wissel += int(wissel[:k].sum())

        wp_kolom = definitief.get("p_warmtepomp_gemeten__W")
        if wp_kolom is not None and wp_kolom.notna().any():
            self.wp_max = max(self.wp_max, float(np.nanmax(wp_kolom.to_numpy())))

        for _, naam, _ in self.momentaan:
            self.notna[naam] = self.notna.get(naam, 0) + int(definitief[naam].notna().sum())

    def _nulmetingen(self, stand: pd.Series, naam: str, k: int) -> pd.Series:
        """:func:`markeer_nulmetingen` over een blok, met het lopende maximum van de vorige blokken.

        ``np.maximum`` laat ``NaN`` staan, en dat is hier precies goed: ``cummax`` zet ``NaN`` op de
        posities waar de stand ontbreekt, en de vergelijking ``> 1`` hoort daar ``False`` te geven.
        Was het maximum eroverheen gelegd, dan zou een ontbrekende stand na een hoge stand ineens
        wél meetellen.
        """
        blok_cummax = stand.cummax()
        globale_cummax = np.maximum(blok_cummax.to_numpy(), self.lopend_max[naam])
        eerder_hoogste = np.empty_like(globale_cummax)
        eerder_hoogste[0] = self.vorige_cummax[naam]
        eerder_hoogste[1:] = globale_cummax[:-1]

        if k > 0:
            # Bijwerken op het DEFINITIEVE deel: de laatste rij van het blok schuift door en wordt
            # volgende ronde opnieuw meegerekend, dus die mag hier nog niet in de toestand zitten.
            self.vorige_cummax[naam] = globale_cummax[k - 1]
            waarden = stand.to_numpy()[:k]
            geldig = waarden[~np.isnan(waarden)]
            if geldig.size:
                self.lopend_max[naam] = max(self.lopend_max[naam], float(geldig.max()))
                self.lopend_min[naam] = min(self.lopend_min[naam], float(geldig.min()))

        gevlagd = (stand.to_numpy() == 0.0) & (eerder_hoogste > TELLER_ONTWAAKT_BOVEN)
        return pd.Series(gevlagd, index=stand.index, dtype=bool)

    # -- afronden ------------------------------------------------------------------------------

    def afronden(self) -> Uitkomst:
        """De arrow-tabel, de gaten en de kenmerken, zoals :func:`verwerk_locatie` ze oplevert.

        De metingen komen er als ``pa.Table`` uit en niet als DataFrame: ze zijn per blok al naar
        arrow omgezet, en er weer een pandas-frame van maken zou de kopie terugbrengen die dit hele
        pad juist weghaalt.
        """
        metingen = pa.concat_tables(self.blokken)
        gaten = (
            pd.concat(self.gaten, ignore_index=True)
            if self.gaten
            else bouw_gaten(pd.Series(dtype="datetime64[ms, UTC]"), self.home_id)
        )

        span__min = 0.0
        if self.n_rijen >= 2:
            span__min = (self.laatste_minuut - self.eerste_minuut).total_seconds() / 60.0 + 1.0
        wp_max = self.wp_max if np.isfinite(self.wp_max) else np.nan
        n = self.n_rijen
        kenmerken = {
            "home_id__str": self.home_id,
            "n_minuten": int(n),
            "eerste_minuut": self.eerste_minuut if n else pd.NaT,
            "laatste_minuut": self.laatste_minuut if n else pd.NaT,
            "bezetting__0": float(n / span__min) if span__min > 0 else np.nan,
            "grootste_gat__min": int(gaten["duur__min"].max()) if len(gaten) else 0,
            "n_gaten": int(len(gaten)),
            "n_uitval": int((gaten["soort"] == "uitval").sum()) if len(gaten) else 0,
            "warmtepompkanaal_dood__bool": bool(np.isfinite(wp_max) and wp_max <= WP_UIT_ONDER__W),
            "p_warmtepomp_max__W": wp_max,
            "n_onplausibel": self.n_onplausibel,
            "n_teller_terug": self.n_terug,
            "n_teller_nulmeting": self.n_nulmeting,
            "n_teller_wissel": self.n_wissel,
        }
        proef = pd.DataFrame(
            {naam: np.concatenate(delen) for naam, delen in self.proef.items() if delen}
        )
        kenmerken.update(bepaal_warmtemeter_bereik(proef))
        raster_grenzen = {
            kolom.removesuffix("_eerste"): (self.lopend_min[naam], self.lopend_max[naam])
            for kolom, naam, _ in self.tellers
        }
        kenmerken.update(_raster_kenmerken(raster_grenzen))
        for _, naam, _ in self.momentaan:
            kenmerken[f"dekking_{naam}"] = float(self.notna[naam] / n) if n else np.nan
        for _, naam, _ in self.tellers:
            kenmerken[f"dekking_{naam}"] = float(self.n_geldig[naam] / n) if n else np.nan

        return Uitkomst(home_id=self.home_id, metingen=metingen, gaten=gaten, kenmerken=kenmerken)


def verwerk_locatie_streamend(pad: Path, home_id: str, batchgrootte: int = BATCH_RIJEN) -> Uitkomst:
    """Als :func:`verwerk_locatie`, maar één batch tegelijk in en één tabel aan het eind uit.

    Levert dezelfde kolommen, dezelfde waarden en dezelfde kenmerken als :func:`verwerk_locatie`;
    ``test_minuut_streamend.py`` toetst dat tegen die referentie-implementatie.

    Twee schemakeuzes uit het geheugenontwerp: de zes ``uint16``-kolommen blijven ``uint16`` in
    plaats van naar ``float64`` te verbreden (§5.5), en ``homes_minuut.parquet`` krijgt per teller
    ``raster_<naam>__W`` en ``raster_breuk_<naam>__bool`` (§5.5, §6.7).

    ``sort_values`` is vervangen door een assertie. Alle 174 bronbestanden hebben oplopende,
    niet-overlappende row groups (geheugenontwerp §3), dus sorteren is werk dat al gedaan is; maar
    als een bestand dat ooit niet blijkt te zijn, moet dat een :class:`NietStreambaar` geven en geen
    verkeerd getal.

    **Waarom de uitvoer niet per batch wordt weggeschreven**, zoals §4.4 van het geheugenontwerp
    voorstelt: de uitvoer van één locatie komt als één row group op de NAS te staan, en per batch
    schrijven zou row groups van 100.000 rijen geven in plaats daarvan, met andere bytes voor
    dezelfde getallen. De uitvoer wordt daarom als arrow-batches verzameld en in één keer geschreven;
    dat is de ondergrens die een row group nu eenmaal stelt.
    """
    pf = pq.ParquetFile(pad)
    namen = pf.schema_arrow.names
    if "tijdstip_start" not in namen:
        raise NietStreambaar("de bron heeft geen kolom tijdstip_start")
    staat = _Streamend(home_id, namen)

    wacht: pd.DataFrame | None = None
    vorige_eind: pd.Timestamp | None = None
    for arrow_batch in pf.iter_batches(batch_size=batchgrootte, columns=_nodige_kolommen(namen)):
        # types_mapper voorkomt dat een uint16-kolom met een ontbrekende waarde naar float64
        # verbreedt (§5.5); dat werkt per BATCH consistent, dus een omweg via de footer is niet
        # nodig.
        nieuw = arrow_batch.to_pandas(types_mapper=_types_mapper)
        tijden = nieuw["tijdstip_start"]
        if not tijden.is_monotonic_increasing:
            raise NietStreambaar("een batch is niet oplopend in tijdstip_start")
        if vorige_eind is not None and len(tijden) and tijden.iloc[0] < vorige_eind:
            raise NietStreambaar("twee batches overlappen in tijdstip_start")
        if len(tijden):
            vorige_eind = tijden.iloc[-1]
        blok = nieuw if wacht is None else pd.concat([wacht, nieuw], ignore_index=True)
        staat.blok(blok, flush=False)
        wacht = blok.iloc[-1:].reset_index(drop=True)

    if wacht is None:
        raise NietStreambaar("de bron heeft geen rijen")
    staat.blok(wacht, flush=True)
    return staat.afronden()


# --- schrijven --------------------------------------------------------------------------------


def schrijf_atomisch(tabel: pd.DataFrame | pa.Table, doel: Path) -> None:
    """Lokaal schrijven, in één keer overzetten, dan hernoemen.

    Parquet rechtstreeks naar de netwerkschijf schrijven bleek de duurste stap van de hele run:
    13 s voor een bestand van 11,6 MB, terwijl datzelfde bestand als kopie in anderhalve seconde
    overgaat. Het verschil zit in het aantal schrijfacties, niet in het aantal bytes; parquet
    schrijft kolom voor kolom en elke flush kost een netwerkronde.

    De volgorde blijft atomisch: op de netwerkschijf ontstaat eerst een ``.tmp`` en pas als die
    compleet is krijgt hij zijn definitieve naam. Een afgebroken run laat dus nooit een half
    bestand achter dat bij de hervatting voor af wordt aangezien.

    Een ``pa.Table`` mag er ook in: het streamende pad heeft zijn uitvoer al in arrow staan en er
    eerst een DataFrame van maken zou de kopie terugbrengen die dat pad juist weghaalt.

    **Hier gaat de uitvoer naar lokale tijd**, net als in het kwartierpad: intern rekent het
    minuutpad in UTC, en elke tz-aware tijdkolom die op schijf komt staat in
    :data:`~dph_preprocessing.timestamps.TZ_UITVOER`. Omdat alle parquet-uitvoer van dit pad hier
    langskomt, kan geen tabel er in UTC doorheen glippen.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    tijdelijk = doel.with_suffix(doel.suffix + ".tmp")
    arrow = tabel if isinstance(tabel, pa.Table) else pa.Table.from_pandas(tabel, preserve_index=False)
    arrow = naar_lokale_tijdzone_arrow(arrow)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as houder:
        lokaal = Path(houder.name)
    try:
        pq.write_table(arrow, lokaal, compression="zstd")
        shutil.copyfile(lokaal, tijdelijk)
        os.replace(tijdelijk, doel)
    finally:
        lokaal.unlink(missing_ok=True)


# --- de runner --------------------------------------------------------------------------------


def _bestanden(bron: Path) -> list[Path]:
    """Klein naar groot (ontwerp §10): bij een deadline telt het aantal afgemaakte locaties."""
    return sorted((p for p in bron.iterdir() if p.suffix == ".parquet"), key=lambda p: p.stat().st_size)


def _home_id(pad: Path) -> str:
    naam = pad.stem
    return naam[len("location_id=") :] if naam.startswith("location_id=") else naam


def _verwerk(pad: Path, home_id: str, streamend: bool) -> Uitkomst:
    """Eén locatie, streamend als het mag en volledig als het moet."""
    if streamend:
        try:
            return verwerk_locatie_streamend(pad, home_id)
        except NietStreambaar as reden:
            log.warning("%s valt terug op het volledige pad: %s", home_id, reden)
    # self_destruct geeft elke arrow-buffer vrij zodra hij in pandas staat, in plaats van beide
    # kopieen tot het eind vast te houden. Op een laptop met 7,8 GB is dat het verschil tussen
    # draaien en een ArrowMemoryError.
    ruw = pq.read_table(pad).to_pandas(self_destruct=True, split_blocks=True, types_mapper=_types_mapper)
    try:
        return verwerk_locatie(ruw, home_id)
    finally:
        del ruw


def _ruim_tmp_op(map_: Path) -> int:
    """Achtergebleven ``.tmp``-bestanden weg (geheugenontwerp §4.4).

    Een afgebroken locatie laat er één achter. Hij wordt bij een hervatting niet voor af aangezien
    (dat is precies waarom :func:`schrijf_atomisch` die naam gebruikt), maar hij blijft wel op de
    NAS staan en is bij de volgende afbreking niet meer van de nieuwe te onderscheiden.
    """
    if not map_.exists():
        return 0
    opgeruimd = 0
    for pad in map_.glob("*.parquet.tmp"):
        pad.unlink(missing_ok=True)
        log.info("Achtergebleven %s opgeruimd", pad.name)
        opgeruimd += 1
    return opgeruimd


class AnderContract(RuntimeError):
    """De uitvoermap bevat metingen van een andere contractversie dan deze code schrijft."""


def controleer_contract(doel: Path, droog: bool = False) -> None:
    """Weiger te hervatten op uitvoer van een ander contract; leg anders het huidige vast.

    Een map met metingen maar zonder ``contract.json`` telt als ander contract: die komt van code
    van vóór deze controle, en daar is niet aan te zien wat hij schreef.
    """
    pad = doel / CONTRACT_BESTAND
    versie = json.loads(pad.read_text(encoding="utf-8")).get("contract") if pad.exists() else None
    metingen_map = doel / "metingen"
    heeft_metingen = metingen_map.exists() and any(metingen_map.glob("*.parquet"))
    if heeft_metingen and versie != MINUUT_CONTRACT_VERSIE:
        raise AnderContract(
            f"{doel} bevat metingen van contract {versie or 'onbekend'}, deze code schrijft "
            f"{MINUUT_CONTRACT_VERSIE}. Hervatten zou oude en nieuwe uitvoer mengen; kies een lege "
            "uitvoermap of zet de oude opzij."
        )
    if not droog and versie != MINUUT_CONTRACT_VERSIE:
        doel.mkdir(parents=True, exist_ok=True)
        pad.write_text(json.dumps({"contract": MINUUT_CONTRACT_VERSIE}) + "\n", encoding="utf-8")


def run(
    bron: Path,
    doel: Path,
    deadline: datetime | None = None,
    droog: bool = False,
    beperk: int | None = None,
    streamend: bool = True,
) -> dict:
    """Verwerk alle locaties tot de deadline. Hervatbaar: af is af, en wordt overgeslagen.

    ``streamend`` kiest het pad van :func:`verwerk_locatie_streamend`; met ``False`` gaat alles via
    :func:`verwerk_locatie`, dat de hele locatie in het geheugen zet. Dat is de weg terug als het
    streamende pad ooit iets anders blijkt te doen, en hij blijft daarom bereikbaar.

    Een uitvoermap met metingen van een ander contract geeft :class:`AnderContract`; zie
    :func:`controleer_contract`.
    """
    controleer_contract(doel, droog)
    metingen_map = doel / "metingen"
    bestanden = _bestanden(bron)
    if beperk:
        bestanden = bestanden[:beperk]
    if not droog:
        _ruim_tmp_op(metingen_map)

    gedaan, overgeslagen, mislukt = 0, 0, 0
    alle_gaten: list[pd.DataFrame] = []
    alle_kenmerken: list[dict] = []
    t_start = time.time()

    for i, pad in enumerate(bestanden, 1):
        home_id = _home_id(pad)
        doelbestand = metingen_map / f"location_id={home_id}.parquet"
        if doelbestand.exists():
            overgeslagen += 1
            continue
        if deadline is not None and datetime.now() >= deadline:
            log.warning("Deadline %s bereikt; gestopt na %d van de %d locaties.",
                        deadline.strftime("%H:%M"), i - 1, len(bestanden))
            break
        mb = pad.stat().st_size / 1e6
        if droog:
            log.info("[%3d/%d] %-10s %7.1f MB  zou verwerkt worden", i, len(bestanden), home_id, mb)
            gedaan += 1
            continue
        t0 = time.time()
        try:
            uitkomst = _verwerk(pad, home_id, streamend)
            schrijf_atomisch(uitkomst.metingen, doelbestand)
            if len(uitkomst.gaten):
                alle_gaten.append(uitkomst.gaten)
            alle_kenmerken.append(uitkomst.kenmerken)
            # Meteen wegschrijven, regel voor regel. De kenmerken en de gaten komen uit de ene
            # leesslag en zijn zonder die slag niet te herberekenen; ze pas aan het eind van run()
            # wegschrijven zou ze bij een harde afbreking weggooien terwijl de metingen zelf er
            # wel staan. De compactieslag van gisteravond sneuvelde zo na 24 minuten.
            _voeg_regels_toe(doel / "kenmerken.jsonl", [uitkomst.kenmerken])
            _voeg_regels_toe(doel / "gaten.jsonl", uitkomst.gaten.to_dict("records"))
            gedaan += 1
            log.info("[%3d/%d] %-10s %7.1f MB  %9d rijen  %6.1f s  bereik=%s",
                     i, len(bestanden), home_id, mb, len(uitkomst.metingen), time.time() - t0,
                     uitkomst.kenmerken.get("warmtemeter_bereik__cat", "?"))
            del uitkomst
        except Exception:
            mislukt += 1
            log.exception("[%3d/%d] %-10s MISLUKT; ga door met de volgende", i, len(bestanden), home_id)

    if not droog and alle_kenmerken:
        _schrijf_verzamelingen(doel, alle_gaten, alle_kenmerken)
        _schrijf_dekking(doel)
        _schrijf_kwaliteitsrapport(doel)
    if not droog:
        _schrijf_datapackage(doel)

    samenvatting = {
        "gedaan": gedaan, "overgeslagen": overgeslagen, "mislukt": mislukt,
        "totaal": len(bestanden), "duur__s": round(time.time() - t_start, 1),
    }
    log.info("Klaar: %s", json.dumps(samenvatting))
    return samenvatting


def _lokaal(tijdstip: pd.Timestamp) -> pd.Timestamp:
    return tijdstip.tz_convert(TZ_UITVOER) if tijdstip.tzinfo is not None else tijdstip


def _voeg_regels_toe(pad: Path, regels: list[dict]) -> None:
    """Regels als JSON aan een bestand toevoegen, met tijdstempels als tekst in lokale tijd.

    Lokaal om dezelfde reden als :func:`schrijf_atomisch`: ``gaten.jsonl`` en ``gaten.parquet``
    horen hetzelfde tijdstip op dezelfde manier te schrijven.
    """
    if not regels:
        return
    pad.parent.mkdir(parents=True, exist_ok=True)
    with pad.open("a", encoding="utf-8") as bestand:
        for regel in regels:
            schoon = {
                sleutel: (_lokaal(waarde).isoformat() if isinstance(waarde, pd.Timestamp) else waarde)
                for sleutel, waarde in regel.items()
                if not (isinstance(waarde, float) and np.isnan(waarde))
            }
            print(json.dumps(schoon, default=str), file=bestand)


def _schrijf_verzamelingen(doel: Path, gaten: list[pd.DataFrame], kenmerken: list[dict]) -> None:
    """``gaten.parquet`` en ``homes_minuut.parquet``, aanvullend op wat er al stond.

    Aanvullend en niet overschrijvend, want een run die op de deadline stopt moet de kenmerken van
    een eerdere run niet weggooien.
    """
    nieuw_homes = pd.DataFrame(kenmerken)
    # raster_breuk_<naam>__bool mist bij een locatie zonder die teller (bv. de vier zonder DSMR,
    # §6.6a) en komt dan als NaN binnen in plaats van pd.NA; nullable boolean maakt dat expliciet
    # in plaats van er stilzwijgend een object-kolom van te maken.
    for kolom in nieuw_homes.columns:
        if kolom.startswith("raster_breuk_") and kolom.endswith("__bool"):
            nieuw_homes[kolom] = nieuw_homes[kolom].astype("boolean")
    pad_homes = doel / "homes_minuut.parquet"
    if pad_homes.exists():
        oud = pq.read_table(pad_homes).to_pandas()
        nieuw_homes = pd.concat([oud[~oud["home_id__str"].isin(nieuw_homes["home_id__str"])], nieuw_homes])
    schrijf_atomisch(nieuw_homes.sort_values("home_id__str").reset_index(drop=True), pad_homes)

    if gaten:
        nieuw_gaten = pd.concat(gaten, ignore_index=True)
        pad_gaten = doel / "gaten.parquet"
        if pad_gaten.exists():
            oud = pq.read_table(pad_gaten).to_pandas()
            nieuw_gaten = pd.concat([oud[~oud["home_id__str"].isin(nieuw_gaten["home_id__str"])], nieuw_gaten])
        schrijf_atomisch(nieuw_gaten.reset_index(drop=True), pad_gaten)


def _schrijf_dekking(doel: Path) -> None:
    """``dekking.parquet`` uit de ``gaten.parquet`` en ``homes_minuut.parquet`` die er dan staan.

    Uit de verzamelingen op schijf en niet uit deze run alleen, want een hervatte run verwerkt maar
    een deel van de locaties; zo dekt de tabel altijd alle locaties in de map. Net als het
    kwaliteitsrapport laat een mislukking de run niet vallen, want de metingen staan er al.
    """
    try:
        pad_gaten = doel / "gaten.parquet"
        homes = pq.read_table(doel / "homes_minuut.parquet").to_pandas()
        gaten = (
            pq.read_table(pad_gaten).to_pandas()
            if pad_gaten.exists()
            else bouw_gaten(pd.Series(dtype="datetime64[ms, UTC]"), "")
        )
        schrijf_atomisch(bouw_dekking_tabel(gaten, homes), doel / "dekking.parquet")
        log.info("Dekking geschreven naar %s", doel / "dekking.parquet")
    except Exception:  # noqa: BLE001 - de metingen staan er al; de dekking is bijvangst
        log.exception("dekking.parquet mislukt; de metingen zijn wel weggeschreven")


def _schrijf_kwaliteitsrapport(doel: Path) -> None:
    """``kwaliteit.md`` aan het eind van de run, uit de jsonl's die er dan staan.

    Ontwerp §9 belooft dit rapport als uitvoer, maar niets riep het aan: na de eerste volledige run
    stond het er niet en moest het met de hand gemaakt worden. Een uitvoer die alleen ontstaat als
    iemand eraan denkt, is geen uitvoer.

    De import staat hier en niet bovenaan omdat :mod:`minuut_rapport` deze module importeert; op
    modulenieveau zou dat een kringverwijzing zijn. En een mislukt rapport mag een geslaagde run niet
    alsnog laten vallen, want de data is dan al weggeschreven.
    """
    try:
        from dph_preprocessing import minuut_rapport

        pad = doel / "kwaliteit.md"
        pad.write_text(minuut_rapport.bouw_rapport(doel), encoding="utf-8")
        log.info("Kwaliteitsrapport geschreven naar %s", pad)
    except Exception:  # noqa: BLE001 - de metingen staan er al; het rapport is bijvangst
        log.exception("Kwaliteitsrapport mislukt; de metingen zijn wel weggeschreven")


def _schrijf_datapackage(doel: Path) -> None:
    """``datapackage.json`` in de uitvoermap: de machineleesbare beschrijving van deze tabellen.

    Uit de code (:mod:`dph_preprocessing.datapackage`) en niet uit de data, dus ook na een hervatting
    die niets meer te doen had. Lokale import om dezelfde reden als bij
    :func:`_schrijf_kwaliteitsrapport`: ``datapackage`` importeert deze module. Een mislukking laat de
    run niet vallen, want de metingen staan er dan al.
    """
    try:
        from dph_preprocessing import datapackage

        metingen_map = doel / "metingen"
        n_bestanden = len(list(metingen_map.glob("*.parquet"))) if metingen_map.exists() else 0
        pad = datapackage.schrijf_datapackage(
            doel / datapackage.DATAPACKAGE_BESTANDSNAAM, onderdeel="minuut", n_metingenbestanden=n_bestanden
        )
        log.info("Datapackage geschreven naar %s", pad)
    except Exception:  # noqa: BLE001 - de metingen staan er al; het datapackage is bijvangst
        log.exception("datapackage.json mislukt; de metingen zijn wel weggeschreven")


def _parse_deadline(tekst: str | None) -> datetime | None:
    if not tekst:
        return None
    uur, minuut = (int(deel) for deel in tekst.split(":"))
    nu = datetime.now()
    kandidaat = nu.replace(hour=uur, minute=minuut, second=0, microsecond=0)
    if kandidaat <= nu:
        kandidaat = kandidaat + pd.Timedelta(days=1).to_pytimedelta()
    return kandidaat


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bron", default=BRON_STANDAARD, help="map met location_id=*.parquet")
    p.add_argument("--doel", default=DOEL_STANDAARD, help="uitvoermap")
    p.add_argument("--deadline", default=None, help="HH:MM; stopt schoon vóór de volgende locatie")
    p.add_argument("--beperk", type=int, default=None, help="alleen de eerste N locaties")
    p.add_argument("--droog", action="store_true", help="niets lezen of schrijven, alleen het plan")
    p.add_argument("--volledig", action="store_true",
                   help="elke locatie in één keer in het geheugen, zonder het streamende pad")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    deadline = _parse_deadline(args.deadline)
    if deadline:
        log.info("Deadline: %s (over %.1f uur)", deadline.strftime("%Y-%m-%d %H:%M"),
                 (deadline - datetime.now()).total_seconds() / 3600)
    samenvatting = run(Path(args.bron), Path(args.doel), deadline=deadline,
                       droog=args.droog, beperk=args.beperk, streamend=not args.volledig)
    return 0 if samenvatting["mislukt"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
