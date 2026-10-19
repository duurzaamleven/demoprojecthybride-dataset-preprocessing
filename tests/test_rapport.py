# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.rapport: het gegenereerde datakwaliteitsrapport.

Focus hier: de Nederlandse getalopmaak (opmaak.py) komt daadwerkelijk in de gegenereerde
rapporttekst terecht -- geen Amerikaanse duizendtalkomma, wel een punt per duizendtal en een
komma als decimaalteken.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from dph_preprocessing import gaskwaliteit, rapport

_NBSP = " "


def _accumulator_met_testdata() -> rapport.RapportAccumulator:
    acc = rapport.RapportAccumulator()
    acc.n_rijen_measurements = 12345
    acc.n_rijen_quality = 20000
    acc.per_woning_rows = [
        {
            "home_id__str": "a",
            "dsmr": 12345,
            "kamstrup": 100,
            "heatpump": 50,
            "boiler": 10,
            "eerste_kwartier": pd.Timestamp("2022-01-01", tz="UTC"),
            "laatste_kwartier": pd.Timestamp("2022-06-01", tz="UTC"),
            "n_stookseizoenen": 1,
        },
        {
            "home_id__str": "b",
            "dsmr": 200,
            "kamstrup": 100,
            "heatpump": 50,
            "boiler": 10,
            "eerste_kwartier": pd.Timestamp("2022-01-01", tz="UTC"),
            "laatste_kwartier": pd.Timestamp("2023-06-01", tz="UTC"),
            "n_stookseizoenen": 2,
        },
    ]
    acc.n_compleet = 1
    acc.n_geobserveerd = 3
    acc.n_terug = 1
    acc.n_teruglevering = 1
    acc.n_sprong = 1
    acc.n_beoordeeld = 3
    acc.scheefheid_chunks = [np.array([1.0, 2.0, 400.0], dtype="float32")]
    return acc


def test_build_report_geen_amerikaanse_duizendtalkomma():
    homes = pd.DataFrame({"home_id__str": ["a", "b"]})
    tekst = rapport.build_report(homes, _accumulator_met_testdata(), is_steekproef=False)
    # Het signaal van een Amerikaanse duizendtalscheiding: een cijfer, een komma, drie cijfers.
    assert not re.search(r"[0-9],[0-9]{3}", tekst)


def test_build_report_gebruikt_punt_als_duizendtalscheiding():
    homes = pd.DataFrame({"home_id__str": ["a", "b"]})
    tekst = rapport.build_report(homes, _accumulator_met_testdata(), is_steekproef=False)
    # acc.n_rijen_measurements = 12345 en per_woning_rows[0]["dsmr"] = 12345 komen beide als
    # "12.345" terecht.
    assert "12.345" in tekst


def test_build_report_gebruikt_komma_als_decimaalteken_in_percentages():
    homes = pd.DataFrame({"home_id__str": ["a", "b"]})
    tekst = rapport.build_report(homes, _accumulator_met_testdata(), is_steekproef=False)
    # n_compleet=1, n_geobserveerd=3 -> aandeel(1, 3) = "1 van 3 (33,3<vaste spatie>%)".
    assert re.search(r"\d,\d" + _NBSP + "%", tekst)


def test_rapport_telt_de_terugval_op_de_vaste_calorische_waarde():
    """docs/lessen-uit-im3.md punt 2: een terugval op een aanname moet in het rapport staan, met
    hoeveel rijen het raakt. Een stille terugval ziet er in de uitvoer hetzelfde uit als een
    geslaagde ophaal."""
    acc = _accumulator_met_testdata()
    acc.voeg_chunk_toe(
        pd.DataFrame(
            {
                "home_id__str": ["a"] * 4,
                "tijdstip_start": pd.date_range("2022-01-01", periods=4, freq="15min", tz="UTC"),
                "tijdstip_meting": pd.date_range("2022-01-01", periods=4, freq="15min", tz="UTC"),
                **{kolom: [1.0] * 4 for kolom in rapport._BRON_PROXYKOLOM.values()},
            }
        ),
        pd.DataFrame(
            {
                "home_id__str": ["a"] * 4,
                "bron_incompleet__bool": pd.array([False] * 4, dtype="boolean"),
                "teller_initialisatie__bool": pd.array([False] * 4, dtype="boolean"),
                "teller_nulmeting__bool": pd.array([False] * 4, dtype="boolean"),
                "teller_wissel__bool": pd.array([False] * 4, dtype="boolean"),
                "teller_terug__bool": pd.array([False] * 4, dtype="boolean"),
                "teruglevering__bool": pd.array([False] * 4, dtype="boolean"),
                "teller_sprong__bool": pd.array([False] * 4, dtype="boolean"),
            }
        ),
        derived=pd.DataFrame(
            {
                "home_id__str": ["a"] * 4,
                gaskwaliteit.BRON_KOLOM: [
                    gaskwaliteit.BRON_ACTUEEL, gaskwaliteit.BRON_ACTUEEL,
                    gaskwaliteit.BRON_ACTUEEL, gaskwaliteit.BRON_FALLBACK,
                ],
                gaskwaliteit.KOLOM: [36.0e6, 36.0e6, 36.0e6, 35.17e6],
                "temp_buiten__degC": [5.0, 5.0, None, None],
                "wind__m_s_1": [3.0, 3.0, None, None],
                "ghi__W_m_2": [0.0, None, None, None],
            }
        ),
    )

    tekst = rapport.build_report(pd.DataFrame({"home_id__str": ["a"]}), acc, is_steekproef=False)

    assert "## 6. Calorische gaswaarde" in tekst
    assert f"`{gaskwaliteit.BRON_FALLBACK}`: 1 van 4 (25,0{_NBSP}%)" in tekst
    assert f"`{gaskwaliteit.BRON_ACTUEEL}`: 3 van 4 (75,0{_NBSP}%)" in tekst


