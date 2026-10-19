# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.analyses: het analyseprogramma (ontwerp-preprocessing.md §8).

Elke test bouwt een kleine, met de hand gemaakte DataFrame en rekent minstens één uitkomst met de
hand uit, conform de opdracht bij deze module.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from dph_preprocessing import analyses, gaskwaliteit
from dph_preprocessing.tellers import J_PER_KWH, SPRONG_DREMPEL__W, differentieer_teller


def _tijden(start: str, n: int, freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq, tz="UTC")


# --------------------------------------------------------------------------------------------
# Gedeelde hulpfuncties
# --------------------------------------------------------------------------------------------


def test_run_lengths_breekt_op_woninggrens():
    # A: aanwezig,aanwezig,afwezig -- B: afwezig,aanwezig (mag niet samensmelten met A's afwezig).
    aanwezig = pd.Series([True, True, False, False, True])
    home = pd.Series(["A", "A", "A", "B", "B"])
    reeksen = analyses._run_lengths(aanwezig, home)
    # Verwacht: (A,True,2), (A,False,1), (B,False,1), (B,True,1) -- vier reeksen, geen vijf.
    assert len(reeksen) == 4
    a_reeksen = reeksen[reeksen["home_id__str"] == "A"].to_dict("records")
    assert {"home_id__str": "A", "aanwezig": True, "lengte": 2} in a_reeksen
    assert {"home_id__str": "A", "aanwezig": False, "lengte": 1} in a_reeksen
    b_reeksen = reeksen[reeksen["home_id__str"] == "B"].to_dict("records")
    assert {"home_id__str": "B", "aanwezig": False, "lengte": 1} in b_reeksen
    assert {"home_id__str": "B", "aanwezig": True, "lengte": 1} in b_reeksen


def test_delta_t_s_gebruikt_werkelijke_tijd_en_negeert_volgorde():
    # Voorwaarts (ontwerp-intervalsemantiek.md §2): delta_t__s op een rij is de tijd TOT de
    # volgende rij van dezelfde woning, dus bij de "eerdere" rij (11:00), niet de "latere" (11:15).
    tijd = pd.Series(pd.to_datetime(["2022-01-01T11:15:00", "2022-01-01T11:00:00"]).tz_localize("UTC"))
    home = pd.Series(["A", "A"])
    dt = analyses._delta_t__s(tijd, home)
    assert pd.isna(dt.iloc[0])  # 11:15 is de LAATSTE rij van woning A: geen volgende rij
    assert dt.iloc[1] == 900.0  # 11:00 is de eerste rij: 900 s tot de volgende (11:15)


# --------------------------------------------------------------------------------------------
# A1 -- warmtepompteller
# --------------------------------------------------------------------------------------------


def test_a1_warmtepompteller_perfecte_correlatie_en_fysische_grens():
    derived = pd.DataFrame(
        {
            "home_id__str": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "p_warmtepomp__W": [0.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 100_000.0],
            "p_warmtepomp_meting__W": [0.0, 1.0, 2.0, 3.0, 500.0, 10.0, 200.0, 100.0],
        }
    )
    resultaat = analyses.analyse_a1_warmtepompteller(derived, drempel__W=50_000.0)
    a = resultaat.set_index("home_id__str").loc["A"]
    b = resultaat.set_index("home_id__str").loc["B"]
    # Woning A: teller == meting, dus corr == 1.0 exact (met de hand na te rekenen).
    assert a["corr_teller_meting"] == pytest.approx(1.0)
    assert a["n_boven_grens_teller"] == 0
    assert a["max_teller__W"] == 3.0
    # Woning B: één tellerwaarde (100.000 W) boven de grens van 50 kW.
    assert b["n_boven_grens_teller"] == 1
    assert b["max_teller__W"] == 100_000.0


# --------------------------------------------------------------------------------------------
# A3 -- meterwissels en resets
# --------------------------------------------------------------------------------------------


def test_vind_spiegelparen_ontdekt_grote_sprong_die_direct_teruggedraaid_wordt():
    # Acht "normale" deltas van 1, dan een sprong van +1000 direct gevolgd door -999 (bijna
    # exacte compensatie, binnen 2 kwartieren) -- de handtekening van een meterwissel.
    delta = pd.Series([1.0] * 8 + [1000.0, -999.0])
    assert analyses._vind_spiegelparen(delta) == 1


def test_vind_spiegelparen_telt_geen_ongerelateerde_sprongen():
    delta = pd.Series([1.0] * 8 + [1000.0, 1000.0])  # geen compensatie, geen spiegelpaar
    assert analyses._vind_spiegelparen(delta) == 0


