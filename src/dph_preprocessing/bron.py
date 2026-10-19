# SPDX-License-Identifier: EUPL-1.2
"""Streamend lezen uit ``dph-dataset.zip`` + schema-validatie tegen ``metadata.csv``
(ontwerp-preprocessing.md §1, §4; zie ook de zusterrepo's ``im3_preprocessing.bron``/``io``).

**Structureel anders dan bij IM3.** De Installatiemonitor levert één CSV per woning; deze dataset
levert één CSV per *meetbron* (``dsmr.csv``, ``kamstrup.csv``, ...) met ALLE woningen erin. Filteren
op een deelverzameling woningen kan hier dus niet door een los bestand te openen, maar vereist een
streamende scan van het hele bronbestand met een rij-filter. Een steekproef (26-aug-2026) van
``dsmr.csv`` liet zien dat de 174 woningen NIET in aaneengesloten blokken per woning staan (dezelfde
woning duikt verderop in het bestand opnieuw op, vermoedelijk door batchgewijze aanlevering); een
"stop zodra de gevraagde woningen gezien zijn"-optimalisatie is dus niet veilig, en deze module doet
bewust een volledige streamende pas per bronbestand, met ``pandas.read_csv(..., chunksize=...)``
rechtstreeks op de ``zipfile.ZipExtFile`` (nooit uitgepakt naar schijf, net als bij IM3).

**Twee schema-afwijkingen tussen ``metadata.csv``/``docs/variable-dictionary.md`` en de
werkelijke koppen, geverifieerd in de data zelf (niet aangenomen):**

1. ``heatpump.csv`` en ``boiler.csv`` hebben in werkelijkheid de kale kolomnamen
   ``power,voltage,current,energy`` (in beide bestanden identiek), niet de door
   ``metadata.csv``/de variable-dictionary gesuggereerde ``heatpump_power``/``boiler_power`` etc.
   De disambiguatie gebeurt uitsluitend via de bestandsnaam. :data:`KOLOM_HERNOEM_RUW` corrigeert
   dit vlak na het lezen, zodat de rest van de pijplijn wél de gedocumenteerde namen ziet.
2. ``household.csv`` heeft zijn sleutelkolom ``participant_id`` (niet ``location_id`` zoals de
   overige zes bestanden) én een kolom ``wrong_elec_measurement`` (0/1/2; de betekenis staat NIET
   in ``metadata.csv`` maar wel in ``notebooks/README.md`` van het meegeleverde analysepakket: of
   de elektriciteitsmeting van de warmtepomp van die woning bruikbaar is). Geen van beide staat in
   ``docs/variable-dictionary.md``'s brontabel. ``wrong_elec_measurement`` wordt hier geaccepteerd
   in de schema-validatie (het is een echte, geverifieerde kolom, geen datadefect) én doorgezet
   naar ``homes.parquet`` als ``elektrameting_verdacht__cat`` (ontwerp §8, A2; zie
   :func:`dph_preprocessing.tabellen.build_homes`).
"""

from __future__ import annotations

import logging
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

import pandas as pd

log = logging.getLogger(__name__)

METADATA_BESTANDSNAAM = "metadata.csv"
HOUSEHOLD_BESTANDSNAAM = "household.csv"

# De zes "domein"-bestanden die location_id/timestamp als sleutel hebben (ontwerp §1). household.csv
# staat hier bewust niet bij: dat heeft geen tijdreeks, en een eigen sleutelkolom (zie boven).
DOMEIN_BESTANDEN = ("dsmr.csv", "kamstrup.csv", "heatpump.csv", "boiler.csv", "room.csv", "knmi.csv")

CHUNKSIZE_STANDAARD = 250_000

# Zie module-docstring, afwijking 1.
KOLOM_HERNOEM_RUW: dict[str, dict[str, str]] = {
    "heatpump.csv": {"power": "heatpump_power", "voltage": "heatpump_voltage", "current": "heatpump_current", "energy": "heatpump_energy"},
    "boiler.csv": {"power": "boiler_power", "voltage": "boiler_voltage", "current": "boiler_current", "energy": "boiler_energy"},
}

# Zie module-docstring, afwijking 2: kolommen die in de data zelf voorkomen maar niet in
# metadata.csv gedocumenteerd staan. Vast gecodeerd na verificatie tegen de echte header
# (26-aug-2026), niet afgeleid: metadata.csv is hier zelf onvolledig.
HOUSEHOLD_SLEUTEL_KOLOM = "participant_id"
HOUSEHOLD_ONGEDOCUMENTEERDE_KOLOMMEN = ("wrong_elec_measurement",)


