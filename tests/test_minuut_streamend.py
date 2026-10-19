# SPDX-License-Identifier: EUPL-1.2
"""Tests voor het streamende minuutpad (``ontwerp-preprocessing-minuut-geheugen.md``).

De kern van dit pad is niet wat het uitrekent maar dat het dat hetzelfde blijft doen als het in
stukken gaat. ``verwerk_locatie`` is en blijft de norm; vrijwel elke test hieronder legt de twee
naast elkaar, en het liefst bij een batchgrootte die de grens dwars door het verschijnsel heen legt
dat getoetst wordt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dph_preprocessing import minuut
from dph_preprocessing.timestamps import naar_lokale_tijdzone_arrow


# --- gereedschap ---------------------------------------------------------------------------------


def _minuten(n: int, start: str = "2023-01-01 00:00") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="1min", tz="UTC"))


def _schrijf_bron(pad, tijdstip_start: pd.Series, rijgroep: int | None = None, **kolommen) -> None:
    """Een bronbestand met hetzelfde schema als de extractie levert: float32 en uint16.

    De dtypes doen ertoe. De bron heeft geen enkele float64 (geheugenontwerp §5.1) en negen
    uint16-kolommen, en juist die uint16 is de valkuil waar :func:`minuut._types_mapper` voor
    bestaat: zonder hem verbreedt een uint16-kolom met een ontbrekende waarde stilletjes naar
    float64 (§5.5).
    """
    velden = [("tijdstip_start", pa.timestamp("ms", tz="UTC"))]
    data = [pa.array(tijdstip_start, type=pa.timestamp("ms", tz="UTC"))]
    for naam, waarden in kolommen.items():
        soort = pa.uint16() if naam in minuut.OVERNEMEN else pa.float32()
        velden.append((naam, soort))
        data.append(pa.array(waarden, type=soort))
    tabel = pa.Table.from_arrays(data, schema=pa.schema(velden))
    # Een row group van 0 rijen mag niet van parquet; bij een lege bron valt de indeling weg.
    pq.write_table(tabel, pad, row_group_size=rijgroep or len(tijdstip_start) or None)


def _beide(pad, home_id: str, batchgrootte: int):
    """Beide paden over hetzelfde bestand; geeft (volledig, streamend).

    ``types_mapper`` moet hier ook op de referentie-lezing, anders vergelijkt de test uint16 in het
    ene pad met de float64-verbreding in het andere en faalt hij op een verschil dat niets met het
    streamende pad te maken heeft.
    """
    ruw = pq.read_table(pad).to_pandas(types_mapper=minuut._types_mapper)
    volledig = minuut.verwerk_locatie(ruw, home_id)
    streamend = minuut.verwerk_locatie_streamend(pad, home_id, batchgrootte=batchgrootte)
    return volledig, streamend


def _gelijk(pad, home_id: str, batchgrootte: int) -> None:
    """De harde eis: dezelfde tabel, dezelfde gaten, dezelfde kenmerken."""
    volledig, streamend = _beide(pad, home_id, batchgrootte)
    verwacht = pa.Table.from_pandas(volledig.metingen, preserve_index=False)
    assert verwacht.schema.equals(streamend.metingen.schema), "het uitvoerschema loopt uiteen"
    assert verwacht.equals(streamend.metingen), f"de metingen lopen uiteen bij batch {batchgrootte}"
    pd.testing.assert_frame_equal(volledig.gaten, streamend.gaten)
    assert set(volledig.kenmerken) == set(streamend.kenmerken)
    for sleutel, waarde in volledig.kenmerken.items():
        ander = streamend.kenmerken[sleutel]
        if isinstance(waarde, float) and np.isnan(waarde):
            assert isinstance(ander, float) and np.isnan(ander), sleutel
        else:
            assert waarde == ander, f"kenmerk {sleutel}: {waarde!r} != {ander!r}"


@pytest.fixture
def bron(tmp_path):
    """Een locatie met van alles wat: tellers, een gat, een onplausibele waarde, dekking."""
    n = 60
    tijd = pd.concat([_minuten(30), _minuten(30, "2023-01-01 01:00")], ignore_index=True)
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(
        pad,
        tijd,
        heatpump_energy_eerste=np.arange(n, dtype="float32") * 0.5,
        boiler_energy_eerste=np.zeros(n, dtype="float32"),
        dsmr_e_consumed_low_eerste=np.arange(n, dtype="float32") + 1000.0,
        dsmr_e_consumed_high_eerste=np.arange(n, dtype="float32") + 2000.0,
        dsmr_e_delivered_low_eerste=np.zeros(n, dtype="float32"),
        dsmr_e_delivered_high_eerste=np.arange(n, dtype="float32") * 0.1,
        heatpump_power=np.full(n, 500.0, dtype="float32"),
        boiler_power=np.concatenate([np.full(n - 1, 50.0), [809_000.0]]).astype("float32"),
        kamstrup_p_thermal_system=np.full(n, 2.0, dtype="float32"),
        n_g1=np.full(n, 12, dtype="uint16"),
    )
    return pad


# --- de kerneigenschap: de batchgrootte mag niets uitmaken -----------------------------------------


@pytest.mark.parametrize("batchgrootte", [1, 2, 7, 13, 30, 59, 60, 61, 1000])
def test_dezelfde_uitkomst_ongeacht_de_batchgrootte(bron, batchgrootte):
    """Dit is de hele belofte van het streamende pad, en de rest van deze module zijn details.

    Batchgrootte 1 is geen kunstje: bij één rij per batch bestaat elk blok uit de doorgeschoven rij
    plus één nieuwe, en dan moet de draagtoestand alles dragen wat een vol frame gratis heeft.
    """
    _gelijk(bron, "A", batchgrootte)


# --- de vooruitkijk van één rij (geheugenontwerp §4.2) ---------------------------------------------


def test_differentieren_loopt_door_over_een_batchgrens(tmp_path):
    """``delta[i] = stand[i+1] - stand[i]``, dus de laatste rij van een batch mist zijn opvolger.

    Zonder de doorgeschoven rij zou het vermogen op elke batchgrens ``NaN`` worden. Met tien rijen
    en batches van vijf valt die grens precies tussen rij 4 en 5.
    """
    tijd = _minuten(10)
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(10, dtype="float32"))
    uit = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=5).metingen.to_pandas()
    # 1 kWh per minuut is 3.600.000 J / 60 s = 60.000 W, ook op de grens.
    assert uit["p_warmtepomp__W"].iloc[4] == pytest.approx(60_000.0)
    assert uit["p_warmtepomp__W"].iloc[:9].eq(60_000.0).all()


def test_de_laatste_rij_van_de_locatie_blijft_nan(tmp_path):
    """Die heeft écht geen opvolger; daar hoort de vooruitkijk niets te verzinnen."""
    tijd = _minuten(10)
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(10, dtype="float32"))
    uit = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=3).metingen.to_pandas()
    assert pd.isna(uit["p_warmtepomp__W"].iloc[-1])
    assert len(uit) == 10, "geen rij mag zoekraken of dubbel geteld worden"


# --- het lopende maximum van markeer_nulmetingen ---------------------------------------------------


def test_nulmeting_wordt_herkend_over_een_batchgrens_heen(tmp_path):
    """De teller loopt in batch 0 op en valt in batch 1 terug naar 0,0.

    Zonder het lopende maximum uit de vorige batch begint ``cummax`` per batch opnieuw, staat er
    geen "eerder" meer, en glipt de nulmeting ongemerkt door naar de uitvoer.
    """
    stand = np.array([10.0, 11.0, 12.0, 13.0, 0.0, 15.0], dtype="float32")
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, _minuten(6), heatpump_energy_eerste=stand)
    uit = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=4).metingen.to_pandas()
    assert uit["teller_nulmeting__bool"].tolist() == [False, False, False, False, True, False]
    assert pd.isna(uit["e_warmtepomp_cum__kWh"].iloc[4]), "de nulmeting gaat op NaN"
    _gelijk(pad, "A", 4)


def test_nullen_aan_het_begin_blijven_ongemoeid_over_batchgrenzen(tmp_path):
    """"Eerder boven 1" en niet "ooit boven 1", ook als die twee in verschillende batches liggen.

    Dit is de valkuil uit ``markeer_nulmetingen``, en streamen kan hem op een nieuwe manier maken:
    een lopend maximum dat te ver vooruitloopt zou de hele beginperiode alsnog vlaggen.
    """
    stand = np.array([0.0, 0.0, 0.0, 0.0, 5.0, 6.0], dtype="float32")
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, _minuten(6), heatpump_energy_eerste=stand)
    for batchgrootte in (1, 2, 3, 4, 5, 6):
        uit = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=batchgrootte).metingen.to_pandas()
        assert not uit["teller_nulmeting__bool"].any(), f"batch {batchgrootte} vlagde de beginnullen"


def test_ontbrekende_stand_telt_niet_als_eerder_maximum(tmp_path):
    """``cummax`` laat NaN staan waar de stand ontbreekt, en dat onderscheid moet blijven.

    Wordt het lopende maximum over de NaN heen gelegd, dan zou de rij ná een ontbrekende stand een
    "eerder hoogste" krijgen die er in het volledige pad niet is.
    """
    stand = np.array([10.0, np.nan, 0.0, 12.0, np.nan, 0.0], dtype="float32")
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, _minuten(6), heatpump_energy_eerste=stand)
    for batchgrootte in (1, 2, 3, 5, 6):
        _gelijk(pad, "A", batchgrootte)


def test_terugsprong_en_tellerwissel_over_een_batchgrens(tmp_path):
    """Een daling die niet naar 0 loopt is een wissel; die toets kijkt één rij vooruit.

    De vlag ``teller_wissel__bool`` gebruikt ``volgende_is_nul``, en dat is precies het soort
    stencil dat op een batchgrens stuk kan gaan. Reviewpunt A2 (ontwerp-teller-artefacten.md §10):
    het wissel-interval (rij 2, 102 -> 5) hoort ook gemaskeerd te zijn in p_warmtepomp__W, niet
    alleen gevlagd -- dat gold hiervoor niet, en is zichtbaar geweest als q_geleverd__W =
    -100.000,7 bij woning W5J0QUUq.
    """
    stand = np.array([100.0, 101.0, 102.0, 5.0, 6.0, 7.0], dtype="float32")
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, _minuten(6), heatpump_energy_eerste=stand)
    for batchgrootte in (1, 2, 3, 4, 5, 6):
        volledig, streamend = _beide(pad, "A", batchgrootte)
        assert volledig.kenmerken["n_teller_wissel"] == 1
        assert streamend.kenmerken["n_teller_wissel"] == 1
        assert pd.isna(volledig.metingen["p_warmtepomp__W"].iloc[2]), "het gemaskeerde wissel-interval"
        assert pd.isna(streamend.metingen["p_warmtepomp__W"][2].as_py())
        _gelijk(pad, "A", batchgrootte)


# --- gaten (ontwerp §7) ----------------------------------------------------------------------------


def test_een_gat_op_de_batchgrens_wordt_precies_een_keer_geteld(tmp_path):
    """Een gat hoort bij de latere van twee rijen, en die rij zit in twee blokken.

    Wordt het uit het hele blok geteld inclusief de doorgeschoven rij, dan komt hetzelfde gat er
    twee keer in; wordt het alleen uit het definitieve deel geteld, dan verdwijnt het.
    """
    tijd = pd.concat([_minuten(4), _minuten(4, "2023-01-01 02:00")], ignore_index=True)
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(8, dtype="float32"))
    for batchgrootte in (1, 2, 3, 4, 5, 8):
        streamend = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=batchgrootte)
        assert len(streamend.gaten) == 1, f"batch {batchgrootte} telde {len(streamend.gaten)} gaten"
        assert streamend.gaten["duur__min"].iloc[0] == 116
        _gelijk(pad, "A", batchgrootte)


# --- de verbreding van de uint16-kolommen ----------------------------------------------------------


def test_uint16_met_ontbrekende_waarden_blijft_uint16(tmp_path):
    """De reparatie uit geheugenontwerp §5.5: geen float64-verbreding meer, met of zonder gat.

    Zonder :func:`minuut._types_mapper` verbreedt ``to_pandas`` ``n_g1`` naar float64 zodra er één
    waarde ontbreekt, en dat viel bovendien per batch anders uit: een batch zónder ontbrekende
    waarde bleef op zichzelf uint16. Met de mapper is het uitvoerschema nu onafhankelijk van zowel
    "ontbreekt er iets" als "waar viel de batchgrens toevallig".
    """
    n_g1 = pa.array([12, 12, 12, None, 12, 12], type=pa.uint16())
    velden = pa.schema([("tijdstip_start", pa.timestamp("ms", tz="UTC")),
                        ("heatpump_energy_eerste", pa.float32()), ("n_g1", pa.uint16())])
    tabel = pa.Table.from_arrays(
        [pa.array(_minuten(6), type=pa.timestamp("ms", tz="UTC")),
         pa.array(np.arange(6, dtype="float32"), type=pa.float32()), n_g1],
        schema=velden,
    )
    pad = tmp_path / "location_id=A.parquet"
    pq.write_table(tabel, pad, row_group_size=3)

    # Batch 0 heeft geen enkele ontbrekende waarde; batch 1 wel. Beide horen uint16 te blijven.
    for batchgrootte in (1, 2, 3, 6):
        streamend = minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=batchgrootte)
        assert streamend.metingen.schema.field("n_g1").type == pa.uint16()
        _gelijk(pad, "A", batchgrootte)


# --- het terugvalpad -------------------------------------------------------------------------------


def test_ongesorteerde_bron_geeft_nietstreambaar(tmp_path):
    """Geen stille verkeerde uitkomst maar een uitzondering, zodat ``run`` kan terugvallen.

    De footer van alle 174 bestanden zegt dat dit nooit voorkomt (geheugenontwerp §3). Juist daarom
    moet het luidruchtig zijn als het tóch gebeurt.
    """
    tijd = pd.Series(pd.to_datetime(
        ["2023-01-01 00:00", "2023-01-01 00:03", "2023-01-01 00:01", "2023-01-01 00:04"], utc=True))
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(4, dtype="float32"))
    with pytest.raises(minuut.NietStreambaar):
        minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=10)


def test_overlappende_batches_geven_nietstreambaar(tmp_path):
    """Binnen elke batch oplopend, maar batch 2 begint vóór batch 1 eindigt."""
    tijd = pd.Series(pd.to_datetime(
        ["2023-01-01 00:00", "2023-01-01 00:09", "2023-01-01 00:01", "2023-01-01 00:10"], utc=True))
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(4, dtype="float32"))
    with pytest.raises(minuut.NietStreambaar):
        minuut.verwerk_locatie_streamend(pad, "A", batchgrootte=2)


def test_verwerk_valt_terug_op_het_volledige_pad(tmp_path):
    """``_verwerk`` moet een niet-streambare locatie alsnog afmaken, niet laten vallen."""
    tijd = pd.Series(pd.to_datetime(
        ["2023-01-01 00:00", "2023-01-01 00:03", "2023-01-01 00:01", "2023-01-01 00:04"], utc=True))
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, tijd, heatpump_energy_eerste=np.arange(4, dtype="float32"))
    uitkomst = minuut._verwerk(pad, "A", streamend=True)
    assert uitkomst.kenmerken["n_minuten"] == 4
    assert isinstance(uitkomst.metingen, pd.DataFrame), "het terugvalpad levert een DataFrame"


def test_lege_bron_valt_terug_in_plaats_van_te_breken(tmp_path):
    """Een locatie zonder rijen mag de run niet omvergooien (zie ``test_minuut.py``)."""
    pad = tmp_path / "location_id=A.parquet"
    _schrijf_bron(pad, pd.Series(dtype="datetime64[ms, UTC]"),
                  heatpump_energy_eerste=np.array([], dtype="float32"))
    with pytest.raises(minuut.NietStreambaar):
        minuut.verwerk_locatie_streamend(pad, "A")
    assert minuut._verwerk(pad, "A", streamend=True).kenmerken["n_minuten"] == 0


# --- de kolomselectie ------------------------------------------------------------------------------


def test_de_laatste_varianten_worden_niet_gelezen(tmp_path):
    """Geheugenontwerp §4.1: acht ``*_laatste``-kolommen worden nergens gebruikt.

    Ze overslaan scheelt 17 % van de float-payload, en deze test bewaakt dat ze niet stilletjes
    terugkruipen in de leeslijst.
    """
    namen = ["tijdstip_start", "location_id", "heatpump_energy_eerste", "heatpump_energy_laatste",
             "heatpump_power", "n_g1"]
    nodig = minuut._nodige_kolommen(namen)
    assert "heatpump_energy_laatste" not in nodig
    assert "location_id" not in nodig
    assert set(nodig) == {"tijdstip_start", "heatpump_energy_eerste", "heatpump_power", "n_g1"}


# --- opruimen (geheugenontwerp §4.4) ---------------------------------------------------------------


def test_achtergebleven_tmp_wordt_opgeruimd(tmp_path):
    """Een afgebroken locatie laat er één achter; die hoort bij de volgende run weg te zijn."""
    (tmp_path / "location_id=A.parquet.tmp").write_bytes(b"half")
    (tmp_path / "location_id=B.parquet").write_bytes(b"af")
    assert minuut._ruim_tmp_op(tmp_path) == 1
    assert not (tmp_path / "location_id=A.parquet.tmp").exists()
    assert (tmp_path / "location_id=B.parquet").exists(), "een af bestand blijft staan"


def test_opruimen_op_een_map_die_nog_niet_bestaat(tmp_path):
    assert minuut._ruim_tmp_op(tmp_path / "bestaat_niet") == 0


# --- schrijven -------------------------------------------------------------------------------------


def test_schrijf_atomisch_neemt_ook_een_arrow_tabel(tmp_path, bron):
    """Het streamende pad heeft zijn uitvoer al in arrow; daar hoeft geen pandas-kopie meer overheen."""
    streamend = minuut.verwerk_locatie_streamend(bron, "A", batchgrootte=7)
    doel = tmp_path / "uit" / "location_id=A.parquet"
    minuut.schrijf_atomisch(streamend.metingen, doel)
    assert doel.exists()
    assert not doel.with_suffix(".parquet.tmp").exists(), "de tijdelijke naam hoort weg te zijn"
    # Dezelfde tabel, alleen met de tijdkolom in lokale tijd (zie test_minuut_tijdzone.py).
    assert pq.read_table(doel).equals(naar_lokale_tijdzone_arrow(streamend.metingen))
