# SPDX-License-Identifier: EUPL-1.2
"""De uitvoer van het minuutpad staat in Europe/Amsterdam, net als die van het kwartierpad.

Intern rekent het minuutpad in UTC. Deze toetsen leggen vast dat elke tijdkolom die op schijf komt
lokaal is, dat het instant daarbij niet verschuift, en dat dat ook door de oktoberwissel heen klopt,
waar lokaal het uur 02:00-02:59 twee keer voorkomt.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import minuut as m

# Rond de wissel van 29-10-2023 (01:00 UTC), met een gat van tien minuten dat de wissel overspant:
# 00:55-01:04 UTC ontbreekt, dus lokaal 02:55 zomertijd tot 02:04 wintertijd.
BEGIN = pd.Timestamp("2023-10-29 00:00", tz="UTC")


def _bron(map_: Path, home_id: str = "AAA") -> pd.Series:
    map_.mkdir(parents=True, exist_ok=True)
    tijd = pd.Series(pd.date_range(BEGIN, periods=150, freq="1min"))
    tijd = tijd[(tijd < BEGIN + pd.Timedelta(minutes=55)) | (tijd >= BEGIN + pd.Timedelta(minutes=65))]
    tijd = tijd.reset_index(drop=True)
    n = len(tijd)
    tabel = pa.table({
        "tijdstip_start": pa.array(tijd, type=pa.timestamp("ms", tz="UTC")),
        "heatpump_power": pa.array(np.linspace(0, 1500, n), type=pa.float32()),
        "heatpump_energy_eerste": pa.array(np.linspace(10.0, 10.5, n), type=pa.float32()),
    })
    pq.write_table(tabel, map_ / f"location_id={home_id}.parquet")
    return tijd


@pytest.mark.parametrize("streamend", [True, False])
def test_elke_tijdkolom_op_schijf_is_lokaal_en_het_instant_blijft(tmp_path, streamend):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    tijd = _bron(bron)
    m.run(bron, doel, streamend=streamend)

    metingen = pq.read_table(doel / "metingen" / "location_id=AAA.parquet")
    gaten = pq.read_table(doel / "gaten.parquet")
    homes = pq.read_table(doel / "homes_minuut.parquet")
    for tabel, kolommen in (
        (metingen, ["tijdstip_start"]),
        (gaten, ["begin", "eind"]),
        (homes, ["eerste_minuut", "laatste_minuut"]),
    ):
        uit = tabel.to_pandas()
        for kolom in kolommen:
            assert tabel.schema.field(kolom).type.tz == "Europe/Amsterdam", kolom
            assert str(uit[kolom].dt.tz) == "Europe/Amsterdam", kolom

    uit = metingen.to_pandas()
    pd.testing.assert_series_equal(
        uit["tijdstip_start"].dt.tz_convert("UTC"), tijd.astype("datetime64[ms, UTC]"), check_names=False
    )
    # ``begin`` is de eerste ontbrekende minuut en ``eind`` de eerste aanwezige erna. Lokaal ligt
    # het eind op de klok vóór het begin, maar het blijft tien minuten; daarom rekent alles op het
    # instant en niets op de wandklok.
    gat = gaten.to_pandas().iloc[0]
    assert gat["begin"].isoformat() == "2023-10-29T02:55:00+02:00"
    assert gat["eind"].isoformat() == "2023-10-29T02:05:00+01:00"
    assert gat["duur__min"] == 10
    home = homes.to_pandas().iloc[0]
    assert home["eerste_minuut"].isoformat() == "2023-10-29T02:00:00+02:00"
    assert home["laatste_minuut"].isoformat() == "2023-10-29T03:29:00+01:00"


def test_de_jsonl_bestanden_schrijven_lokale_tijd(tmp_path):
    """``gaten.jsonl`` en ``gaten.parquet`` schrijven hetzelfde tijdstip op dezelfde manier."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel)
    kenmerk = json.loads((doel / "kenmerken.jsonl").read_text(encoding="utf-8").splitlines()[0])
    gat = json.loads((doel / "gaten.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert kenmerk["eerste_minuut"] == "2023-10-29T02:00:00+02:00"
    assert gat["begin"] == "2023-10-29T02:55:00+02:00"
    assert gat["eind"] == "2023-10-29T02:05:00+01:00"
