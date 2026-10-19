# SPDX-License-Identifier: EUPL-1.2
"""Tests voor dph_preprocessing.chunking: chunk-partitionering, hervatten, en het samenvoegen van
deelbestanden (taak: gechunkte, hervatbare verwerking van de volledige dataset)."""

from __future__ import annotations

import pandas as pd
import pytest

from dph_preprocessing import chunking


def test_verdeel_in_chunks_en_terug():
    home_ids = [f"h{i}" for i in range(7)]
    chunks = chunking.verdeel_in_chunks(home_ids, 3)
    assert chunks == [["h0", "h1", "h2"], ["h3", "h4", "h5"], ["h6"]]
    omgekeerd = chunking.chunk_van_home_id(chunks)
    assert omgekeerd["h0"] == 0
    assert omgekeerd["h5"] == 1
    assert omgekeerd["h6"] == 2


def test_verdeel_in_chunks_weigert_niet_positieve_grootte():
    with pytest.raises(ValueError):
        chunking.verdeel_in_chunks(["a"], 0)


def test_schrijf_part_atomisch_laat_geen_tmp_achter(tmp_path):
    pad = tmp_path / "measurements" / "chunk_000.parquet"
    df = pd.DataFrame({"a": [1, 2, 3]})
    chunking.schrijf_part_atomisch(pad, df)
    assert pad.is_file()
    assert not pad.with_suffix(".parquet.tmp").exists()
    terug = pd.read_parquet(pad)
    pd.testing.assert_frame_equal(terug, df)


def test_chunk_compleet_vereist_alle_tabellen(tmp_path):
    parts_dir = tmp_path / "parts"
    df = pd.DataFrame({"a": [1]})
    for tabel in ("homes", "measurements", "quality", "derived"):  # "weer" ontbreekt bewust
        chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, tabel, 0), df)
    assert chunking.chunk_compleet(parts_dir, 0) is False
    chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, "weer", 0), df)
    assert chunking.chunk_compleet(parts_dir, 0) is True


def test_chunk_compleet_ziet_een_tmp_bestand_niet_als_compleet(tmp_path):
    parts_dir = tmp_path / "parts"
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, tabel, 0), pd.DataFrame({"a": [1]}))
    assert chunking.chunk_compleet(parts_dir, 0) is True
    # Simuleer een halverwege afgebroken herschrijving: alleen het .tmp-bestand van "derived" bestaat.
    definitief = chunking.chunk_pad(parts_dir, "derived", 0)
    definitief.unlink()
    definitief.with_suffix(definitief.suffix + ".tmp").write_bytes(b"half geschreven, geen geldig parquet")
    assert chunking.chunk_compleet(parts_dir, 0) is False


def test_ruim_chunk_op_verwijdert_definitief_en_tmp(tmp_path):
    parts_dir = tmp_path / "parts"
    pad = chunking.chunk_pad(parts_dir, "derived", 0)
    chunking.schrijf_part_atomisch(pad, pd.DataFrame({"a": [1]}))
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(b"restant van een vorige, afgebroken poging")
    chunking.ruim_chunk_op(parts_dir, 0, tabellen=("derived",))
    assert not pad.exists()
    assert not tmp.exists()


def test_herstel_run_slaat_complete_chunks_over_en_ruimt_incomplete_op(tmp_path):
    out_dir = tmp_path / "out"
    chunks = [["a"], ["b"], ["c"]]
    # Eerst een run beginnen, zodat het chunkplan vastligt; zonder dat worden de deelbestanden
    # hieronder terecht als "van een ander plan" weggegooid (zie de vingerafdruk-test onderaan).
    chunking.herstel_run(out_dir, chunks, opnieuw=False)
    # Chunk 0: helemaal compleet. Chunk 1: alleen "homes" (dus NIET compleet -- moet opgeruimd).
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(out_dir / "parts", tabel, 0), pd.DataFrame({"a": [1]}))
    chunking.schrijf_part_atomisch(chunking.chunk_pad(out_dir / "parts", "homes", 1), pd.DataFrame({"a": [1]}))

    parts_dir, interim_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw=False)
    assert te_doen == [1, 2]
    # Chunk 1's halve "homes"-deel moet opgeruimd zijn.
    assert not chunking.chunk_pad(parts_dir, "homes", 1).exists()
    # Chunk 0 blijft ongemoeid.
    assert chunking.chunk_compleet(parts_dir, 0) is True


