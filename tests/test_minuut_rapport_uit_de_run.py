# SPDX-License-Identifier: EUPL-1.2
"""De run maakt zelf een kwaliteitsrapport.

Ontwerp §9 belooft `kwaliteit.md` als uitvoer, maar niets riep het aan: na de eerste volledige run van
17-09-2026 stond het er niet. Deze toetsen leggen vast dat dat nu wel gebeurt, en dat een mislukt
rapport de run niet alsnog laat vallen.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from dph_preprocessing import minuut as m


def _bron(map_: Path, home_id: str = "AAA", n: int = 40) -> Path:
    """Een minimale, streambare bronlocatie."""
    map_.mkdir(parents=True, exist_ok=True)
    tijd = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    tabel = pa.table({
        "tijdstip_start": pa.array(tijd),
        "heatpump_power": pa.array(np.linspace(0, 1500, n), type=pa.float32()),
        "heatpump_energy_eerste": pa.array(np.linspace(10.0, 10.5, n), type=pa.float32()),
    })
    pad = map_ / f"location_id={home_id}.parquet"
    pq.write_table(tabel, pad)
    return pad


def test_de_run_schrijft_kwaliteit_md(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel)
    rapport = doel / "kwaliteit.md"
    assert rapport.exists()
    tekst = rapport.read_text(encoding="utf-8")
    assert "Kwaliteit van de minuut-preprocessing" in tekst


def test_een_droogloop_schrijft_geen_rapport(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel, droog=True)
    assert not (doel / "kwaliteit.md").exists()


def test_het_rapport_wordt_ververst_bij_een_tweede_run(tmp_path):
    """Hervatten mag het rapport niet op de oude stand laten staan."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron, "AAA")
    m.run(bron, doel)
    eerste = (doel / "kwaliteit.md").read_text(encoding="utf-8")
    _bron(bron, "BBB")
    m.run(bron, doel)
    tweede = (doel / "kwaliteit.md").read_text(encoding="utf-8")
    assert "1 locaties" in eerste or "**1 locaties" in eerste
    assert tweede != eerste
    assert "2 locaties" in tweede


def test_een_mislukt_rapport_laat_de_run_niet_vallen(tmp_path, monkeypatch):
    """De metingen staan er al; het rapport is bijvangst en mag de uitkomst niet omgooien."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)

    def stuk(_doel):
        raise RuntimeError("rapport stuk")

    from dph_preprocessing import minuut_rapport

    monkeypatch.setattr(minuut_rapport, "bouw_rapport", stuk)
    samenvatting = m.run(bron, doel)

    assert samenvatting["gedaan"] == 1
    assert samenvatting["mislukt"] == 0
    assert not (doel / "kwaliteit.md").exists()
    assert (doel / "metingen" / "location_id=AAA.parquet").exists()


def test_de_run_schrijft_dekking_parquet_over_alle_locaties(tmp_path):
    """Ook na een hervatting dekt de tabel elke locatie in de map, niet alleen die van deze run."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron, "AAA")
    m.run(bron, doel)
    _bron(bron, "BBB")
    m.run(bron, doel)
    dekking = pq.read_table(doel / "dekking.parquet").to_pandas()
    assert set(dekking["home_id__str"]) == {"AAA", "BBB"}
    assert not dekking.duplicated(["home_id__str", "kolom__str", "drempel__min"]).any()
