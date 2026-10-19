# SPDX-License-Identifier: EUPL-1.2
"""Referentieschema's van de uitvoer van beide paden: welke kolommen, in welke volgorde, met welk
Parquet-type.

**Waarvoor.** De pijplijnen schrijven hun tabellen via pandas (``chunking.schrijf_part_atomisch``,
``minuut.schrijf_atomisch``), en het Parquet-type volgt dan uit de dtypes. Er stond dus nergens één
plek waar het uitvoercontract als schema te lezen was. Deze module is die plek, en
:mod:`dph_preprocessing.datapackage` bouwt ``datapackage.json`` hieruit. Het zijn
REFERENTIESCHEMA's, net als ``tabellen.ETMAAL_SCHEMA`` e.d. in de WarmingUP-preprocessing: ze sturen
het schrijfpad niet aan, maar ``tests/test_datapackage.py`` draait beide pijplijnen op een kleine
synthetische bron en eist dat de geschreven bestanden precies deze kolommen met precies deze typen
hebben. Loopt de code weg van dit schema, dan wordt die test rood.

**Geverifieerd tegen de echte uitvoer.** De typen hieronder zijn afgelezen uit de Parquet-footers van
de volledige kwartierrun (contract ``2026-09-22-teller-artefacten``) en de volledige minuutrun
(contract ``2026-09-24-lokale-tijd``, 174 locaties), niet uit de code afgeleid.

**Kolommen die de code per grootheid opbouwt, worden hier ook zo opgebouwd**: uit
``minuut.MOMENTAAN``, ``minuut.TELLERS`` en ``minuut.OVERNEMEN``. Een nieuwe momentane grootheid in
het minuutpad verschijnt dan vanzelf in het schema en in het datapackage, en de test controleert dat
de pijplijn hem ook echt schrijft.
"""

from __future__ import annotations

import pyarrow as pa

from . import minuut
from .timestamps import TZ_UITVOER

_STR = pa.large_string()
_CAT = pa.dictionary(pa.int8(), pa.string())
_F32 = pa.float32()
_F64 = pa.float64()
_KWARTIER_TIJD = pa.timestamp("us", tz=TZ_UITVOER)
_MINUUT_TIJD = pa.timestamp("ms", tz=TZ_UITVOER)


# --- kwartierpad (pipeline.py, tabellen.py) ------------------------------------------------------

HOMES_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("woningtype__cat", _CAT),
        ("bouwjaar_klasse__cat", _CAT),
        ("oppervlak_klasse__cat", _CAT),
        ("energielabel__cat", _CAT),
        ("bewoners__cat", _CAT),
        ("eigendom__cat", _CAT),
        ("gas_voor_2__m3", _F32),
        ("gas_voor_1__m3", _F32),
        ("elektra_voor_2__kWh", _F32),
        ("elektra_voor_1__kWh", _F32),
        ("heeft_vloerverwarming__bool", pa.bool_()),
        ("heeft_radiatoren__bool", pa.bool_()),
        ("heeft_gasfornuis__bool", pa.bool_()),
        ("heeft_dubbelglas__bool", pa.bool_()),
        ("heeft_dakisolatie__bool", pa.bool_()),
        ("heeft_muurisolatie__bool", pa.bool_()),
        ("heeft_vloerisolatie__bool", pa.bool_()),
        ("elektrameting_verdacht__cat", _CAT),
    ]
)

MEASUREMENTS_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("tijdstip_start", _KWARTIER_TIJD),
        ("tijdstip_meting", _KWARTIER_TIJD),
        ("e_import_laag_cum__kWh", _F64),
        ("e_import_hoog_cum__kWh", _F64),
        ("e_export_laag_cum__kWh", _F64),
        ("e_export_hoog_cum__kWh", _F64),
        ("g_gebruik_cum__m3", _F64),
        ("e_warmtepomp_cum__kWh", _F64),
        ("e_ketel_cum__kWh", _F64),
        ("q_geleverd_cum__J", _F32),
    ]
)

