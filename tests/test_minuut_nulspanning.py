# SPDX-License-Identifier: EUPL-1.2
"""Een spanning van exact 0,0 is afwezig, niet onplausibel.

Achtergrond: de DSMR-spanningen melden op meters die geen spanning rapporteren een harde 0,0 op alle
drie de fasen tegelijk. De plausibiliteitstoets van ontwerp §6 rekende die minuten als onplausibel,
waardoor ``onplausibel__bool`` op 29,8 % van alle minuten stond en vooral markeerde wélke meter geen
spanning levert. Zie :data:`dph_preprocessing.minuut.NUL_IS_AFWEZIG`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dph_preprocessing import minuut as m


def _ruw(spanningen: list[float], n: int | None = None) -> pd.DataFrame:
    """Minimale ruwe tabel met alleen een tijdas en de drie DSMR-spanningen."""
    n = n if n is not None else len(spanningen)
    tijd = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "tijdstip_start": tijd,
        "dsmr_u_L1": np.array(spanningen, dtype="float32"),
        "dsmr_u_L2": np.array(spanningen, dtype="float32"),
        "dsmr_u_L3": np.array(spanningen, dtype="float32"),
    })


# --- de kern van de wijziging ------------------------------------------------------------------


def test_nul_volt_zet_de_vlag_niet():
    uit = m.verwerk_locatie(_ruw([0.0, 0.0, 0.0]), "X").metingen
    assert not uit["onplausibel__bool"].any()


def test_nul_volt_wordt_wel_nan():
    """De waarde verdwijnt nog steeds: 0 V is geen meting, dus hij hoort niet in de data."""
    uit = m.verwerk_locatie(_ruw([0.0, 230.0, 0.0]), "X").metingen
    assert uit["u_L1__V"].isna().tolist() == [True, False, True]


def test_een_echte_overschrijding_zet_de_vlag_nog_steeds():
    """100 V is geen sentinel maar een onmogelijke netspanning, en moet blijven opvallen."""
    uit = m.verwerk_locatie(_ruw([100.0, 230.0, 400.0]), "X").metingen
    assert uit["onplausibel__bool"].tolist() == [True, False, True]


def test_plausibele_spanning_blijft_ongemoeid():
    uit = m.verwerk_locatie(_ruw([230.0, 231.5, 229.0]), "X").metingen
    assert not uit["onplausibel__bool"].any()
    assert uit["u_L1__V"].notna().all()


def test_nan_blijft_afwezig_en_zet_de_vlag_niet():
    uit = m.verwerk_locatie(_ruw([float("nan"), 230.0]), "X").metingen
    assert not uit["onplausibel__bool"].any()
    assert bool(uit["u_L1__V"].isna().iloc[0])


def test_n_onplausibel_in_de_kenmerken_telt_mee():
    uitkomst = m.verwerk_locatie(_ruw([0.0, 100.0, 230.0]), "X")
    assert uitkomst.kenmerken["n_onplausibel"] == 1


# --- de uitzondering geldt alleen waar hij hoort ------------------------------------------------


def test_alleen_de_drie_dsmr_fasen_staan_in_de_uitzondering():
    assert m.NUL_IS_AFWEZIG == frozenset({"u_L1__V", "u_L2__V", "u_L3__V"})


def test_een_andere_spanningskolom_vlagt_nul_wel():
    """`u_warmtepomp__V` staat bewust niet in de uitzondering; daar is 0 V nog steeds verdacht."""
    tijd = pd.date_range("2024-01-01", periods=2, freq="1min", tz="UTC")
    ruw = pd.DataFrame({"tijdstip_start": tijd,
                        "heatpump_voltage": np.array([0.0, 230.0], dtype="float32")})
    uit = m.verwerk_locatie(ruw, "X").metingen
    assert uit["onplausibel__bool"].tolist() == [True, False]


def test_een_nul_op_een_vermogenskolom_is_gewoon_geldig():
    """Nul watt is een normale meting; die valt sowieso binnen de grenzen en raakt niets."""
    tijd = pd.date_range("2024-01-01", periods=2, freq="1min", tz="UTC")
    ruw = pd.DataFrame({"tijdstip_start": tijd,
                        "heatpump_power": np.array([0.0, 1500.0], dtype="float32")})
    uit = m.verwerk_locatie(ruw, "X").metingen
    assert not uit["onplausibel__bool"].any()
    assert uit["p_warmtepomp_gemeten__W"].tolist() == [0.0, 1500.0]


# --- de hulpfunctie zelf -----------------------------------------------------------------------


@pytest.mark.parametrize("naam", sorted(m.NUL_IS_AFWEZIG))
def test_hulpfunctie_haalt_de_nul_eruit(naam):
    waarde = np.array([0.0, 100.0, 230.0])
    buiten = np.array([True, True, False])
    assert m._telt_als_onplausibel(naam, waarde, buiten).tolist() == [False, True, False]


def test_hulpfunctie_laat_andere_kolommen_ongemoeid():
    waarde = np.array([0.0, 100.0, 230.0])
    buiten = np.array([True, True, False])
    assert m._telt_als_onplausibel("u_ketel__V", waarde, buiten).tolist() == [True, True, False]


# --- beide paden moeten hetzelfde doen ----------------------------------------------------------


def test_het_streamende_pad_doet_hetzelfde(tmp_path):
    """De kruistoets die telt: de wijziging zit in gedeelde code, dus beide paden schuiven mee."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    spanningen = [0.0, 230.0, 100.0, 0.0, 231.0, 400.0, 0.0, 229.5]
    ruw = _ruw(spanningen)
    pad = tmp_path / "location_id=X.parquet"
    pq.write_table(pa.Table.from_pandas(ruw, preserve_index=False), pad, row_group_size=3)

    verwacht = m.verwerk_locatie(ruw.copy(), "X").metingen["onplausibel__bool"].tolist()
    assert verwacht == [False, False, True, False, False, True, False, False]

    # Het streamende pad levert een arrow-tabel en geen dataframe; zie §4.4 van het geheugenontwerp.
    gestreamd = m.verwerk_locatie_streamend(pad, "X").metingen["onplausibel__bool"].to_pylist()
    assert gestreamd == verwacht