def test_tel_spiegelparen_alle_woningen_gelijk_aan_de_referentie_per_woning():
    # Zelfde reeks als test_vind_spiegelparen_ontdekt_grote_sprong_..., maar nu voor TWEE woningen
    # tegelijk door de gevectoriseerde functie gehaald -- moet exact hetzelfde antwoord geven als
    # _vind_spiegelparen per woning apart.
    per_woning = [1.0] * 8 + [1000.0, -999.0]
    geldig = pd.DataFrame(
        {
            "home_id__str": ["A"] * 10 + ["B"] * 10,
            "tijdstip_start": list(_tijden("2022-01-01T00:00:00", 10)) * 2,
            "delta": per_woning + per_woning,
        }
    )
    resultaat = analyses._tel_spiegelparen_alle_woningen(geldig)
    assert resultaat["A"] == analyses._vind_spiegelparen(pd.Series(per_woning)) == 1
    assert resultaat["B"] == 1


def test_tel_spiegelparen_alle_woningen_lekt_niet_over_een_woninggrens():
    # Woning A eindigt met een grote sprong (+1000); woning B begint met de bijna-compenserende
    # sprong (-999). Zonder het woninggrens-masker zou shift(-1) dit als spiegelpaar over de grens
    # heen tellen -- met het masker (home_id-vergelijking) hoort dat NUL op te leveren voor beide
    # woningen (geen van beide heeft, los bekeken, een groot-genoeg tegenhanger).
    geldig = pd.DataFrame(
        {
            "home_id__str": ["A"] * 9 + ["B"] * 9,
            "tijdstip_start": list(_tijden("2022-01-01T00:00:00", 9)) * 2,
            "delta": ([1.0] * 8 + [1000.0]) + ([-999.0] + [1.0] * 8),
        }
    )
    resultaat = analyses._tel_spiegelparen_alle_woningen(geldig)
    assert resultaat.reindex(["A", "B"], fill_value=0).tolist() == [0, 0]


_A3_STAND_KOLOMMEN = (
    "e_import_laag_cum__kWh", "e_import_hoog_cum__kWh", "e_export_laag_cum__kWh", "e_export_hoog_cum__kWh",
    "g_gebruik_cum__m3", "e_warmtepomp_cum__kWh", "e_ketel_cum__kWh", "q_geleverd_cum__J",
)


def test_a3_meterwissels_verdeling_van_deltas():
    # Woning A, e_import_laag_cum__kWh: 10 -> 11 -> 9 (een stijging van 1, dan een daling van 2).
    measurements = pd.DataFrame(
        {
            "home_id__str": ["A", "A", "A"],
            "tijdstip_start": _tijden("2022-02-07T11:00:00", 3),
            **{k: [0.0, 0.0, 0.0] for k in _A3_STAND_KOLOMMEN},
        }
    )
    measurements["e_import_laag_cum__kWh"] = [10.0, 11.0, 9.0]
    resultaat = analyses.analyse_a3_meterwissels(measurements)
    rij = resultaat[(resultaat["home_id__str"] == "A") & (resultaat["teller"] == "e_import_laag_cum__kWh")].iloc[0]
    # Twee geldige deltas: [1, -2] -- mediaan (p50) is -0,5, precies met de hand na te rekenen.
    assert rij["p50"] == pytest.approx(-0.5)
    assert rij["min"] == -2.0
    assert rij["max"] == 1.0
    assert rij["n_dalingen"] == 1
    assert rij["n"] == 2


# --------------------------------------------------------------------------------------------
# A5 -- scheefheid per bron
# --------------------------------------------------------------------------------------------


def test_a5_scheefheid_per_bron_is_doorgeefluik_van_de_preprocessing_tabel():
    # A5 leest geen brondata opnieuw (dat zou ~20 min kosten op de volledige dataset): de
    # samenvatting komt kant-en-klaar uit data/processed/scheefheid.parquet
    # (tabellen.bouw_scheefheid_samenvatting), en deze functie geeft 'm ongewijzigd door -- zie de
    # module-docstring van tabellen.bouw_scheefheid_samenvatting voor de rekenkern
    # (die daar getest wordt, test_tabellen.py::test_bouw_scheefheid_samenvatting_*).
    scheefheid = pd.DataFrame(
        {
            "home_id__str": ["A"],
            "bron": ["dsmr"],
            "mediaan__s": [10.0],
            "p95__s": [19.0],
            "max__s": [20.0],
            "n": [3],
        }
    )
    resultaat = analyses.analyse_a5_scheefheid_per_bron(scheefheid)
    pd.testing.assert_frame_equal(resultaat, scheefheid)


# --------------------------------------------------------------------------------------------
# A6 -- uitval per bron of per woning
# --------------------------------------------------------------------------------------------