DERIVED_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("tijdstip_start", _KWARTIER_TIJD),
        ("g_gebruik__W", _F32),
        ("p_warmtepomp__W", _F32),
        ("p_ketel__W", _F32),
        ("q_geleverd__W", _F32),
        ("e_net__W", _F32),
        ("actual_gas_std_hhv__J_m_3", _F32),
        ("gas_hhv_bron__cat", _CAT),
        ("u_L1_meting__V", _F32),
        ("u_L2_meting__V", _F32),
        ("u_L3_meting__V", _F32),
        ("i_L1_meting__A", _F32),
        ("i_L2_meting__A", _F32),
        ("i_L3_meting__A", _F32),
        ("p_import_L1_meting__W", _F32),
        ("p_import_L2_meting__W", _F32),
        ("p_import_L3_meting__W", _F32),
        ("p_export_L1_meting__W", _F32),
        ("p_export_L2_meting__W", _F32),
        ("p_export_L3_meting__W", _F32),
        ("temp_aanvoer_meting__degC", _F32),
        ("temp_retour_meting__degC", _F32),
        ("debiet_meting__dm3_s_1", _F32),
        ("q_geleverd_meting__W", _F32),
        ("p_warmtepomp_meting__W", _F32),
        ("p_ketel_meting__W", _F32),
        ("temp_binnen_meting__degC", _F32),
        ("rv_binnen_meting__0", _F32),
        ("temp_buiten__degC", _F32),
        ("wind__m_s_1", _F32),
        ("ghi__W_m_2", _F32),
    ]
)

WEER_SCHEMA = pa.schema(
    [
        ("weerstation_nr", pa.int32()),
        ("tijdstip_start", _KWARTIER_TIJD),
        ("temp_buiten__degC", _F32),
        ("wind__m_s_1", _F32),
        ("ghi__W_m_2", _F32),
    ]
)

QUALITY_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("tijdstip_start", _KWARTIER_TIJD),
        ("ontbrekend__bool", pa.bool_()),
        ("scheef__bool", pa.bool_()),
        ("teller_initialisatie__bool", pa.bool_()),
        ("teller_nulmeting__bool", pa.bool_()),
        ("teller_wissel__bool", pa.bool_()),
        ("teller_terug__bool", pa.bool_()),
        ("teruglevering__bool", pa.bool_()),
        ("teller_sprong__bool", pa.bool_()),
        ("bron_incompleet__bool", pa.bool_()),
    ]
)

#: ``scheefheid.parquet`` is geen contracttabel (zie ``pipeline._verwerk_en_schrijf_chunk``), maar hij
#: staat wel in de uitvoermap en hoort daarom beschreven te zijn.
SCHEEFHEID_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("bron", _STR),
        ("mediaan__s", _F32),
        ("p95__s", _F64),
        ("max__s", _F32),
        ("n", pa.int64()),
    ]
)

#: Tabelnaam -> schema, in de volgorde waarin ze in het datapackage verschijnen. De bestandsnaam is
#: steeds ``<naam>.parquet`` in de uitvoermap van ``pipeline.run``.
KWARTIER_SCHEMAS: dict[str, pa.Schema] = {
    "homes": HOMES_SCHEMA,
    "measurements": MEASUREMENTS_SCHEMA,
    "derived": DERIVED_SCHEMA,
    "weer": WEER_SCHEMA,
    "quality": QUALITY_SCHEMA,
    "scheefheid": SCHEEFHEID_SCHEMA,
}


# --- minuutpad (minuut.py, minuut_dekking.py) ----------------------------------------------------

#: Afgeleide kolom die direct na een tellerstand komt (``minuut._Streamend.blok``, stap 2).
MINUUT_AFGELEID_NA_TELLER: dict[str, str] = {
    "g_gebruik_cum__m3": "g_gebruik__m3_s_1",
    "e_warmtepomp_cum__kWh": "p_warmtepomp__W",
    "e_ketel_cum__kWh": "p_ketel__W",
    "q_geleverd_cum__J": "q_geleverd__W",
}

