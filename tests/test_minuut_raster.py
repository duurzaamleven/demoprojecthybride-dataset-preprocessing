# SPDX-License-Identifier: EUPL-1.2
"""Toetsen bij :mod:`dph_preprocessing.minuut_raster`.

Deze tests pinnen de getallen vast die in ``ontwerp-preprocessing-minuut-geheugen.md`` §5.3 en §6
staan. Dat is opzet: die getallen dragen de conclusie dat het minuutrooster een probleem heeft dat
het kwartierrooster niet heeft, en een conclusie die nergens wordt nagerekend verschuift ongemerkt.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import minuut_raster as mr


# --- het raster zelf ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stand", "verwacht"),
    [
        (10_778.457, 2.0**-10),   # §5.3, de gemeten locatie ZzY3cd3h
        (12_869.0, 2.0**-10),     # §6.1, de mediane woning: net op de grens
        (36_326.0, 2.0**-8),      # §6.1, het 95e percentiel
        (63_766.0, 2.0**-8),      # §6.1, de hoogste stand in de set
        (7_844.46, 2.0**-11),     # heatpump_energy van ZzY3cd3h
        (118.931, 2.0**-17),      # boiler_energy van ZzY3cd3h
        (120.362, 2.0**-17),      # kamstrup_e_thermal_system van ZzY3cd3h, in GJ
    ],
)
def test_raster_komt_overeen_met_de_formule(stand, verwacht):
    assert mr.raster(stand) == pytest.approx(verwacht)
    # en met 2**(floor(log2 s) - 23), de formule uit het ontwerp
    assert mr.raster(stand) == pytest.approx(2.0 ** (math.floor(math.log2(stand)) - 23))


@pytest.mark.parametrize("stand", [0.0, -1.0, float("nan"), float("inf")])
def test_raster_is_nan_waar_hij_geen_betekenis_heeft(stand):
    assert math.isnan(mr.raster(stand))


def test_raster_op_een_macht_van_twee_pakt_de_stap_erboven():
    """Op 16.384 begint het grovere raster; numpy kent dat randgeval en de formule ook."""
    assert mr.raster(16_384.0) == pytest.approx(2.0**-9)
    assert mr.raster(16_383.9) == pytest.approx(2.0**-10)


# --- van raster naar watt ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stand", "bron", "verwacht__W"),
    [
        (10_778.457, "dsmr_e_consumed_low", 58.59375),   # §5.3
        (12_869.0, "dsmr_e_consumed_low", 58.59375),     # §6.2, mediaan
        (36_326.0, "dsmr_e_consumed_low", 234.375),      # §6.2, p95
        (7_844.46, "heatpump_energy", 29.296875),        # §5.3
        (118.931, "boiler_energy", 0.457763671875),      # §5.3
        (120.362, "kamstrup_e_thermal_system", 127.156), # §5.3, 7.629 J per minuut
    ],
)
def test_raster_in_watt(stand, bron, verwacht__W):
    gekregen = mr.raster__W(stand, mr.NAAR_J[bron])
    assert gekregen == pytest.approx(verwacht__W, rel=1e-4)


def test_gas_krijgt_geen_watt():
    """Volume is geen energie; een watt zou hier een calorische waarde veronderstellen."""
    assert math.isnan(mr.raster__W(2_982.54, mr.NAAR_J["dsmr_v_gas_consumed"]))
    # het raster zelf is er wel, in m³ per minuut
    assert mr.raster(2_982.54) == pytest.approx(2.0**-12)


def test_het_raster_schaalt_met_een_over_delta_t():
    """De kern van §6.2: vijftien keer zo lang interval is vijftien keer zo fijne trap."""
    minuut = mr.raster__W(36_326.0, mr.NAAR_J["dsmr_e_consumed_low"], interval__s=60.0)
    kwartier = mr.raster__W(36_326.0, mr.NAAR_J["dsmr_e_consumed_low"], interval__s=900.0)
    assert minuut / kwartier == pytest.approx(15.0)
    assert kwartier == pytest.approx(15.625)


# --- de drempel en de rasterbreuk --------------------------------------------------------------


def test_drempelstand_bij_een_metertik_van_een_milli():
    """Boven 16.384 haalt het float32-raster de metertik van 0,001 en vallen standen samen."""
    assert mr.drempelstand(0.001) == 16_384.0
    assert mr.raster(16_384.0) >= 0.001
    assert mr.raster(16_383.0) < 0.001


def test_machten_van_twee_telt_alleen_de_passages_die_ertoe_doen():
    # van 15.000 naar 40.000 passeert 16.384 en 32.768
    assert mr.machten_van_twee(15_000.0, 40_000.0, 16_384.0) == [16_384.0, 32_768.0]
    # van 1 naar 8.000 passeert een hoop machten van twee, maar geen enkele boven de drempel
    assert mr.machten_van_twee(1.0, 8_000.0, 16_384.0) == []
    # binnen één octaaf gebeurt er niets
    assert mr.machten_van_twee(17_000.0, 30_000.0, 16_384.0) == []


def test_breuk_wordt_gevonden_waar_hij_zit():
    post = mr.beoordeel_teller("dsmr_e_consumed_low", 15_000.0, 20_000.0)
    assert post["raster_breuk__bool"] is True
    assert post["n_verdubbelingen"] == 1
    assert post["raster_boven_metertik__bool"] is True


def test_geen_breuk_binnen_een_octaaf():
    post = mr.beoordeel_teller("dsmr_e_consumed_low", 17_000.0, 30_000.0)
    assert post["raster_breuk__bool"] is False
    assert post["n_verdubbelingen"] == 0
    assert post["raster_boven_metertik__bool"] is True


def test_teller_onder_de_drempel_is_nog_fijner_dan_de_meter():
    post = mr.beoordeel_teller("dsmr_e_consumed_low", 2_000.0, 10_778.457)
    assert post["raster_boven_metertik__bool"] is False
    assert post["raster_breuk__bool"] is False


def test_een_teller_die_op_nul_begint_krijgt_geen_valse_breuk():
    """``heatpump_energy`` staat legitiem op 0,0 aan het begin van de meetperiode.

    Dat nulpunt zegt niets over het raster van de reeks; zonder ONTWAAKT_BOVEN zou elke zulke teller
    tientallen machten van twee 'passeren' en dus altijd als breuk gemeld worden.
    """
    post = mr.beoordeel_teller("heatpump_energy", 0.0, 7_844.46)
    assert post["raster_breuk__bool"] is False
    assert post["raster__W"] == pytest.approx(29.296875)


def test_kamstrup_laat_het_oordeel_leeg_want_de_metertik_is_onbekend():
    post = mr.beoordeel_teller("kamstrup_e_thermal_system", 0.0, 120.362)
    assert post["raster_boven_metertik__bool"] is pd.NA
    assert post["raster_breuk__bool"] is pd.NA
    assert post["raster__W"] == pytest.approx(127.156, rel=1e-4)


# --- de scan over bestanden --------------------------------------------------------------------


def _schrijf_locatie(map_, home_id: str, standen: dict[str, tuple[float, float]], rijen: int = 4):
    """Een minimaal bestand met alleen de tellerkolommen, in twee row groups.

    Twee row groups en niet één, want de scan moet de statistieken over de groepen samenvoegen; een
    bestand met één groep zou die fout niet aan het licht brengen.
    """
    kolommen: dict[str, pa.Array] = {}
    for bron, (lo, hi) in standen.items():
        reeks = list(np.linspace(lo, hi, rijen))
        kolommen[f"{bron}_eerste"] = pa.array(reeks, type=pa.float32())
        kolommen[f"{bron}_laatste"] = pa.array(reeks, type=pa.float32())
    tabel = pa.table(kolommen)
    pad = map_ / f"location_id={home_id}.parquet"
    pq.write_table(tabel, pad, row_group_size=max(1, rijen // 2))
    return pad


def test_standen_uit_footer_voegt_de_row_groups_samen(tmp_path):
    pad = _schrijf_locatie(tmp_path, "AAA", {"dsmr_e_consumed_low": (15_000.0, 20_000.0)}, rijen=8)
    grenzen = mr._standen_uit_footer(pad)
    lo, hi = grenzen["dsmr_e_consumed_low"]
    assert lo == pytest.approx(15_000.0, rel=1e-6)
    assert hi == pytest.approx(20_000.0, rel=1e-6)


def _schrijf_reeks(map_, home_id: str, bron: str, waarden_per_groep: list[list[float]]):
    """Eén bronkolom (``<bron>_eerste``), met een expliciete rij-naar-row-group-indeling."""
    reeks = [w for groep in waarden_per_groep for w in groep]
    tabel = pa.table({f"{bron}_eerste": pa.array(reeks, type=pa.float32())})
    pad = map_ / f"location_id={home_id}.parquet"
    grootste_groep = max(len(g) for g in waarden_per_groep)
    # Alle groepen op dezelfde grootte forceren gaat niet met één row_group_size; schrijf daarom
    # in aparte writer-aanroepen per groep zodat de indeling exact is die de test vraagt.
    with pq.ParquetWriter(pad, tabel.schema) as schrijver:
        i = 0
        for groep in waarden_per_groep:
            deel = tabel.slice(i, len(groep))
            schrijver.write_table(deel)
            i += len(groep)
    return pad


def test_eerste_laatste_uit_footer_pakt_het_min_van_de_eerste_en_max_van_de_laatste_groep(tmp_path):
    """Nagebouwd op `RHON9wor`'s echte `dsmr_e_consumed_low`: een sentinelwaarde in de eerste
    minuten (8969,994), gevolgd door de echte reeks vanaf 5619,978 tot 8951,071 (zie
    `docs/analyse-bevindingen-minuut.md`, de vergelijking met het kwartierpad). Het globale min/max
    van `_standen_uit_footer` zou hier 8969,994 als stand pakken; deze functie niet.
    """
    pad = _schrijf_reeks(
        tmp_path, "AAA", "dsmr_e_consumed_low",
        [[8969.994, 8969.994, 5619.978, 5620.5, 5621.0], [8950.0, 8951.019, 8951.071]],
    )
    eerste, laatste = mr.eerste_laatste_uit_footer(pad)["dsmr_e_consumed_low"]
    assert eerste == pytest.approx(5619.978, rel=1e-5)
    assert laatste == pytest.approx(8951.071, rel=1e-5)


def test_eerste_laatste_uit_footer_op_een_normale_monotone_reeks(tmp_path):
    pad = _schrijf_reeks(tmp_path, "AAA", "heatpump_energy", [[10.0, 11.0, 12.0], [13.0, 14.0]])
    eerste, laatste = mr.eerste_laatste_uit_footer(pad)["heatpump_energy"]
    assert eerste == pytest.approx(10.0, rel=1e-6)
    assert laatste == pytest.approx(14.0, rel=1e-6)


def test_eerste_laatste_uit_footer_negeert_afwezige_tellers(tmp_path):
    pad = _schrijf_reeks(tmp_path, "AAA", "heatpump_energy", [[1.0, 2.0]])
    grenzen = mr.eerste_laatste_uit_footer(pad)
    assert set(grenzen) == {"heatpump_energy"}


def test_scan_levert_een_regel_per_locatie_per_teller(tmp_path):
    _schrijf_locatie(tmp_path, "AAA", {
        "dsmr_e_consumed_low": (15_000.0, 20_000.0),
        "heatpump_energy": (0.0, 7_844.46),
    })
    _schrijf_locatie(tmp_path, "BBB", {"dsmr_e_consumed_low": (2_000.0, 9_000.0)})

    df = mr.scan(tmp_path)
    assert len(df) == 3
    assert set(df["home_id__str"]) == {"AAA", "BBB"}

    aaa = df[(df["home_id__str"] == "AAA") & (df["bronkolom__str"] == "dsmr_e_consumed_low")].iloc[0]
    assert aaa["raster_breuk__bool"]
    bbb = df[df["home_id__str"] == "BBB"].iloc[0]
    assert not bbb["raster_boven_metertik__bool"]


def test_scan_slaat_een_onleesbaar_bestand_over_en_gaat_door(tmp_path):
    _schrijf_locatie(tmp_path, "AAA", {"dsmr_e_consumed_low": (15_000.0, 20_000.0)})
    (tmp_path / "location_id=KAPOT.parquet").write_bytes(b"dit is geen parquet")
    df = mr.scan(tmp_path)
    assert list(df["home_id__str"]) == ["AAA"]


def test_scan_op_een_lege_map_geeft_een_leeg_frame(tmp_path):
    assert mr.scan(tmp_path).empty


def test_samenvatting_noemt_de_breuken(tmp_path):
    _schrijf_locatie(tmp_path, "AAA", {"dsmr_e_consumed_low": (15_000.0, 20_000.0)})
    tekst = mr.vat_samen(mr.scan(tmp_path))
    assert "rasterbreuk" in tekst.lower()
    assert "AAA" in tekst
    assert "e_import_laag_cum__kWh" in tekst


def test_samenvatting_op_leeg():
    assert "Geen tellerdata" in mr.vat_samen(pd.DataFrame())


def test_samenvatting_schrijft_getallen_nederlands(tmp_path):
    """Punt per duizendtal, komma als decimaalteken, en een streepje waar niets staat.

    Gas heeft geen raster in watt, dus die regel hoort een streepje te tonen en niet "nan".
    """
    _schrijf_locatie(tmp_path, "AAA", {
        "dsmr_e_consumed_low": (15_000.0, 40_000.0),
        "dsmr_v_gas_consumed": (1_750.0, 2_982.0),
    })
    tekst = mr.vat_samen(mr.scan(tmp_path))
    assert "40.000,0" in tekst
    assert "15.000,0" in tekst
    assert "40,000.0" not in tekst
    assert "nan" not in tekst.lower()