class BronError(ValueError):
    """De opgegeven ruwe-databron is niet bruikbaar. Hoort niet stil te falen."""


class SchemaError(ValueError):
    """Structureel schemaprobleem: een verwachte kolom ontbreekt, of een onverwachte kolom is
    aangetroffen. Faalt hard en vroeg (vóór er ook maar één rij verwerkt is), zoals gevraagd."""


def lees_metadata(stream: IO[bytes]) -> pd.DataFrame:
    """Lees ``metadata.csv`` (het variabelenwoordenboek van de dataset zelf) in.

    Kolommen: ``velden, toelichting, document, eenheid_groot, eenheid_klein, resolutie, decimalen,
    extra_omschrijving``. ``document`` is de bronbestandsnaam waar het veld in voorkomt, of
    ``"ALL"`` voor ``location_id``/``timestamp`` (in elk van de zes domeinbestanden aanwezig).
    """
    verwacht = {
        "velden", "toelichting", "document", "eenheid_groot", "eenheid_klein", "resolutie",
        "decimalen", "extra_omschrijving",
    }
    # metadata.csv is GEEN geldige UTF-8 (geverifieerd: "ampère" bevat een 0xE8-byte die als UTF-8
    # niet decodeert), maar wel geldig Windows-1252 -- een kenmerk van het bronbestand zelf, geen
    # aanname van deze implementatie.
    df = pd.read_csv(stream, encoding="cp1252")
    ontbrekend = verwacht - set(df.columns)
    if ontbrekend:
        raise SchemaError(f"{METADATA_BESTANDSNAAM}: ontbrekende kolommen {sorted(ontbrekend)}")
    return df


def verwachte_kolommen(metadata: pd.DataFrame, bestandsnaam: str) -> set[str]:
    """De volledige verzameling kolomnamen die in ``bestandsnaam`` verwacht mag worden.

    Voor de zes domeinbestanden: alle ``velden`` met ``document in {bestandsnaam, "ALL"}``, met de
    kolomnaam-correctie van :data:`KOLOM_HERNOEM_RUW` toegepast in omgekeerde richting (de RUWE
    naam die metadata.csv niet gebruikt, maar het bestand zelf wel).

    Voor ``household.csv``: de rijen met ``document == "household.csv"``, aangevuld met de twee
    kolommen die metadata.csv niet documenteert (zie module-docstring, afwijking 2).
    """
    if bestandsnaam == HOUSEHOLD_BESTANDSNAAM:
        namen = set(metadata.loc[metadata["document"] == HOUSEHOLD_BESTANDSNAAM, "velden"])
        return namen | {HOUSEHOLD_SLEUTEL_KOLOM} | set(HOUSEHOLD_ONGEDOCUMENTEERDE_KOLOMMEN)

    namen = set(metadata.loc[metadata["document"].isin({bestandsnaam, "ALL"}), "velden"])
    hernoem = KOLOM_HERNOEM_RUW.get(bestandsnaam)
    if hernoem:
        # hernoem is {ruwe_naam: metadata_naam}; metadata_naam moet vervangen worden door
        # ruwe_naam in de verwachte-kolommenset, want DIE staat werkelijk in het bestand.
        omgekeerd = {v: k for k, v in hernoem.items()}
        namen = {omgekeerd.get(n, n) for n in namen}
    return namen


def lege_domein_frame(bestandsnaam: str, metadata: pd.DataFrame) -> pd.DataFrame:
    """Een leeg (0-rijen) DataFrame met exact de kolommen die :meth:`ZipBron.lees_domein`/
    :meth:`ZipBron.verdeel_domein_over_chunks` voor ``bestandsnaam`` zouden opleveren. Gebruikt
    zowel als "geen rijen gevonden voor deze selectie"-resultaat als (in ``chunking``/``pipeline``)
    als terugval wanneer een chunk toevallig geen enkele rij voor dit domein bleek te hebben."""
    hernoem = dict(KOLOM_HERNOEM_RUW.get(bestandsnaam, {}))
    hernoem["location_id"] = "home_id__str"
    kolommen = [hernoem.get(c, c) for c in verwachte_kolommen(metadata, bestandsnaam)]
    return pd.DataFrame(columns=sorted(kolommen))