#: De zeven vlaggen van het minuutpad, in de volgorde van ``minuut._Streamend.blok``, stap 5.
MINUUT_VLAGGEN: tuple[str, ...] = (
    "teller_nulmeting__bool",
    "teller_terug__bool",
    "teller_wissel__bool",
    "teruglevering__bool",
    "onplausibel__bool",
    "gat_na__bool",
    "uitval_na__bool",
)


def _minuut_tellernamen() -> list[str]:
    return [naam for naam, _ in minuut.TELLERS.values()]


def _minuut_momentaan_namen() -> list[str]:
    return [naam for naam, _ in minuut.MOMENTAAN.values()]


def _bouw_metingen_schema() -> pa.Schema:
    velden: list[tuple[str, pa.DataType]] = [("home_id__str", _STR), ("tijdstip_start", _MINUUT_TIJD)]
    velden += [(naam, _F32) for naam in _minuut_momentaan_namen()]
    for naam in _minuut_tellernamen():
        velden.append((naam, _F32))
        if naam in MINUUT_AFGELEID_NA_TELLER:
            velden.append((MINUUT_AFGELEID_NA_TELLER[naam], _F32))
    velden += [("e_net_cum__kWh", _F32), ("e_net__W", _F32), ("delta_t__s", _F32)]
    velden += [(kolom, pa.uint16()) for kolom in minuut.OVERNEMEN]
    velden += [(vlag, pa.bool_()) for vlag in MINUUT_VLAGGEN]
    return pa.schema(velden)


def _bouw_homes_minuut_schema() -> pa.Schema:
    velden: list[tuple[str, pa.DataType]] = [
        ("home_id__str", _STR),
        ("n_minuten", pa.int64()),
        ("eerste_minuut", _MINUUT_TIJD),
        ("laatste_minuut", _MINUUT_TIJD),
        ("bezetting__0", _F64),
        ("grootste_gat__min", pa.int64()),
        ("n_gaten", pa.int64()),
        ("n_uitval", pa.int64()),
        ("warmtepompkanaal_dood__bool", pa.bool_()),
        ("p_warmtepomp_max__W", _F64),
        ("n_onplausibel", pa.int64()),
        ("n_teller_terug", pa.int64()),
        ("n_teller_nulmeting", pa.int64()),
        ("n_teller_wissel", pa.int64()),
        ("bereik_n", pa.int64()),
        ("bereik_fractie", _F64),
        ("bereik_controle", _F64),
        ("bereik_referentie", _F64),
        ("warmtemeter_bereik__cat", _STR),
    ]
    for naam in _minuut_tellernamen():
        kort = naam.split("__")[0]
        velden += [(f"raster_{kort}__W", _F64), (f"raster_breuk_{kort}__bool", pa.bool_())]
    velden += [(f"dekking_{naam}", _F64) for naam in _minuut_momentaan_namen()]
    velden += [(f"dekking_{naam}", _F64) for naam in _minuut_tellernamen()]
    return pa.schema(velden)


METINGEN_SCHEMA = _bouw_metingen_schema()
HOMES_MINUUT_SCHEMA = _bouw_homes_minuut_schema()

GATEN_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("begin", _MINUUT_TIJD),
        ("eind", _MINUUT_TIJD),
        ("duur__min", pa.int64()),
        ("soort", _STR),
    ]
)

DEKKING_SCHEMA = pa.schema(
    [
        ("home_id__str", _STR),
        ("kolom__str", _STR),
        ("drempel__min", _F64),
        ("totale_tijd__min", _F64),
        ("gedekte_tijd__min", _F64),
        ("aandeel_gedekt", _F64),
    ]
)

#: Tabelnaam -> schema. ``metingen`` is één bestand per locatie
#: (``metingen/location_id=<id>.parquet``); de andere drie staan als ``<naam>.parquet`` in de
#: uitvoermap van ``minuut.run``.
MINUUT_SCHEMAS: dict[str, pa.Schema] = {
    "metingen": METINGEN_SCHEMA,
    "homes_minuut": HOMES_MINUUT_SCHEMA,
    "gaten": GATEN_SCHEMA,
    "dekking": DEKKING_SCHEMA,
}