def test_herstel_run_opnieuw_wist_alles(tmp_path):
    out_dir = tmp_path / "out"
    chunks = [["a"]]
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(out_dir / "parts", tabel, 0), pd.DataFrame({"a": [1]}))
    (out_dir / "interim" / "dsmr").mkdir(parents=True)

    parts_dir, interim_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw=True)
    assert te_doen == [0]
    # parts/ bestaat nog, maar bevat alleen het verse chunkplan -- geen enkel deelbestand.
    assert not chunking.chunk_compleet(parts_dir, 0)
    assert list(parts_dir.glob("*/*.parquet")) == []
    assert (parts_dir / chunking.PLAN_BESTAND).is_file()
    assert not interim_dir.exists()


def test_voeg_samen_streamend_behoudt_alle_rijen_en_volgorde(tmp_path):
    parts_dir = tmp_path / "parts"
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "measurements", 0), pd.DataFrame({"home_id__str": ["a", "a"], "x": [1, 2]})
    )
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "measurements", 1), pd.DataFrame({"home_id__str": ["b"], "x": [3]})
    )
    uitvoer = tmp_path / "measurements.parquet"
    n = chunking.voeg_samen_streamend(parts_dir, "measurements", 2, uitvoer)
    assert n == 3
    resultaat = pd.read_parquet(uitvoer)
    assert resultaat["x"].tolist() == [1, 2, 3]


def test_voeg_samen_streamend_slaat_ontbrekende_chunks_over(tmp_path):
    # Chunk 1 heeft geen deelbestand (bv. een lege chunk); dat mag geen fout geven.
    parts_dir = tmp_path / "parts"
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "homes", 0), pd.DataFrame({"home_id__str": ["a"]})
    )
    uitvoer = tmp_path / "homes.parquet"
    n = chunking.voeg_samen_streamend(parts_dir, "homes", 2, uitvoer)
    assert n == 1


def test_voeg_samen_streamend_laat_bestaand_uitvoerbestand_ongemoeid_zonder_delen(tmp_path):
    # Als GEEN ENKELE chunk een deelbestand heeft voor deze tabel, mag een al bestaand
    # uitvoerbestand niet overschreven/leeggemaakt worden -- pipeline.run's samenvoeging van
    # "scheefheid" (geen lid van PARTS_TABELLEN, zie chunking.PARTS_TABELLEN's docstring) leunt
    # hierop: een eenmalige backfill van scheefheid.parquet mag niet verdwijnen bij een gewone
    # hervatte run die zelf geen enkele chunk opnieuw doet.
    parts_dir = tmp_path / "parts"
    uitvoer = tmp_path / "scheefheid.parquet"
    bestaand = pd.DataFrame({"x": [1, 2, 3]})
    bestaand.to_parquet(uitvoer, index=False)

    n = chunking.voeg_samen_streamend(parts_dir, "scheefheid", 3, uitvoer)

    assert n == 0
    terug = pd.read_parquet(uitvoer)
    pd.testing.assert_frame_equal(terug, bestaand)


def test_voeg_weer_samen_ontdubbelt_over_chunks_heen(tmp_path):
    # Twee woningen op hetzelfde station, in verschillende chunks: hun weer-delen overlappen.
    parts_dir = tmp_path / "parts"
    gemeenschappelijk = pd.DataFrame(
        {
            "weerstation_nr": [1, 1],
            "tijdstip_start": pd.to_datetime(["2022-01-01T00:00", "2022-01-01T01:00"]).tz_localize("UTC"),
            "temp_buiten__degC": [5.0, 5.5],
        }
    )
    chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, "weer", 0), gemeenschappelijk)
    chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, "weer", 1), gemeenschappelijk.copy())

    uitvoer = tmp_path / "weer.parquet"
    n = chunking.voeg_weer_samen(parts_dir, 2, uitvoer)
    assert n == 2  # niet 4: ontdubbeld op (weerstation_nr, tijdstip_start)
    resultaat = pd.read_parquet(uitvoer)
    assert len(resultaat) == 2
    assert resultaat["tijdstip_start"].is_monotonic_increasing


