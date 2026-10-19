# SPDX-License-Identifier: EUPL-1.2
"""Een hervatting mag geen uitvoer van een ander contract laten staan.

Het minuutpad slaat elke locatie over waarvan het bestand al bestaat. Zonder contractversie zou een
run met nieuwe code de oude bestanden stil laten staan, en is aan de map niet te zien dat hij twee
soorten uitvoer bevat.
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


def _bron(map_: Path, home_id: str = "AAA", n: int = 40) -> None:
    map_.mkdir(parents=True, exist_ok=True)
    tijd = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    pq.write_table(
        pa.table({
            "tijdstip_start": pa.array(tijd),
            "heatpump_power": pa.array(np.linspace(0, 1500, n), type=pa.float32()),
        }),
        map_ / f"location_id={home_id}.parquet",
    )


def test_een_nieuwe_run_legt_het_contract_vast(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel)
    vastgelegd = json.loads((doel / m.CONTRACT_BESTAND).read_text(encoding="utf-8"))
    assert vastgelegd == {"contract": m.MINUUT_CONTRACT_VERSIE}


def test_hervatten_op_hetzelfde_contract_mag(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron, "AAA")
    m.run(bron, doel)
    _bron(bron, "BBB")
    samenvatting = m.run(bron, doel)
    assert samenvatting["gedaan"] == 1 and samenvatting["overgeslagen"] == 1


def test_hervatten_op_een_ander_contract_weigert(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel)
    (doel / m.CONTRACT_BESTAND).write_text(json.dumps({"contract": "oud"}), encoding="utf-8")
    with pytest.raises(m.AnderContract, match="oud"):
        m.run(bron, doel)


def test_metingen_zonder_contractbestand_tellen_als_ander_contract(tmp_path):
    """Zo ziet uitvoer eruit van code van vóór de controle; daaraan is niet te zien wat hij schreef."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel)
    (doel / m.CONTRACT_BESTAND).unlink()
    with pytest.raises(m.AnderContract, match="onbekend"):
        m.run(bron, doel)
    with pytest.raises(m.AnderContract):
        m.run(bron, doel, droog=True)


def test_een_droogloop_schrijft_geen_contract(tmp_path):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _bron(bron)
    m.run(bron, doel, droog=True)
    assert not (doel / m.CONTRACT_BESTAND).exists()
