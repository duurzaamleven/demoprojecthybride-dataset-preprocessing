# SPDX-License-Identifier: EUPL-1.2
"""Chunked, hervatbare verwerking van de woningen (taak: volledige dataset, ~174 woningen). Volgt
het patroon van de IM3-zusterrepo
(``ontwerp-preprocessing.md`` §12.9 daar: woningen in blokken verwerken en incrementeel naar
Parquet wegschrijven, zodat het piekgeheugen bepaald wordt door de chunkgrootte, niet door de
datasetomvang) met één toevoeging die IM3 niet had: HERVATTEN na een afbreking.

**Twee lagen bewaring, met opzet verschillend duurzaam:**

1. ``<out-dir>/parts/<tabel>/chunk_<nnn>.parquet`` -- het resultaat per tabel per chunk. Dit is de
   enige laag die hervatten mogelijk maakt: een chunk waarvan alle vijf tabellen hier compleet
   staan, wordt bij een volgende run OVERGESLAGEN (:func:`chunk_compleet`). Geschreven met een
   atomische hernoeming (``.tmp`` -> definitieve naam, :func:`schrijf_part_atomisch`): een halverwege
   afgebroken schrijfactie laat nooit een bestand achter met de definitieve naam, dus die kan nooit
   voor compleet worden aangezien.
2. ``<out-dir>/interim/<domein_stem>/chunk_<nnn>.parquet`` -- het RUWE domeinbestand
   (``dsmr.csv``, ...) opgesplitst per chunk, zodat elk domeinbestand maar ÉÉN keer gelezen hoeft
   te worden per run in plaats van eenmaal per chunk (het knelpunt uit de taakomschrijving: 6
   bestanden x N chunks x tot 962 MB is onacceptabel). Deze laag is BEWUST NIET zelf hervatbaar: hij
   wordt bij elke run die nog iets te doen heeft, leeg opgehaald en opnieuw opgebouwd, alleen voor de
   chunks die nog moeten (her)gebeuren. Reden: een domeinbestand is niet op woning gesorteerd (zie
   bron.py), dus "alleen de ontbrekende chunks aanvullen" zou alsnog een volledige pas over het
   bestand vergen -- er is dus niets te winnen bij het BEWAREN van een gedeeltelijke interim-split
   over een afbreking heen, en veel te verliezen aan complexiteit (een manifest bijhouden, staleness
   detecteren bij een andere ``--chunk-grootte``/woningselectie, ...). De eenvoudigste keuze is dus:
   interim is wegwerpdata binnen één run, alleen ``parts/`` is duurzaam. Zie
   ``pipeline.run`` voor waar dat wordt afgewogen.

Er staat nog een derde map in ``<out-dir>``, die niet van deze module is en aan geen van beide
lagen meedoet: ``gaskwaliteit/`` (:data:`pipeline.GASKWALITEIT_CACHE_MAP`), de opgehaalde calorische
gaswaarden per gasmaand. Dat is een momentopname van een externe bron, geen afgeleide van de ruwe
data, en wordt daarom noch per run opnieuw gebouwd noch door ``--opnieuw`` weggegooid.
"""

from __future__ import annotations

import hashlib
import json

import logging
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

#: Bovengrens aan de row-group-grootte in de samengevoegde output, losgekoppeld van
#: --chunk-grootte (zelfde redenering als IM3, ontwerp-preprocessing.md §12.12 daar): zonder deze
#: grens zou een lezer van de output gedwongen worden een hele chunk in één keer in te lezen.
ROW_GROUP_MAX = 1_000_000

#: De vijf contract-tabellen die per chunk als apart deelbestand geschreven worden. ``weer`` hoort
#: hier ook bij (ook al is de UITEINDELIJKE weer.parquet per station, niet per woning): per chunk
#: bevat het deelbestand het weer van de woningen IN die chunk, met overlap tussen chunks mogelijk
#: (zie tabellen.build_weer/derived); de eindsamenvoeging in pipeline.py ontdubbelt dat.
#:
#: ``pipeline.py`` schrijft daarnaast een ZESDE, niet-contractueel deelbestand per chunk,
#: ``scheefheid`` (de samenvatting achter A5, zie ``tabellen.bouw_scheefheid_samenvatting``).
#: Die staat HIER BEWUST NIET bij: :func:`chunk_compleet` (en dus ``herstel_run``'s
#: hervat-beslissing) mag niet van 'm afhangen, want dat zou een dataset die al compleet was VOORDAT
#: deze tabel bestond bij de eerstvolgende hervatting alsnog volledig laten herverwerken (de hele
#: dure CSV-lezing + tabelopbouw opnieuw) puur om één klein deelbestand aan te vullen -- terwijl het
#: hele punt van die tabel is een latere, dure herberekening te VOORKOMEN. ``scheefheid`` wordt dus
#: los van ``PARTS_TABELLEN`` weggeschreven/samengevoegd (zie ``pipeline._verwerk_en_schrijf_chunk``
#: / ``pipeline.run``): een chunk die (nog) geen ``scheefheid``-deel heeft levert bij het
#: samenvoegen gewoon minder rijen op, geen fout.
PARTS_TABELLEN = ("homes", "measurements", "quality", "derived", "weer")

