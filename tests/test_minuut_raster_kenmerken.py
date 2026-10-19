# SPDX-License-Identifier: EUPL-1.2
"""Tests voor `raster_<naam>__W` en `raster_breuk_<naam>__bool` in `homes_minuut.parquet`.

Hoort bij `ontwerp-preprocessing-minuut-geheugen.md` §5.5 en §6.7. De rekenregels zelf zijn al
getoetst in `test_minuut_raster.py`, dus deze module toetst alleen de INTEGRATIE: komen de twee
kolommen op de juiste naam in `kenmerken` terecht, uit de RUWE stand die deze pas zelf al aan het
lezen is, en blijven het volledige pad en het streamende pad daarin gelijk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import minuut


def _minuten(n: int, start: str = "2023-01-01 00:00") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="1min", tz="UTC"))


def _ruw(tijdstip_start: pd.Series, **kolommen) -> pd.DataFrame:
    df = pd.DataFrame({"tijdstip_start": tijdstip_start})
    for naam, waarden in kolommen.items():
        df[naam] = waarden
    return df


def _schrijf_bron(pad, tijdstip_start: pd.Series, **kolommen) -> None:
    velden = [("tijdstip_start", pa.timestamp("ms", tz="UTC"))]
    data = [pa.array(tijdstip_start, type=pa.timestamp("ms", tz="UTC"))]
    for naam, waarden in kolommen.items():
        soort = pa.uint16() if naam in minuut.OVERNEMEN else pa.float32()
        velden.append((naam, soort))
        data.append(pa.array(waarden, type=soort))
    tabel = pa.Table.from_arrays(data, schema=pa.schema(velden))
    pq.write_table(tabel, pad, row_group_size=1)


# --- de kern: raster_<naam>__W en raster_breuk_<naam>__bool op de juiste naam --------------------


def test_dsmr_teller_met_een_rasterbreuk_wordt_gevonden():
    """15.000 naar 20.000 passeert 16.384 (test_minuut_raster.test_breuk_wordt_gevonden_waar_hij_zit)."""
    ruw = _ruw(_minuten(2), dsmr_e_consumed_low_eerste=np.array([15_000.0, 20_000.0], dtype="float64"))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert kenmerken["raster_breuk_e_import_laag_cum__bool"] is True
    # 20.000 zit in [16.384, 32.768): e=14, raster 2**-9 kWh = 0,001953125 kWh -> 117,1875 W/min.
    assert kenmerken["raster_e_import_laag_cum__W"] == pytest.approx(117.1875)


def test_dsmr_teller_zonder_rasterbreuk_binnen_een_octaaf():
    ruw = _ruw(_minuten(2), dsmr_e_consumed_low_eerste=np.array([17_000.0, 30_000.0], dtype="float64"))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert kenmerken["raster_breuk_e_import_laag_cum__bool"] is False


def test_kamstrup_krijgt_geen_breukoordeel_maar_wel_een_raster():
    """De metertik van de Kamstrup is onbekend (test_minuut_raster.test_kamstrup_laat_...leeg)."""
    ruw = _ruw(_minuten(2), kamstrup_e_thermal_system_eerste=np.array([50.0, 120.362], dtype="float64"))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert kenmerken["raster_breuk_q_geleverd_cum__bool"] is pd.NA
    assert kenmerken["raster_q_geleverd_cum__W"] == pytest.approx(127.156, rel=1e-3)


def test_gas_krijgt_geen_watt_maar_wel_een_breukoordeel():
    """Volume is geen energie (test_minuut_raster.test_gas_krijgt_geen_watt); de breuktoets werkt wel."""
    ruw = _ruw(_minuten(2), dsmr_v_gas_consumed_eerste=np.array([15_000.0, 20_000.0], dtype="float64"))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert np.isnan(kenmerken["raster_g_gebruik_cum__W"])
    assert kenmerken["raster_breuk_g_gebruik_cum__bool"] is True


def test_een_teller_die_op_nul_begint_krijgt_geen_valse_breuk():
    """`heatpump_energy` staat legitiem op 0,0 aan het begin; dat nulpunt mag geen breuk verzinnen."""
    ruw = _ruw(_minuten(2), heatpump_energy_eerste=np.array([0.0, 7_844.46], dtype="float64"))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert kenmerken["raster_breuk_e_warmtepomp_cum__bool"] is False
    assert kenmerken["raster_e_warmtepomp_cum__W"] == pytest.approx(29.296875)


def test_afwezige_teller_levert_geen_rasterkenmerk():
    ruw = _ruw(_minuten(2), heatpump_power=np.array([500.0, 500.0]))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert not any(k.startswith("raster_") for k in kenmerken)


# --- gelijkheid met het streamende pad -----------------------------------------------------------


def test_streamend_pad_geeft_dezelfde_rasterkenmerken(tmp_path):
    """De rasterkenmerken horen precies zo mee te lopen als de rest van de kenmerken."""
    n = 20
    stand = np.linspace(15_000.0, 20_000.0, n).astype("float32")
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, _minuten(n), dsmr_e_consumed_low_eerste=stand)

    ruw = pq.read_table(pad).to_pandas(types_mapper=minuut._types_mapper)
    volledig = minuut.verwerk_locatie(ruw, "A")
    for batchgrootte in (1, 3, 7, n):
        streamend = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=batchgrootte)
        assert streamend.kenmerken["raster_breuk_e_import_laag_cum__bool"] == (
            volledig.kenmerken["raster_breuk_e_import_laag_cum__bool"]
        )
        assert streamend.kenmerken["raster_e_import_laag_cum__W"] == pytest.approx(
            volledig.kenmerken["raster_e_import_laag_cum__W"]
        )


# --- de uint16-reparatie geldt ook op het volledige pad, niet alleen het streamende --------------


def test_het_volledige_pad_houdt_uint16_vast_bij_een_gat(tmp_path):
    """§5.5: dezelfde reparatie hoort te gelden voor `_verwerk` met `streamend=False`."""
    n_g1 = pa.array([12, 12, None, 12], type=pa.uint16())
    velden = pa.schema(
        [("tijdstip_start", pa.timestamp("ms", tz="UTC")),
         ("heatpump_energy_eerste", pa.float32()), ("n_g1", pa.uint16())]
    )
    tabel = pa.Table.from_arrays(
        [pa.array(_minuten(4), type=pa.timestamp("ms", tz="UTC")),
         pa.array(np.arange(4, dtype="float32"), type=pa.float32()), n_g1],
        schema=velden,
    )
    pad = tmp_path / "location_id=A.parquet"
    pq.write_table(tabel, pad)

    uitkomst = minuut._verwerk(pad, "A", streamend=False)
    assert isinstance(uitkomst.metingen, pd.DataFrame)
    assert uitkomst.metingen["n_g1"].dtype == pd.UInt16Dtype()


# --- de kenmerkentabel krijgt een nette dtype, ook als een locatie een teller mist ---------------


def test_homes_minuut_krijgt_nullable_boolean_ook_bij_ontbrekende_tellers(tmp_path):
    """Eén locatie zonder DSMR (§6.6a: vier van de 174 missen die volledig) mag de andere niet naar
    een object-kolom duwen."""
    bron, doel = tmp_path / "bron", tmp_path / "doel"
    bron.mkdir()
    _schrijf_bron(
        bron / "location_id=AAA.parquet",
        _minuten(4),
        dsmr_e_consumed_low_eerste=np.array([15_000.0, 16_000.0, 17_000.0, 20_000.0], dtype="float32"),
    )
    _schrijf_bron(
        bron / "location_id=BBB.parquet",
        _minuten(4),
        heatpump_power=np.array([500.0, 500.0, 500.0, 500.0], dtype="float32"),
    )
    minuut.run(bron, doel)
    tabel = pq.read_table(doel / "homes_minuut.parquet")
    assert pa.types.is_boolean(tabel.schema.field("raster_breuk_e_import_laag_cum__bool").type)
    homes = tabel.to_pandas().set_index("home_id__str")
    assert homes.loc["AAA", "raster_breuk_e_import_laag_cum__bool"] == True  # noqa: E712
    assert pd.isna(homes.loc["BBB", "raster_breuk_e_import_laag_cum__bool"])
