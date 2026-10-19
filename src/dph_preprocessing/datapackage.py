# SPDX-License-Identifier: EUPL-1.2
"""Bouwt ``datapackage.json`` (Frictionless Data Package v1, met een Table Schema per resource) UIT
DE CODE, niet met de hand bijgehouden.

**Bron van waarheid.** De velden per resource komen uit de referentieschema's in
:mod:`dph_preprocessing.uitvoerschema` (``KWARTIER_SCHEMAS``, ``MINUUT_SCHEMAS``). Een test
(``tests/test_datapackage.py``) borgt twee dingen: dat elk veld in een schema in het datapackage staat
en omgekeerd, en dat beide pijplijnen op een synthetische bron precies die schema's schrijven. Code,
schema en datapackage kunnen dus niet uit de pas lopen zonder dat een test rood wordt.

De beschrijving per veld staat hieronder in :data:`VELD_BESCHRIJVINGEN`; voor de kolommen die de code
per grootheid opbouwt (de ``dekking_*``- en ``raster_*``-kolommen van ``homes_minuut``) maakt
:func:`_beschrijving` de tekst uit de naam. De volledige toelichting per kolom, met de exacte regel
per kwaliteitsvlag, staat in ``docs/datacatalogus.md``.

**Twee paden, drie plekken.** Het kwartierpad (``pipeline.run``) en het minuutpad (``minuut.run``)
schrijven elk naar een eigen uitvoermap, en elk schrijft aan het eind van zijn run een
``datapackage.json`` met alleen zijn eigen tabellen in die map; de paden in dat bestand zijn relatief
aan die map, zoals de standaard vraagt. De kopie in de repo-root (``python -m
dph_preprocessing.datapackage``) beschrijft beide paden samen; daar staat per resource in
``uitvoerpad`` bij welke uitvoermap hij hoort, want naast de root staat geen data.

**Resourcepad van ``metingen``: een patroon-string.** Het minuutpad schrijft één bestand per locatie.
Een ``path`` als lijst (multipart) betekent in Data Package "plak deze bestanden aan elkaar tot één
bytestroom", en dat levert voor Parquet geen geldig bestand op; ``frictionless`` wijst het bij deze
resources ook af. Daarom altijd ``"metingen/location_id=*.parquet"``, net als de oplossing in de
WarmingUP-preprocessing (commit 47f7e74 daar). Het aantal bestanden van een concrete run komt alleen
in de titel.

**``primaryKey``: waar de code uniciteit garandeert.** Niet nageteld op de volledige uitvoer; de
onderbouwing per tabel staat in :data:`_PRIMARY_KEY_ONDERBOUWING` en komt als
``primaryKeyOnderbouwing`` in elk resource mee. Eén uitzondering is bekend: de ``dekking.parquet``
van de minuutrun van 24-09-2026 is geschreven vóór de code drempel 0 maar één keer opnam, en bevat
daardoor per kolom twee rijen met ``drempel__min`` 0. De huidige code schrijft hem zonder dubbelingen
(``tests/test_minuut_dekking.py``).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pyarrow as pa

from . import minuut, uitvoerschema
from .chunking import UITVOER_CONTRACT_VERSIE
from .minuut import MINUUT_CONTRACT_VERSIE

DATAPACKAGE_BESTANDSNAAM = "datapackage.json"

ONDERDELEN = ("kwartier", "minuut", "beide")

KITE_PAGINA_URL = "https://kennisdelen.rvo.nl/"  # community "Kennis- en Dataplatform Individuele Technieken", projectpagina Demo Project Hybride
BRON_DOWNLOAD_URL = "https://data.inversable.cloud/demoprojecthybride/datasets/demoprojecthybride-dataset.zip"
#: sha256 en omvang van de kopie waarop de volledige kwartierrun draaide (lokaal ``dph-dataset.zip``
#: genoemd, gedownload van :data:`BRON_DOWNLOAD_URL`). Een andere versie van het archief geeft een
#: andere hash; dan is het niet dezelfde invoer.
BRON_SHA256 = "215bcc04fc8c89e1544c0f8a4f011a05cbb2700f5f448341e2592f74bc06f510"
BRON_OMVANG__B = 393_553_249

_ARROW_NAAR_TYPE = {
    pa.types.is_string: "string",
    pa.types.is_large_string: "string",
    pa.types.is_dictionary: "string",  # een pandas-category met tekstlabels
    pa.types.is_boolean: "boolean",
    pa.types.is_integer: "integer",
    pa.types.is_floating: "number",
    pa.types.is_timestamp: "datetime",
}


def table_schema_type(arrow_type: pa.DataType) -> tuple[str, dict]:
    """Het Table Schema-type bij een Arrow-type, plus eventuele extra veldeigenschappen."""
    for test, naam in _ARROW_NAAR_TYPE.items():
        if test(arrow_type):
            extra = {}
            if naam == "datetime":
                extra["format"] = "default"  # ISO 8601 met offset; pyarrow schrijft een tz-aware instant
            return naam, extra
    raise ValueError(f"Geen Table Schema-type bekend voor Arrow-type {arrow_type!r}")


# --- beschrijvingen ---------------------------------------------------------------------------------

_WONING = "Gepseudonimiseerde woningsleutel van acht tekens (bron: location_id; in household.csv participant_id)."
_KWARTIER_START = (
    "Begin van het kwartier [tijdstip_start, tijdstip_start + 15 min), afgeleid als floor(tijdstip_meting, "
    "15 min). Tz-aware Europe/Amsterdam; de bron is UTC en het instant is ongewijzigd."
)
_STEEKPROEF = "Momentane steekproef op het meetmoment van de bron, geen intervalgemiddelde"
_VERMOGEN_UIT_TELLER = (
    "gemiddeld over het interval tot de volgende aflezing van dezelfde woning: verschil van de teller "
    "gedeeld door de werkelijke intervalduur. NaN op de laatste rij van een woning en op een interval "
    "met een gemaskeerde stand of een tellerwissel."
)

#: Beschrijving per (resourcenaam, veldnaam). Overgenomen uit docs/datacatalogus.md, die de bron per
#: bewering noemt.
VELD_BESCHRIJVINGEN: dict[str, dict[str, str]] = {
    "homes": {
        "home_id__str": _WONING,
        "woningtype__cat": "Woningtype zoals opgegeven bij aanmelding (bron: house_type).",
        "bouwjaar_klasse__cat": "Bouwjaarklasse van 20 jaar, niet het jaar zelf (bron: construction_year).",
        "oppervlak_klasse__cat": "Klasse van het woonoppervlak, stappen van 50 m² (bron: surface).",
        "energielabel__cat": "Energielabel (bron: energylabel); niet bij elke woning ingevuld.",
        "bewoners__cat": "Aantal bewoners als categorie '1' of '2+', geen getal (bron: number_of_inhabitants).",
        "eigendom__cat": "Particulier of woningcorporatie (bron: ownership).",
        "gas_voor_2__m3": "Jaargasverbruik ongeveer twee jaar vóór installatie van de hybride, uit de energiejaarrekening (bron: gas_before_2).",
        "gas_voor_1__m3": "Jaargasverbruik ongeveer één jaar vóór installatie (bron: gas_before_1).",
        "elektra_voor_2__kWh": "Jaarelektriciteitsverbruik ongeveer twee jaar vóór installatie (bron: electricity_before_2).",
        "elektra_voor_1__kWh": "Jaarelektriciteitsverbruik ongeveer één jaar vóór installatie (bron: electricity_before_1).",
        "heeft_vloerverwarming__bool": "Lage-temperatuurvloerverwarming aanwezig (bron: has_low_heat_floor_heating).",
        "heeft_radiatoren__bool": "Radiatoren aanwezig (bron: has_high_heat_radiator_heating).",
        "heeft_gasfornuis__bool": "Koken op gas; False is inductie (bron: has_gas_furnace).",
        "heeft_dubbelglas__bool": "Ten minste dubbel glas (bron: has_double_paned_glass).",
        "heeft_dakisolatie__bool": "Dakisolatie aanwezig (bron: has_roofinsulation).",
        "heeft_muurisolatie__bool": "Muurisolatie aanwezig (bron: has_wallinsulation).",
        "heeft_vloerisolatie__bool": "Vloerisolatie aanwezig (bron: has_floorinsulation).",
        "elektrameting_verdacht__cat": (
            "Deugt de elektriciteitsmeting van de warmtepomp: '0' bruikbaar, '1' onbruikbaar, '2' tijdens het "
            "project gerepareerd (bron: wrong_elec_measurement; niet in metadata.csv, betekenis uit "
            "notebooks/README.md van het analysepakket)."
        ),
    },
    "measurements": {
        "home_id__str": _WONING,
        "tijdstip_start": _KWARTIER_START + " Roostersleutel; de stand hoort bij tijdstip_meting.",
        "tijdstip_meting": (
            "Originele tijdstempel van de meting; als meer bronnen in het kwartier vallen de eerste "
            "beschikbare in de volgorde dsmr, kamstrup, heatpump, boiler. Tz-aware Europe/Amsterdam."
        ),
        "e_import_laag_cum__kWh": "Meterstand afgenomen elektriciteit, laagtarief (bron: dsmr.e_consumed_low). NaN bij een initialisatietelegram of nulmeting.",
        "e_import_hoog_cum__kWh": "Meterstand afgenomen elektriciteit, normaaltarief (bron: dsmr.e_consumed_high). NaN bij een initialisatietelegram of nulmeting.",
        "e_export_laag_cum__kWh": "Meterstand teruggeleverde elektriciteit, laagtarief (bron: dsmr.e_delivered_low). NaN bij een initialisatietelegram of nulmeting.",
        "e_export_hoog_cum__kWh": "Meterstand teruggeleverde elektriciteit, normaaltarief (bron: dsmr.e_delivered_high). NaN bij een initialisatietelegram of nulmeting.",
        "g_gebruik_cum__m3": "Meterstand gas (bron: dsmr.v_gas_consumed). NaN bij een initialisatietelegram of nulmeting.",
        "e_warmtepomp_cum__kWh": "Meterstand elektriciteitsverbruik van de warmtepomp, aparte kWh-meter (bron: heatpump.energy). NaN bij een nulmeting.",
        "e_ketel_cum__kWh": "Meterstand elektriciteitsverbruik van de cv-ketel, niet het gas (bron: boiler.energy). NaN bij een nulmeting.",
        "q_geleverd_cum__J": "Meterstand geleverde warmte van de warmtemeter (bron: kamstrup.e_thermal_system, GJ x 10^9). NaN bij een nulmeting.",
    },
    "derived": {
        "home_id__str": _WONING,
        "tijdstip_start": _KWARTIER_START,
        "g_gebruik__W": "Gasvermogen, " + _VERMOGEN_UIT_TELLER + " Van m³ naar J met actual_gas_std_hhv__J_m_3 van het uur waarin het interval begint.",
        "p_warmtepomp__W": "Elektrisch vermogen van de warmtepomp uit e_warmtepomp_cum__kWh, " + _VERMOGEN_UIT_TELLER,
        "p_ketel__W": "Elektrisch vermogen van de cv-ketel (niet het gas) uit e_ketel_cum__kWh, " + _VERMOGEN_UIT_TELLER,
        "q_geleverd__W": "Geleverd warmtevermogen uit q_geleverd_cum__J, " + _VERMOGEN_UIT_TELLER,
        "e_net__W": (
            "Netto elektriciteitsvermogen van de woning uit (import laag + hoog) min (export laag + hoog), "
            + _VERMOGEN_UIT_TELLER + " Mag negatief zijn bij teruglevering."
        ),
        "actual_gas_std_hhv__J_m_3": (
            "Toegepaste calorische bovenwaarde van het gas: landelijk uurgemiddelde over de netgebieden met "
            "G-gas (mijnenergiedata.nl), of 35,17 MJ/m³ als terugval. Nooit leeg."
        ),
        "gas_hhv_bron__cat": "Herkomst van actual_gas_std_hhv__J_m_3: 'mijnenergiedata_actueel' of 'vast_gemiddelde_fallback'.",
        "u_L1_meting__V": _STEEKPROEF + ", spanning fase 1 (bron: dsmr.u_L1).",
        "u_L2_meting__V": _STEEKPROEF + ", spanning fase 2 (bron: dsmr.u_L2).",
        "u_L3_meting__V": _STEEKPROEF + ", spanning fase 3 (bron: dsmr.u_L3).",
        "i_L1_meting__A": _STEEKPROEF + ", stroom fase 1 (bron: dsmr.i_L1).",
        "i_L2_meting__A": _STEEKPROEF + ", stroom fase 2 (bron: dsmr.i_L2).",
        "i_L3_meting__A": _STEEKPROEF + ", stroom fase 3 (bron: dsmr.i_L3).",
        "p_import_L1_meting__W": _STEEKPROEF + ", afgenomen vermogen fase 1 (bron: dsmr.p_consumed_L1, kW x 1000).",
        "p_import_L2_meting__W": _STEEKPROEF + ", afgenomen vermogen fase 2 (bron: dsmr.p_consumed_L2, kW x 1000).",
        "p_import_L3_meting__W": _STEEKPROEF + ", afgenomen vermogen fase 3 (bron: dsmr.p_consumed_L3, kW x 1000).",
        "p_export_L1_meting__W": _STEEKPROEF + ", teruggeleverd vermogen fase 1 (bron: dsmr.p_delivered_L1, kW x 1000).",
        "p_export_L2_meting__W": _STEEKPROEF + ", teruggeleverd vermogen fase 2 (bron: dsmr.p_delivered_L2, kW x 1000).",
        "p_export_L3_meting__W": _STEEKPROEF + ", teruggeleverd vermogen fase 3 (bron: dsmr.p_delivered_L3, kW x 1000).",
        "temp_aanvoer_meting__degC": _STEEKPROEF + ", aanvoertemperatuur van de warmtemeter (bron: kamstrup.t_supply).",
        "temp_retour_meting__degC": _STEEKPROEF + ", retourtemperatuur van de warmtemeter (bron: kamstrup.t_return).",
        "debiet_meting__dm3_s_1": _STEEKPROEF + ", debiet van de warmtemeter (bron: kamstrup.f_system, L/h / 3600).",
        "q_geleverd_meting__W": _STEEKPROEF + ", warmtevermogen van de warmtemeter (bron: kamstrup.p_thermal_system, kW x 1000).",
        "p_warmtepomp_meting__W": _STEEKPROEF + ", elektrisch vermogen van de warmtepomp (bron: heatpump.power).",
        "p_ketel_meting__W": _STEEKPROEF + ", elektrisch vermogen van de cv-ketel (bron: boiler.power).",
        "temp_binnen_meting__degC": _STEEKPROEF + ", woonkamertemperatuur (bron: room.temperature).",
        "rv_binnen_meting__0": _STEEKPROEF + ", relatieve luchtvochtigheid als fractie (bron: room.humidity / 100).",
        "temp_buiten__degC": "Buitentemperatuur van het KNMI-uur waarin tijdstip_start valt, van het station van de woning (uit weer).",
        "wind__m_s_1": "Uurgemiddelde windsnelheid van het KNMI-uur waarin tijdstip_start valt (uit weer).",
        "ghi__W_m_2": "Gemiddelde globale instraling over het KNMI-uur waarin tijdstip_start valt (uit weer).",
    },
    "weer": {
        "weerstation_nr": "KNMI-stationsnummer, het dichtstbijzijnde station van de woningen die het gebruiken (bron: knmi.station_code).",
        "tijdstip_start": (
            "Begin van het KNMI-uur [tijdstip_start, tijdstip_start + 1 h). De bron is eind-gelabeld en is "
            "één uur teruggeschoven. Tz-aware Europe/Amsterdam."
        ),
        "temp_buiten__degC": "Buitentemperatuur (bron: knmi.T, 0,1 °C / 10).",
        "wind__m_s_1": "Uurgemiddelde windsnelheid (bron: knmi.FH, 0,1 m/s / 10).",
        "ghi__W_m_2": "Gemiddelde globale instraling over het uur (bron: knmi.Q, J/cm² per uur x 10^4 / 3600).",
    },
    "quality": {
        "home_id__str": _WONING,
        "tijdstip_start": _KWARTIER_START + " Volledig rooster van het eerste tot het laatste waargenomen kwartier per woning.",
        "ontbrekend__bool": (
            "True als geen van de vier tellerbronnen (dsmr, kamstrup, heatpump, boiler) een meting heeft in dit "
            "kwartier. Zo'n rij staat alleen in quality; de andere vlaggen zijn er leeg."
        ),
        "scheef__bool": (
            "True als bij minstens één tellerbron de meting meer dan 300 s na de kwartiergrens lag; leeg als geen "
            "bron een meting had."
        ),
        "teller_initialisatie__bool": (
            "True als de vijf DSMR-registers tegelijk exact op de sentinel van het initialisatietelegram staan "
            "(8969,994, 8789,167, 3433,300 en 8299,146 kWh, 5059,199 m³); die standen zijn in measurements NaN."
        ),
        "teller_nulmeting__bool": (
            "True als minstens één van de acht brontellers exact 0,0 leest terwijl die teller bij deze woning "
            "eerder boven 1 stond (lopend maximum zonder deze rij); die stand is in measurements NaN."
        ),
        "teller_wissel__bool": (
            "True als minstens één van de acht brontellers daalt naar de volgende rij van dezelfde woning, "
            "na maskering van sentinel en nulmeting; het vermogen van dat ene interval is NaN, de stand niet."
        ),
        "teller_terug__bool": "OR van teller_nulmeting__bool en teller_wissel__bool; e_net telt niet mee.",
        "teruglevering__bool": (
            "True als e_export_laag_cum__kWh of e_export_hoog_cum__kWh stijgt naar de volgende rij; leeg als "
            "geen van beide een interval heeft."
        ),
        "teller_sprong__bool": (
            "True als de absolute waarde van een intervalvermogen boven zijn drempel ligt: e_net__W 40 kW, "
            "g_gebruik__W 100 kW, p_warmtepomp__W 10 kW, p_ketel__W 1 kW, q_geleverd__W 50 kW; leeg als alle "
            "vijf NaN zijn."
        ),
        "bron_incompleet__bool": "True als niet alle vier de tellerbronnen een meting hebben in dit kwartier.",
    },
    "scheefheid": {
        "home_id__str": _WONING,
        "bron": "Tellerbron: dsmr, kamstrup, heatpump of boiler.",
        "mediaan__s": "Mediaan van tijdstip_meting - tijdstip_start over de metingen van deze bron bij deze woning.",
        "p95__s": "95e percentiel van dezelfde afwijking.",
        "max__s": "Grootste afwijking.",
        "n": "Aantal metingen waarover gerekend is.",
    },
    "metingen": {
        "home_id__str": _WONING,
        "tijdstip_start": (
            "Begin van de minuut [tijdstip_start, tijdstip_start + 1 min), in de extractie al op de minuutgrens. "
            "Tz-aware Europe/Amsterdam; intern UTC."
        ),
        "e_net_cum__kWh": "Samengestelde stand (import laag + hoog) min (export laag + hoog), na maskering van nulmetingen.",
        "e_net__W": "Netto elektriciteitsvermogen uit e_net_cum__kWh tot de volgende minuut; mag negatief zijn en mag dalen.",
        "g_gebruik__m3_s_1": "Gasdebiet uit g_gebruik_cum__m3 tot de volgende minuut, in m³/s; niet omgerekend naar W.",
        "p_warmtepomp__W": "Elektrisch vermogen van de warmtepomp uit e_warmtepomp_cum__kWh tot de volgende minuut.",
        "p_ketel__W": "Elektrisch vermogen van de cv-ketel uit e_ketel_cum__kWh tot de volgende minuut.",
        "q_geleverd__W": "Warmtevermogen uit q_geleverd_cum__J tot de volgende minuut.",
        "delta_t__s": "Werkelijke tijd tot de volgende aanwezige minuut van deze locatie; NaN op de laatste rij.",
        "teller_nulmeting__bool": (
            "True als minstens één brontteller exact 0,0 leest terwijl die teller bij deze locatie eerder boven 1 "
            "stond; die stand is NaN."
        ),
        "teller_terug__bool": (
            "True als minstens één brontteller daalt naar de volgende minuut, na maskering van nulmetingen. Een "
            "daling naar een nulmeting valt hier niet onder (die stand is NaN), dus anders dan in het kwartierpad "
            "is dit niet de OR met teller_nulmeting__bool."
        ),
        "teller_wissel__bool": (
            "True als minstens één brontteller daalt naar de volgende minuut en die volgende stand geen nulmeting "
            "is; het vermogen van dat interval is NaN, de stand niet."
        ),
        "teruglevering__bool": "True als een van de twee exporttellers stijgt naar de volgende minuut.",
        "onplausibel__bool": (
            "True als minstens één momentane kolom met een grens (minuut.GRENZEN) buiten die grens lag; die waarde "
            "is NaN. Een exacte 0,0 op u_L1__V, u_L2__V of u_L3__V gaat wel op NaN maar zet de vlag niet."
        ),
        "gat_na__bool": "True als delta_t__s groter is dan 60 s: na deze minuut ontbreekt er minstens één.",
        "uitval_na__bool": "True als delta_t__s groter is dan 86.400 s: na deze minuut volgt een gat van meer dan 24 uur.",
    },
    "homes_minuut": {
        "home_id__str": _WONING,
        "n_minuten": "Aantal aanwezige minuten.",
        "eerste_minuut": "Eerste aanwezige minuut, tz-aware Europe/Amsterdam.",
        "laatste_minuut": "Laatste aanwezige minuut, tz-aware Europe/Amsterdam.",
        "bezetting__0": "n_minuten gedeeld door het aantal minuten van eerste_minuut tot en met laatste_minuut.",
        "grootste_gat__min": "Duur van het langste gat, in ontbrekende minuten.",
        "n_gaten": "Aantal gaten.",
        "n_uitval": "Aantal gaten van meer dan 1440 ontbrekende minuten.",
        "warmtepompkanaal_dood__bool": "True als p_warmtepomp_gemeten__W over de hele periode nooit boven 200 W komt.",
        "p_warmtepomp_max__W": "Hoogste p_warmtepomp_gemeten__W van de locatie.",
        "n_onplausibel": "Aantal minuten met onplausibel__bool.",
        "n_teller_terug": "Aantal minuten met teller_terug__bool.",
        "n_teller_nulmeting": "Aantal minuten met teller_nulmeting__bool.",
        "n_teller_wissel": "Aantal minuten met teller_wissel__bool.",
        "bereik_n": "Aantal proefminuten: in reeksen van minstens 10 minuten met de warmtepomp onder 200 W en de ketel boven 20 W.",
        "bereik_fractie": "Aandeel van de proefminuten waarin q_geleverd_gemeten__W boven 2 % van het locatiemaximum ligt.",
        "bereik_controle": "Zelfde aandeel in reeksen met warmtepomp onder 200 W en ketel hoogstens 20 W; hoort bijna 0 te zijn.",
        "bereik_referentie": "Zelfde aandeel in minuten met de warmtepomp op of boven 200 W; hoort hoog te zijn.",
        "warmtemeter_bereik__cat": "'systeem' als bereik_fractie > 0,15, 'warmtepomp' als < 0,01, anders of zonder proefminuten 'onbeslist'.",
    },
    "gaten": {
        "home_id__str": _WONING,
        "begin": "Eerste ontbrekende minuut, tz-aware Europe/Amsterdam.",
        "eind": "Eerste aanwezige minuut na het gat, tz-aware Europe/Amsterdam.",
        "duur__min": "Aantal ontbrekende minuten.",
        "soort": "'uitval' als duur__min groter is dan 1440, anders 'hapering'.",
    },
    "dekking": {
        "home_id__str": _WONING,
        "kolom__str": (
            "Kolom van metingen waarvoor de dekking geldt, of 'cop_combo__p_warmtepomp_en_q_geleverd' voor de "
            "COP-combinatie zonder de locaties met een dood warmtepompkanaal."
        ),
        "drempel__min": "Overbruggingsgrens k: gaten van hoogstens k minuten tellen als gedekt. 0 is de referentie zonder overbrugging.",
        "totale_tijd__min": "Minuten van eerste_minuut tot en met laatste_minuut.",
        "gedekte_tijd__min": "totale_tijd__min min de duur van alle gaten langer dan drempel__min.",
        "aandeel_gedekt": "gedekte_tijd__min gedeeld door totale_tijd__min.",
    },
}

_MINUUT_BRON_VAN: dict[str, str] = {naam: bron for bron, (naam, _) in minuut.MOMENTAAN.items()}
_MINUUT_TELLER_BRON_VAN: dict[str, str] = {naam: bron for bron, (naam, _) in minuut.TELLERS.items()}


def _beschrijving(resourcenaam: str, veldnaam: str) -> str | None:
    """De beschrijving van één veld: uit :data:`VELD_BESCHRIJVINGEN`, of opgebouwd uit de naam voor de
    kolommen die de code per grootheid maakt."""
    vast = VELD_BESCHRIJVINGEN.get(resourcenaam, {}).get(veldnaam)
    if vast:
        return vast
    if resourcenaam == "metingen":
        if veldnaam in _MINUUT_BRON_VAN:
            grens = minuut.GRENZEN.get(veldnaam)
            grenstekst = f" Buiten [{grens[0]:g}, {grens[1]:g}] NaN en onplausibel__bool." if grens else ""
            return (
                f"Gemiddelde over de metingen in deze minuut, een intervalgemiddelde en geen steekproef "
                f"(bron: {_MINUUT_BRON_VAN[veldnaam]}).{grenstekst}"
            )
        if veldnaam in _MINUUT_TELLER_BRON_VAN:
            return (
                f"Tellerstand aan het begin van de minuut (bron: {_MINUUT_TELLER_BRON_VAN[veldnaam]}_eerste). "
                "NaN bij een nulmeting."
            )
        if m := re.fullmatch(r"n_g([123])", veldnaam):
            return f"Aantal ruwe metingen van meetgroep {m.group(1)} achter de gemiddelden van deze minuut."
        if m := re.fullmatch(r"offset_(eerste|laatste)_g([123])__ms", veldnaam):
            return f"Milliseconden na de minuutgrens van de {m.group(1)} meting van meetgroep {m.group(2)}."
    if resourcenaam == "homes_minuut":
        if m := re.fullmatch(r"dekking_(.+)", veldnaam):
            return f"Aandeel van de aanwezige minuten waarin {m.group(1)} gevuld is."
        if m := re.fullmatch(r"raster_breuk_(.+)__bool", veldnaam):
            return (
                f"True als de stand van {m.group(1)} binnen de periode een macht van twee passeert boven de stand "
                "waar het float32-raster de metertik haalt: het raster verdubbelt dan middenin de reeks."
            )
        if m := re.fullmatch(r"raster_(.+)__W", veldnaam):
            return (
                f"Stap in het minuutvermogen die het float32-raster bij de hoogste stand van {m.group(1)} oplegt "
                "(raster x omrekening naar J / 60 s); NaN voor een teller die geen energie meet."
            )
    return None


# --- resources --------------------------------------------------------------------------------------

_RESOURCE_TITELS: dict[str, str] = {
    "homes": "Woningkenmerken, één rij per woning",
    "measurements": "Cumulatieve meterstanden per kwartier",
    "derived": "Gemiddeld vermogen per kwartier, momentane steekproeven en gekoppeld weer",
    "weer": "KNMI-uurwaarden per station",
    "quality": "Kwaliteitsvlaggen op het volledige kwartierrooster",
    "scheefheid": "Afwijking van het meetmoment tot de kwartiergrens, per woning en bron (geen contracttabel)",
    "metingen": "Minuutdata per locatie: momentane gemiddelden, tellerstanden, afgeleide vermogens en vlaggen",
    "homes_minuut": "Kenmerken per locatie uit de minuutpas",
    "gaten": "Gaten in het minuutrooster, per locatie",
    "dekking": "Aaneengesloten bruikbare tijd per locatie, kolom en overbruggingsgrens",
}

_PRIMARY_KEYS: dict[str, list[str]] = {
    "homes": ["home_id__str"],
    "measurements": ["home_id__str", "tijdstip_start"],
    "derived": ["home_id__str", "tijdstip_start"],
    "weer": ["weerstation_nr", "tijdstip_start"],
    "quality": ["home_id__str", "tijdstip_start"],
    "scheefheid": ["home_id__str", "bron"],
    "metingen": ["home_id__str", "tijdstip_start"],
    "homes_minuut": ["home_id__str"],
    "gaten": ["home_id__str", "begin"],
    "dekking": ["home_id__str", "kolom__str", "drempel__min"],
}

_PRIMARY_KEY_ONDERBOUWING: dict[str, str] = {
    "homes": "Eén rij per woning uit household.csv (tabellen.build_homes).",
    "measurements": "Elke bron is per (woning, kwartier) ontdubbeld vóór de outer-merge (tabellen.resolveer_domein).",
    "derived": "Rijen van measurements met left-joins op unieke sleutels (tabellen.build_derived).",
    "weer": "Gegroepeerd op (station, uur) en over chunks ontdubbeld (tabellen.build_weer, chunking.voeg_weer_samen).",
    "quality": "Een regelmatig rooster per woning met left-joins op unieke sleutels (quality.bouw_tijdas).",
    "scheefheid": "Eén rij per woning en bron (tabellen.bouw_scheefheid_samenvatting).",
    "metingen": "De extractie levert één rij per (locatie, minuut) (ontwerp-extractie.md §6).",
    "homes_minuut": "Een hervatte run vervangt de rij van een locatie in plaats van er een naast te zetten (minuut._schrijf_verzamelingen).",
    "gaten": "Gaten binnen een locatie overlappen niet, dus hun begin is uniek.",
    "dekking": (
        "Elke drempel één keer (minuut_dekking.STANDAARD_DREMPELS__min). De dekking.parquet van de minuutrun "
        "van 24-09-2026 is ouder dan die regel en heeft drempel 0 per kolom twee keer."
    ),
}

KWARTIER_UITVOERPAD = "de uitvoermap van pipeline.run (standaard data/processed)"
MINUUT_UITVOERPAD = "de uitvoermap van minuut.run (--doel)"


def _veld(schema_veld: pa.Field, resourcenaam: str) -> dict:
    type_naam, extra = table_schema_type(schema_veld.type)
    veld = {"name": schema_veld.name, "type": type_naam}
    veld["description"] = _beschrijving(resourcenaam, schema_veld.name) or (
        "Zie docs/datacatalogus.md voor de volledige beschrijving van dit veld."
    )
    veld.update(extra)
    return veld


def _resource(naam: str, schema: pa.Schema, pad: str, titel: str, uitvoerpad: str | None) -> dict:
    resource = {
        "name": naam,
        "title": titel,
        "format": "parquet",
        "path": pad,
        "schema": {
            "fields": [_veld(f, naam) for f in schema],
            "missingValues": [""],
            "primaryKey": _PRIMARY_KEYS[naam],
        },
        "primaryKeyOnderbouwing": _PRIMARY_KEY_ONDERBOUWING[naam],
    }
    if uitvoerpad is not None:
        resource["uitvoerpad"] = uitvoerpad
    return resource


def _kwartier_resources(met_uitvoerpad: bool) -> list[dict]:
    uitvoerpad = KWARTIER_UITVOERPAD if met_uitvoerpad else None
    return [
        _resource(naam, schema, f"{naam}.parquet", _RESOURCE_TITELS[naam], uitvoerpad)
        for naam, schema in uitvoerschema.KWARTIER_SCHEMAS.items()
    ]


def _minuut_resources(met_uitvoerpad: bool, n_metingenbestanden: int | None) -> list[dict]:
    uitvoerpad = MINUUT_UITVOERPAD if met_uitvoerpad else None
    resources = []
    for naam, schema in uitvoerschema.MINUUT_SCHEMAS.items():
        titel = _RESOURCE_TITELS[naam]
        if naam == "metingen":
            pad = "metingen/location_id=*.parquet"  # patroon, geen lijst: zie de moduledocstring
            if n_metingenbestanden is not None:
                titel += f" ({n_metingenbestanden} bestanden in deze run)"
        else:
            pad = f"{naam}.parquet"
        resources.append(_resource(naam, schema, pad, titel, uitvoerpad))
    return resources


def _versie(onderdeel: str) -> str:
    if onderdeel == "kwartier":
        return UITVOER_CONTRACT_VERSIE
    if onderdeel == "minuut":
        return MINUUT_CONTRACT_VERSIE
    return f"kwartier-{UITVOER_CONTRACT_VERSIE}+minuut-{MINUUT_CONTRACT_VERSIE}"


def bouw_datapackage(onderdeel: str = "beide", n_metingenbestanden: int | None = None) -> dict:
    """Bouw het datapackage-object (een gewone ``dict``, direct naar JSON te schrijven).

    ``onderdeel``: ``"kwartier"`` of ``"minuut"`` voor de kopie die een run in zijn eigen uitvoermap
    schrijft, ``"beide"`` voor de overzichtskopie in de repo-root. ``n_metingenbestanden`` komt alleen
    in de titel van ``metingen`` (zie de moduledocstring).
    """
    if onderdeel not in ONDERDELEN:
        raise ValueError(f"onderdeel moet een van {ONDERDELEN} zijn, niet {onderdeel!r}")
    beide = onderdeel == "beide"
    resources: list[dict] = []
    if onderdeel in ("kwartier", "beide"):
        resources += _kwartier_resources(met_uitvoerpad=beide)
    if onderdeel in ("minuut", "beide"):
        resources += _minuut_resources(met_uitvoerpad=beide, n_metingenbestanden=n_metingenbestanden)

    naam = {"kwartier": "demoprojecthybride-kwartier", "minuut": "demoprojecthybride-minuut"}.get(
        onderdeel, "demoprojecthybride-processed"
    )
    titel = {
        "kwartier": "Demoproject Hybride: voorbewerkte kwartierdata (getypeerde Parquet-tabellen)",
        "minuut": "Demoproject Hybride: voorbewerkte minuutdata (getypeerde Parquet-tabellen)",
    }.get(onderdeel, "Demoproject Hybride: voorbewerkte kwartier- en minuutdata (getypeerde Parquet-tabellen)")
    omschrijving = (
        "Voorbewerkte meetdata van het Demonstratieproject Hybride Warmtepompen: 174 woningen met een "
        "hybride warmtepomp, gemeten van begin 2022 tot 1 juni 2024. Deze repo is niet de data-eigenaar; zie "
        "GEBRUIKSVOORWAARDEN.md voor licentie, meldplicht en herkomst, en docs/datacatalogus.md voor de "
        "volledige beschrijving van elke tabel. Tijdkolommen zijn tz-aware Europe/Amsterdam. Gegenereerd door "
        "dph_preprocessing.datapackage, niet met de hand bijgehouden."
    )
    if beide:
        omschrijving += (
            " Deze kopie beschrijft beide paden samen; elk resource noemt in 'uitvoerpad' de map waar zijn "
            "'path' relatief aan is. Elke run schrijft zijn eigen helft in zijn eigen uitvoermap."
        )

    bronnen: list[dict] = [
        {
            "title": "Demo Project Hybride, KITE-projectpagina (Kennis- en Dataplatform Individuele Technieken)",
            "path": KITE_PAGINA_URL,
        }
    ]
    if onderdeel in ("kwartier", "beide"):
        bronnen.append(
            {
                "title": "demoprojecthybride-dataset.zip (zeven CSV's op kwartierbasis, met metadata.csv)",
                "path": BRON_DOWNLOAD_URL,
                "sha256": BRON_SHA256,
                "bytes": BRON_OMVANG__B,
            }
        )
    if onderdeel in ("minuut", "beide"):
        bronnen.append(
            {
                "title": (
                    "Per-minuut-extractie uit de ruwe meettabel achter het KITE-Grafanadashboard (174 "
                    "Parquet-bestanden, één per locatie); geen openbare URL, toegang aan te vragen via "
                    "kite@rvo.nl, zie GEBRUIKSVOORWAARDEN.md en ontwerp-extractie.md"
                ),
            }
        )

    return {
        "name": naam,
        "title": titel,
        "description": omschrijving,
        "version": _versie(onderdeel),
        "licenses": [
            {
                "name": "andere",
                "title": (
                    "Geen open licentie voor de data. De dataset mag alleen voor open verwerking gebruikt "
                    "worden; toepassing, inzichten en rekenmethoden moeten onder eenzelfde licentie openbaar "
                    "gedeeld en gemeld worden (via data@demoprojecthybride.nl of het KITE-portaal van de RVO). "
                    "Herverspreiding van de ruwe dataset is niet toegestaan. Zie GEBRUIKSVOORWAARDEN.md in "
                    "deze repo."
                ),
                "path": "GEBRUIKSVOORWAARDEN.md",
            }
        ],
        "sources": bronnen,
        "contributors": [
            {"title": "Smart Energy Foundation (eigenaar en uitvoerder van het project)", "role": "author"},
            {"title": "Inversable BV (dataverwerking en data-analyse voor het project)", "role": "contributor"},
            {"title": "Kenniscentrum Duurzaam Leven", "role": "processor"},
        ],
        "resources": resources,
    }


def schrijf_datapackage(
    pad: Path, onderdeel: str = "beide", n_metingenbestanden: int | None = None
) -> Path:
    """Schrijf ``datapackage.json`` atomisch naar ``pad`` (``<pad>.tmp`` + hernoeming)."""
    pakket = bouw_datapackage(onderdeel, n_metingenbestanden)
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.write_text(json.dumps(pakket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pad)
    return pad


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--onderdeel", choices=ONDERDELEN, default="beide",
        help="Welk pad: kwartier, minuut, of beide samen (standaard, voor de kopie in de repo-root).",
    )
    p.add_argument(
        "--pad", type=Path, default=Path(__file__).resolve().parents[2] / DATAPACKAGE_BESTANDSNAAM,
        help="Waar datapackage.json geschreven wordt (standaard: de repo-root).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    schrijf_datapackage(args.pad, args.onderdeel)
    print(f"Geschreven: {args.pad}")


if __name__ == "__main__":
    main()