def _valideer_header(bestandsnaam: str, actuele_kolommen: list[str], metadata: pd.DataFrame) -> None:
    verwacht = verwachte_kolommen(metadata, bestandsnaam)
    actueel = set(actuele_kolommen)
    ontbrekend = verwacht - actueel
    onverwacht = actueel - verwacht
    if ontbrekend or onverwacht:
        delen = []
        if ontbrekend:
            delen.append(f"ontbrekend: {sorted(ontbrekend)}")
        if onverwacht:
            delen.append(f"onverwacht: {sorted(onverwacht)}")
        raise SchemaError(f"{bestandsnaam}: schema wijkt af van metadata.csv ({'; '.join(delen)})")


class ZipBron:
    """Het gedownloade ``dph-dataset.zip``, uitsluitend streamend gelezen (nooit uitgepakt naar
    schijf, ontwerp §1 / GEBRUIKSVOORWAARDEN.md).
    """

    def __init__(self, zip_pad: str | Path):
        self.zip_pad = Path(zip_pad)
        if not self.zip_pad.is_file():
            raise BronError(f"Geen bestand: {self.zip_pad}")
        self._zip = zipfile.ZipFile(self.zip_pad)
        self._namen = set(self._zip.namelist())
        for verplicht in (METADATA_BESTANDSNAAM, HOUSEHOLD_BESTANDSNAAM, *DOMEIN_BESTANDEN):
            if verplicht not in self._namen:
                raise BronError(f"{self.zip_pad.name}: {verplicht} ontbreekt in het archief")
        self._metadata: pd.DataFrame | None = None
        self._home_ids: list[str] | None = None

    def sluit(self) -> None:
        self._zip.close()

    def __enter__(self) -> "ZipBron":
        return self

    def __exit__(self, *exc) -> None:
        self.sluit()

    @contextmanager
    def _open(self, naam: str) -> Iterator[IO[bytes]]:
        with self._zip.open(naam) as f:
            yield f

    def metadata(self) -> pd.DataFrame:
        """Het variabelenwoordenboek, één keer gelezen en gecachet."""
        if self._metadata is None:
            with self._open(METADATA_BESTANDSNAAM) as f:
                self._metadata = lees_metadata(f)
        return self._metadata

    def home_ids(self) -> list[str]:
        """Alle ``home_id``'s (``participant_id`` uit ``household.csv``), gesorteerd."""
        if self._home_ids is None:
            self._home_ids = sorted(self.homes_ruw()[HOUSEHOLD_SLEUTEL_KOLOM].astype(str))
        return self._home_ids

    def homes_ruw(self) -> pd.DataFrame:
        """De ruwe ``household.csv``, schema-gevalideerd. Klein (174 rijen), dus in één keer."""
        with self._open(HOUSEHOLD_BESTANDSNAAM) as f:
            df = pd.read_csv(f, dtype={HOUSEHOLD_SLEUTEL_KOLOM: str})
        _valideer_header(HOUSEHOLD_BESTANDSNAAM, list(df.columns), self.metadata())
        return df

    def lees_domein(
        self,
        bestandsnaam: str,
        gevraagde_home_ids: list[str],
        chunksize: int = CHUNKSIZE_STANDAARD,
    ) -> pd.DataFrame:
        """Streamend filteren: lees ``bestandsnaam`` in blokken van ``chunksize`` rijen en houd
        alleen de rijen van ``gevraagde_home_ids`` over. Schema wordt op het EERSTE blok
        gevalideerd -- een onverwachte kolom faalt dus vóór er ook maar één blok verder gelezen is.

        Geeft de kolommen terug zoals ze in het bestand staan (nog niet hernoemd naar de
        variable-dictionary-namen), met :data:`KOLOM_HERNOEM_RUW` al toegepast waar van
        toepassing, plus een ``home_id__str``-kolom (hernoemd van ``location_id``).
        """
        if bestandsnaam not in DOMEIN_BESTANDEN:
            raise BronError(f"Onbekend domeinbestand: {bestandsnaam}")

        gevraagd = set(gevraagde_home_ids)
        metadata = self.metadata()
        delen: list[pd.DataFrame] = []
        n_gelezen = 0

        with self._open(bestandsnaam) as f:
            for i, chunk in enumerate(pd.read_csv(f, chunksize=chunksize, dtype={"location_id": str})):
                if i == 0:
                    _valideer_header(bestandsnaam, list(chunk.columns), metadata)
                n_gelezen += len(chunk)
                gefilterd = chunk.loc[chunk["location_id"].isin(gevraagd)]
                if len(gefilterd):
                    delen.append(gefilterd)

        log.info(
            "%s: %d rij(en) gelezen (streamend), %d overgehouden voor %d woning(en)",
            bestandsnaam, n_gelezen, sum(len(d) for d in delen), len(gevraagd),
        )

        if not delen:
            return lege_domein_frame(bestandsnaam, metadata)

        hernoem = dict(KOLOM_HERNOEM_RUW.get(bestandsnaam, {}))
        hernoem["location_id"] = "home_id__str"
        resultaat = pd.concat(delen, ignore_index=True)
        return resultaat.rename(columns=hernoem)

    def verdeel_domein_over_chunks(
        self,
        bestandsnaam: str,
        chunk_van_home_id: dict[str, int],
        chunksize: int = CHUNKSIZE_STANDAARD,
    ) -> Iterator[tuple[int, pd.DataFrame]]:
        """Zoals :meth:`lees_domein`, maar verdeeld over MEERDERE chunks in ÉÉN streamende pas,
        in plaats van gefilterd op één enkele home_id-lijst.

        **Waarom dit bestaat (pipeline.py, ``ontwerp-preprocessing.md`` §4 van deze taak).** Zonder
        dit zou elk domeinbestand (tot 962 MB voor ``dsmr.csv``) EENMAAL PER CHUNK gelezen moeten
        worden: bij bv. 7 chunks van 25 woningen is dat 7 volledige passes over 2,9 GB in plaats van
        1. Deze methode leest het bestand nog steeds precies één keer (zelfde streaming-garantie als
        :meth:`lees_domein`) en levert de rijen per blok al opgesplitst naar de chunk waarin hun
        woning hoort; de aanroeper (zie ``chunking.py``) schrijft elk deel meteen weg naar een
        chunk-specifiek interim-bestand, zodat er nooit meer dan één CSV-blok tegelijk in geheugen
        staat.

        ``chunk_van_home_id`` (home_id -> chunk-index) bepaalt de verdeling. Een home_id die er niet
        in voorkomt (buiten de gevraagde selectie, of een chunk die al compleet is en dus niet
        opnieuw gebouwd hoeft te worden) wordt overgeslagen -- dat is een bewuste keuze, geen
        omissie: het scheelt schijfruimte en tijd bij een hervatte run.

        Yields ``(chunk_index, subset)`` per niet-lege combinatie binnen een gelezen blok, met
        dezelfde kolomvorm als :meth:`lees_domein` (hernoemd, ``home_id__str``).
        """
        if bestandsnaam not in DOMEIN_BESTANDEN:
            raise BronError(f"Onbekend domeinbestand: {bestandsnaam}")

        metadata = self.metadata()
        hernoem = dict(KOLOM_HERNOEM_RUW.get(bestandsnaam, {}))
        hernoem["location_id"] = "home_id__str"

        n_gelezen = 0
        n_verdeeld = 0
        with self._open(bestandsnaam) as f:
            for i, blok in enumerate(pd.read_csv(f, chunksize=chunksize, dtype={"location_id": str})):
                if i == 0:
                    _valideer_header(bestandsnaam, list(blok.columns), metadata)
                n_gelezen += len(blok)
                blok = blok.assign(_chunk=blok["location_id"].map(chunk_van_home_id))
                for chunk_idx, subset in blok.dropna(subset=["_chunk"]).groupby("_chunk", sort=False):
                    subset = subset.drop(columns=["_chunk"]).rename(columns=hernoem)
                    n_verdeeld += len(subset)
                    yield int(chunk_idx), subset

        log.info(
            "%s: %d rij(en) gelezen (streamend), %d verdeeld over de te (her)bouwen chunk(s)",
            bestandsnaam, n_gelezen, n_verdeeld,
        )


def maak_bron(raw_pad: str | Path) -> ZipBron:
    """``raw_pad`` moet naar ``dph-dataset.zip`` zelf wijzen (geen map-fallback: deze dataset komt
    als één zip, anders dan bij IM3, en wordt hier bewust nooit uitgepakt, zie GEBRUIKSVOORWAARDEN.md).
    """
    raw_pad = Path(raw_pad)
    if raw_pad.is_dir():
        zips = sorted(raw_pad.glob("*.zip"))
        kandidaten = [z for z in zips if "dataset" in z.name.lower()]
        if len(kandidaten) == 1:
            return ZipBron(kandidaten[0])
        if len(zips) == 1:
            return ZipBron(zips[0])
        raise BronError(
            f"Geen eenduidige dataset-zip gevonden in {raw_pad}; wijs er expliciet één aan"
        )
    return ZipBron(raw_pad)
