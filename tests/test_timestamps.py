# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.timestamps: UTC-toekenning + kwartieruitlijning (ontwerp §2.1, §2.3).

De kamstrup-reeks uit ontwerp-preprocessing.md §2.1 is hier letterlijk als fixture overgenomen:
dat is de geverifieerde bevinding die deze module moet afhandelen, niet een verzonnen scenario.
"""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import timestamps
from dph_preprocessing.timestamps import SCHEEF_DREMPEL, assert_utc, naar_utc, resolve_timestamps

# ontwerp-preprocessing.md §2.1: "-ORiFQC6,2022-02-07T11:10:50 / 11:15:04 / 11:30:02", 11:45 ontbreekt.
SCHEVE_TIJDSTEMPELS = pd.Series(
    ["2022-02-07T11:10:50", "2022-02-07T11:15:04", "2022-02-07T11:30:02"]
)


def test_naar_utc_labelt_naief_als_utc():
    resultaat = naar_utc(pd.Series(["2022-02-07T11:10:50"]))
    # Resolutie (ns vs. us) hangt af van de pandas-versie; de tijdzone en het instant zijn het
    # contract, niet de opslagresolutie.
    assert isinstance(resultaat.dtype, pd.DatetimeTZDtype)
    assert str(resultaat.dtype.tz) == "UTC"
    assert resultaat.iloc[0] == pd.Timestamp("2022-02-07T11:10:50", tz="UTC")


def test_naar_utc_faalt_op_al_tz_aware_invoer():
    tz_aware = pd.Series([pd.Timestamp("2022-02-07T11:10:50", tz="UTC")])
    with pytest.raises(ValueError):
        naar_utc(tz_aware)


def test_assert_utc_faalt_op_naief():
    with pytest.raises(ValueError):
        assert_utc(pd.Series(pd.to_datetime(["2022-02-07T11:10:50"])))


def test_assert_utc_accepteert_utc():
    assert_utc(naar_utc(pd.Series(["2022-02-07T11:10:50"])))


def test_resolve_timestamps_floort_op_kwartier():
    result = resolve_timestamps(SCHEVE_TIJDSTEMPELS)

    verwacht_start = pd.to_datetime(
        ["2022-02-07T11:00:00", "2022-02-07T11:15:00", "2022-02-07T11:30:00"]
    ).tz_localize("UTC")
    assert list(result["tijdstip_start"]) == list(verwacht_start)

    # tijdstip_meting blijft de ORIGINELE, niet-uitgelijnde tijd.
    verwacht_meting = naar_utc(SCHEVE_TIJDSTEMPELS)
    assert list(result["tijdstip_meting"]) == list(verwacht_meting)


def test_resolve_timestamps_scheefheid_klopt():
    result = resolve_timestamps(SCHEVE_TIJDSTEMPELS)
    # 11:10:50 hoort bij het kwartier van 11:00 -> 10 min 50 s = 650 s scheef.
    assert result["scheefheid__s"].iloc[0] == pytest.approx(650.0)
    # 11:15:04 hoort bij 11:15 -> 4 s scheef.
    assert result["scheefheid__s"].iloc[1] == pytest.approx(4.0)
    # 11:30:02 -> 2 s scheef.
    assert result["scheefheid__s"].iloc[2] == pytest.approx(2.0)


def test_scheefheid_is_nooit_negatief():
    # Precies op de kwartiergrens: scheefheid moet 0 zijn, niet negatief.
    result = resolve_timestamps(pd.Series(["2022-02-07T11:00:00"]))
    assert result["scheefheid__s"].iloc[0] == 0.0


def test_scheef_drempel_is_vijf_minuten():
    # De drempel uit ontwerp §5 ("voorstel: 5 minuten") moet exact terugkomen als constante.
    assert SCHEEF_DREMPEL == pd.Timedelta(minutes=5)


def test_naar_lokale_tijdzone_zet_elke_tijdkolom_om_zonder_het_instant_te_raken():
    """De uitvoer is tz-aware Europe/Amsterdam, gelijk aan de IM3-zusterrepo (§12.10 daar).

    `tz_convert` verandert alleen het label, niet het moment: terugconverteren naar UTC moet
    exact hetzelfde opleveren. Een lokale tz-aware kolom draagt dus strikt meer informatie dan een
    kale UTC-kolom.
    """
    df = pd.DataFrame(
        {
            "home_id__str": ["a", "b"],
            "tijdstip_start": pd.to_datetime(["2023-06-01 12:00", "2023-12-01 12:00"], utc=True),
            "tijdstip_meting": pd.to_datetime(["2023-06-01 12:00:04", "2023-12-01 12:00:02"], utc=True),
            "waarde": [1.0, 2.0],
        }
    )
    uit = timestamps.naar_lokale_tijdzone(df)
    for kolom in ("tijdstip_start", "tijdstip_meting"):
        assert str(uit[kolom].dt.tz) == "Europe/Amsterdam"
        pd.testing.assert_series_equal(
            uit[kolom].dt.tz_convert("UTC"), df[kolom], check_names=False
        )
    # zomertijd +02:00, wintertijd +01:00 -- niet één vaste offset
    assert uit["tijdstip_start"].dt.hour.tolist() == [14, 13]
    # niet-tijdkolommen blijven ongemoeid
    assert uit["waarde"].tolist() == [1.0, 2.0]
    assert uit["home_id__str"].tolist() == ["a", "b"]


def test_naar_lokale_tijdzone_laat_een_frame_zonder_tijdkolommen_met_rust():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    pd.testing.assert_frame_equal(timestamps.naar_lokale_tijdzone(df), df)


def test_naar_lokale_tijdzone_arrow_overleeft_parquet_en_pandas(tmp_path):
    """Het arrow-type omzetten is niet genoeg: ``to_pandas`` gaat op de pandas-metadata af.

    Zonder die metadata bij te werken komt de kolom bij het teruglezen stil weer als UTC binnen,
    terwijl het parquet-schema Europe/Amsterdam zegt.
    """
    df = pd.DataFrame(
        {
            "tijdstip_start": pd.to_datetime(["2023-10-29 00:30", "2023-10-29 01:30"], utc=True)
            .astype("datetime64[ms, UTC]"),
            "naief": pd.to_datetime(["2023-01-01", "2023-01-02"]),
            "waarde": [1.0, 2.0],
        }
    )
    tabel = timestamps.naar_lokale_tijdzone_arrow(pa.Table.from_pandas(df, preserve_index=False))
    pad = tmp_path / "t.parquet"
    pq.write_table(tabel, pad)

    terug = pq.read_table(pad)
    assert terug.schema.field("tijdstip_start").type == pa.timestamp("ms", tz="Europe/Amsterdam")
    uit = terug.to_pandas()
    assert str(uit["tijdstip_start"].dt.tz) == "Europe/Amsterdam"
    # hetzelfde instant, en de wissel is zichtbaar: tweemaal 02:30, eerst +02:00 dan +01:00
    pd.testing.assert_series_equal(uit["tijdstip_start"].dt.tz_convert("UTC"), df["tijdstip_start"])
    assert [t.isoformat() for t in uit["tijdstip_start"]] == [
        "2023-10-29T02:30:00+02:00",
        "2023-10-29T02:30:00+01:00",
    ]
    # een naïeve kolom krijgt geen tijdzone opgedrongen, en de rest blijft ongemoeid
    assert uit["naief"].dt.tz is None
    assert uit["waarde"].tolist() == [1.0, 2.0]