CHUNK_GROOTTE_STANDAARD = 25


def verdeel_in_chunks(home_ids: list[str], chunk_grootte: int) -> list[list[str]]:
    """Verdeel ``home_ids`` (in de gegeven volgorde) in opeenvolgende blokken van ``chunk_grootte``."""
    if chunk_grootte < 1:
        raise ValueError(f"chunk_grootte moet >= 1 zijn, kreeg {chunk_grootte}")
    return [home_ids[i : i + chunk_grootte] for i in range(0, len(home_ids), chunk_grootte)]


def chunk_van_home_id(chunks: list[list[str]]) -> dict[str, int]:
    """``home_id -> chunk-index`` over ALLE chunks; de inverse van :func:`verdeel_in_chunks`."""
    return {home_id: i for i, ids in enumerate(chunks) for home_id in ids}


def chunk_pad(parts_dir: Path, tabel: str, chunk_idx: int) -> Path:
    """Het pad van het deelbestand van ``tabel`` voor chunk ``chunk_idx``."""
    return parts_dir / tabel / f"chunk_{chunk_idx:03d}.parquet"


def chunk_compleet(parts_dir: Path, chunk_idx: int, tabellen: tuple[str, ...] = PARTS_TABELLEN) -> bool:
    """True als voor ``chunk_idx`` ALLE tabellen een (definitief, niet-``.tmp``) deelbestand hebben.

    Dit is de hervat-check: alleen als dit True is, mag een chunk overgeslagen worden. Eén
    ontbrekende tabel (bv. het proces stierf na het schrijven van ``measurements`` maar vóór
    ``derived``) is genoeg om de hele chunk als "nog te doen" te behandelen -- zie
    :func:`ruim_chunk_op`.
    """
    return all(chunk_pad(parts_dir, tabel, chunk_idx).is_file() for tabel in tabellen)


def ruim_chunk_op(parts_dir: Path, chunk_idx: int, tabellen: tuple[str, ...] = PARTS_TABELLEN) -> None:
    """Verwijder alle (mogelijk halve) deelbestanden van ``chunk_idx``, inclusief eventuele
    achtergebleven ``.tmp``-bestanden van een eerdere, afgebroken poging. Bedoeld om vooraf te
    draaien voor elke chunk die opnieuw (of voor het eerst) gedaan gaat worden, zodat een oude,
    inconsistente deelverzameling nooit blijft liggen naast de nieuwe."""
    for tabel in tabellen:
        pad = chunk_pad(parts_dir, tabel, chunk_idx)
        for kandidaat in (pad, pad.with_suffix(pad.suffix + ".tmp")):
            if kandidaat.exists():
                kandidaat.unlink()


def schrijf_part_atomisch(pad: Path, df: pd.DataFrame) -> None:
    """Schrijf ``df`` naar ``pad`` via een tijdelijk bestand + hernoeming, zodat een halverwege
    afgebroken schrijfactie nooit een bestand met de DEFINITIEVE naam achterlaat (de garantie
    waarop :func:`chunk_compleet` leunt). ``Path.replace`` is op één filesystem atomisch."""
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(pad)


#: Naam van het bestandje waarin het chunkplan van een run wordt vastgelegd (:func:`plan_vingerafdruk`).
PLAN_BESTAND = "plan.json"

#: Versie van het UITVOERCONTRACT: kolomnamen, eenheden, tijdzone en de semantiek van de waarden.
#:
#: **Hoog dit op zodra de uitvoer van vorm of betekenis verandert.** De vingerafdruk van het
#: chunkplan alleen is niet genoeg, en dat is op 05-09-2026 bijna misgegaan: na een dag waarin het
#: weer een uur verschoof, de tijdzone naar Europe/Amsterdam ging, ``ghi__kWh_m_2`` ``ghi__W_m_2``
#: werd en de kolommen ``__flag``/``_cum`` kregen, stonden er nog deelbestanden van de OUDE code op
#: schijf. Dezelfde woningen, dezelfde chunkgrootte, dus dezelfde planvingerafdruk -- de hervatting
#: zou ze klakkeloos hebben geaccepteerd en de oude uitvoer hebben samengevoegd. Zonder foutmelding.
#:
#: Dit is bewust een HANDMATIGE teller en geen automatische schemavergelijking. Automatisch zou
#: vergen dat je eerst een chunk bouwt om te weten wat de huidige code oplevert, en juist in het
#: geval dat ertoe doet -- alle chunks al "compleet" -- bouw je er geen. Een expliciete versie is
#: minder elegant en wel betrouwbaar; hem vergeten op te hogen is een zichtbare fout in een diff,
#: een stille schemadrift niet.
UITVOER_CONTRACT_VERSIE = "2026-09-22-teller-artefacten"