def test_hervatten_weigert_deelbestanden_van_een_ander_chunkplan(tmp_path):
    """Deelbestanden van een ANDER plan mogen niet hergebruikt worden (chunking.plan_vingerafdruk).

    De regressie die dit afdekt is echt gebeurd (05-09-2026): een ``chunk_000.parquet`` uit een
    proefrun met 5 woningen bleef staan, en een volgende run met 25 woningen per chunk sloeg chunk 1
    over omdat de bestanden er nu eenmaal stonden. De uitvoer zou dan stilzwijgend 20 woningen
    missen -- geen foutmelding, alleen een verkeerd antwoord.
    """
    out_dir = tmp_path / "out"
    plan_klein = [["a", "b"]]
    parts_dir, _, te_doen = chunking.herstel_run(out_dir, plan_klein, opnieuw=False)
    assert te_doen == [0]

    # doe alsof chunk 0 van het KLEINE plan netjes af is
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(
            chunking.chunk_pad(parts_dir, tabel, 0), pd.DataFrame({"x": [1]})
        )
    assert chunking.chunk_compleet(parts_dir, 0)

    # zelfde plan: chunk 0 mag overgeslagen worden
    _, _, te_doen = chunking.herstel_run(out_dir, plan_klein, opnieuw=False)
    assert te_doen == []

    # ANDER plan (meer woningen in dezelfde chunk): niets mag hergebruikt worden
    plan_groot = [["a", "b", "c", "d"]]
    parts_dir, _, te_doen = chunking.herstel_run(out_dir, plan_groot, opnieuw=False)
    assert te_doen == [0]
    assert not chunking.chunk_compleet(parts_dir, 0), "oude deelbestanden zijn niet opgeruimd"


def test_plan_vingerafdruk_onderscheidt_selectie_en_chunkgrootte():
    a = chunking.plan_vingerafdruk([["h1", "h2"], ["h3"]])
    assert a == chunking.plan_vingerafdruk([["h1", "h2"], ["h3"]])
    assert a != chunking.plan_vingerafdruk([["h1", "h2", "h3"]]), "andere chunkgrootte"
    assert a != chunking.plan_vingerafdruk([["h1", "h2"], ["h4"]]), "andere woningselectie"
    assert a != chunking.plan_vingerafdruk([["h3"], ["h1", "h2"]]), "andere volgorde"


def test_hervatten_weigert_deelbestanden_van_een_ander_uitvoercontract(tmp_path, monkeypatch):
    """Zelfde woningen en zelfde chunkgrootte, maar andere UITVOER_CONTRACT_VERSIE: niet hergebruiken.

    De planvingerafdruk alleen dekt dit niet -- daar zit precies het gat dat op 05-09-2026 bijna
    tot een stille fout leidde. Er stonden deelbestanden van vóór de weercorrectie, de
    tijdzone-omzetting en de kolomhernoemingen; het plan was identiek, dus zouden ze geaccepteerd
    zijn en had de run de oude uitvoer samengevoegd.
    """
    out_dir = tmp_path / "out"
    plan = [["a", "b"]]
    parts_dir, _, te_doen = chunking.herstel_run(out_dir, plan, opnieuw=False)
    assert te_doen == [0]
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, tabel, 0), pd.DataFrame({"x": [1]}))
    # zelfde contract: overslaan mag
    assert chunking.herstel_run(out_dir, plan, opnieuw=False)[2] == []

    # contract gewijzigd: alles opnieuw, ook al is het plan hetzelfde
    monkeypatch.setattr(chunking, "UITVOER_CONTRACT_VERSIE", "een-andere-versie")
    parts_dir, _, te_doen = chunking.herstel_run(out_dir, plan, opnieuw=False)
    assert te_doen == [0]
    assert not chunking.chunk_compleet(parts_dir, 0), "oude deelbestanden zijn niet opgeruimd"
