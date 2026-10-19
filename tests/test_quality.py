# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.quality: de vijf vlaggen (ontwerp §5)."""

from __future__ import annotations

import pandas as pd
import pytest

from dph_preprocessing.quality import (
    bouw_tijdas,
    bron_incompleet_masker,
    or_vlaggen,
    scheef_masker,
)


def test_bouw_tijdas_vult_ontbrekend_kwartier():
    # ontwerp §2: het kwartier 11:15 ontbreekt (11:00 en 11:30 zijn wel gezien).
    gezien = pd.DataFrame(
        {
            "home_id__str": ["A", "A"],
            "tijdstip_start": pd.to_datetime(
                ["2022-02-07T11:00:00", "2022-02-07T11:30:00"]
            ).tz_localize("UTC"),
        }
    )
    tijdas = bouw_tijdas(gezien)
    assert len(tijdas) == 3  # 11:00, 11:15, 11:30
    verwacht = pd.to_datetime(
        ["2022-02-07T11:00:00", "2022-02-07T11:15:00", "2022-02-07T11:30:00"]
    ).tz_localize("UTC")
    assert list(tijdas.sort_values("tijdstip_start")["tijdstip_start"]) == list(verwacht)


def test_bouw_tijdas_per_woning_eigen_venster():
    gezien = pd.DataFrame(
        {
            "home_id__str": ["A", "B"],
            "tijdstip_start": pd.to_datetime(
                ["2022-01-01T00:00:00", "2023-06-01T00:00:00"]
            ).tz_localize("UTC"),
        }
    )
    tijdas = bouw_tijdas(gezien)
    # Elke woning heeft hier maar 1 waargenomen kwartier, dus haar eigen rooster is ook 1 rij.
    assert len(tijdas[tijdas["home_id__str"] == "A"]) == 1
    assert len(tijdas[tijdas["home_id__str"] == "B"]) == 1


def test_scheef_masker():
    scheefheid__s = pd.Series([0.0, 301.0, 299.0, None])
    result = scheef_masker(scheefheid__s, drempel=pd.Timedelta(minutes=5))
    assert result.tolist() == [False, True, False, pd.NA]


def test_or_vlaggen_combineert():
    a = pd.Series([True, False, pd.NA], dtype="boolean")
    b = pd.Series([False, False, pd.NA], dtype="boolean")
    result = or_vlaggen(a, b)
    assert result.tolist() == [True, False, pd.NA]


def test_or_vlaggen_na_telt_niet_als_true_maar_wel_als_geen_van_beide_iets_weet():
    a = pd.Series([pd.NA, True], dtype="boolean")
    b = pd.Series([False, pd.NA], dtype="boolean")
    result = or_vlaggen(a, b)
    # rij 0: a=NA, b=False -> "niets wat True zegt", maar niet ALLE inputs NA (b is False) -> False
    assert result.iloc[0] == False
    # rij 1: a=True, b=NA -> True (een van de twee zegt wel degelijk True)
    assert result.iloc[1] == True


def test_bron_incompleet_masker():
    dsmr = pd.Series([True, True, False])
    kamstrup = pd.Series([True, False, False])
    heatpump = pd.Series([True, True, False])
    boiler = pd.Series([True, True, False])
    result = bron_incompleet_masker(dsmr, kamstrup, heatpump, boiler)
    assert result.tolist() == [False, True, True]
