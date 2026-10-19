# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.gaskwaliteit: de werkelijke calorische gaswaarde ophalen, koppelen
en -- als dat niet lukt -- zichtbaar terugvallen op de vaste waarde.

De netwerkcall zelf staat achter de ``network``-marker (standaard uitgesloten, zie pyproject.toml).
Alles daaromheen is hier zonder netwerk getest, inclusief het geval dat de ophaal helemaal mislukt:
juist dat pad moet betrouwbaar zijn, want het is het pad dat de terugvaltelling in het rapport
voedt.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from dph_preprocessing import gaskwaliteit

FALLBACK = gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3


def _uurreeks(tijdstippen, waarden__MJ_m3):
    return pd.DataFrame(
        {
            "tijdstip": pd.to_datetime(tijdstippen).tz_localize("UTC"),
            gaskwaliteit.KOLOM: [w * gaskwaliteit.MJ_NAAR_J for w in waarden__MJ_m3],
            "n_gebieden": [170] * len(tijdstippen),
            "n_gebieden_uitgesloten": [7] * len(tijdstippen),
        }
    )


def _kwartieren(tijdstippen):
    return pd.to_datetime(tijdstippen).tz_localize("UTC").to_series(index=range(len(tijdstippen)))


# --- gasmaanden -------------------------------------------------------------------------------


def test_gasmaanden_gebruikt_de_gasmaand_niet_de_kalendermaand():
    # De publicatie loopt van de eerste van de maand 06:00 lokaal tot de eerste van de volgende
    # maand 06:00. 1 februari 01:00 lokaal (= 00:00 UTC) zit dus nog in de JANUARI-publicatie; wie
    # de kalendermaand pakt, haalt februari op en laat die rijen stil op de vaste waarde landen.
    start = pd.Timestamp("2023-02-01T00:00:00Z")
    assert gaskwaliteit.gasmaanden(start, start) == ["2023-01"]


def test_gasmaanden_dekt_het_hele_venster():
    maanden = gaskwaliteit.gasmaanden(
        pd.Timestamp("2022-12-20T12:00:00Z"), pd.Timestamp("2023-02-10T12:00:00Z")
    )
    assert maanden == ["2022-12", "2023-01", "2023-02"]


