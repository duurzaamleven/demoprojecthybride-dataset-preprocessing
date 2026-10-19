# SPDX-License-Identifier: EUPL-1.2
"""Tests voor het minuut-invoerpad (``ontwerp-preprocessing-minuut.md``).

Dezelfde stijl als de overige testmodules: kleine synthetische frames, elk scenario één
gedragsaspect, en een docstring die naar het ontwerppunt verwijst dat getoetst wordt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dph_preprocessing import minuut


def _minuten(n: int, start: str = "2023-01-01 00:00") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="1min", tz="UTC"))


def _ruw(tijdstip_start: pd.Series, **kolommen) -> pd.DataFrame:
    """Een ruwe minuuttabel met alleen de genoemde kolommen gevuld, de rest afwezig."""
    df = pd.DataFrame({"tijdstip_start": tijdstip_start})
    for naam, waarden in kolommen.items():
        df[naam] = waarden
    return df


# --- _streaks ---------------------------------------------------------------------------------


def test_streaks_vindt_alleen_reeksen_die_lang_genoeg_zijn():
    """Ontwerp §8: de proef eist tien aaneengesloten minuten, niet tien losse minuten."""
    masker = np.array([1, 1, 1, 0] + [1] * 10 + [0], dtype=bool)
    uit = minuut._streaks(masker, 10)
    assert uit[:4].sum() == 0
    assert uit[4:14].all()


def test_streaks_op_leeg_masker():
    assert minuut._streaks(np.array([], dtype=bool), 10).size == 0


def test_streaks_reeks_tot_het_einde_van_de_reeks():
    """Een reeks die aan de rand van de array eindigt mag niet afgekapt worden."""
    assert minuut._streaks(np.ones(10, dtype=bool), 10).all()


# --- nulmetingen (ontwerp §5) -----------------------------------------------------------------


def test_nulmeting_wordt_gevlagd_als_de_teller_ooit_gelopen_heeft():
    """37 van de 43 terugsprongen in de verkenning waren een losse 0,0 met daarna herstel."""
    stand = pd.Series([10.0, 11.0, 0.0, 12.0])
    assert minuut.markeer_nulmetingen(stand).tolist() == [False, False, True, False]


def test_nullen_aan_het_begin_van_een_teller_zijn_geen_nulmeting():
    """De valkuil die deze test heeft gevonden: "eerder boven 1" en niet "ooit boven 1".

    ``heatpump_energy`` en ``kamstrup_e_thermal_system`` staan bij het begin van de meetperiode
    gewoon op 0,0 en gaan pas later lopen. Een regel die vraagt of de teller érgens in de reeks
    boven 1 komt, nulde die hele beginperiode; een lopend maximum vraagt of de stand terugvalt.
    """
    stand = pd.Series([0.0, 0.0, 0.0, 1.5, 2.0])
    assert not minuut.markeer_nulmetingen(stand).any()


def test_teller_die_nooit_boven_een_kwam_levert_geen_nulmeting():
    """De teruglevertelller van een woning zonder zonnepanelen staat legitiem op 0,0.

    Ruim vier miljoen waarnemingen in de steekproef; zonder deze uitzondering zou elke daarvan
    als foutieve uitlezing gevlagd worden.
    """
    stand = pd.Series([0.0] * 5)
    assert not minuut.markeer_nulmetingen(stand).any()


def test_nulmeting_gaat_op_nan_voor_het_differentieren():
    """Ontwerp §5: anders levert één foute 0 een enorme negatieve en daarna positieve piek."""
    tijd__ns = _minuten(4).to_numpy(dtype="datetime64[ns]").astype("int64")
    stand = pd.Series([10.0, 11.0, 0.0, 13.0])
    schoon, afgeleid, nul = minuut.verwerk_teller(stand, tijd__ns, minuut.J_PER_KWH)
    assert pd.isna(schoon.iloc[2])
    assert nul.iloc[2]
    # De sprong 11 -> 13 wordt niet als 11 -> 0 -> 13 gezien.
    eindig = afgeleid["delta"][np.isfinite(afgeleid["delta"])]
    assert (eindig >= 0).all()


def test_differentieer_snel_is_gelijk_aan_de_gedeelde_functie():
    """De snelle numpy-versie mag alleen sneller zijn, niet anders (module-docstring).

    De gedeelde functie bleef de norm; deze test is wat de twee bij elkaar houdt, zodat een
    wijziging aan de ene kant hier opvalt in plaats van in de uitvoer van een nachtrun.
    """
    from dph_preprocessing.tellers import differentieer_teller

    tijd = pd.Series(
        pd.to_datetime(
            ["2023-01-01 00:00", "2023-01-01 00:01", "2023-01-01 00:05", "2023-01-01 00:06"],
            utc=True,
        )
    )
    stand = pd.Series([100.0, 100.5, 102.0, 102.25])
    traag = differentieer_teller(stand, tijd, pd.Series(["A"] * 4), eenheid_naar_J=minuut.J_PER_KWH)
    snel = minuut.differentieer_snel(
        stand.to_numpy(), tijd.to_numpy(dtype="datetime64[ns]").astype("int64"), minuut.J_PER_KWH
    )
    for kolom in ("delta", "delta_t__s", "vermogen__W"):
        np.testing.assert_allclose(
            snel[kolom].astype("float64"),
            traag[kolom].to_numpy(dtype="float64"),
            rtol=1e-6,
            equal_nan=True,
            err_msg=f"{kolom} loopt uiteen tussen de twee implementaties",
        )


def test_differentieer_snel_geeft_geen_oneindig_bij_dubbele_tijdstempels():
    """Twee rijen op dezelfde minuut zou delen door nul zijn; dat hoort NaN te worden, niet inf."""
    tijd__ns = np.array([0, 0, 60_000_000_000], dtype="int64")
    uit = minuut.differentieer_snel(np.array([1.0, 2.0, 3.0]), tijd__ns, 1.0)
    assert np.isnan(uit["vermogen__W"][0])


# --- gaten (ontwerp §7) -------------------------------------------------------------------------


def test_gaten_scheidt_hapering_van_uitval():
    """92,7 % van het gemis zit in gaten van meer dan een dag; die horen uit de noemer."""
    tijd = pd.Series(
        pd.to_datetime(
            ["2023-01-01 00:00", "2023-01-01 00:01", "2023-01-01 00:05", "2023-01-03 00:05"],
            utc=True,
        )
    )
    gaten = minuut.bouw_gaten(tijd, "A")
    assert gaten["soort"].tolist() == ["hapering", "uitval"]
    assert gaten["duur__min"].tolist() == [3, 2879]


def test_geen_gaten_bij_een_aaneengesloten_reeks():
    assert len(minuut.bouw_gaten(_minuten(10), "A")) == 0


def test_gaten_bij_een_enkele_rij():
    """Eén minuut heeft geen opvolger en dus geen gat; mag geen fout geven."""
    assert len(minuut.bouw_gaten(_minuten(1), "A")) == 0


# --- de warmtemeterproef (ontwerp §8) ------------------------------------------------------------


def test_warmtemeter_op_het_systeem_wordt_herkend():
    """Warmte tijdens tien minuten ketelbedrijf zonder warmtepomp: de meter zit achter beide."""
    n = 60
    df = pd.DataFrame(
        {
            "p_warmtepomp_gemeten__W": np.zeros(n),
            "p_ketel_gemeten__W": np.full(n, 100.0),
            "q_geleverd_gemeten__W": np.full(n, 5000.0),
        }
    )
    uit = minuut.bepaal_warmtemeter_bereik(df)
    assert uit["warmtemeter_bereik__cat"] == "systeem"
    assert uit["bereik_n"] == n


def test_warmtemeter_alleen_op_de_warmtepomp_wordt_herkend():
    n = 60
    df = pd.DataFrame(
        {
            "p_warmtepomp_gemeten__W": np.concatenate([np.zeros(30), np.full(30, 1000.0)]),
            "p_ketel_gemeten__W": np.concatenate([np.full(30, 100.0), np.zeros(30)]),
            "q_geleverd_gemeten__W": np.concatenate([np.zeros(30), np.full(30, 5000.0)]),
        }
    )
    uit = minuut.bepaal_warmtemeter_bereik(df)
    assert uit["warmtemeter_bereik__cat"] == "warmtepomp"


def test_warmtemeter_onbeslist_bij_een_tussenwaarde():
    """De verkenning vond locaties op 2,7 tot 8,5 %, niet te scheiden van een uitzakkend buffervat.

    Die horen niet naar één van beide kanten geduwd te worden.
    """
    n = 100
    warmte = np.zeros(n)
    warmte[:5] = 5000.0
    df = pd.DataFrame(
        {
            "p_warmtepomp_gemeten__W": np.zeros(n),
            "p_ketel_gemeten__W": np.full(n, 100.0),
            "q_geleverd_gemeten__W": warmte,
        }
    )
    assert minuut.bepaal_warmtemeter_bereik(df)["warmtemeter_bereik__cat"] == "onbeslist"


def test_warmtemeter_onbeslist_zonder_bruikbare_proefminuten():
    """Geen enkele streak van tien minuten: dan is er geen uitspraak, geen gok."""
    df = pd.DataFrame(
        {
            "p_warmtepomp_gemeten__W": np.full(5, 1000.0),
            "p_ketel_gemeten__W": np.zeros(5),
            "q_geleverd_gemeten__W": np.full(5, 100.0),
        }
    )
    assert minuut.bepaal_warmtemeter_bereik(df)["warmtemeter_bereik__cat"] == "onbeslist"


# --- verwerk_locatie, end to end ------------------------------------------------------------------


@pytest.fixture
def ruwe_locatie() -> pd.DataFrame:
    """Tien minuten met een oplopende warmtepompteller en één onmogelijke ketelwaarde."""
    tijd = _minuten(10)
    return _ruw(
        tijd,
        heatpump_energy_eerste=np.arange(10, dtype="float64"),
        boiler_energy_eerste=np.zeros(10),
        heatpump_power=np.full(10, 500.0),
        boiler_power=np.concatenate([np.full(9, 50.0), [809_000.0]]),
        kamstrup_p_thermal_system=np.full(10, 2.0),
        n_g1=np.full(10, 12, dtype="uint16"),
    )


def test_verwerk_locatie_zet_de_teller_om_naar_vermogen(ruwe_locatie):
    """Ontwerp §4: vooruit differentiëren, gedeeld door de werkelijke tijd.

    1 kWh per minuut is 3.600.000 J / 60 s = 60.000 W.
    """
    uit = minuut.verwerk_locatie(ruwe_locatie, "A").metingen
    assert uit["p_warmtepomp__W"].iloc[0] == pytest.approx(60_000.0)
    assert pd.isna(uit["p_warmtepomp__W"].iloc[-1]), "de laatste rij heeft geen opvolger"


def test_verwerk_locatie_vlagt_de_onmogelijke_ketelwaarde(ruwe_locatie):
    """Ontwerp §6: 809 kW elektrisch voor een cv-ketel is een defect, geen extreme meting."""
    uit = minuut.verwerk_locatie(ruwe_locatie, "A").metingen
    assert uit["onplausibel__bool"].iloc[-1]
    assert not uit["onplausibel__bool"].iloc[0]
    assert pd.isna(uit["p_ketel_gemeten__W"].iloc[-1]), "de waarde gaat op NaN, niet op de grens"


def test_verwerk_locatie_rekent_kamstrup_van_kw_naar_w(ruwe_locatie):
    """De bron levert kW; de uitvoernaam zegt W, dus de factor hoort erbij."""
    uit = minuut.verwerk_locatie(ruwe_locatie, "A").metingen
    assert uit["q_geleverd_gemeten__W"].iloc[0] == pytest.approx(2000.0)


def test_verwerk_locatie_noemt_het_gemiddelde_niet_meting(ruwe_locatie):
    """Ontwerp §3: in de minuutdata is dit een intervalgemiddelde over twaalf metingen.

    Het achtervoegsel ``_meting__`` uit het kwartierpad betekent "momentane steekproef" en zou er
    hier over liegen.
    """
    uit = minuut.verwerk_locatie(ruwe_locatie, "A").metingen
    assert "p_warmtepomp_gemeten__W" in uit.columns
    assert not any(kolom.endswith("_meting__W") for kolom in uit.columns)


def test_verwerk_locatie_herkent_een_dood_warmtepompkanaal():
    """39 van de 174 locaties hebben dit; ze stil laten meelopen bederft elk gepoold rendement."""
    tijd = _minuten(20)
    ruw = _ruw(tijd, heatpump_power=np.zeros(20), kamstrup_p_thermal_system=np.full(20, 3.0))
    kenmerken = minuut.verwerk_locatie(ruw, "A").kenmerken
    assert kenmerken["warmtepompkanaal_dood__bool"]


def test_verwerk_locatie_bezetting_telt_de_ontbrekende_minuten_mee():
    """Ontwerp §7: de noemer is de tijdspanne, niet het aantal aanwezige rijen."""
    tijd = pd.Series(
        pd.to_datetime(["2023-01-01 00:00", "2023-01-01 00:01", "2023-01-01 00:09"], utc=True)
    )
    kenmerken = minuut.verwerk_locatie(_ruw(tijd, heatpump_power=np.zeros(3)), "A").kenmerken
    assert kenmerken["bezetting__0"] == pytest.approx(3 / 10)


def test_verwerk_locatie_maskeert_het_wissel_interval_niet_de_stand():
    """Reviewpunt A2 (ontwerp-teller-artefacten.md §10): een echte tellerwissel werd al gevlagd
    (teller_wissel__bool) maar niet gemaskeerd. Zichtbaar in de bestaande uitvoer als
    q_geleverd__W = -100.000,7 bij woning W5J0QUUq. Hier met v_gas_consumed: 100, 110, 30, 40 -- een
    breuk naar 30 (niet naar 0), dus geen nulmeting-herstel maar een echte wissel.
    """
    tijd = _minuten(4)
    ruw = _ruw(tijd, dsmr_v_gas_consumed_eerste=np.array([100.0, 110.0, 30.0, 40.0]))
    uit = minuut.verwerk_locatie(ruw, "A").metingen
    assert uit["teller_wissel__bool"].tolist() == [False, True, False, False]
    # De stand blijft ongemoeid (geen segmentreparatie); alleen het vermogeninterval gaat op NaN.
    assert uit["g_gebruik_cum__m3"].tolist() == [100.0, 110.0, 30.0, 40.0]
    assert uit["g_gebruik__m3_s_1"].iloc[0] > 0
    assert pd.isna(uit["g_gebruik__m3_s_1"].iloc[1]), "het gemaskeerde wissel-interval"
    assert uit["g_gebruik__m3_s_1"].iloc[2] > 0


def test_verwerk_locatie_op_een_lege_tabel():
    """Een locatie zonder rijen mag de run niet omvergooien."""
    leeg = pd.DataFrame({"tijdstip_start": pd.Series(dtype="datetime64[ms, UTC]")})
    uitkomst = minuut.verwerk_locatie(leeg, "A")
    assert len(uitkomst.metingen) == 0
    assert uitkomst.kenmerken["n_minuten"] == 0
