# SPDX-License-Identifier: EUPL-1.2
"""datapackage.json wordt UIT DE CODE gebouwd (datapackage.py, uit de referentieschema's in
uitvoerschema.py). Deze tests bewaken dat de drie niet uit de pas kunnen lopen:

- elk veld in een referentieschema staat in het datapackage, en omgekeerd;
- beide pijplijnen schrijven op een kleine synthetische bron precies de referentieschema's, en
  zetten een ``datapackage.json`` in hun uitvoermap;
- de kopie in de repo-root is gelijk aan wat de code nu bouwt;
- het resultaat is structureel geldig volgens frictionless (overgeslagen als dat niet geïnstalleerd
  is).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import bron as bron_mod
from dph_preprocessing import datapackage, minuut, pipeline, uitvoerschema
from dph_preprocessing.chunking import UITVOER_CONTRACT_VERSIE
from dph_preprocessing.minuut import MINUUT_CONTRACT_VERSIE
from tests import test_bron

REPO_ROOT = Path(__file__).resolve().parents[1]

_SCHEMAS = {**uitvoerschema.KWARTIER_SCHEMAS, **uitvoerschema.MINUUT_SCHEMAS}


def _resources(pakket: dict) -> dict[str, dict]:
    return {r["name"]: r for r in pakket["resources"]}


# --- het datapackage zelf ---------------------------------------------------------------------------


@pytest.mark.parametrize("onderdeel", datapackage.ONDERDELEN)
def test_datapackage_bouwt_zonder_fouten(onderdeel):
    pakket = datapackage.bouw_datapackage(onderdeel)
    assert pakket["resources"]
    json.dumps(pakket)  # moet JSON-serialiseerbaar zijn


def test_elk_onderdeel_bevat_precies_zijn_eigen_tabellen():
    assert set(_resources(datapackage.bouw_datapackage("kwartier"))) == set(uitvoerschema.KWARTIER_SCHEMAS)
    assert set(_resources(datapackage.bouw_datapackage("minuut"))) == set(uitvoerschema.MINUUT_SCHEMAS)
    assert set(_resources(datapackage.bouw_datapackage("beide"))) == set(_SCHEMAS)


def test_elke_resource_heeft_precies_de_velden_van_zijn_schema_in_dezelfde_volgorde():
    resources = _resources(datapackage.bouw_datapackage("beide"))
    for naam, schema in _SCHEMAS.items():
        package_velden = [v["name"] for v in resources[naam]["schema"]["fields"]]
        assert package_velden == schema.names, (
            f"{naam}: schema en datapackage lopen uit de pas.\n"
            f"alleen in schema: {set(schema.names) - set(package_velden)}\n"
            f"alleen in datapackage: {set(package_velden) - set(schema.names)}"
        )


def test_veldtype_volgt_het_arrow_type():
    resources = _resources(datapackage.bouw_datapackage("beide"))
    for naam, schema in _SCHEMAS.items():
        for schema_veld, veld in zip(schema, resources[naam]["schema"]["fields"]):
            verwacht, _ = datapackage.table_schema_type(schema_veld.type)
            assert veld["type"] == verwacht, f"{naam}.{veld['name']}"


def test_elk_veld_heeft_een_eigen_beschrijving():
    """Geen enkel veld valt terug op de generieke verwijzing naar de datacatalogus."""
    for resource in datapackage.bouw_datapackage("beide")["resources"]:
        for veld in resource["schema"]["fields"]:
            assert veld.get("description"), f"{resource['name']}.{veld['name']} heeft geen description"
            assert not veld["description"].startswith("Zie docs/"), (
                f"{resource['name']}.{veld['name']} heeft alleen de generieke beschrijving"
            )


def test_elke_tabel_heeft_een_primary_key_met_onderbouwing():
    for resource in datapackage.bouw_datapackage("beide")["resources"]:
        sleutel = resource["schema"]["primaryKey"]
        assert sleutel, resource["name"]
        assert set(sleutel) <= {v["name"] for v in resource["schema"]["fields"]}, resource["name"]
        assert resource["primaryKeyOnderbouwing"], resource["name"]


def test_licentie_verwijst_naar_gebruiksvoorwaarden_geen_open_licentienaam():
    for onderdeel in datapackage.ONDERDELEN:
        licentie = datapackage.bouw_datapackage(onderdeel)["licenses"][0]
        assert licentie["path"] == "GEBRUIKSVOORWAARDEN.md"
        assert licentie["name"] not in ("cc-by-4.0", "cc-by-nc-4.0", "cc0-1.0", "odbl-1.0", "mit")
    assert (REPO_ROOT / "GEBRUIKSVOORWAARDEN.md").is_file()


def test_version_is_de_contractversie_van_het_pad():
    assert datapackage.bouw_datapackage("kwartier")["version"] == UITVOER_CONTRACT_VERSIE
    assert datapackage.bouw_datapackage("minuut")["version"] == MINUUT_CONTRACT_VERSIE
    beide = datapackage.bouw_datapackage("beide")["version"]
    assert UITVOER_CONTRACT_VERSIE in beide and MINUUT_CONTRACT_VERSIE in beide


def test_metingen_pad_blijft_patroon_ook_met_een_bestandentelling():
    """Een lijst als ``path`` betekent "plak aan elkaar", en dat is ongeldig voor Parquet; zie de
    moduledocstring van datapackage.py. Het aantal komt in de titel."""
    metingen = _resources(datapackage.bouw_datapackage("minuut", n_metingenbestanden=174))["metingen"]
    assert metingen["path"] == "metingen/location_id=*.parquet"
    assert "174 bestanden" in metingen["title"]


def test_alleen_de_overzichtskopie_noemt_een_uitvoerpad():
    for onderdeel in ("kwartier", "minuut"):
        assert all("uitvoerpad" not in r for r in datapackage.bouw_datapackage(onderdeel)["resources"])
    assert all(r["uitvoerpad"] for r in datapackage.bouw_datapackage("beide")["resources"])


def test_datapackage_in_de_repo_root_is_bij():
    """De kopie in de repo-root is gegenereerd, niet met de hand bijgehouden. Wijkt hij af, draai dan
    ``python -m dph_preprocessing.datapackage``."""
    op_schijf = json.loads((REPO_ROOT / datapackage.DATAPACKAGE_BESTANDSNAAM).read_text(encoding="utf-8"))
    assert op_schijf == datapackage.bouw_datapackage("beide")


@pytest.mark.parametrize("onderdeel", datapackage.ONDERDELEN)
def test_frictionless_structurele_validatie(onderdeel):
    """Structurele validatie (het JSON Schema-profiel van Data Package v1), zonder de Parquet-data
    zelf te lezen. Slaat zichzelf over als frictionless niet geïnstalleerd is (optionele
    dev-afhankelijkheid, zie pyproject.toml)."""
    frictionless = pytest.importorskip("frictionless")
    pakket = datapackage.bouw_datapackage(onderdeel, n_metingenbestanden=1)
    assert list(frictionless.Package.metadata_validate(pakket)) == []


# --- de pijplijnen schrijven wat het schema zegt ------------------------------------------------------


def _schrijf_dataset_zip(pad: Path) -> Path:
    """De fixture-zip van test_bron.py, met ``wrong_elec_measurement`` ingevuld: zonder die waarde
    kan ``tabellen.build_homes`` de kolom niet naar een categorie omzetten."""
    household = test_bron.HOUSEHOLD_CSV.replace("1,0\n", "1,0,0\n")
    with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(bron_mod.METADATA_BESTANDSNAAM, test_bron.METADATA_CSV)
        z.writestr(bron_mod.HOUSEHOLD_BESTANDSNAAM, household)
        z.writestr("dsmr.csv", test_bron.DSMR_CSV)
        z.writestr("kamstrup.csv", test_bron.KAMSTRUP_CSV)
        z.writestr("heatpump.csv", test_bron.HEATPUMP_CSV)
        z.writestr("boiler.csv", test_bron.BOILER_CSV)
        z.writestr("room.csv", test_bron.ROOM_CSV)
        z.writestr("knmi.csv", test_bron.KNMI_CSV)
    return pad


@pytest.fixture
def kwartierrun(tmp_path):
    zip_pad = _schrijf_dataset_zip(tmp_path / "dph-dataset.zip")
    uit = tmp_path / "processed"
    resultaat = pipeline.run(zip_pad, uit, docs_dir=None, skip_gaskwaliteit=True)
    return uit, resultaat


def test_kwartierrun_schrijft_precies_de_referentieschemas(kwartierrun):
    uit, _ = kwartierrun
    for naam, schema in uitvoerschema.KWARTIER_SCHEMAS.items():
        geschreven = pq.read_schema(uit / f"{naam}.parquet").remove_metadata()
        assert geschreven.equals(schema), f"{naam}:\ngeschreven {geschreven}\nreferentie {schema}"


def test_kwartierrun_schrijft_zijn_datapackage(kwartierrun):
    uit, resultaat = kwartierrun
    pad = uit / datapackage.DATAPACKAGE_BESTANDSNAAM
    assert resultaat["datapackage"] == pad
    assert json.loads(pad.read_text(encoding="utf-8")) == datapackage.bouw_datapackage("kwartier")
    for resource in datapackage.bouw_datapackage("kwartier")["resources"]:
        assert (uit / resource["path"]).is_file(), resource["path"]


_MINUUT_BEGIN = pd.Timestamp("2023-01-10 00:00", tz="UTC")


def _minuutbron(map_: Path, home_id: str = "AAA") -> None:
    """Eén locatie met alle 57 bronkolommen van de extractie (ontwerp-extractie.md §6) en een gat van
    tien minuten, zodat ``gaten.parquet`` en ``dekking.parquet`` ook geschreven worden."""
    map_.mkdir(parents=True, exist_ok=True)
    tijd = pd.Series(pd.date_range(_MINUUT_BEGIN, periods=200, freq="1min"))
    tijd = tijd[(tijd < _MINUUT_BEGIN + pd.Timedelta(minutes=100)) | (tijd >= _MINUUT_BEGIN + pd.Timedelta(minutes=110))]
    n = len(tijd)
    kolommen: dict[str, pa.Array] = {"tijdstip_start": pa.array(tijd.reset_index(drop=True), type=pa.timestamp("ms", tz="UTC"))}
    for bron in minuut.MOMENTAAN:
        kolommen[bron] = pa.array(np.full(n, 1.0), type=pa.float32())
    kolommen["heatpump_power"] = pa.array(np.linspace(0, 1500, n), type=pa.float32())
    kolommen["dsmr_u_L1"] = pa.array(np.full(n, 230.0), type=pa.float32())
    for i, bron in enumerate(minuut.TELLERS):
        stand = np.linspace(10.0 + i, 10.5 + i, n)
        kolommen[f"{bron}_eerste"] = pa.array(stand, type=pa.float32())
        kolommen[f"{bron}_laatste"] = pa.array(stand + 0.001, type=pa.float32())
    for kolom in minuut.OVERNEMEN:
        kolommen[kolom] = pa.array(np.full(n, 6), type=pa.uint16())
    pq.write_table(pa.table(kolommen), map_ / f"location_id={home_id}.parquet")


@pytest.fixture(params=[True, False], ids=["streamend", "volledig"])
def minuutrun(tmp_path, request):
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    _minuutbron(bron)
    samenvatting = minuut.run(bron, doel, streamend=request.param)
    assert samenvatting["mislukt"] == 0
    return doel


def test_minuutrun_schrijft_precies_de_referentieschemas(minuutrun):
    doel = minuutrun
    paden = {
        "metingen": doel / "metingen" / "location_id=AAA.parquet",
        "homes_minuut": doel / "homes_minuut.parquet",
        "gaten": doel / "gaten.parquet",
        "dekking": doel / "dekking.parquet",
    }
    assert set(paden) == set(uitvoerschema.MINUUT_SCHEMAS)
    for naam, schema in uitvoerschema.MINUUT_SCHEMAS.items():
        geschreven = pq.read_schema(paden[naam]).remove_metadata()
        assert geschreven.equals(schema), f"{naam}:\ngeschreven {geschreven}\nreferentie {schema}"


def test_minuutrun_schrijft_zijn_datapackage(minuutrun):
    doel = minuutrun
    pakket = json.loads((doel / datapackage.DATAPACKAGE_BESTANDSNAAM).read_text(encoding="utf-8"))
    assert pakket == datapackage.bouw_datapackage("minuut", n_metingenbestanden=1)
    for resource in pakket["resources"]:
        assert list(doel.glob(resource["path"])), resource["path"]


def test_frictionless_valideert_het_datapackage_van_een_concrete_run(kwartierrun, minuutrun):
    """De les van de WarmingUP-preprocessing (commit 47f7e74 daar): ook de kopie die een concrete run
    schrijft moet valideren, niet alleen de generieke."""
    frictionless = pytest.importorskip("frictionless")
    uit, _ = kwartierrun
    for pad in (uit / datapackage.DATAPACKAGE_BESTANDSNAAM, minuutrun / datapackage.DATAPACKAGE_BESTANDSNAAM):
        pakket = json.loads(pad.read_text(encoding="utf-8"))
        assert list(frictionless.Package.metadata_validate(pakket)) == [], pad