def test_gasmaanden_weigert_naieve_tijdstempels():
    with pytest.raises(ValueError):
        gaskwaliteit.fetch_actual_gas_hhv(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02"))


# --- koppelen ---------------------------------------------------------------------------------


def test_koppel_neemt_de_waarde_van_het_uur_waarin_het_kwartier_valt():
    # Trapfunctie, geen interpolatie: alle vier kwartieren van 10:00 krijgen de 10:00-waarde,
    # gelijk aan hoe deze pijplijn het weer koppelt.
    reeks = _uurreeks(["2023-01-05T10:00:00", "2023-01-05T11:00:00"], [36.0, 34.0])
    kwartieren = _kwartieren(
        ["2023-01-05T10:00:00", "2023-01-05T10:15:00", "2023-01-05T10:45:00", "2023-01-05T11:00:00"]
    )

    resultaat = gaskwaliteit.koppel_gas_hhv(kwartieren, reeks)

    assert list(resultaat[gaskwaliteit.KOLOM]) == [36e6, 36e6, 36e6, 34e6]
    assert set(resultaat[gaskwaliteit.BRON_KOLOM]) == {gaskwaliteit.BRON_ACTUEEL}


def test_koppel_valt_zichtbaar_terug_buiten_het_opgehaalde_venster():
    reeks = _uurreeks(["2023-01-05T10:00:00"], [36.0])
    kwartieren = _kwartieren(["2023-01-05T10:00:00", "2023-01-05T12:00:00"])

    resultaat = gaskwaliteit.koppel_gas_hhv(kwartieren, reeks)

    assert resultaat[gaskwaliteit.KOLOM].tolist() == [36e6, FALLBACK]
    # Niet leeg laten en niet stil vullen: de herkomst per rij is precies wat het rapport telt.
    assert resultaat[gaskwaliteit.BRON_KOLOM].tolist() == [
        gaskwaliteit.BRON_ACTUEEL,
        gaskwaliteit.BRON_FALLBACK,
    ]


@pytest.mark.parametrize("leeg", [None, "leeg"])
def test_koppel_zonder_reeks_valt_overal_terug(leeg):
    kwartieren = _kwartieren(["2023-01-05T10:00:00", "2023-01-05T10:15:00"])
    gas_hhv = None if leeg is None else gaskwaliteit.lege_gas_hhv()

    resultaat = gaskwaliteit.koppel_gas_hhv(kwartieren, gas_hhv)

    assert (resultaat[gaskwaliteit.KOLOM] == FALLBACK).all()
    assert (resultaat[gaskwaliteit.BRON_KOLOM] == gaskwaliteit.BRON_FALLBACK).all()


def test_koppel_behoudt_de_index_van_de_invoer():
    # build_measurements_en_quality geeft de uitkomst per rij door aan differentieer_teller, dus de
    # index moet die van measurements zijn en niet stil hernummerd worden.
    kwartieren = _kwartieren(["2023-01-05T10:00:00", "2023-01-05T10:15:00"])
    kwartieren.index = [7, 42]

    resultaat = gaskwaliteit.koppel_gas_hhv(kwartieren, gaskwaliteit.lege_gas_hhv())

    assert list(resultaat.index) == [7, 42]


def test_koppel_weigert_een_naieve_tijdkolom():
    kwartieren = pd.Series(pd.to_datetime(["2023-01-05T10:00:00"]))
    with pytest.raises(ValueError):
        gaskwaliteit.koppel_gas_hhv(kwartieren, gaskwaliteit.lege_gas_hhv())


# --- ophalen en cachen ------------------------------------------------------------------------

#: Twee netgebieden met G-gas en één met H-gas, in hetzelfde uur. De H-gas-waarde moet buiten het
#: gemiddelde blijven: meegeteld zou het uurgemiddelde 37,3 worden in plaats van 35,5.
_CSV_EEN_UUR = (
    '"grid_area","date_time","value"\r\n'
    '"871718518003000050","2023-01-01T06:00:00+01:00","35.400000"\r\n'
    '"871718518003000098","2023-01-01T06:00:00+01:00","35.600000"\r\n'
    '"871718518003015603","2023-01-01T06:00:00+01:00","41.000000"\r\n'
)


class _NepResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_fetch_sluit_hoogcalorische_netgebieden_uit(monkeypatch, tmp_path):
    aanroepen = []

    def nep_get(url, params, headers, timeout):
        aanroepen.append(params["startMonth"])
        return _NepResponse(_CSV_EEN_UUR)

    monkeypatch.setitem(
        __import__("sys").modules, "requests", type("requests", (), {"get": staticmethod(nep_get)})
    )

    gas_hhv = gaskwaliteit.fetch_actual_gas_hhv(
        pd.Timestamp("2023-01-01T06:00:00Z"), pd.Timestamp("2023-01-01T06:00:00Z"), cache_dir=tmp_path
    )

    assert len(gas_hhv) == 1
    assert gas_hhv[gaskwaliteit.KOLOM].iloc[0] == pytest.approx(35.5e6)
    assert gas_hhv["n_gebieden"].iloc[0] == 2
    assert gas_hhv["n_gebieden_uitgesloten"].iloc[0] == 1

    # Tweede aanroep leest uit de cache: geen tweede request, zelfde uitkomst. Dat is wat de
    # gechunkte verwerking goedkoop maakt en een hervatte run reproduceerbaar.
    opnieuw = gaskwaliteit.fetch_actual_gas_hhv(
        pd.Timestamp("2023-01-01T06:00:00Z"), pd.Timestamp("2023-01-01T06:00:00Z"), cache_dir=tmp_path
    )
    assert aanroepen == ["2023-01"]
    assert opnieuw[gaskwaliteit.KOLOM].iloc[0] == pytest.approx(35.5e6)


def test_fetch_bij_een_mislukte_ophaal_geeft_een_lege_tabel_geen_fout(monkeypatch, tmp_path):
    def nep_get(url, params, headers, timeout):
        raise RuntimeError("API onbereikbaar")

    monkeypatch.setitem(
        __import__("sys").modules, "requests", type("requests", (), {"get": staticmethod(nep_get)})
    )

    gas_hhv = gaskwaliteit.fetch_actual_gas_hhv(
        pd.Timestamp("2023-01-15T06:00:00Z"), pd.Timestamp("2023-01-15T06:00:00Z"), cache_dir=tmp_path
    )

    assert gas_hhv.empty
    assert list(gas_hhv.columns) == list(gaskwaliteit.GAS_HHV_KOLOMMEN)
    # En de koppeling maakt daar een expliciete terugval van, geen lege kolom.
    resultaat = gaskwaliteit.koppel_gas_hhv(_kwartieren(["2023-01-15T10:00:00"]), gas_hhv)
    assert resultaat[gaskwaliteit.BRON_KOLOM].iloc[0] == gaskwaliteit.BRON_FALLBACK


@pytest.mark.network
def test_de_echte_api_geeft_nog_de_vorm_die_we_verwachten():
    """Rookproef op de niet-gedocumenteerde API: hij kan zonder aankondiging wijzigen, en dan is
    dit de test die dat als eerste zegt in plaats van een rapport dat stil naar 100% fallback gaat.
    """
    gas_hhv = gaskwaliteit.fetch_actual_gas_hhv(
        pd.Timestamp("2023-01-15T00:00:00Z"), pd.Timestamp("2023-01-15T00:00:00Z")
    )

    assert not gas_hhv.empty
    assert list(gas_hhv.columns) == list(gaskwaliteit.GAS_HHV_KOLOMMEN)
    # Een volle gasmaand aan uurwaarden (januari: 744), en waarden in het bereik van G-gas.
    assert len(gas_hhv) == 744
    waarden__MJ_m3 = gas_hhv[gaskwaliteit.KOLOM] / gaskwaliteit.MJ_NAAR_J
    assert waarden__MJ_m3.between(33.0, 38.0).all()
    assert (gas_hhv["n_gebieden"] > 100).all()


def test_csv_uit_de_api_wordt_als_utc_gelezen():
    """De API levert lokale tijd met offset (``+01:00``/``+02:00``). Die moet naar UTC, want de rest
    van de pijplijn rekent intern in UTC en koppelt op ``floor("h")``."""
    ruw = pd.read_csv(io.StringIO(_CSV_EEN_UUR))
    tijdstip = pd.to_datetime(ruw["date_time"], utc=True).iloc[0]
    assert tijdstip == pd.Timestamp("2023-01-01T05:00:00Z")
