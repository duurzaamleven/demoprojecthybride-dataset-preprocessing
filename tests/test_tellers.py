# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.tellers: cumulatieve tellers -> intervalgemiddeld vermogen (§2.2),
VOORWAARTS gedifferentieerd zodat rij Q het interval [tijdstip_start(Q), +900s) beschrijft
(ontwerp-intervalsemantiek.md §2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dph_preprocessing.tellers import (
    INITIALISATIETELEGRAM_SENTINEL,
    differentieer_teller,
    is_initialisatietelegram,
    markeer_nulmetingen,
    teller_gestegen_masker,
    teller_sprong_masker,
    teller_terug_masker,
    verwerk_bronteller,
)


def _reeks(home_ids, tijden, waarden):
    return (
        pd.Series(waarden, dtype="float64"),
        pd.to_datetime(tijden).tz_localize("UTC"),
        pd.Series(home_ids),
    )


def test_differentieer_teller_normale_kwartieren():
    # Twee opeenvolgende kwartieren, 1 kWh verschil -> 1 kWh / 900 s * 3.6e6 J/kWh = 4000 W.
    # Voorwaarts: die 4000 W hoort bij de EERSTE rij (interval [11:00, 11:15)); de laatste rij van
    # de woning (11:15) heeft geen volgende teller en wordt NaN.
    waarde, tijd, home = _reeks(
        ["A", "A"], ["2022-02-07T11:00:00", "2022-02-07T11:15:00"], [10.0, 11.0]
    )
    result = differentieer_teller(waarde, tijd, home, eenheid_naar_J=3_600_000.0)
    assert result["vermogen__W"].iloc[0] == 4000.0
    assert result["delta_t__s"].iloc[0] == 900.0
    assert pd.isna(result["vermogen__W"].iloc[1])  # laatste rij van de woning: geen volgende teller


def test_differentieer_teller_vermogen_op_rij_q_beschrijft_interval_q_tot_q_plus_1():
    # ontwerp-intervalsemantiek.md §2, de trapeziumtoets: het vermogen op rij Q hoort bij het
    # interval NA Q (de VOLGENDE aflezing), niet bij het interval ervoor. Drie aflezingen met een
    # duidelijk andere stapgrootte vóór en na Q maken voorwaarts/achterwaarts onderscheidbaar.
    waarde, tijd, home = _reeks(
        ["A", "A", "A"],
        ["2022-02-07T11:00:00", "2022-02-07T11:15:00", "2022-02-07T11:30:00"],
        [10.0, 11.0, 15.0],  # stap vóór Q (11:15) is 1 kWh, stap NA Q is 4 kWh
    )
    result = differentieer_teller(waarde, tijd, home, eenheid_naar_J=3_600_000.0)
    # Rij Q (11:15) moet de stap NAAR 11:30 dragen (4 kWh/900s = 16000 W), niet de stap vanaf
    # 11:00 (1 kWh/900s = 4000 W, wat een achterwaarts verschil zou opleveren).
    assert result["vermogen__W"].iloc[1] == 16000.0


def test_differentieer_teller_gebruikt_werkelijke_intervalduur_bij_ontbrekend_kwartier():
    # ontwerp §5/§2.2: het kwartier van 11:15 ontbreekt. Rij Q (11:00) beschrijft dan het interval
    # [11:00, 11:30), 1800 s lang -- dat moet de deler zijn, niet de aangenomen 900 s.
    waarde, tijd, home = _reeks(
        ["A", "A"], ["2022-02-07T11:00:00", "2022-02-07T11:30:00"], [10.0, 12.0]
    )
    result = differentieer_teller(waarde, tijd, home, eenheid_naar_J=3_600_000.0)
    assert result["delta_t__s"].iloc[0] == 1800.0
    # 2 kWh / 1800 s * 3.6e6 = 4000 W (niet 8000 W, wat een aangenomen 900 s zou opleveren).
    assert result["vermogen__W"].iloc[0] == 4000.0
    assert pd.isna(result["vermogen__W"].iloc[1])  # laatste rij van de woning


def test_differentieer_teller_groepeert_per_woning():
    # Woning A's laatste rij mag niet differentiëren met woning B's (toevallig gelijktijdige) rij.
    waarde, tijd, home = _reeks(
        ["A", "A", "B"],
        ["2022-02-07T11:00:00", "2022-02-07T11:15:00", "2022-02-07T11:15:00"],
        [10.0, 11.0, 500.0],
    )
    result = differentieer_teller(waarde, tijd, home, eenheid_naar_J=3_600_000.0)
    assert result["vermogen__W"].iloc[0] == 4000.0  # A's eerste rij, interval naar A's volgende rij
    assert pd.isna(result["vermogen__W"].iloc[1])  # A's laatste rij: geen volgende teller
    assert pd.isna(result["vermogen__W"].iloc[2])  # B's enige (en dus ook laatste) rij


def test_differentieer_teller_ongevoelig_voor_invoervolgorde():
    # Zelfde data, maar in willekeurige volgorde aangeleverd: het resultaat (op de oorspronkelijke
    # index terug) moet identiek zijn.
    waarde, tijd, home = _reeks(
        ["A", "A"], ["2022-02-07T11:15:00", "2022-02-07T11:00:00"], [11.0, 10.0]
    )
    result = differentieer_teller(waarde, tijd, home, eenheid_naar_J=3_600_000.0)
    assert pd.isna(result["vermogen__W"].iloc[0])  # dit is de "latere" rij (11:15): laatste na sortering
    assert result["vermogen__W"].iloc[1] == 4000.0  # de "eerdere" rij (11:00)


def test_teller_terug_masker():
    delta = pd.Series([5.0, -3.0, None])
    result = teller_terug_masker(delta)
    assert result.tolist() == [False, True, pd.NA]


def test_teller_gestegen_masker():
    delta = pd.Series([5.0, -3.0, 0.0, None])
    result = teller_gestegen_masker(delta)
    assert result.tolist() == [True, False, False, pd.NA]


def test_teller_sprong_masker():
    vermogen = pd.Series([1000.0, 50_000.0, None])
    result = teller_sprong_masker(vermogen, drempel__W=40_000.0)
    assert result.tolist() == [False, True, pd.NA]


# --- is_initialisatietelegram (ontwerp-teller-artefacten.md §3/§4.1) --------------------------


def test_is_initialisatietelegram_strikte_handtekening():
    # Alle vijf sentinelwaarden tegelijk -> True. Eén register anders (rij 2) -> False, ook al
    # staan de andere vier nog op hun sentinelwaarde: de handtekening is strikt (§4.1).
    df = pd.DataFrame(
        {
            "e_import_laag_cum__kWh": [8969.994, 8969.994, 100.0],
            "e_import_hoog_cum__kWh": [8789.167, 500.0, 100.0],
            "e_export_laag_cum__kWh": [3433.300, 3433.300, 100.0],
            "e_export_hoog_cum__kWh": [8299.146, 8299.146, 100.0],
            "g_gebruik_cum__m3": [5059.199, 5059.199, 100.0],
        }
    )
    assert is_initialisatietelegram(df).tolist() == [True, False, False]


def test_is_initialisatietelegram_één_register_toevallig_op_sentinelwaarde_is_geen_treffer():
    # §9: een echte meting kan toevallig op e_import_laag_cum__kWh = 8969,994 staan (df79ygat,
    # A0JoUuz-) zonder een initialisatietelegram te zijn. De strikte handtekening mag dat niet
    # meenemen.
    df = pd.DataFrame(
        {
            "e_import_laag_cum__kWh": [INITIALISATIETELEGRAM_SENTINEL["e_import_laag_cum__kWh"]],
            "e_import_hoog_cum__kWh": [8975.163],
            "e_export_laag_cum__kWh": [6381.683],
            "e_export_hoog_cum__kWh": [14182.572],
            "g_gebruik_cum__m3": [8894.696],
        }
    )
    assert is_initialisatietelegram(df).tolist() == [False]


def test_is_initialisatietelegram_op_de_volledige_dsmr_csv():
    # Regressietoets op de exacte telling uit §3/§6: 1896 rijen op de volledige dsmr.csv.
    import zipfile

    pad = Path(__file__).resolve().parents[1] / "data" / "raw" / "dph-dataset.zip"
    if not pad.exists():
        pytest.skip("data/raw/dph-dataset.zip niet aanwezig (ruwe data staat buiten git)")
    with zipfile.ZipFile(pad) as z:
        [naam] = [n for n in z.namelist() if n.endswith("dsmr.csv")]
        with z.open(naam) as f:
            ruw = pd.read_csv(f)
    df = ruw.rename(
        columns={
            "e_consumed_low": "e_import_laag_cum__kWh",
            "e_consumed_high": "e_import_hoog_cum__kWh",
            "e_delivered_low": "e_export_laag_cum__kWh",
            "e_delivered_high": "e_export_hoog_cum__kWh",
            "v_gas_consumed": "g_gebruik_cum__m3",
        }
    )
    treffers = is_initialisatietelegram(df)
    assert int(treffers.sum()) == 1896
    assert df.loc[treffers, "location_id"].nunique() == 167


# --- markeer_nulmetingen (ontwerp-teller-artefacten.md §4.2) -----------------------------------


def test_markeer_nulmetingen_zonder_home_id_zelfde_als_minuutpad():
    # Eén woning: 100, 110, 0, 0, 250 -> de twee nullen zijn nulmetingen (eerder al > 1 gestaan).
    stand = pd.Series([100.0, 110.0, 0.0, 0.0, 250.0])
    assert markeer_nulmetingen(stand).tolist() == [False, False, True, True, False]


def test_markeer_nulmetingen_begin_bij_nul_wordt_niet_gevlagd():
    # Een teller die bij nul begint en pas later gaat lopen (e_warmtepomp_cum__kWh,
    # q_geleverd_cum__J) mag zijn beginperiode niet als nulmeting verliezen.
    stand = pd.Series([0.0, 0.0, 5.0, 10.0])
    assert markeer_nulmetingen(stand).tolist() == [False, False, False, False]


def test_markeer_nulmetingen_per_woning_groepeert_correct():
    # Twee woningen door elkaar (zoals het kwartierpad ze aanlevert): het lopende maximum van
    # woning B mag niet worden aangestoken door woning A se hoge standen.
    stand = pd.Series([100.0, 110.0, 0.0, 0.0, 250.0, 50.0, 0.0, 60.0])
    home = pd.Series(["A", "A", "A", "A", "A", "B", "B", "B"])
    tijd = pd.to_datetime(
        [
            "2024-01-01T00:00", "2024-01-01T00:15", "2024-01-01T00:30", "2024-01-01T00:45",
            "2024-01-01T01:00", "2024-01-01T00:00", "2024-01-01T00:15", "2024-01-01T00:30",
        ]
    ).tz_localize("UTC")
    result = markeer_nulmetingen(stand, home_id=home, tijdstip_start=tijd)
    assert result.tolist() == [False, False, True, True, False, False, True, False]


def test_markeer_nulmetingen_met_home_id_vereist_tijdstip_start():
    with pytest.raises(ValueError):
        markeer_nulmetingen(pd.Series([0.0]), home_id=pd.Series(["A"]))


# --- verwerk_bronteller (ontwerp-teller-artefacten.md §4.2/§4.3) -------------------------------


def test_verwerk_bronteller_nulmeting_masker_beide_helften_geen_piek():
    # Reviewpunt A1: een gemaskeerd interval bridged NIET naar de eerstvolgende geldige aflezing --
    # het wordt gewoon NaN, aan beide kanten, geen valse piek van 140 kWh of een sprong naar 250.
    stand = pd.Series([100.0, 110.0, 0.0, 0.0, 0.0, 250.0])
    home = pd.Series(["A"] * 6)
    tijd = pd.date_range("2024-01-01", periods=6, freq="15min", tz="UTC")
    resultaat = verwerk_bronteller(stand, pd.Series(tijd), home)
    delta = resultaat["gedifferentieerd"]["delta"]
    assert delta.iloc[0] == 10.0  # 100 -> 110, ongemoeid
    assert delta.iloc[1:5].isna().all()  # alle intervallen rond/in de nulmeting: NaN, geen piek
    assert resultaat["nulmeting__bool"].tolist() == [False, False, True, True, True, False]
    assert not resultaat["wissel__bool"].any()  # herstel, dus geen wissel


def test_verwerk_bronteller_echte_wissel_maskeert_alleen_het_ene_interval():
    # Stand valt terug naar 30 (niet 0): een echte breuk, geen uitval-met-herstel. Alleen het ene
    # interval (110 -> 30) hoort op NaN; de stand zelf blijft staan (§4.3: geen segmentreparatie).
    stand = pd.Series([100.0, 110.0, 30.0, 40.0])
    home = pd.Series(["A"] * 4)
    tijd = pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC")
    resultaat = verwerk_bronteller(stand, pd.Series(tijd), home)
    assert resultaat["wissel__bool"].tolist() == [False, True, False, False]
    delta = resultaat["gedifferentieerd"]["delta"]
    assert delta.iloc[0] == 10.0
    assert pd.isna(delta.iloc[1])  # het gemaskeerde wissel-interval
    assert delta.iloc[2] == 10.0
    assert pd.isna(delta.iloc[3])  # laatste rij van de woning: geen volgende teller
    assert resultaat["schoon"].tolist() == [100.0, 110.0, 30.0, 40.0]  # stand ongemoeid


# --- volgorde: sentinel VOOR cummax (ontwerp-teller-artefacten.md §5) --------------------------


def test_sentinel_voor_cummax_is_dwingend_anders_valse_nulmetingen():
    # §5: bij een woning zonder teruglevering staat e_export_laag_cum__kWh structureel op 0,0 NA de
    # sentinelrij. Blijft de sentinelwaarde (3433,300, ruim boven TELLER_ONTWAAKT_BOVEN) meetellen in
    # het lopende maximum, dan vlagt markeer_nulmetingen elke latere 0,0-aflezing als valse
    # uitval-met-herstel. Dit is de kern van de 542.507-vs-361-vondst uit §5: hier op kleine schaal
    # (1 sentinelrij + 5 legitieme nullen), maar hetzelfde mechanisme.
    export_laag = pd.Series(
        [INITIALISATIETELEGRAM_SENTINEL["e_export_laag_cum__kWh"], 0.0, 0.0, 0.0, 0.0, 0.0]
    )

    # FOUTE volgorde: cummax-criterium zonder de sentinel eerst weg te halen.
    fout = markeer_nulmetingen(export_laag)
    assert fout.tolist() == [False, True, True, True, True, True]  # alle vijf nullen ten onrechte

    # GOEDE volgorde: sentinel eerst op NaN (zoals build_measurements_en_quality nu doet), dan pas
    # het cummax-criterium.
    df = pd.DataFrame(
        {
            "e_import_laag_cum__kWh": [INITIALISATIETELEGRAM_SENTINEL["e_import_laag_cum__kWh"]] + [0.0] * 5,
            "e_import_hoog_cum__kWh": [INITIALISATIETELEGRAM_SENTINEL["e_import_hoog_cum__kWh"]] + [0.0] * 5,
            "e_export_laag_cum__kWh": export_laag,
            "e_export_hoog_cum__kWh": [INITIALISATIETELEGRAM_SENTINEL["e_export_hoog_cum__kWh"]] + [0.0] * 5,
            "g_gebruik_cum__m3": [INITIALISATIETELEGRAM_SENTINEL["g_gebruik_cum__m3"]] + [0.0] * 5,
        }
    )
    sentinel = is_initialisatietelegram(df)
    export_laag_schoon = export_laag.mask(sentinel)
    goed = markeer_nulmetingen(export_laag_schoon)
    # Geen enkele nul is meer een nulmeting: de sentinelrij zelf is nu NaN (geen "stand"), en het
    # lopende maximum van de resterende reeks komt nooit boven TELLER_ONTWAAKT_BOVEN.
    assert goed.tolist() == [False, False, False, False, False, False]


def test_verwerk_bronteller_wissel_naar_nul_bij_teller_die_nooit_boven_1_kwam():
    # §4.3: "of naar 0 bij een teller die nooit boven 1 kwam" -- markeer_nulmetingen vlagt dat NIET
    # (cummax nooit > TELLER_ONTWAAKT_BOVEN), dus dit moet als wissel gezien worden, niet als
    # uitval-met-herstel.
    stand = pd.Series([0.5, 0.8, 0.0, 0.3])
    home = pd.Series(["A"] * 4)
    tijd = pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC")
    resultaat = verwerk_bronteller(stand, pd.Series(tijd), home)
    assert not resultaat["nulmeting__bool"].any()
    assert resultaat["wissel__bool"].tolist() == [False, True, False, False]