def plan_vingerafdruk(chunks: list[list[str]]) -> str:
    """Een vingerafdruk van het chunkplan: welke woningen in welke chunk, in welke volgorde.

    Hervatten mag alleen als de bestaande deelbestanden bij HETZELFDE plan horen. Zonder deze
    controle kijkt :func:`chunk_compleet` alleen of de bestanden bestaan, en dan wordt een
    ``chunk_000.parquet`` uit een eerdere proefrun met 5 woningen klakkeloos hergebruikt als chunk 1
    van een run met 25 woningen per chunk -- de uitvoer mist dan stilzwijgend 20 woningen. Dat is
    één keer echt gebeurd (05-09-2026) en is de reden dat deze functie bestaat: een hervatting die
    ongemerkt het verkeerde antwoord geeft is erger dan geen hervatting.

    De vingerafdruk dekt **twee** dingen: welke woningen in welke chunk zitten, én
    :data:`UITVOER_CONTRACT_VERSIE`. Dat tweede is er later bij gekomen omdat het eerste niet
    genoeg bleek: bij ongewijzigde woningselectie en chunkgrootte, maar gewijzigde uitvoer, is het
    plan identiek en zouden deelbestanden van de oude code alsnog geaccepteerd worden.
    """
    ruw = json.dumps(
        {"chunks": chunks, "contract": UITVOER_CONTRACT_VERSIE},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(ruw).hexdigest()


def _lees_plan(parts_dir: Path) -> str | None:
    pad = parts_dir / PLAN_BESTAND
    if not pad.is_file():
        return None
    try:
        return json.loads(pad.read_text(encoding="utf-8")).get("vingerafdruk")
    except (json.JSONDecodeError, OSError):
        return None


def _schrijf_plan(parts_dir: Path, chunks: list[list[str]]) -> None:
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / PLAN_BESTAND).write_text(
        json.dumps(
            {
                "vingerafdruk": plan_vingerafdruk(chunks),
                "n_chunks": len(chunks),
                "n_woningen": sum(len(c) for c in chunks),
                "chunk_grootte": max((len(c) for c in chunks), default=0),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def herstel_run(out_dir: Path, chunks: list[list[str]], opnieuw: bool) -> tuple[Path, Path, list[int]]:
    """Bepaal ``(parts_dir, interim_dir, te_doen)`` aan het begin van een run.

    ``--opnieuw`` gooit ``parts/`` en ``interim/`` helemaal weg en begint schoon (``te_doen`` = alle
    chunks). Anders wordt eerst gecontroleerd of de aanwezige deelbestanden bij HETZELFDE chunkplan
    horen (:func:`plan_vingerafdruk`); zo niet, dan worden ze weggegooid, want ze gaan dan over een
    andere woningselectie of een andere ``--chunk-grootte``. Pas daarna wordt per chunk gekeken of
    hij al compleet is (:func:`chunk_compleet`); zo ja, wordt hij overgeslagen (gelogd, niet
    stilzwijgend), zo nee, worden zijn eventuele halve deelbestanden eerst opgeruimd
    (:func:`ruim_chunk_op`) zodat hij schoon opnieuw gedaan wordt.
    """
    parts_dir = out_dir / "parts"
    interim_dir = out_dir / "interim"

    if opnieuw:
        log.info("--opnieuw: parts/ en interim/ worden gewist, alle chunks worden (her)gedaan")
        shutil.rmtree(parts_dir, ignore_errors=True)
        shutil.rmtree(interim_dir, ignore_errors=True)
        _schrijf_plan(parts_dir, chunks)
        return parts_dir, interim_dir, list(range(len(chunks)))

    bestaand = _lees_plan(parts_dir)
    huidig = plan_vingerafdruk(chunks)
    if parts_dir.exists() and bestaand != huidig:
        log.warning(
            "De aanwezige deelbestanden horen bij een ANDER chunkplan (%s) dan dit (%s); ze worden "
            "weggegooid en alle chunks worden opnieuw gedaan. Hervatten is alleen geldig binnen "
            "hetzelfde plan: zelfde woningselectie, zelfde chunkgrootte.",
            bestaand or "geen plan vastgelegd",
            huidig[:12],
        )
        shutil.rmtree(parts_dir, ignore_errors=True)
        shutil.rmtree(interim_dir, ignore_errors=True)
        _schrijf_plan(parts_dir, chunks)
        return parts_dir, interim_dir, list(range(len(chunks)))
    _schrijf_plan(parts_dir, chunks)

    te_doen = []
    for i in range(len(chunks)):
        if chunk_compleet(parts_dir, i):
            log.info("chunk %d/%d: al compleet, wordt overgeslagen", i + 1, len(chunks))
        else:
            log.info("chunk %d/%d: (nog) niet compleet, wordt (opnieuw) gedaan", i + 1, len(chunks))
            ruim_chunk_op(parts_dir, i)
            te_doen.append(i)
    return parts_dir, interim_dir, te_doen


def voeg_samen_streamend(parts_dir: Path, tabel: str, n_chunks: int, uitvoer_pad: Path) -> int:
    """Voeg alle ``chunk_*.parquet``-delen van ``tabel`` samen tot ``uitvoer_pad``, STREAMEND
    (``pyarrow.parquet.ParquetWriter`` + rij-groep-voor-rij-groep lezen), zonder ooit de volledige
    tabel als pandas-DataFrame in geheugen te nemen. Dit is de vereiste uit de taakomschrijving:
    "streamend met pyarrow.parquet.ParquetWriter (dus NIET alles in pandas laden)".

    Voor ``homes`` is dit méér dan strikt nodig (174 rijen past moeiteloos in pandas), maar dezelfde
    route houdt de merge-logica voor alle vier de grote tabellen (en homes) identiek en eenvoudig.
    ``weer`` gebruikt bewust een ANDERE route, zie :func:`voeg_weer_samen`.

    Retourneert het totaal aantal weggeschreven rijen.
    """
    schema = None
    writer: pq.ParquetWriter | None = None
    n_rijen = 0
    try:
        for i in range(n_chunks):
            pad = chunk_pad(parts_dir, tabel, i)
            if not pad.is_file():
                continue  # kan voorkomen als een chunk leeg was (zie schrijf_part_atomisch-aanroeper)
            parquet_file = pq.ParquetFile(pad)
            for row_group_idx in range(parquet_file.num_row_groups):
                tabel_arrow = parquet_file.read_row_group(row_group_idx)
                if writer is None:
                    schema = tabel_arrow.schema
                    writer = pq.ParquetWriter(uitvoer_pad, schema, compression="snappy")
                else:
                    tabel_arrow = tabel_arrow.cast(schema)
                writer.write_table(tabel_arrow, row_group_size=ROW_GROUP_MAX)
                n_rijen += tabel_arrow.num_rows
    finally:
        if writer is not None:
            writer.close()
    return n_rijen


def voeg_weer_samen(parts_dir: Path, n_chunks: int, uitvoer_pad: Path) -> int:
    """Voeg de per-chunk ``weer``-delen samen tot ``weer.parquet``, met ontdubbeling op
    (``weerstation_nr``, ``tijdstip_start``) -- ANDERS dan :func:`voeg_samen_streamend`.

    **Waarom een andere route.** ``weer`` is niet per woning maar per station (ontwerp-
    preprocessing.md §4): meerdere woningen op hetzelfde station leveren in hun eigen chunk
    dezelfde (station, uur)-rijen, dus simpelweg concateneren zou duplicaten opleveren. Ontdubbelen
    vraagt de volledige verzameling tegelijk (``drop_duplicates`` kan niet streamend over
    afzonderlijke Parquet-rijgroepen heen). Dat mag hier wél in pandas: het totaal is per
    definitie klein (stations x uren, niet woningen x kwartieren) -- voor de proefrun van 5 woningen
    op 1-2 stations ruim onder een MB, en voor de volle 174 woningen op naar schatting enkele
    tientallen stations nog steeds een fractie van de kwartierdata.
    """
    delen = []
    for i in range(n_chunks):
        pad = chunk_pad(parts_dir, "weer", i)
        if pad.is_file():
            delen.append(pd.read_parquet(pad))
    if not delen:
        return 0
    samengevoegd = (
        pd.concat(delen, ignore_index=True)
        .drop_duplicates(subset=["weerstation_nr", "tijdstip_start"])
        .sort_values(["weerstation_nr", "tijdstip_start"])
        .reset_index(drop=True)
    )
    samengevoegd.to_parquet(uitvoer_pad, index=False)
    return len(samengevoegd)