def test_rapport_zegt_het_als_de_herkomst_niet_is_vastgelegd():
    tekst = rapport.build_report(
        pd.DataFrame({"home_id__str": ["a"]}), _accumulator_met_testdata(), is_steekproef=False
    )
    assert "niet vastgelegd" in tekst


def test_rapport_rekent_de_afwijking_van_de_vaste_waarde_zelf_uit():
    """Het percentage in punt 6 is een gegenereerd getal, geen met de hand bijgehouden claim
    (ontwerp principe 5). 35,8 MJ/m3 gemiddeld is 1,79% boven de vaste 35,17."""
    acc = _accumulator_met_testdata()
    acc.gas_hhv_bron_tellingen = {gaskwaliteit.BRON_ACTUEEL: 4}
    acc.gas_hhv_som__J_m_3 = 4 * 35.8e6
    acc.gas_hhv_n = 4

    tekst = rapport.build_report(pd.DataFrame({"home_id__str": ["a"]}), acc, is_steekproef=False)

    assert "35,800 MJ/m³" in tekst
    assert f"1,79{_NBSP}% hoger" in tekst


def test_rapport_telt_de_kwartieren_zonder_weer():
    """docs/lessen-uit-im3.md punt 1, tweede kandidaat: de weerkoppeling vult niets in maar laat een
    kwartier zonder KNMI-uurwaarde leeg. Dat is de juiste keuze en even onzichtbaar als een stille
    aanname, dus het rapport telt het."""
    acc = _accumulator_met_testdata()
    acc.n_rijen_derived = 4
    acc.weer_ontbrekend = {"temp_buiten__degC": 2, "wind__m_s_1": 2, "ghi__W_m_2": 3}
    acc.n_woningen_weer_onvolledig = 1

    tekst = rapport.build_report(pd.DataFrame({"home_id__str": ["a", "b"]}), acc, is_steekproef=False)

    assert "## 7. Weerkoppeling" in tekst
    assert f"`temp_buiten__degC` leeg: 2 van 4 (50,0{_NBSP}%)" in tekst
    assert f"`ghi__W_m_2` leeg: 3 van 4 (75,0{_NBSP}%)" in tekst
    assert "1 van 2" in tekst


def test_rapport_splitst_de_drie_teller_artefacten_en_toont_de_langste_uitvalperiode():
    """ontwerp-teller-artefacten.md §8: drie losse regels (initialisatie/nulmeting/wissel) in plaats
    van één samengevoegd teller_terug__bool-getal, plus de langste aaneengesloten nulmeting-periode.
    """
    acc = rapport.RapportAccumulator()
    acc.n_rijen_measurements = 6
    acc.n_rijen_quality = 6
    acc.per_woning_rows = [
        {
            "home_id__str": "a", "dsmr": 6, "kamstrup": 0, "heatpump": 0, "boiler": 0,
            "eerste_kwartier": pd.Timestamp("2022-01-01", tz="UTC"),
            "laatste_kwartier": pd.Timestamp("2022-01-01", tz="UTC"), "n_stookseizoenen": 1,
        },
    ]
    acc.voeg_chunk_toe(
        pd.DataFrame(
            {
                "home_id__str": ["a"] * 6,
                "tijdstip_start": pd.date_range("2022-01-01", periods=6, freq="15min", tz="UTC"),
                "tijdstip_meting": pd.date_range("2022-01-01", periods=6, freq="15min", tz="UTC"),
                **{kolom: [1.0] * 6 for kolom in rapport._BRON_PROXYKOLOM.values()},
            }
        ),
        pd.DataFrame(
            {
                "home_id__str": ["a"] * 6,
                "bron_incompleet__bool": pd.array([False] * 6, dtype="boolean"),
                # rij 0: initialisatietelegram. rijen 1-3: een nulmeting van drie kwartier
                # aaneengesloten (de langste periode). rij 4: een echte wissel.
                "teller_initialisatie__bool": pd.array(
                    [True, False, False, False, False, False], dtype="boolean"
                ),
                "teller_nulmeting__bool": pd.array(
                    [False, True, True, True, False, False], dtype="boolean"
                ),
                "teller_wissel__bool": pd.array(
                    [False, False, False, False, True, False], dtype="boolean"
                ),
                "teller_terug__bool": pd.array(
                    [False, True, True, True, True, False], dtype="boolean"
                ),
                "teruglevering__bool": pd.array([False] * 6, dtype="boolean"),
                "teller_sprong__bool": pd.array([False] * 6, dtype="boolean"),
            }
        ),
    )

    tekst = rapport.build_report(pd.DataFrame({"home_id__str": ["a"]}), acc, is_steekproef=False)

    assert "`teller_initialisatie__bool`" in tekst
    assert "1 rijen bij 1 woningen" in tekst  # de initialisatierij
    assert "3 rijen bij 1 woningen" in tekst  # de nulmeting-rijen
    assert "Langste aaneengesloten periode bij één woning: 3 kwartieren" in tekst
    assert "1 rijen bij 1 woningen" in tekst  # de wisselrij (zelfde telling als initialisatie hier)


def test_rapport_zegt_het_als_de_weerdekking_niet_is_vastgelegd():
    tekst = rapport.build_report(
        pd.DataFrame({"home_id__str": ["a"]}), _accumulator_met_testdata(), is_steekproef=False
    )
    assert "weerdekking is voor deze run **niet vastgelegd**" in tekst