def test_a6_onderscheidt_alle_vier_ontbrekend_van_precies_een():
    # Q0: alle 4 bronnen aanwezig. Q1: heatpump ontbreekt (precies 1 bron). Q2: ontbreekt bij
    # ALLE bronnen (geen rij in measurements, wel als ontbrekend__bool=True-rij in quality).
    # Q3: alle 4 weer aanwezig.
    measurements = pd.DataFrame(
        {
            "home_id__str": ["A", "A", "A"],
            "tijdstip_start": [_tijden("2022-02-07T11:00:00", 1)[0], _tijden("2022-02-07T11:15:00", 1)[0], _tijden("2022-02-07T11:45:00", 1)[0]],
            "e_import_laag_cum__kWh": [1.0, 1.0, 1.0],
            "q_geleverd_cum__J": [1.0, 1.0, 1.0],
            "e_warmtepomp_cum__kWh": [1.0, np.nan, 1.0],
            "e_ketel_cum__kWh": [1.0, 1.0, 1.0],
        }
    )
    quality = pd.DataFrame(
        {
            "home_id__str": ["A", "A", "A", "A"],
            "tijdstip_start": _tijden("2022-02-07T11:00:00", 4),
            "ontbrekend__bool": pd.array([False, False, True, False], dtype="boolean"),
        }
    )
    resultaat = analyses.analyse_a6_uitval_bron_of_woning(measurements, quality)
    rij = resultaat.set_index("home_id__str").loc["A"]
    assert rij["n_alle_vier_ontbrekend"] == 1
    assert rij["n_precies_een_ontbrekend"] == 1


# --------------------------------------------------------------------------------------------
# B2 -- energiebalans
# --------------------------------------------------------------------------------------------


