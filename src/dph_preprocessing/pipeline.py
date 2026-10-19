# SPDX-License-Identifier: EUPL-1.2
"""Orchestratie: bouwt homes/measurements/weer/quality/derived uit ``dph-dataset.zip`` (ontwerp
-preprocessing.md §4) en schrijft ``docs/data-quality.md`` (§7).

**Gechunkt en hervatbaar** (taak: de volledige dataset, ~174 woningen / 2,9 GB CSV, standalone
draaien met hervatten na een afbreking). Volgt het patroon van de IM3-zusterrepo (chunks van
woningen, incrementeel naar Parquet -- zie ``chunking.py``), met één toevoeging die IM3 niet had:
een onderbroken run hervat zonder de al voltooide chunks opnieuw te doen.

**Het knelpunt dat dit oplost.** ``bron.lees_domein`` leest per aanroep het HELE domeinbestand
(tot 962 MB voor ``dsmr.csv``). Zonder verdere maatregel zou dat per chunk opnieuw gebeuren: bij
zeven chunks van 25 woningen is dat zeven keer 2,9 GB lezen in plaats van één keer. Oplossing (zie
``bron.ZipBron.verdeel_domein_over_chunks`` en ``chunking.py``): elk domeinbestand wordt precies
ÉÉN keer gelezen en tijdens die ene pas al verdeeld over de chunks die nog gedaan moeten worden, als
tussenbestanden in ``<out-dir>/interim/``. Pas daarna verwerkt de chunk-loop elke chunk uit die
tussenbestanden, niet uit het bronbestand.

Gebruik als CLI: ``python -m dph_preprocessing --raw-dir data/raw --out-dir data/processed
--n-woningen 5``. Zonder ``--n-woningen``/``--home-ids`` wordt de VOLLEDIGE dataset (~174 woningen)
verwerkt -- een expliciete, aparte keuze, niet het standaardpad tijdens ontwikkeling.
``--chunk-grootte`` (standaard 25) bepaalt het piekgeheugen; ``--opnieuw`` gooit een eerdere
gedeeltelijke run weg en begint schoon (zonder die vlag wordt een eerdere, onderbroken run
hervat: chunks waarvan alle vijf tabellen al op schijf staan, worden overgeslagen).

**Eén netwerkstap:** de werkelijke calorische gaswaarde, nodig om ``g_gebruik__W`` uit m³ te
berekenen (``gaskwaliteit.py``, ontwerp §2.4). Die wordt per gasmaand opgehaald en in
``<out-dir>/gaskwaliteit/`` bewaard, dus een volgende chunk of een hervatte run haalt niets opnieuw
op. ``--skip-gaskwaliteit`` slaat het over en rekent met de vaste terugvalwaarde; het rapport telt
in beide gevallen hoeveel rijen op welke waarde leunen.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import bron as bron_mod
from . import chunking
from . import datapackage as datapackage_mod
from . import gaskwaliteit
from . import rapport
from . import tabellen
from .timestamps import naar_lokale_tijdzone

log = logging.getLogger(__name__)

DOMEIN_BESTANDEN_MET_TELLER = ("dsmr.csv", "kamstrup.csv", "heatpump.csv", "boiler.csv")
ALLE_DOMEIN_BESTANDEN = (*DOMEIN_BESTANDEN_MET_TELLER, "room.csv", "knmi.csv")

#: Submap van ``--out-dir`` waarin de opgehaalde calorische gaswaarden per gasmaand bewaard worden.
#: Bewust GEEN onderdeel van ``interim/`` (dat is wegwerpdata die per run opnieuw wordt gebouwd) en
#: bewust niet weggegooid door ``--opnieuw``: dit is een momentopname van een EXTERNE bron, geen
#: afgeleide van de ruwe data. Hem bewaren maakt een herhaalde run reproduceerbaar, ook als de
#: niet-gedocumenteerde API inmiddels andere waarden zou teruggeven.
GASKWALITEIT_CACHE_MAP = "gaskwaliteit"


def _domein_stem(bestandsnaam: str) -> str:
    return bestandsnaam.rsplit(".", 1)[0]


def _bouw_interim_voor_domein(
    bron: bron_mod.ZipBron, bestandsnaam: str, chunk_van_home_id: dict[str, int], interim_dir: Path
) -> None:
    """Verdeel ``bestandsnaam`` in ÉÉN streamende pas over de chunks in ``chunk_van_home_id``
    (zie module-docstring). Schrijft ``interim_dir/<stem>/chunk_<nnn>.parquet`` -- eerst als
    ``.tmp``, en pas hernoemd naar de definitieve naam nadat de VOLLEDIGE pas over het bronbestand
    zonder fouten is afgerond, zodat een afgebroken pas nooit een interim-bestand achterlaat dat
    voor compleet kan worden aangezien (zelfde atomiciteitsprincipe als ``chunking.
    schrijf_part_atomisch``, hier met de hand omdat er per domein N schrijvers tegelijk open staan).
    """
    stem = _domein_stem(bestandsnaam)
    domein_dir = interim_dir / stem
    domein_dir.mkdir(parents=True, exist_ok=True)

    schrijvers: dict[int, pq.ParquetWriter] = {}
    schemas: dict[int, pa.Schema] = {}
    n_gelezen_totaal = 0
    try:
        for chunk_idx, subset in bron.verdeel_domein_over_chunks(bestandsnaam, chunk_van_home_id):
            tabel = pa.Table.from_pandas(subset, preserve_index=False)
            if chunk_idx not in schrijvers:
                tmp_pad = domein_dir / f"chunk_{chunk_idx:03d}.parquet.tmp"
                schrijvers[chunk_idx] = pq.ParquetWriter(tmp_pad, tabel.schema, compression="snappy")
                schemas[chunk_idx] = tabel.schema
            else:
                tabel = tabel.cast(schemas[chunk_idx])
            schrijvers[chunk_idx].write_table(tabel)
            n_gelezen_totaal += tabel.num_rows
    finally:
        for schrijver in schrijvers.values():
            schrijver.close()

    # Pas NU, na een volledig geslaagde pas, de tmp-bestanden hernoemen naar hun definitieve naam.
    for chunk_idx in schrijvers:
        tmp_pad = domein_dir / f"chunk_{chunk_idx:03d}.parquet.tmp"
        tmp_pad.replace(domein_dir / f"chunk_{chunk_idx:03d}.parquet")

    log.info(
        "interim/%s: %d rij(en) verdeeld over %d chunk(s)", stem, n_gelezen_totaal, len(schrijvers)
    )


def _lees_ruw_voor_chunk(
    interim_dir: Path, metadata: pd.DataFrame, chunk_idx: int
) -> dict[str, pd.DataFrame]:
    """De 6 domeinbestanden voor chunk ``chunk_idx`` uit ``interim/`` (niet uit het bronbestand:
    dat is al in :func:`_bouw_interim_voor_domein` gebeurd). Een ontbrekend interim-bestand (een
    chunk kan toevallig 0 rijen voor een domein hebben) valt terug op een leeg frame met het juiste
    schema, in plaats van te falen."""
    ruw = {}
    for bestandsnaam in ALLE_DOMEIN_BESTANDEN:
        pad = interim_dir / _domein_stem(bestandsnaam) / f"chunk_{chunk_idx:03d}.parquet"
        if pad.is_file():
            ruw[bestandsnaam] = pd.read_parquet(pad)
        else:
            ruw[bestandsnaam] = bron_mod.lege_domein_frame(bestandsnaam, metadata)
    return ruw


def _gas_hhv_voor_chunk(dsmr_r: pd.DataFrame, cache_dir: Path | None) -> pd.DataFrame | None:
    """De calorische gaswaarden voor het tijdvenster van deze chunk, of ``None`` bij
    ``--skip-gaskwaliteit``.

    Het venster komt uit ``dsmr.csv``, want dat is de enige bron met een gasteller. Per chunk
    opnieuw bepalen (in plaats van één keer vooraf over de hele dataset) scheelt een extra
    volledige pas over de brondata puur om het tijdvenster te weten: elke chunk heeft de rijen die
    hij nodig heeft toch al in geheugen. De maand-cache in ``cache_dir`` maakt dat goedkoop, want
    de tweede chunk haalt niets meer op wat de eerste al heeft.
    """
    if cache_dir is None:
        return None
    tijd = dsmr_r["tijdstip_start"].dropna()
    if tijd.empty:
        return None
    return gaskwaliteit.fetch_actual_gas_hhv(tijd.min(), tijd.max(), cache_dir=cache_dir)


def _verwerk_en_schrijf_chunk(
    homes_ruw_alle: pd.DataFrame,
    interim_dir: Path,
    parts_dir: Path,
    metadata: pd.DataFrame,
    chunk_idx: int,
    chunk_ids: list[str],
    gaskwaliteit_cache_dir: Path | None = None,
) -> tuple[int, int]:
    """Verwerk chunk ``chunk_idx`` (de woningen in ``chunk_ids``) tot de vijf tabellen, en schrijf
    elk atomisch weg naar ``parts_dir``. Retourneert ``(n_measurements, n_quality)`` voor logging.

    ``gaskwaliteit_cache_dir`` is ``None`` bij ``--skip-gaskwaliteit``; dan valt ``g_gebruik__W``
    terug op de vaste calorische waarde (zichtbaar in ``gas_hhv_bron__cat``, geteld in het rapport).
    """
    ruw = _lees_ruw_voor_chunk(interim_dir, metadata, chunk_idx)

    homes_ruw_chunk = homes_ruw_alle[
        homes_ruw_alle[bron_mod.HOUSEHOLD_SLEUTEL_KOLOM].astype(str).isin(chunk_ids)
    ]
    homes_chunk = tabellen.build_homes(homes_ruw_chunk)

    resolved = {naam: tabellen.resolveer_domein(df) for naam, df in ruw.items()}
    gas_hhv = _gas_hhv_voor_chunk(resolved["dsmr.csv"], gaskwaliteit_cache_dir)
    measurements, quality, vermogens = tabellen.build_measurements_en_quality(
        resolved["dsmr.csv"], resolved["kamstrup.csv"], resolved["heatpump.csv"], resolved["boiler.csv"],
        gas_hhv=gas_hhv,
    )
    weer_chunk = tabellen.build_weer(resolved["knmi.csv"])
    home_station_chunk = tabellen.home_station_mapping(resolved["knmi.csv"])
    derived_chunk = tabellen.build_derived(
        vermogens,
        resolved["dsmr.csv"], resolved["kamstrup.csv"], resolved["heatpump.csv"], resolved["boiler.csv"],
        resolved["room.csv"], weer_chunk, home_station_chunk,
    )

    delen = {
        "homes": homes_chunk, "measurements": measurements, "quality": quality,
        "derived": derived_chunk, "weer": weer_chunk,
    }
    # Pas hier naar lokale tijd: intern is alles UTC (eenduidig voor joins en floor), de uitvoer is
    # tz-aware Europe/Amsterdam, gelijk aan de IM3-zusterrepo. Zie timestamps.naar_lokale_tijdzone.
    for naam, df in delen.items():
        chunking.schrijf_part_atomisch(
            chunking.chunk_pad(parts_dir, naam, chunk_idx), naar_lokale_tijdzone(df)
        )

    # "scheefheid" (analyses.py's A5) is BEWUST GEEN lid van chunking.PARTS_TABELLEN (dus geen
    # vereiste voor chunk_compleet/hervatten): het wordt hier meegeschreven omdat de resolved-frames
    # toch al in geheugen staan (geen extra I/O, zie tabellen.bouw_scheefheid_samenvatting), maar
    # zou als verplicht zesde deel elke chunk die al compleet was (vóór deze tabel bestond) bij de
    # eerstvolgende hervatting alsnog volledig laten herverwerken -- precies de dure herberekening
    # die deze tabel juist moet voorkomen.
    scheefheid_chunk = tabellen.bouw_scheefheid_samenvatting(
        {_domein_stem(b): resolved[b] for b in DOMEIN_BESTANDEN_MET_TELLER}
    )
    chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, "scheefheid", chunk_idx), scheefheid_chunk)

    return len(measurements), len(quality)


def run(
    raw_dir: str | Path,
    out_dir: str | Path,
    docs_dir: str | Path | None = "docs",
    n_woningen: int | None = None,
    home_ids: list[str] | None = None,
    chunk_grootte: int = chunking.CHUNK_GROOTTE_STANDAARD,
    opnieuw: bool = False,
    skip_gaskwaliteit: bool = False,
) -> dict[str, object]:
    """Bouwt de vijf contract-tabellen en (optioneel) ``docs/data-quality.md``.

    ``skip_gaskwaliteit=True`` slaat de netwerk-ingest van de werkelijke calorische gaswaarde over
    en rekent ``g_gebruik__W`` met de vaste terugvalwaarde. Bedoeld om zonder netwerk te kunnen
    draaien, niet als normale route: de uitkomst is dan een aanname, en het rapport zegt dat ook.

    Retourneert ``{"paden": {tabel: Path}, "n_rijen": {tabel: int}, "datapackage": Path}`` -- BEWUST
    niet de vijf DataFrames zelf: op de volledige dataset zou dat alsnog alles in geheugen laden, precies wat
    deze pijplijn probeert te vermijden. Wie de tabellen nodig heeft, leest ze terug via de paden
    (``pandas.read_parquet``/``pyarrow``), desgewenst gefilterd.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    gaskwaliteit_cache_dir = None if skip_gaskwaliteit else out_dir / GASKWALITEIT_CACHE_MAP
    if skip_gaskwaliteit:
        log.warning(
            "--skip-gaskwaliteit: g_gebruik__W rekent met de vaste waarde van %.2f MJ/m3 in plaats "
            "van de werkelijke, per uur gepubliceerde waarde.",
            gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / gaskwaliteit.MJ_NAAR_J,
        )

    bron = bron_mod.maak_bron(raw_dir)
    log.info("Ruwe databron: %s", bron.zip_pad)
    try:
        alle_home_ids = bron.home_ids()
        if home_ids is None:
            home_ids = alle_home_ids[:n_woningen] if n_woningen is not None else alle_home_ids
        is_steekproef = len(home_ids) < len(alle_home_ids)
        log.info("%d van %d woning(en) geselecteerd", len(home_ids), len(alle_home_ids))

        metadata = bron.metadata()
        homes_ruw = bron.homes_ruw()
        homes_ruw = homes_ruw[homes_ruw[bron_mod.HOUSEHOLD_SLEUTEL_KOLOM].astype(str).isin(home_ids)]

        chunks = chunking.verdeel_in_chunks(home_ids, chunk_grootte)
        log.info("%d chunk(s) van ten hoogste %d woning(en)", len(chunks), chunk_grootte)

        parts_dir, interim_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw)
        log.info("%d van %d chunk(s) moeten (opnieuw) gedaan worden", len(te_doen), len(chunks))

        if te_doen:
            # Interim is wegwerpdata (zie chunking.py's module-docstring): altijd vers opbouwen
            # voor precies de chunks die nog moeten, nooit hergebruikt van een vorige run.
            shutil.rmtree(interim_dir, ignore_errors=True)
            interim_dir.mkdir(parents=True, exist_ok=True)
            chunk_van_home_id_te_doen = {hid: i for i in te_doen for hid in chunks[i]}

            for bestandsnaam in ALLE_DOMEIN_BESTANDEN:
                t0 = time.monotonic()
                _bouw_interim_voor_domein(bron, bestandsnaam, chunk_van_home_id_te_doen, interim_dir)
                log.info(
                    "interim/%s opgebouwd in %.1f s (totaal verstreken: %.1f s)",
                    _domein_stem(bestandsnaam), time.monotonic() - t0, time.monotonic() - start,
                )

            for teller, chunk_idx in enumerate(te_doen, start=1):
                t0 = time.monotonic()
                n_meas, n_qual = _verwerk_en_schrijf_chunk(
                    homes_ruw, interim_dir, parts_dir, metadata, chunk_idx, chunks[chunk_idx],
                    gaskwaliteit_cache_dir=gaskwaliteit_cache_dir,
                )
                log.info(
                    "chunk %d/%d (index %d, %d woning(en)) verwerkt in %.1f s: "
                    "%d measurement-rij(en), %d quality-rij(en) (totaal verstreken: %.1f s)",
                    teller, len(te_doen), chunk_idx, len(chunks[chunk_idx]),
                    time.monotonic() - t0, n_meas, n_qual, time.monotonic() - start,
                )

            shutil.rmtree(interim_dir, ignore_errors=True)
        else:
            log.info("niets te doen: alle chunks waren al compleet")
    finally:
        bron.sluit()

    # --- samenvoegen: streamend voor de vier grote tabellen + homes, apart (met dedup) voor weer --
    paden: dict[str, Path] = {}
    n_rijen: dict[str, int] = {}
    for tabel in ("homes", "measurements", "quality", "derived"):
        pad = out_dir / f"{tabel}.parquet"
        n_rijen[tabel] = chunking.voeg_samen_streamend(parts_dir, tabel, len(chunks), pad)
        paden[tabel] = pad
        log.info("%s geschreven: %d rij(en) (%s)", pad.name, n_rijen[tabel], pad)

    weer_pad = out_dir / "weer.parquet"
    n_rijen["weer"] = chunking.voeg_weer_samen(parts_dir, len(chunks), weer_pad)
    paden["weer"] = weer_pad
    log.info("%s geschreven: %d rij(en) (%s)", weer_pad.name, n_rijen["weer"], weer_pad)

    # "scheefheid" is geen contracttabel en geen lid van chunking.PARTS_TABELLEN (zie
    # _verwerk_en_schrijf_chunk): een chunk die (nog) geen deelbestand voor deze tabel heeft,
    # levert dus gewoonweg minder rijen op in plaats van een fout (chunking.voeg_samen_streamend
    # slaat een ontbrekend deelbestand al over). Vindt deze run GEEN ENKEL scheefheid-deelbestand
    # (bv. een dataset die al volledig verwerkt was vóórdat deze tabel bestond, en verder gewoon
    # hervat wordt), dan schrijft voeg_samen_streamend niets -- het bestaande scheefheid.parquet
    # (bv. uit een eenmalige backfill) blijft dan ONAANGEROERD i.p.v. leeggemaakt te worden.
    scheefheid_pad = out_dir / "scheefheid.parquet"
    n_scheefheid = chunking.voeg_samen_streamend(parts_dir, "scheefheid", len(chunks), scheefheid_pad)
    if n_scheefheid == 0 and scheefheid_pad.is_file():
        n_scheefheid = pq.ParquetFile(scheefheid_pad).metadata.num_rows
        log.info("%s: geen enkel chunk had deze run een scheefheid-deel; bestaand bestand ongewijzigd (%d rij(en))", scheefheid_pad.name, n_scheefheid)
    else:
        log.info("%s geschreven: %d rij(en) (%s)", scheefheid_pad.name, n_scheefheid, scheefheid_pad)
    n_rijen["scheefheid"] = n_scheefheid
    paden["scheefheid"] = scheefheid_pad

    # De machineleesbare beschrijving van precies deze uitvoermap, naast de tabellen. Uit de code
    # (datapackage.py), dus geen invoer nodig; de kopie in de repo-root beschrijft beide paden samen.
    datapackage_pad = datapackage_mod.schrijf_datapackage(
        out_dir / datapackage_mod.DATAPACKAGE_BESTANDSNAAM, onderdeel="kwartier"
    )
    log.info("%s geschreven (%s)", datapackage_pad.name, datapackage_pad)

    if docs_dir is not None:
        docs_dir = Path(docs_dir)
        acc = rapport.RapportAccumulator()
        for chunk_idx in range(len(chunks)):
            m_pad = chunking.chunk_pad(parts_dir, "measurements", chunk_idx)
            q_pad = chunking.chunk_pad(parts_dir, "quality", chunk_idx)
            if not (m_pad.is_file() and q_pad.is_file()):
                log.warning("chunk %d: geen part-bestanden gevonden voor het rapport, overgeslagen", chunk_idx)
                continue
            # Alleen rapport.DERIVED_KOLOMMEN, niet de hele tabel: derived is met ruim 200 MB de
            # grootste van de vijf, en het rapport heeft er maar een handvol kolommen van nodig.
            # Een deelbestand van vóór die kolommen levert None op i.p.v. een fout.
            d_pad = chunking.chunk_pad(parts_dir, "derived", chunk_idx)
            derived_deel = None
            if d_pad.is_file():
                aanwezig = set(pq.ParquetFile(d_pad).schema_arrow.names)
                if set(rapport.DERIVED_KOLOMMEN) <= aanwezig:
                    derived_deel = pd.read_parquet(d_pad, columns=list(rapport.DERIVED_KOLOMMEN))
            acc.voeg_chunk_toe(pd.read_parquet(m_pad), pd.read_parquet(q_pad), derived=derived_deel)
        homes_volledig = pd.read_parquet(paden["homes"])
        rapport.write_report(docs_dir / "data-quality.md", homes=homes_volledig, acc=acc, is_steekproef=is_steekproef)
        log.info("data-quality.md geschreven naar %s", docs_dir / "data-quality.md")

    log.info("Klaar in %.1f s", time.monotonic() - start)
    return {"paden": paden, "n_rijen": n_rijen, "datapackage": datapackage_pad}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"), help="Pad naar dph-dataset.zip, of een map waarin die staat")
    p.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    p.add_argument("--docs-dir", type=Path, default=Path("docs"))
    p.add_argument("--n-woningen", type=int, default=None, help="Verwerk alleen de eerste N woningen")
    p.add_argument("--home-ids", nargs="*", default=None, help="Verwerk alleen deze specifieke home_id's")
    p.add_argument(
        "--chunk-grootte",
        type=int,
        default=chunking.CHUNK_GROOTTE_STANDAARD,
        help=f"Aantal woningen per chunk; bepaalt het piekgeheugen (standaard {chunking.CHUNK_GROOTTE_STANDAARD})",
    )
    p.add_argument(
        "--opnieuw",
        action="store_true",
        help="Gooi een eerdere (gedeeltelijke) run weg en begin schoon, i.p.v. te hervatten",
    )
    p.add_argument(
        "--skip-gaskwaliteit",
        action="store_true",
        help=(
            "Haal de werkelijke calorische gaswaarde NIET op (geen netwerk) en reken g_gebruik__W "
            "met de vaste terugvalwaarde; het rapport meldt hoeveel rijen dat raakt"
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run(
        args.raw_dir,
        args.out_dir,
        docs_dir=args.docs_dir,
        n_woningen=args.n_woningen,
        home_ids=args.home_ids,
        chunk_grootte=args.chunk_grootte,
        opnieuw=args.opnieuw,
        skip_gaskwaliteit=args.skip_gaskwaliteit,
    )


if __name__ == "__main__":
    main()
