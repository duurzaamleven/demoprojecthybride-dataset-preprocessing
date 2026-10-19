# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.tabellen: de vijf tabellen + eenheidsomrekeningen.

Elke fixture bootst één van de drie geverifieerde bevindingen uit ontwerp-preprocessing.md §2 na
(scheve tijdstempels, een teruglopende teller, een ontbrekend kwartier), plus de vier COP-bronnen
compleet/incompleet, en toetst dat de pijplijn ze correct afhandelt.
"""

from __future__ import annotations

import pandas as pd
import pytest

from dph_preprocessing import gaskwaliteit, tabellen
from dph_preprocessing.tellers import INITIALISATIETELEGRAM_SENTINEL

DSMR_DEFAULTS = dict(
    e_consumed_low=0.0, e_consumed_high=0.0, e_delivered_low=0.0, e_delivered_high=0.0,
    v_gas_consumed=0.0, u_L1=230.0, u_L2=230.0, u_L3=230.0, i_L1=0.0, i_L2=0.0, i_L3=0.0,
    p_consumed_L1=0.0, p_consumed_L2=0.0, p_consumed_L3=0.0,
    p_delivered_L1=0.0, p_delivered_L2=0.0, p_delivered_L3=0.0,
)
KAMSTRUP_DEFAULTS = dict(t_supply=40.0, t_return=35.0, e_thermal_system=0.0, p_thermal_system=0.0, f_system=0.0)
HEATPUMP_DEFAULTS = dict(heatpump_power=0.0, heatpump_voltage=230.0, heatpump_current=0.0, heatpump_energy=0.0)
BOILER_DEFAULTS = dict(boiler_power=0.0, boiler_voltage=230.0, boiler_current=0.0, boiler_energy=0.0)
ROOM_DEFAULTS = dict(temperature=20.0, humidity=50.0)


def _rij(home_id, timestamp, defaults, **overrides):
    rij = {"home_id__str": home_id, "timestamp": timestamp, **defaults, **overrides}
    return rij


def _frame(rijen):
    return pd.DataFrame(rijen)


@pytest.fixture
def resolved_tellerbronnen():
    """Vijf woningen, elk één van de gevraagde scenario's:

    - ``A``: een teruglopende teller (e_consumed_low daalt van 10 naar 8 kWh) -> teller_terug__bool.
    - ``B``: het kwartier 11:15 ontbreekt bij ALLE vier bronnen -> ontbrekend__bool.
    - ``C``: een scheve tijdstempel (10 min na de kwartiergrens) -> scheef__bool.
    - ``D``: alleen dsmr heeft data; kamstrup/heatpump/boiler ontbreken -> bron_incompleet__bool.
    - ``E``: de SAMENGESTELDE teller e_net (=import-export) daalt (teruglevering van zonnestroom:
      export stijgt, import blijft gelijk) -> teruglevering__bool True, teller_terug__bool False
      (ontwerp §8, B3: e_net zelf triggert dit niet).
    """
    dsmr = _frame(
        [
            _rij("A", "2022-02-07T11:00:00", DSMR_DEFAULTS, e_consumed_low=10.0),
            _rij("A", "2022-02-07T11:15:00", DSMR_DEFAULTS, e_consumed_low=8.0),
            _rij("B", "2022-02-07T11:00:00", DSMR_DEFAULTS, e_consumed_low=5.0),
            _rij("B", "2022-02-07T11:30:00", DSMR_DEFAULTS, e_consumed_low=6.0),
            _rij("C", "2022-03-01T09:10:00", DSMR_DEFAULTS, e_consumed_low=1.0),
            _rij("D", "2022-02-07T11:00:00", DSMR_DEFAULTS, e_consumed_low=1.0),
            _rij("E", "2022-02-07T11:00:00", DSMR_DEFAULTS, e_consumed_low=10.0, e_delivered_low=0.0),
            _rij("E", "2022-02-07T11:15:00", DSMR_DEFAULTS, e_consumed_low=10.0, e_delivered_low=5.0),
        ]
    )
    kamstrup = _frame(
        [
            _rij("A", "2022-02-07T11:00:00", KAMSTRUP_DEFAULTS),
            _rij("A", "2022-02-07T11:15:00", KAMSTRUP_DEFAULTS),
            _rij("B", "2022-02-07T11:00:00", KAMSTRUP_DEFAULTS),
            _rij("B", "2022-02-07T11:30:00", KAMSTRUP_DEFAULTS),
            _rij("C", "2022-03-01T09:10:00", KAMSTRUP_DEFAULTS, e_thermal_system=10.0),
            _rij("E", "2022-02-07T11:00:00", KAMSTRUP_DEFAULTS),
            _rij("E", "2022-02-07T11:15:00", KAMSTRUP_DEFAULTS),
        ]
    )
    heatpump = _frame(
        [
            _rij("A", "2022-02-07T11:00:00", HEATPUMP_DEFAULTS),
            _rij("A", "2022-02-07T11:15:00", HEATPUMP_DEFAULTS),
            _rij("B", "2022-02-07T11:00:00", HEATPUMP_DEFAULTS),
            _rij("B", "2022-02-07T11:30:00", HEATPUMP_DEFAULTS),
            _rij("C", "2022-03-01T09:10:00", HEATPUMP_DEFAULTS),
            _rij("E", "2022-02-07T11:00:00", HEATPUMP_DEFAULTS),
            _rij("E", "2022-02-07T11:15:00", HEATPUMP_DEFAULTS),
        ]
    )
    boiler = _frame(
        [
            _rij("A", "2022-02-07T11:00:00", BOILER_DEFAULTS),
            _rij("A", "2022-02-07T11:15:00", BOILER_DEFAULTS),
            _rij("B", "2022-02-07T11:00:00", BOILER_DEFAULTS),
            _rij("B", "2022-02-07T11:30:00", BOILER_DEFAULTS),
            _rij("C", "2022-03-01T09:10:00", BOILER_DEFAULTS),
            _rij("E", "2022-02-07T11:00:00", BOILER_DEFAULTS),
            _rij("E", "2022-02-07T11:15:00", BOILER_DEFAULTS),
        ]
    )
    return {
        "dsmr": tabellen.resolveer_domein(dsmr),
        "kamstrup": tabellen.resolveer_domein(kamstrup),
        "heatpump": tabellen.resolveer_domein(heatpump),
        "boiler": tabellen.resolveer_domein(boiler),
    }


def test_ontbrekend_kwartier_wordt_gevlagd(resolved_tellerbronnen):
    _, quality, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    b = quality[quality["home_id__str"] == "B"].sort_values("tijdstip_start")
    assert len(b) == 3  # 11:00, 11:15 (ontbrekend), 11:30
    assert b["ontbrekend__bool"].tolist() == [False, True, False]
    # Een ontbrekend kwartier is "niets om over te oordelen", niet automatisch False.
    ontbrekende_rij = b[b["ontbrekend__bool"]].iloc[0]
    assert pd.isna(ontbrekende_rij["bron_incompleet__bool"])


def test_teller_terug_wordt_gevlagd(resolved_tellerbronnen):
    measurements, quality, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    a = quality[quality["home_id__str"] == "A"].sort_values("tijdstip_start")
    # Voorwaartse differentiatie (ontwerp-intervalsemantiek.md §2): de rij op 11:00 beschrijft het
    # interval naar 11:15, waar de teller terugliep (10.0 -> 8.0 kWh) -> True. teller_terug__bool is
    # volgens ontwerp-teller-artefacten.md §7 de OR van teller_nulmeting__bool/teller_wissel__bool,
    # en die twee zijn (net als in het minuutpad) altijd concreet True/False, nooit NA:
    # ze oordelen over de STAND zelf (is hij 0 na eerder >1; daalt hij naar iets anders), niet over
    # de aanwezigheid van een volgende aflezing. Bij de laatste rij van een woning (11:15, geen
    # volgende teller) is er dus gewoon niets aan de hand: False, geen NA.
    vlaggen = a["teller_terug__bool"].tolist()
    assert vlaggen[0] is True
    assert vlaggen[1] is False
    # measurements zelf blijft de ruwe, dalende meterstand tonen -- geen stille correctie (§3).
    a_meas = measurements[measurements["home_id__str"] == "A"].sort_values("tijdstip_start")
    assert a_meas["e_import_laag_cum__kWh"].tolist() == [10.0, 8.0]


def test_teller_terug_flag_negeert_teruglevering_via_e_net(resolved_tellerbronnen):
    # ontwerp §8, B3: woning E's e_net (=import-export) daalt (10 -> 5), maar dat komt uitsluitend
    # doordat de EXPORTteller stijgt (teruglevering van zonnestroom); geen enkele echte bronteller
    # daalt. teller_terug__bool mag hier dus niet True zijn, en teruglevering__bool wel.
    _, quality, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    e = quality[quality["home_id__str"] == "E"].sort_values("tijdstip_start")
    assert bool(e["teller_terug__bool"].iloc[0]) is False
    assert bool(e["teruglevering__bool"].iloc[0]) is True
    # Laatste rij van de woning: teller_terug__bool is niet op delta-aanwezigheid gebaseerd
    # (zie test_teller_terug_wordt_gevlagd) en is hier gewoon False. teruglevering__bool gebruikt
    # wel teller_gestegen_masker, dus die is NA: geen volgende teller om de
    # exportstijging aan af te lezen.
    assert bool(e["teller_terug__bool"].iloc[1]) is False
    assert pd.isna(e["teruglevering__bool"].iloc[1])


def test_scheve_tijdstempel_wordt_gevlagd(resolved_tellerbronnen):
    _, quality, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    c = quality[quality["home_id__str"] == "C"]
    assert len(c) == 1
    assert bool(c["scheef__bool"].iloc[0]) is True


def test_bouw_scheefheid_samenvatting_mediaan_en_max():
    # ontwerp-preprocessing.md §8.1 A5: per woning en per bron mediaan/p95/max/n van scheefheid__s,
    # uit een AL resolveer_domein'de DataFrame -- dezelfde vorm die de preprocessing (pipeline.py)
    # per chunk wegschrijft naar data/processed/scheefheid.parquet.
    resolved_per_bron = {
        "dsmr": pd.DataFrame({"home_id__str": ["A", "A", "A"], "scheefheid__s": [0.0, 10.0, 20.0]}),
    }
    resultaat = tabellen.bouw_scheefheid_samenvatting(resolved_per_bron)
    assert list(resultaat.columns) == list(tabellen.SCHEEFHEID_KOLOMMEN)
    rij = resultaat.iloc[0]
    assert rij["bron"] == "dsmr"
    assert rij["mediaan__s"] == 10.0
    assert rij["max__s"] == 20.0
    assert rij["n"] == 3


def test_bouw_scheefheid_samenvatting_negeert_ontbrekende_waarden_en_lege_bronnen():
    # Woning A: één NaN valt weg (dus n=1 i.p.v. 2). Woning B heeft alleen NaN's -> helemaal geen
    # rij (net als de oude analyses._scheefheid_per_bron_uit_resolved).
    resolved_per_bron = {
        "kamstrup": pd.DataFrame(
            {"home_id__str": ["A", "A", "B"], "scheefheid__s": [5.0, float("nan"), float("nan")]}
        ),
    }
    resultaat = tabellen.bouw_scheefheid_samenvatting(resolved_per_bron)
    assert resultaat["home_id__str"].tolist() == ["A"]
    assert resultaat.iloc[0]["n"] == 1


def test_bron_incompleet_wordt_gevlagd(resolved_tellerbronnen):
    _, quality, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    d = quality[quality["home_id__str"] == "D"]
    assert len(d) == 1
    assert bool(d["bron_incompleet__bool"].iloc[0]) is True


def test_q_geleverd_j_is_gj_maal_1e9(resolved_tellerbronnen):
    # variable-dictionary.md: e_thermal_system (GJ) -> q_geleverd_cum__J, omrekening x10^9.
    measurements, _, _ = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    c = measurements[measurements["home_id__str"] == "C"].iloc[0]
    assert c["q_geleverd_cum__J"] == pytest.approx(10.0 * 1e9, rel=1e-5)


# --- drie teller-artefacten (ontwerp-teller-artefacten.md §4/§12) ------------------------------


def test_initialisatietelegram_wordt_gemaskeerd_en_verstoort_latere_nulmetingen_niet(resolved_tellerbronnen):
    # Woning F: rij 1 is de sentinel-handtekening (alle vijf registers op hun sentinelwaarde,
    # inclusief e_delivered_low=3433,300), rij 2/3 zijn een woning zonder teruglevering (export
    # blijft legitiem op 0,0). Dit toetst zowel §4.1 (de sentinelrij wordt NaN) als §5 (de sentinel
    # mag niet meetellen in het cummax-criterium van rij 2/3 -- anders worden die twee nullen ten
    # onrechte als uitval-met-herstel gevlagd, zie de 542.507-vs-361-vondst). Net als woning D in
    # de fixture heeft F alleen dsmr-data; de andere drie bronnen blijven ongewijzigd.
    sentinel = INITIALISATIETELEGRAM_SENTINEL
    nieuw = _frame(
        [
            _rij(
                "F", "2022-02-07T11:00:00", DSMR_DEFAULTS,
                e_consumed_low=sentinel["e_import_laag_cum__kWh"],
                e_consumed_high=sentinel["e_import_hoog_cum__kWh"],
                e_delivered_low=sentinel["e_export_laag_cum__kWh"],
                e_delivered_high=sentinel["e_export_hoog_cum__kWh"],
                v_gas_consumed=sentinel["g_gebruik_cum__m3"],
            ),
            _rij(
                "F", "2022-02-07T11:15:00", DSMR_DEFAULTS,
                e_consumed_low=50.0, e_consumed_high=40.0, e_delivered_low=0.0, e_delivered_high=0.0,
                v_gas_consumed=20.0,
            ),
            _rij(
                "F", "2022-02-07T11:30:00", DSMR_DEFAULTS,
                e_consumed_low=51.0, e_consumed_high=41.0, e_delivered_low=0.0, e_delivered_high=0.0,
                v_gas_consumed=21.0,
            ),
        ]
    )
    dsmr = pd.concat([resolved_tellerbronnen["dsmr"], tabellen.resolveer_domein(nieuw)], ignore_index=True)
    measurements, quality, _ = tabellen.build_measurements_en_quality(
        dsmr, resolved_tellerbronnen["kamstrup"], resolved_tellerbronnen["heatpump"],
        resolved_tellerbronnen["boiler"],
    )
    m = measurements[measurements["home_id__str"] == "F"].sort_values("tijdstip_start")
    q = quality[quality["home_id__str"] == "F"].sort_values("tijdstip_start")

    # §4.1: de sentinelrij zelf is NaN op alle vijf registers.
    assert q["teller_initialisatie__bool"].tolist() == [True, False, False]
    assert m["e_import_laag_cum__kWh"].isna().tolist() == [True, False, False]
    assert m["e_export_laag_cum__kWh"].isna().tolist() == [True, False, False]
    assert m["e_export_laag_cum__kWh"].dropna().tolist() == [0.0, 0.0]

    # §5: de twee legitieme 0,0-exportaflezingen NA de sentinel zijn GEEN nulmeting -- de sentinel
    # (3433,300, ruim boven TELLER_ONTWAAKT_BOVEN) mag niet meetellen in het lopende maximum.
    assert q["teller_nulmeting__bool"].tolist() == [False, False, False]
    assert q["teller_terug__bool"].tolist() == [False, False, False]


def test_uitval_met_herstel_maskeert_beide_helften_zonder_piek(resolved_tellerbronnen):
    # Woning G, e_consumed_low: 100, 110, 0, 0, 250 -- een meteruitval die na twee kwartier herstelt
    # op ongeveer het oude spoor. Reviewpunt A1: dit mag GEEN piek opleveren (140 kWh in één
    # kwartier), alleen NaN op de betrokken intervallen.
    nieuw = _frame(
        [
            _rij("G", "2022-02-07T11:00:00", DSMR_DEFAULTS, e_consumed_low=100.0),
            _rij("G", "2022-02-07T11:15:00", DSMR_DEFAULTS, e_consumed_low=110.0),
            _rij("G", "2022-02-07T11:30:00", DSMR_DEFAULTS, e_consumed_low=0.0),
            _rij("G", "2022-02-07T11:45:00", DSMR_DEFAULTS, e_consumed_low=0.0),
            _rij("G", "2022-02-07T12:00:00", DSMR_DEFAULTS, e_consumed_low=250.0),
        ]
    )
    dsmr = pd.concat([resolved_tellerbronnen["dsmr"], tabellen.resolveer_domein(nieuw)], ignore_index=True)
    measurements, quality, _ = tabellen.build_measurements_en_quality(
        dsmr, resolved_tellerbronnen["kamstrup"], resolved_tellerbronnen["heatpump"],
        resolved_tellerbronnen["boiler"],
    )
    m = measurements[measurements["home_id__str"] == "G"].sort_values("tijdstip_start")
    q = quality[quality["home_id__str"] == "G"].sort_values("tijdstip_start")

    assert q["teller_nulmeting__bool"].tolist() == [False, False, True, True, False]
    assert not q["teller_wissel__bool"].any()
    assert q["teller_terug__bool"].tolist() == [False, False, True, True, False]
    # measurements: de twee nulmeting-rijen zijn NaN (net als de sentinelrij), de rest blijft staan.
    assert m["e_import_laag_cum__kWh"].isna().tolist() == [False, False, True, True, False]
    assert m["e_import_laag_cum__kWh"].dropna().tolist() == [100.0, 110.0, 250.0]


def test_cummax_criterium_op_g_gebruik_cum_m3_langdurige_uitval(resolved_tellerbronnen):
    # §12 stap 7 met naam genoemd: het cummax-criterium specifiek op g_gebruik_cum__m3, de teller
    # met verreweg de langste aaneengesloten uitvalperiode in de echte dataset (§6: 32.203 rijen bij
    # één woning, een gasmeterstoring van maanden). Hier op kleine schaal: normaal, normaal, VIER
    # aaneengesloten nulkwartieren, herstel, normaal -- met een normale meting vóór en NA de uitval
    # zodat zichtbaar wordt dat ALLEEN de intervallen die de uitval raken NaN worden, de rest niet.
    nieuw = _frame(
        [
            _rij("I", "2022-02-07T10:45:00", DSMR_DEFAULTS, v_gas_consumed=480.0),
            _rij("I", "2022-02-07T11:00:00", DSMR_DEFAULTS, v_gas_consumed=500.0),
            _rij("I", "2022-02-07T11:15:00", DSMR_DEFAULTS, v_gas_consumed=0.0),
            _rij("I", "2022-02-07T11:30:00", DSMR_DEFAULTS, v_gas_consumed=0.0),
            _rij("I", "2022-02-07T11:45:00", DSMR_DEFAULTS, v_gas_consumed=0.0),
            _rij("I", "2022-02-07T12:00:00", DSMR_DEFAULTS, v_gas_consumed=0.0),
            _rij("I", "2022-02-07T12:15:00", DSMR_DEFAULTS, v_gas_consumed=520.0),
            _rij("I", "2022-02-07T12:30:00", DSMR_DEFAULTS, v_gas_consumed=540.0),
        ]
    )
    dsmr = pd.concat([resolved_tellerbronnen["dsmr"], tabellen.resolveer_domein(nieuw)], ignore_index=True)
    measurements, quality, vermogens = tabellen.build_measurements_en_quality(
        dsmr, resolved_tellerbronnen["kamstrup"], resolved_tellerbronnen["heatpump"],
        resolved_tellerbronnen["boiler"],
    )
    m = measurements[measurements["home_id__str"] == "I"].sort_values("tijdstip_start")
    q = quality[quality["home_id__str"] == "I"].sort_values("tijdstip_start")
    v = vermogens[vermogens["home_id__str"] == "I"].sort_values("tijdstip_start")

    # ALLE vier de nulperiode-rijen zijn nulmeting, niet alleen de overgangsrij (§4.2: "dit
    # criterium markeert elke rij die aan de voorwaarde voldoet").
    assert q["teller_nulmeting__bool"].tolist() == [False, False, True, True, True, True, False, False]
    assert not q["teller_wissel__bool"].any()  # herstel, geen echte breuk
    assert m["g_gebruik_cum__m3"].isna().tolist() == [False, False, True, True, True, True, False, False]
    assert m["g_gebruik_cum__m3"].dropna().tolist() == [480.0, 500.0, 520.0, 540.0]
    # Geen piek: alleen de intervallen die de uitval raken zijn NaN (10:45->11:00 en de rest van de
    # uitval eromheen); het interval VOOR de uitval (10:45->11:00) en NA het herstel (12:15->12:30)
    # blijven een normaal, klein vermogen -- geen sprong van 20 m3 in één kwartier.
    assert v["g_gebruik__W"].iloc[0] > 0  # 10:45 -> 11:00: normaal, buiten de uitval
    assert v["g_gebruik__W"].iloc[1:6].isna().all()  # 11:00 t/m 12:00: raken allemaal de uitval
    assert v["g_gebruik__W"].iloc[6] > 0  # 12:15 -> 12:30: weer normaal, NA het herstel
    assert pd.isna(v["g_gebruik__W"].iloc[7])  # laatste rij van de woning: geen volgende teller


def test_echte_wissel_maskeert_alleen_het_ene_vermogeninterval(resolved_tellerbronnen):
    # Woning H, v_gas_consumed: 100, 110, 30, 40 -- een echte meterwissel (valt terug naar 30, niet
    # naar 0,0). Alleen het interval 110 -> 30 hoort in g_gebruik__W op NaN; de stand
    # (g_gebruik_cum__m3) blijft ongemoeid (§4.3: geen segmentreparatie).
    nieuw = _frame(
        [
            _rij("H", "2022-02-07T11:00:00", DSMR_DEFAULTS, v_gas_consumed=100.0),
            _rij("H", "2022-02-07T11:15:00", DSMR_DEFAULTS, v_gas_consumed=110.0),
            _rij("H", "2022-02-07T11:30:00", DSMR_DEFAULTS, v_gas_consumed=30.0),
            _rij("H", "2022-02-07T11:45:00", DSMR_DEFAULTS, v_gas_consumed=40.0),
        ]
    )
    dsmr = pd.concat([resolved_tellerbronnen["dsmr"], tabellen.resolveer_domein(nieuw)], ignore_index=True)
    measurements, quality, vermogens = tabellen.build_measurements_en_quality(
        dsmr, resolved_tellerbronnen["kamstrup"], resolved_tellerbronnen["heatpump"],
        resolved_tellerbronnen["boiler"],
    )
    m = measurements[measurements["home_id__str"] == "H"].sort_values("tijdstip_start")
    q = quality[quality["home_id__str"] == "H"].sort_values("tijdstip_start")
    v = vermogens[vermogens["home_id__str"] == "H"].sort_values("tijdstip_start")

    assert q["teller_wissel__bool"].tolist() == [False, True, False, False]
    assert not q["teller_nulmeting__bool"].any()
    assert q["teller_terug__bool"].tolist() == [False, True, False, False]
    assert m["g_gebruik_cum__m3"].tolist() == [100.0, 110.0, 30.0, 40.0]  # stand ongemoeid
    assert v["g_gebruik__W"].iloc[0] > 0  # eerste interval (100->110): normaal
    assert pd.isna(v["g_gebruik__W"].iloc[1])  # het gemaskeerde wissel-interval
    assert v["g_gebruik__W"].iloc[2] > 0  # derde interval (30->40): weer normaal


def test_build_homes_kolommen_en_dtypes():
    homes_ruw = pd.DataFrame(
        {
            "participant_id": ["A", "B"],
            "house_type": ["vrijstaand", "rijwoning"],
            "construction_year": ["[1980-1999]", "2000=>"],
            "surface": ["[200 - 249]", "[100 - 149]"],
            "energylabel": ["B", None],
            "number_of_inhabitants": ["2+", "1"],
            "ownership": ["particulier", "particulier"],
            "gas_before_2": [2400.0, 1271.0],
            "gas_before_1": [2200.0, 1304.0],
            "electricity_before_2": [3600.0, 2352.0],
            "electricity_before_1": [3500.0, 3000.0],
            "has_low_heat_floor_heating": [1, 0],
            "has_high_heat_radiator_heating": [1, 1],
            "has_gas_furnace": [0, 0],
            "has_double_paned_glass": [1, 1],
            "has_roofinsulation": [1, 1],
            "has_wallinsulation": [1, 1],
            "has_floorinsulation": [1, 1],
            "wrong_elec_measurement": [0, 1],
        }
    )
    homes = tabellen.build_homes(homes_ruw)
    assert list(homes["home_id__str"]) == ["A", "B"]
    assert "wrong_elec_measurement" not in homes.columns  # ruwe naam, hernoemd naar onze naam
    assert homes["heeft_vloerverwarming__bool"].tolist() == [True, False]
    assert str(homes["woningtype__cat"].dtype) == "category"
    assert homes["gas_voor_2__m3"].dtype == "float32"


def test_build_homes_elektrameting_verdacht_cat():
    # ontwerp §8 A2 / variable-dictionary.md: wrong_elec_measurement (0/1/2) -> onze
    # elektrameting_verdacht__cat, als __cat van STRINGS, en moet alle drie de waarden kunnen dragen.
    homes_ruw = pd.DataFrame(
        {
            "participant_id": ["A", "B", "C"],
            "house_type": ["vrijstaand", "vrijstaand", "vrijstaand"],
            "construction_year": ["2000=>", "2000=>", "2000=>"],
            "surface": ["[100 - 149]", "[100 - 149]", "[100 - 149]"],
            "energylabel": ["A", "A", "A"],
            "number_of_inhabitants": ["2+", "2+", "2+"],
            "ownership": ["particulier", "particulier", "particulier"],
            "gas_before_2": [1000.0, 1000.0, 1000.0],
            "gas_before_1": [1000.0, 1000.0, 1000.0],
            "electricity_before_2": [2000.0, 2000.0, 2000.0],
            "electricity_before_1": [2000.0, 2000.0, 2000.0],
            "has_low_heat_floor_heating": [0, 0, 0],
            "has_high_heat_radiator_heating": [1, 1, 1],
            "has_gas_furnace": [0, 0, 0],
            "has_double_paned_glass": [1, 1, 1],
            "has_roofinsulation": [1, 1, 1],
            "has_wallinsulation": [1, 1, 1],
            "has_floorinsulation": [1, 1, 1],
            # 0 = bruikbaar, 1 = onbruikbaar, 2 = tijdens het project gerepareerd.
            "wrong_elec_measurement": [0, 1, 2],
        }
    )
    homes = tabellen.build_homes(homes_ruw)
    assert "elektrameting_verdacht__cat" in homes.columns
    assert str(homes["elektrameting_verdacht__cat"].dtype) == "category"
    assert homes["elektrameting_verdacht__cat"].tolist() == ["0", "1", "2"]


def test_build_weer_eenheidsomrekeningen():
    # T (0.1 C) -> degC (/10), FH (0.1 m/s) -> m_s_1 (/10), Q (J/cm2/uur) -> W_m_2 (x2,7778).
    knmi = _frame(
        [
            {"home_id__str": "A", "timestamp": "2022-02-07T11:00:00", "station_code": 273, "T": 70, "FH": 60, "Q": 100},
            # Zelfde station+tijdstip via een andere woning: moet ontdubbeld worden tot 1 rij.
            {"home_id__str": "B", "timestamp": "2022-02-07T11:00:00", "station_code": 273, "T": 70, "FH": 60, "Q": 100},
        ]
    )
    weer = tabellen.build_weer(tabellen.resolveer_domein(knmi))
    assert len(weer) == 1
    rij = weer.iloc[0]
    assert rij["temp_buiten__degC"] == pytest.approx(7.0)
    assert rij["wind__m_s_1"] == pytest.approx(6.0)
    assert rij["ghi__W_m_2"] == pytest.approx(100 * (100 * 100) / (60 * 60), rel=1e-4)


def test_build_derived_eenheidsomrekeningen(resolved_tellerbronnen):
    measurements, _, vermogens = tabellen.build_measurements_en_quality(
        resolved_tellerbronnen["dsmr"], resolved_tellerbronnen["kamstrup"],
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
    )
    room = _frame(
        [_rij("A", "2022-02-07T11:00:00", ROOM_DEFAULTS, temperature=21.5, humidity=45.0)]
    )
    kamstrup_met_debiet = resolved_tellerbronnen["kamstrup"].copy()
    kamstrup_met_debiet.loc[
        (kamstrup_met_debiet["home_id__str"] == "A")
        & (kamstrup_met_debiet["tijdstip_start"] == pd.Timestamp("2022-02-07T11:00:00", tz="UTC")),
        ["p_thermal_system", "f_system"],
    ] = [2.0, 360.0]  # 2 kW, 360 L/h

    # De KNMI-uurreeks is EIND-gelabeld, en build_weer trekt er daarom een uur af. Om het uur
    # 11:00-12:00 te beschrijven moet de bronrij dus op 12:00 staan. Zie
    # ontwerp-intervalsemantiek.md §3.
    knmi = tabellen.resolveer_domein(
        _frame([{"home_id__str": "A", "timestamp": "2022-02-07T12:00:00", "station_code": 273, "T": 70, "FH": 60, "Q": 100}])
    )
    weer = tabellen.build_weer(knmi)
    home_station = tabellen.home_station_mapping(knmi)

    derived = tabellen.build_derived(
        vermogens, resolved_tellerbronnen["dsmr"], kamstrup_met_debiet,
        resolved_tellerbronnen["heatpump"], resolved_tellerbronnen["boiler"],
        tabellen.resolveer_domein(room), weer, home_station,
    )
    rij = derived[
        (derived["home_id__str"] == "A")
        & (derived["tijdstip_start"] == pd.Timestamp("2022-02-07T11:00:00", tz="UTC"))
    ].iloc[0]

    assert rij["q_geleverd_meting__W"] == pytest.approx(2000.0)  # kW -> W, x1000
    assert rij["debiet_meting__dm3_s_1"] == pytest.approx(0.1)  # 360 L/h / 3600 = 0.1 dm3/s
    assert rij["temp_binnen_meting__degC"] == pytest.approx(21.5)
    assert rij["rv_binnen_meting__0"] == pytest.approx(0.45)
    assert rij["temp_buiten__degC"] == pytest.approx(7.0)  # weerkoppeling via het eigen station


def test_build_weer_verschuift_het_knmi_uur_een_uur_terug():
    """De KNMI-uurreeks is eind-gelabeld: HH=1 is het uur 00:00-01:00.

    Zonder deze verschuiving krijgt elke meting het weer van het uur ervóór. Bewezen op 05-09-2026
    tegen een onafhankelijke KNMI-ophaal: onze reeks een uur eerder leggen gaf een mediane afwijking
    van 3,8e-07 K (float32-afrondgrens) op alle 23 vergelijkbare stations. Zie
    ontwerp-intervalsemantiek.md §3.
    """
    knmi_r = pd.DataFrame(
        {
            "home_id__str": ["a", "a"],
            "station_code": [260, 260],
            "tijdstip_start": pd.to_datetime(["2023-06-01 12:00", "2023-06-01 13:00"], utc=True),
            "tijdstip_meting": pd.to_datetime(["2023-06-01 12:00", "2023-06-01 13:00"], utc=True),
            "scheefheid__s": [0.0, 0.0],
            "T": [200, 210],
            "FH": [30, 40],
            "Q": [100, 200],
        }
    )
    weer = tabellen.build_weer(knmi_r)
    assert weer["tijdstip_start"].tolist() == list(
        pd.to_datetime(["2023-06-01 11:00", "2023-06-01 12:00"], utc=True)
    ), "de waarde met KNMI-label 12:00 beschrijft het uur 11:00-12:00"
    assert "ghi__W_m_2" in weer.columns and "ghi__kWh_m_2" not in weer.columns


def _gasbron(waarden__m3, tijden):
    """Eén woning met alleen een gasteller, om de calorische omrekening apart te kunnen toetsen."""
    return tabellen.resolveer_domein(
        _frame(
            [
                _rij("G", tijdstip, DSMR_DEFAULTS, v_gas_consumed=waarde)
                for tijdstip, waarde in zip(tijden, waarden__m3)
            ]
        )
    )


def _lege_teller_bron(tellerkolom):
    """Een lege, al geresolveerde bron met alleen de kolommen die build_measurements_en_quality van
    die bron leest. Nodig om de gasomrekening apart te toetsen: de andere drie bronnen mogen dan
    leeg zijn, maar hun teller moet als kolom bestaan."""
    return pd.DataFrame(
        {
            "home_id__str": pd.Series(dtype="object"),
            "tijdstip_start": pd.Series(dtype="datetime64[ns, UTC]"),
            "tijdstip_meting": pd.Series(dtype="datetime64[ns, UTC]"),
            "scheefheid__s": pd.Series(dtype="float64"),
            tellerkolom: pd.Series(dtype="float64"),
        }
    )


def _lege_overige_bronnen():
    return (
        _lege_teller_bron("e_thermal_system"),
        _lege_teller_bron("heatpump_energy"),
        _lege_teller_bron("boiler_energy"),
    )


def test_g_gebruik_gebruikt_de_werkelijke_calorische_waarde_per_uur():
    """1 m3 in 900 s bij 36 MJ/m3 is 40 kW; bij de vaste 35,17 MJ/m3 zou het 39,08 kW zijn. Dit
    toetst dus zowel dat de per-rij factor doorwerkt als dat het NIET de constante is."""
    dsmr = _gasbron([100.0, 101.0], ["2022-02-07T11:00:00", "2022-02-07T11:15:00"])
    gas_hhv = pd.DataFrame(
        {
            "tijdstip": pd.to_datetime(["2022-02-07T11:00:00"], utc=True),
            gaskwaliteit.KOLOM: [36.0e6],
            "n_gebieden": [170],
            "n_gebieden_uitgesloten": [7],
        }
    )

    _, _, vermogens = tabellen.build_measurements_en_quality(
        dsmr, *_lege_overige_bronnen(), gas_hhv=gas_hhv
    )

    assert vermogens["g_gebruik__W"].iloc[0] == pytest.approx(40_000.0)
    assert vermogens[gaskwaliteit.KOLOM].iloc[0] == pytest.approx(36.0e6)
    assert vermogens[gaskwaliteit.BRON_KOLOM].iloc[0] == gaskwaliteit.BRON_ACTUEEL


def test_g_gebruik_valt_zonder_ingest_terug_op_de_vaste_waarde_en_zegt_dat():
    dsmr = _gasbron([100.0, 101.0], ["2022-02-07T11:00:00", "2022-02-07T11:15:00"])

    _, _, vermogens = tabellen.build_measurements_en_quality(
        dsmr, *_lege_overige_bronnen(), gas_hhv=None
    )

    verwacht__W = gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / 900.0
    assert vermogens["g_gebruik__W"].iloc[0] == pytest.approx(verwacht__W, rel=1e-6)
    # De terugval moet in de uitvoer te zien zijn, anders is hij niet te tellen (lessen-uit-im3 §2).
    assert vermogens[gaskwaliteit.BRON_KOLOM].iloc[0] == gaskwaliteit.BRON_FALLBACK


def test_de_calorische_waarde_en_haar_herkomst_komen_in_derived_terecht(resolved_tellerbronnen):
    bronnen = resolved_tellerbronnen
    measurements, _, vermogens = tabellen.build_measurements_en_quality(
        bronnen["dsmr"], bronnen["kamstrup"], bronnen["heatpump"], bronnen["boiler"]
    )
    derived = tabellen.build_derived(
        vermogens, bronnen["dsmr"], bronnen["kamstrup"], bronnen["heatpump"], bronnen["boiler"],
        bronnen["dsmr"].assign(temperature=20.0, humidity=50.0),
        tabellen.build_weer(bronnen["dsmr"].assign(station_code=260, T=200, FH=30, Q=100)),
        pd.DataFrame({"home_id__str": ["A"], "weerstation_nr": [260]}),
    )
    assert gaskwaliteit.KOLOM in derived.columns
    assert gaskwaliteit.BRON_KOLOM in derived.columns