def _b2_basis(home_id, tijden, kwh_reeks_per_kolom: dict[str, list[float]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bouw een (measurements, derived)-paar waarbij ``derived``'s vermogenskolommen ECHT via
    ``differentieer_teller`` berekend zijn (zelfde logica als tabellen.py), zodat de fixture
    representatief is voor wat de pijplijn zelf zou produceren."""
    n = len(tijden)
    home = pd.Series([home_id] * n)
    tijd = pd.Series(tijden)
    measurements = pd.DataFrame({"home_id__str": home, "tijdstip_start": tijd})
    for kolom in _A3_STAND_KOLOMMEN:
        measurements[kolom] = kwh_reeks_per_kolom.get(kolom, [0.0] * n)

    e_import = measurements[["e_import_laag_cum__kWh", "e_import_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_export = measurements[["e_export_laag_cum__kWh", "e_export_hoog_cum__kWh"]].sum(axis=1, min_count=1)
    e_net_cum = e_import - e_export
    derived = pd.DataFrame({"home_id__str": home, "tijdstip_start": tijd})
    derived["e_net__W"] = differentieer_teller(e_net_cum, tijd, home, J_PER_KWH)["vermogen__W"]
    derived["g_gebruik__W"] = differentieer_teller(measurements["g_gebruik_cum__m3"], tijd, home, 1.0)["vermogen__W"]
    derived["p_warmtepomp__W"] = differentieer_teller(measurements["e_warmtepomp_cum__kWh"], tijd, home, J_PER_KWH)["vermogen__W"]
    derived["p_ketel__W"] = differentieer_teller(measurements["e_ketel_cum__kWh"], tijd, home, J_PER_KWH)["vermogen__W"]
    derived["q_geleverd__W"] = differentieer_teller(measurements["q_geleverd_cum__J"], tijd, home, 1.0)["vermogen__W"]
    return measurements, derived


def test_b2_energiebalans_sluit_bij_volledige_reeks():
    # e_warmtepomp_cum__kWh: 10 -> 11 -> 13 over 2 kwartieren (900 s elk). Delta's: 1 kWh en 2 kWh.
    # Energie uit de tellerstand: (13-10) kWh * 3.6e6 J/kWh = 10.800.000 J. Dat moet EXACT gelijk
    # zijn aan de som van vermogen*delta_t, want geen enkel kwartier ontbreekt.
    tijden = _tijden("2022-02-07T11:00:00", 3)
    measurements, derived = _b2_basis("A", tijden, {"e_warmtepomp_cum__kWh": [10.0, 11.0, 13.0]})
    resultaat = analyses.analyse_b2_energiebalans(measurements, derived)
    rij = resultaat[(resultaat["home_id__str"] == "A") & (resultaat["teller"] == "p_warmtepomp__W")].iloc[0]
    assert rij["energie_uit_teller__J"] == pytest.approx(10_800_000.0)
    assert rij["energie_uit_vermogen__J"] == pytest.approx(10_800_000.0)
    assert rij["relatieve_afwijking"] == pytest.approx(0.0, abs=1e-9)


def test_b2_energiebalans_breekt_bij_een_gat_in_de_eigen_teller():
    # e_ketel_cum__kWh is aanwezig bij Q0 (=5) en Q3 (=8), maar ONTBREEKT bij Q1/Q2 -- de RIJEN
    # bestaan wel (een andere bron leverde die kwartieren aan), dus dit is geen "ontbrekend
    # kwartier" in de zin van quality.ontbrekend__bool. .diff() breekt de keten dan volledig: geen
    # van de vier delta's rond het gat is berekenbaar, dus de energie uit vermogen is NIET
    # beschikbaar (NaN), terwijl de tellerstand zelf wél 3 kWh verschil laat zien.
    tijden = _tijden("2022-02-07T11:00:00", 4)
    measurements, derived = _b2_basis("B", tijden, {"e_ketel_cum__kWh": [5.0, np.nan, np.nan, 8.0]})
    resultaat = analyses.analyse_b2_energiebalans(measurements, derived)
    rij = resultaat[(resultaat["home_id__str"] == "B") & (resultaat["teller"] == "p_ketel__W")].iloc[0]
    assert rij["energie_uit_teller__J"] == pytest.approx(3.0 * J_PER_KWH)
    assert pd.isna(rij["energie_uit_vermogen__J"])
    assert pd.isna(rij["relatieve_afwijking"])


# --------------------------------------------------------------------------------------------
# B4 -- verdeling van de gaten per grootheid
# --------------------------------------------------------------------------------------------


def test_b4_gatverdeling_bakt_een_gat_van_dertig_minuten_correct():
    tijden = _tijden("2022-02-07T11:00:00", 6)  # 11:00 .. 12:15
    quality = pd.DataFrame({"home_id__str": ["A"] * 6, "tijdstip_start": tijden})
    derived = pd.DataFrame(
        {
            "home_id__str": ["A"] * 6,
            "tijdstip_start": tijden,
            # aanwezig, aanwezig, ONTBREEKT, ONTBREEKT, aanwezig, aanwezig -- 2 kwartier = 1800 s.
            "temp_binnen_meting__degC": [20.0, 20.1, np.nan, np.nan, 20.2, 20.3],
        }
    )
    resultaat = analyses.analyse_b4_gatverdeling(quality, derived)
    rij = resultaat[(resultaat["kolom"] == "temp_binnen_meting__degC") & (resultaat["home_id__str"] == "A")]
    # Alle zes bakken komen terug (ook de lege, dat is bewust -- ontwerp: laat zien dat "<15 min"
    # op kwartierdata per definitie leeg is), maar precies één bak heeft een gevonden gat.
    assert len(rij) == 6
    gevuld = rij[rij["n_gaten"] > 0]
    assert len(gevuld) == 1
    r = gevuld.iloc[0]
    assert r["bak"] == "30-90 min"
    assert r["n_gaten"] == 1
    assert r["totale_duur__s"] == pytest.approx(1800.0)
    leeg = rij[rij["bak"] == "<15 min"].iloc[0]
    assert leeg["n_gaten"] == 0


# --------------------------------------------------------------------------------------------
# B5 -- aaneengesloten bruikbare tijd
# --------------------------------------------------------------------------------------------


def test_b5_aaneengesloten_tijd_dekking_en_streaks():
    # Patroon: aanwezig,aanwezig,ONTBREEKT,aanwezig,aanwezig,aanwezig,aanwezig,aanwezig (8 kwartieren).
    tijden = _tijden("2022-02-07T11:00:00", 8)
    ontbrekend = pd.array([False, False, True, False, False, False, False, False], dtype="boolean")
    quality = pd.DataFrame({"home_id__str": ["A"] * 8, "tijdstip_start": tijden, "ontbrekend__bool": ontbrekend})
    resultaat = analyses.analyse_b5_aaneengesloten_tijd(quality, max_gat__s=90 * 60.0)
    breed = resultaat.pivot(index="home_id__str", columns="metric", values="waarde").loc["A"]
    # Totale tijdspanne: 7 * 900 s = 6300 s. Het enige gat (1 kwartier = 900 s) valt ruim onder de
    # limiet van 90 minuten, dus telt volledig mee: gedekte_tijd == totale_tijd.
    assert breed["totale_tijd__s"] == pytest.approx(6300.0)
    assert breed["gedekte_tijd__s"] == pytest.approx(6300.0)
    assert breed["aandeel_gedekt"] == pytest.approx(1.0)
    # Aaneengesloten AANWEZIGE reeksen: lengte 2 (1800 s, bak kwartier_tot_uur) en lengte 5 (4500
    # s, bak uur_tot_dag). Samen weer 6300 s.
    assert breed["streak__kwartier_tot_uur__s"] == pytest.approx(1800.0)
    assert breed["streak__uur_tot_dag__s"] == pytest.approx(4500.0)


# --------------------------------------------------------------------------------------------
# B7 -- sprongdrempels tegen de werkelijke verdeling
# --------------------------------------------------------------------------------------------


def test_b7_sprongdrempels_percentielen():
    derived = pd.DataFrame(
        {
            "home_id__str": ["A"] * 5,
            "p_warmtepomp__W": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    resultaat = analyses.analyse_b7_sprongdrempels(derived)
    rij = resultaat[(resultaat["home_id__str"] == "A") & (resultaat["teller"] == "p_warmtepomp__W")].iloc[0]
    # Lineaire quantile-interpolatie op [10,20,30,40,50]: p99 op positie 0,99*4=3,96 -> 49,6.
    assert rij["p99__W"] == pytest.approx(49.6)
    assert rij["max__W"] == 50.0
    # Niet hardcoderen: de drempels zijn op 05-09-2026 op de gemeten verdeling herzien (analyse B7)
    # en kunnen dat weer worden. Deze test gaat over de KOPPELING teller -> drempel, niet over de
    # waarde; die hoort in tellers.py te staan en niet hier verdubbeld te worden.
    assert rij["huidige_drempel__W"] == SPRONG_DREMPEL__W["p_warmtepomp__W"]
    assert rij["n"] == 5


# --------------------------------------------------------------------------------------------
# B8 -- stookseizoenen: een eerlijke telling
# --------------------------------------------------------------------------------------------


def test_stookseizoen_venster_okt_tot_mei():
    start, eind = analyses._stookseizoen_venster(2022)
    assert start == pd.Timestamp("2022-10-01T00:00:00", tz="UTC")
    assert eind == pd.Timestamp("2023-05-01T00:00:00", tz="UTC")


def test_b8_stookseizoen_dekking_exact_aandeel():
    # Vijf aanwezige kwartieren binnen het venster 2022/2023 (okt 2022 t/m apr 2023). Het venster
    # zelf telt 212 dagen (31+30+31+31+28+31+30) * 96 kwartier/dag = 20.352 kwartieren.
    tijden = pd.to_datetime(
        ["2022-10-05T00:00:00", "2022-10-05T00:15:00", "2022-11-01T00:00:00", "2023-01-15T00:00:00", "2023-04-29T23:45:00"]
    ).tz_localize("UTC")
    quality = pd.DataFrame(
        {"home_id__str": ["A"] * 5, "tijdstip_start": tijden, "ontbrekend__bool": pd.array([False] * 5, dtype="boolean")}
    )
    resultaat = analyses.analyse_b8_stookseizoen_dekking(quality)
    rij = resultaat[resultaat["stookseizoen"] == "2022/2023"].iloc[0]
    assert rij["verwacht_aantal"] == 20_352
    assert rij["aanwezig_aantal"] == 5
    assert rij["aandeel_gedekt"] == pytest.approx(5 / 20_352)


# --------------------------------------------------------------------------------------------
# B9 -- loopt er tapwater langs de warmtemeter?
# --------------------------------------------------------------------------------------------


def test_b9_tapwater_verrijking_en_vlag():
    n_warmte = 12
    n_zonder = 18
    tijden = _tijden("2022-07-01T00:00:00", n_warmte + n_zonder)
    q = [300.0] * n_warmte + [50.0] * n_zonder  # >200 W is "warmte"
    # Van de 12 warmte-kwartieren: 10 met gas>500W, 2 niet.
    gas = [600.0] * 10 + [100.0] * 2 + [600.0] * 3 + [100.0] * 15  # van de 18 zonder-warmte: 3 met gas>500W
    wp = [2 * v for v in q]  # exacte lineaire relatie -> corr == 1.0
    aanvoer = [55.0] * 6 + [45.0] * 6 + [20.0] * n_zonder  # helft van de warmte-kwartieren > 50 °C
    derived = pd.DataFrame(
        {
            "home_id__str": ["A"] * (n_warmte + n_zonder),
            "tijdstip_start": tijden,
            "q_geleverd__W": q,
            "g_gebruik__W": gas,
            "p_warmtepomp__W": wp,
            "temp_aanvoer_meting__degC": aanvoer,
        }
    )
    resultaat = analyses.analyse_b9_tapwater_langs_warmtemeter(derived)
    rij = resultaat.iloc[0]
    assert rij["n_zomerkwartieren_met_warmte"] == 12
    assert rij["aandeel_zomerkwartieren_met_warmte"] == pytest.approx(12 / 30)
    assert rij["aandeel_gas_bij_warmte"] == pytest.approx(10 / 12)
    assert rij["basiskans_gas_zonder_warmte"] == pytest.approx(3 / 18)
    assert rij["verrijking"] == pytest.approx(5.0)
    assert rij["corr_warmte_wp_elektra"] == pytest.approx(1.0)
    assert rij["aandeel_aanvoer_boven_50c"] == pytest.approx(0.5)
    assert bool(rij["tapwater_langs_warmtemeter__vlag"]) is True


def test_b9_geen_vlag_bij_te_weinig_warmtekwartieren():
    # Zelfde verrijking als hierboven, maar met maar 4 warmte-kwartieren (< B9_MIN_N_WARMTE): de
    # vlag mag dan niet gezet worden, ook al is de verrijking sterk.
    tijden = _tijden("2022-07-01T00:00:00", 4 + 6)
    q = [300.0] * 4 + [50.0] * 6
    gas = [600.0] * 3 + [100.0] * 1 + [600.0] * 1 + [100.0] * 5
    wp = [2 * v for v in q]
    aanvoer = [55.0] * 4 + [20.0] * 6
    derived = pd.DataFrame(
        {"home_id__str": ["A"] * 10, "tijdstip_start": tijden, "q_geleverd__W": q, "g_gebruik__W": gas, "p_warmtepomp__W": wp, "temp_aanvoer_meting__degC": aanvoer}
    )
    resultaat = analyses.analyse_b9_tapwater_langs_warmtemeter(derived)
    assert bool(resultaat.iloc[0]["tapwater_langs_warmtemeter__vlag"]) is False


# --------------------------------------------------------------------------------------------
# B10 -- rekent de Kamstrup na wat hij zegt te meten?
# --------------------------------------------------------------------------------------------


def test_b10_kamstrup_consistentie_mediane_afwijking():
    rho, cp = analyses.B10_RHO_WATER__KG_M3, analyses.B10_CP_WATER__J_KGK
    q_berekend = rho * cp * (0.1 * 1e-3) * 10.0  # debiet 0,1 dm3/s, delta_t 10 K
    derived = pd.DataFrame(
        {
            "home_id__str": ["A"] * 3,
            "debiet_meting__dm3_s_1": [0.1, 0.1, 0.01],  # de derde rij zit ONDER de debietdrempel
            "temp_aanvoer_meting__degC": [50.0, 50.0, 50.0],
            "temp_retour_meting__degC": [40.0, 40.0, 40.0],
            # rij 1: exacte match (afwijking 0). rij 2: meter meet 10% te veel. rij 3: zou een
            # enorme afwijking geven als hij NIET uitgesloten werd door de debietdrempel.
            "q_geleverd_meting__W": [q_berekend, q_berekend * 1.1, 1.0],
        }
    )
    resultaat = analyses.analyse_b10_kamstrup_consistentie(derived)
    rij = resultaat.iloc[0]
    assert rij["n"] == 2  # de rij onder de debietdrempel telt niet mee
    # mediaan van [0, -1/11] (twee waarnemingen) is het gemiddelde: -1/22.
    assert rij["mediane_relatieve_afwijking"] == pytest.approx(-1 / 22)


# --------------------------------------------------------------------------------------------
# Registry / runner
# --------------------------------------------------------------------------------------------


def test_registry_namen_zijn_uniek():
    namen = [spec.naam for spec in analyses.REGISTRY]
    assert len(namen) == len(set(namen))


def test_sectie_b2_verdraagt_meerdere_tellers(tmp_path):
    """Regressie: `groupby(...).apply()` op een functie die een dict teruggeeft, klapt die dict uit.

    `_spreiding_over_woningen` geeft een dict terug. Geef je die aan `SeriesGroupBy.apply`, dan maakt
    pandas er een Series met MultiIndex van, en levert itereren losse floats op in plaats van de
    dicts -- `AttributeError: 'float' object has no attribute 'get'`. Dat gebeurde pas bij het
    schrijven van het rapport, dus ná twee uur rekenen (05-09-2026).
    """
    df = pd.DataFrame(
        {
            "home_id__str": ["a", "b", "a", "b"],
            "teller": ["e_net__W", "e_net__W", "q_geleverd__W", "q_geleverd__W"],
            "relatieve_afwijking": [0.01, 0.02, 0.03, 0.04],
            "energie_uit_teller__J": [1.0, 2.0, 3.0, 4.0],
            "energie_uit_vermogen__J": [1.0, 2.0, 3.0, 4.0],
        }
    )
    regels = analyses._sectie_b2(df)
    tekst = "\n".join(regels)
    assert "e_net__W" in tekst and "q_geleverd__W" in tekst
    assert "| 2 |" in tekst, "beide tellers moeten twee woningen tellen"


def test_sectie_b2_verdraagt_een_teller_zonder_bruikbare_waarden():
    df = pd.DataFrame(
        {
            "home_id__str": ["a", "b"],
            "teller": ["e_net__W", "q_geleverd__W"],
            "relatieve_afwijking": [0.01, float("nan")],
            "energie_uit_teller__J": [1.0, 2.0],
            "energie_uit_vermogen__J": [1.0, 2.0],
        }
    )
    regels = analyses._sectie_b2(df)
    assert any("q_geleverd__W | 0 |" in r for r in regels), "lege teller moet een nulrij geven"


# --------------------------------------------------------------------------------------------
# Nederlandse getalopmaak in de gegenereerde rapporttekst (opmaak.py)
# --------------------------------------------------------------------------------------------


def test_sectie_a1_gebruikt_nederlandse_opmaak():
    df = pd.DataFrame(
        {
            "home_id__str": ["woning_a", "woning_b", "woning_c"],
            "corr_teller_meting": [0.9, 0.246, 0.5],
            "n_boven_grens_teller": [0, 12345, 0],
            "p99_teller__W": [100.0, 200.0, 300.0],
            "max_teller__W": [1000.0, 2000.0, 3000.0],
            "max_meting__W": [1000.0, 2000.0, 3000.0],
        }
    )
    tekst = "\n".join(analyses._sectie_a1(df))
    # Duizendtalscheiding: een punt, niet de Amerikaanse komma (die had hier "12,345"
    # opgeleverd met de oude {:,}-opmaak). Let op: een simpele "cijfer,drie cijfers"-regex is
    # HIER geen goede toets, want opmaak.getal(x, 3) op de correlatiekolom levert legitieme
    # 3-decimalen-Nederlandse getallen op (bv. "0,900") die toevallig hetzelfde patroon hebben.
    assert "12.345" in tekst
    assert "12,345" not in tekst
    # aandeel(1, 3) (woning_b heeft corr < 0,5 EN >=1 waarde boven de grens): een komma als
    # decimaalteken in het percentage.
    assert re.search(r"\d,\d %", tekst)



def test_a3_is_ongevoelig_voor_de_rijvolgorde_in_de_invoer():
    """A3 sorteert EEN keer vooraf in plaats van per teller (dat was zestien keer op 8,6 mln rijen).

    Het risico van die wijziging is precies dit: eerst deed `differentieer_teller` een eigen
    sortering en sorteerde A3 er daarna nog eens overheen, dus een ongesorteerde invoer kwam hoe
    dan ook goed. Nu hangt de uitkomst af van die ene sortering vooraf. Deze test geeft dezelfde
    data in twee volgordes en eist dezelfde uitkomst.
    """
    tijden = pd.date_range("2023-01-01", periods=6, freq="15min", tz="UTC")
    op_volgorde = pd.DataFrame(
        {
            "home_id__str": ["a"] * 6 + ["b"] * 6,
            "tijdstip_start": list(tijden) * 2,
            **{
                k: ([0.0, 1.0, 2.0, 3.0, 4.0, 5.0] + [10.0, 12.0, 11.0, 13.0, 14.0, 15.0])
                for k in analyses.A3_RUWE_TELLERS
            },
        }
    )
    door_elkaar = op_volgorde.sample(frac=1.0, random_state=7).reset_index(drop=True)

    k = ["home_id__str", "teller"]
    a = analyses.analyse_a3_meterwissels(op_volgorde).sort_values(k).reset_index(drop=True)
    b = analyses.analyse_a3_meterwissels(door_elkaar).sort_values(k).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)

    # en de deltas kloppen inhoudelijk: woning b heeft één daling (12 -> 11)
    rij_b = a[(a["home_id__str"] == "b") & (a["teller"] == analyses.A3_RUWE_TELLERS[0])].iloc[0]
    assert rij_b["n_dalingen"] == 1
    assert rij_b["n"] == 5, "vijf deltas uit zes standen"


def test_b2_normaliseert_de_werkelijke_calorische_gaswaarde_weg():
    """B2 toetst of het DIFFERENTIËREN verliesvrij is, niet of de calorische omrekening klopt. Nu
    die omrekening per rij verschilt (gaskwaliteit.py), moet de vermogenskant worden teruggerekend
    naar de vaste referentiewaarde -- anders meldt B2 een afwijking van ~2% die niets met
    differentiëren te maken heeft."""
    tijden = _tijden("2022-02-07T11:00:00", 3)
    measurements, derived = _b2_basis("A", tijden, {"g_gebruik_cum__m3": [100.0, 101.0, 103.0]})

    toegepast__J_m_3 = 36.0e6
    derived["g_gebruik__W"] = differentieer_teller(
        measurements["g_gebruik_cum__m3"], measurements["tijdstip_start"],
        measurements["home_id__str"], toegepast__J_m_3,
    )["vermogen__W"]
    derived[gaskwaliteit.KOLOM] = toegepast__J_m_3

    rij = analyses.analyse_b2_energiebalans(measurements, derived)
    gas = rij[(rij["home_id__str"] == "A") & (rij["teller"] == "g_gebruik__W")].iloc[0]

    # 3 m3 bij de referentiewaarde van 35,17 MJ/m3, en de balans sluit exact.
    assert gas["energie_uit_teller__J"] == pytest.approx(
        3.0 * gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3
    )
    assert gas["relatieve_afwijking"] == pytest.approx(0.0, abs=1e-6)


def test_b2_zonder_de_hhv_kolom_valt_terug_op_de_vaste_factor():
    """Een derived-tabel van vóór de gaskwaliteit-ingest heeft de kolom niet. Dan moet B2 gewoon met
    de vaste factor rekenen in plaats van te falen."""
    tijden = _tijden("2022-02-07T11:00:00", 3)
    measurements, derived = _b2_basis("A", tijden, {"g_gebruik_cum__m3": [100.0, 101.0, 103.0]})
    derived["g_gebruik__W"] = differentieer_teller(
        measurements["g_gebruik_cum__m3"], measurements["tijdstip_start"],
        measurements["home_id__str"], gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3,
    )["vermogen__W"]
    assert gaskwaliteit.KOLOM not in derived.columns

    rij = analyses.analyse_b2_energiebalans(measurements, derived)
    gas = rij[(rij["home_id__str"] == "A") & (rij["teller"] == "g_gebruik__W")].iloc[0]
    assert gas["relatieve_afwijking"] == pytest.approx(0.0, abs=1e-6)


def _a4_measurements(standen__m3):
    """Eén woning met alleen een gasteller, om het omslagpatroon te kunnen nabootsen."""
    n = len(standen__m3)
    tijden = _tijden("2022-02-07T11:00:00", n)
    kolommen = {
        "e_import_laag_cum__kWh": [0.0] * n, "e_import_hoog_cum__kWh": [0.0] * n,
        "e_export_laag_cum__kWh": [0.0] * n, "e_export_hoog_cum__kWh": [0.0] * n,
        "e_warmtepomp_cum__kWh": [0.0] * n, "e_ketel_cum__kWh": [0.0] * n,
        "q_geleverd_cum__J": [0.0] * n,
    }
    return pd.DataFrame(
        {"home_id__str": ["A"] * n, "tijdstip_start": tijden, "g_gebruik_cum__m3": standen__m3, **kolommen}
    )


def test_a4_herkent_een_echte_omslag():
    """9999,4 -> 0,3 is precies het IM3-patroon: stand ervóór vlak onder een macht van tien, erna
    vlak boven nul. Op cumulatieve standen is dat geen vermoeden maar een exact patroon."""
    r = analyses.analyse_a4_modulusartefacten(_a4_measurements([9998.1, 9999.4, 0.3, 1.5]))
    gas = r[r["teller"] == "g_gebruik_cum__m3"].iloc[0]
    assert gas["n_omslag_kandidaat"] == 1
    assert gas["n_naar_nul"] == 0


def test_a4_noemt_een_teller_die_naar_nul_valt_geen_omslag():
    """Het overheersende patroon in DEZE dataset: de teller meldt ineens nul terwijl de stand
    ervóór nergens in de buurt van een macht van tien lag. Dat is uitval, geen omslag, en een
    modulo zou het niet repareren maar wegpoetsen."""
    r = analyses.analyse_a4_modulusartefacten(_a4_measurements([5059.2, 5060.0, 0.0, 5061.0]))
    gas = r[r["teller"] == "g_gebruik_cum__m3"].iloc[0]
    assert gas["n_omslag_kandidaat"] == 0
    assert gas["n_naar_nul"] == 1


def test_a4_meterwissel_is_noch_omslag_noch_nul():
    """Een nieuwe meter begint op zijn eigen stand: een daling die nergens naar nul gaat en niet
    onder een macht van tien vandaan komt."""
    r = analyses.analyse_a4_modulusartefacten(_a4_measurements([5059.2, 5060.0, 812.0, 813.0]))
    gas = r[r["teller"] == "g_gebruik_cum__m3"].iloc[0]
    assert (gas["n_omslag_kandidaat"], gas["n_naar_nul"], gas["n_overig"]) == (0, 0, 1)


def test_a4_conclusie_zegt_expliciet_dat_er_geen_omslag_is():
    r = analyses.analyse_a4_modulusartefacten(_a4_measurements([5059.2, 5060.0, 0.0, 5061.0]))
    tekst = "\n".join(analyses._sectie_a4(r))
    assert "GEEN omslag-kandidaten" in tekst
    assert "modulo-correctie zou hier dus niets repareren" in tekst
