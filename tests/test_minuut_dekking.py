# SPDX-License-Identifier: EUPL-1.2
"""Tests voor `dph_preprocessing.minuut_dekking` (`ontwerp-interpolatie-en-dekking.md` §4, §5).

Alle scenario's bouwen hun eigen kleine `gaten`/`homes_minuut`-tabellen; er wordt geen echte
minuutdata gelezen, precies het punt van deze module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dph_preprocessing import minuut_dekking as d


def _tijd(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def _gaten(rijen: list[tuple[str, str, str, int]]) -> pd.DataFrame:
    """rijen = (home_id, begin, eind, duur__min)."""
    if not rijen:
        return pd.DataFrame(columns=["home_id__str", "begin", "eind", "duur__min"])
    return pd.DataFrame(
        [{"home_id__str": h, "begin": _tijd(b), "eind": _tijd(e), "duur__min": dd} for h, b, e, dd in rijen]
    )


def _homes(rijen: list[tuple[str, str, str]]) -> pd.DataFrame:
    """rijen = (home_id, eerste_minuut, laatste_minuut)."""
    return pd.DataFrame(
        [{"home_id__str": h, "eerste_minuut": _tijd(a), "laatste_minuut": _tijd(b)} for h, a, b in rijen]
    )


# --- gedekte_tijd__min -----------------------------------------------------------------------


def test_gedekte_tijd_zonder_gaten_is_de_hele_span():
    leeg = _gaten([])
    assert d.gedekte_tijd__min(leeg, span__min=100.0, max_gat__min=0.0) == 100.0


def test_gedekte_tijd_bij_k_nul_is_de_rauwe_aanwezigheid():
    """De sanity check uit de moduledocstring: k=0 telt geen enkel gat als overbrugd."""
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:15", 4)])
    # span 100 min, 4 ontbrekende minuten -> 96 aanwezig.
    assert d.gedekte_tijd__min(gaten, span__min=100.0, max_gat__min=0.0) == 96.0


def test_een_kort_gat_wordt_overbrugd_een_lang_gat_niet():
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:12", 1), ("A", "2024-01-01 01:00", "2024-01-01 02:00", 59)])
    # het gat van 1 minuut mag overbrugd bij k=1; het gat van 59 minuten niet.
    assert d.gedekte_tijd__min(gaten, span__min=200.0, max_gat__min=1.0) == 200.0 - 59
    # bij k=60 mogen beide overbrugd.
    assert d.gedekte_tijd__min(gaten, span__min=200.0, max_gat__min=60.0) == 200.0


# --- segmenten --------------------------------------------------------------------------------


def test_segmenten_zonder_gaten_is_een_enkel_stuk():
    stukken = d.segmenten(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 01:00"), _gaten([]), 0.0)
    assert stukken == [(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 01:00"))]


def test_segmenten_splitst_bij_een_niet_overbrugd_gat():
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:15", 4)])
    stukken = d.segmenten(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:30"), gaten, max_gat__min=0.0)
    assert stukken == [
        (_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:09")),
        (_tijd("2024-01-01 00:15"), _tijd("2024-01-01 00:30")),
    ]


def test_segmenten_smelt_samen_over_een_overbrugd_gat():
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:15", 4)])
    stukken = d.segmenten(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:30"), gaten, max_gat__min=4.0)
    assert stukken == [(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:30"))]


def test_segmenten_met_meerdere_gaten_gemengd_overbrugd_en_niet():
    gaten = _gaten([
        ("A", "2024-01-01 00:10", "2024-01-01 00:12", 1),   # overbrugbaar bij k=1
        ("A", "2024-01-01 01:00", "2024-01-01 02:00", 59),  # niet
    ])
    stukken = d.segmenten(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 03:00"), gaten, max_gat__min=1.0)
    assert stukken == [
        (_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:59")),
        (_tijd("2024-01-01 02:00"), _tijd("2024-01-01 03:00")),
    ]


# --- streak_bakken__min ------------------------------------------------------------------------


def test_streak_bakken_verdeelt_naar_de_juiste_bak():
    stukken = [
        (_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:14")),  # 15 min -> kwartier_tot_uur
        (_tijd("2024-02-01 00:00"), _tijd("2024-02-08 00:00")),  # >week -> meer_dan_maand niet, week_tot_maand
    ]
    bakken = d.streak_bakken__min(stukken)
    assert bakken["kwartier_tot_uur"] == pytest.approx(15.0)
    assert "week_tot_maand" in bakken


def test_streak_bakken_negeert_stukken_onder_de_kleinste_bak():
    stukken = [(_tijd("2024-01-01 00:00"), _tijd("2024-01-01 00:05"))]  # 6 minuten
    assert d.streak_bakken__min(stukken) == {}


# --- analyse_b5_minuut -------------------------------------------------------------------------


def test_b5_minuut_referentie_is_de_rauwe_aanwezigheid():
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 01:11", 60)])
    homes = _homes([("A", "2024-01-01 00:00", "2024-01-02 00:00")])
    b5 = d.analyse_b5_minuut(gaten, homes)
    assert set(b5["grootheid"]) == set(d.OVERBRUGGINGSGRENS__min)
    span = (pd.Timestamp("2024-01-02 00:00", tz="UTC") - pd.Timestamp("2024-01-01 00:00", tz="UTC")).total_seconds() / 60 + 1
    rij = b5[b5["grootheid"] == "temp_binnen__degC"].iloc[0]
    assert rij["totale_tijd__min"] == pytest.approx(span)
    assert rij["gedekte_tijd__min_referentie"] == pytest.approx(span - 60)
    # temp_binnen__degC heeft een grens van 60 min (§4): dit ene gat van 60 min wordt overbrugd.
    assert rij["drempel__min"] == 60.0
    assert rij["gedekte_tijd__min"] == pytest.approx(span)
    assert rij["aandeel_gedekt"] == pytest.approx(1.0)


def test_b5_minuut_gebruikt_de_grens_per_grootheid():
    """Hetzelfde gat van 2 minuten: overbrugbaar voor temp_aanvoer (grens 2), niet voor debiet (grens 1)."""
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:13", 2)])
    homes = _homes([("A", "2024-01-01 00:00", "2024-01-01 01:00")])
    b5 = d.analyse_b5_minuut(gaten, homes)
    aanvoer = b5[b5["grootheid"] == "temp_aanvoer__degC"].iloc[0]
    debiet = b5[b5["grootheid"] == "debiet__dm3_s_1"].iloc[0]
    assert aanvoer["aandeel_gedekt"] == pytest.approx(1.0)
    assert debiet["aandeel_gedekt"] < 1.0


# --- analyse_cop_combo -------------------------------------------------------------------------


def test_cop_combo_sluit_dode_kanalen_uit():
    gaten = _gaten([])
    homes = pd.DataFrame([
        {"home_id__str": "levend", "eerste_minuut": _tijd("2024-01-01"), "laatste_minuut": _tijd("2024-01-02"),
         "warmtepompkanaal_dood__bool": False},
        {"home_id__str": "dood", "eerste_minuut": _tijd("2024-01-01"), "laatste_minuut": _tijd("2024-01-02"),
         "warmtepompkanaal_dood__bool": True},
    ])
    combo = d.analyse_cop_combo(gaten, homes)
    assert set(combo["home_id__str"]) == {"levend"}
    assert (combo["drempel__min"] == 0.0).all()


def test_cop_combo_behandelt_ontbrekende_vlag_als_niet_dood():
    """Nullable boolean met NA (locatie zonder warmtepompteller) hoort niet stil uitgesloten te worden."""
    gaten = _gaten([])
    homes = pd.DataFrame([
        {"home_id__str": "A", "eerste_minuut": _tijd("2024-01-01"), "laatste_minuut": _tijd("2024-01-02"),
         "warmtepompkanaal_dood__bool": pd.NA},
    ])
    homes["warmtepompkanaal_dood__bool"] = homes["warmtepompkanaal_dood__bool"].astype("boolean")
    combo = d.analyse_cop_combo(gaten, homes)
    assert list(combo["home_id__str"]) == ["A"]


# --- bouw_dekking_tabel ------------------------------------------------------------------------


def test_dekking_tabel_bevat_referentie_en_gemeten_drempels_en_de_combo():
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:15", 4)])
    homes = _homes([("A", "2024-01-01 00:00", "2024-01-02 00:00")])
    homes["warmtepompkanaal_dood__bool"] = False
    tabel = d.bouw_dekking_tabel(gaten, homes)
    assert 0.0 in set(tabel["drempel__min"])
    assert set(d.OVERBRUGGINGSGRENS__min.values()) <= set(tabel["drempel__min"])
    assert "cop_combo__p_warmtepomp_en_q_geleverd" in set(tabel["kolom__str"])
    assert set(d.OVERBRUGGINGSGRENS__min) <= set(tabel["kolom__str"])


def test_dekking_tabel_heeft_elke_sleutel_een_keer():
    """Drempel 0 is de referentie én de gemeten grens van twee kolommen; hij hoort er één keer in."""
    gaten = _gaten([("A", "2024-01-01 00:10", "2024-01-01 00:15", 4)])
    homes = _homes([("A", "2024-01-01 00:00", "2024-01-02 00:00")])
    homes["warmtepompkanaal_dood__bool"] = False
    tabel = d.bouw_dekking_tabel(gaten, homes)
    assert not tabel.duplicated(["home_id__str", "kolom__str", "drempel__min"]).any()
