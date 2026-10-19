# SPDX-License-Identifier: EUPL-1.2
"""Het float32-raster van de acht cumulatieve tellers, per locatie.

Hoort bij ``ontwerp-preprocessing-minuut-geheugen.md`` §6. De acht tellerkolommen staan bovenstrooms
als ``Nullable(Float32)``, en float32 geeft constante *relatieve* precisie terwijl een teller
constante *absolute* precisie vraagt. Bij de standen die deze meters inmiddels hebben is de afstand
tussen twee opeenvolgende float32 daardoor groter geworden dan de tik van de meter zelf: de mediane
woning zit op 0,00098 tegen een metertik van 0,001, en het 95e percentiel op 0,0039.

Wat deze module oplevert is het getal dat naast elke afgeleide vermogenskolom hoort te staan. Omdat
het afgeleide vermogen ``Δstand × factor / Δt`` is, schaalt de kwantiseringsstap met ``1/Δt``: bij een
kwartier is hij verwaarloosbaar en bij een minuut niet. Zonder dat getal oogt ``p_warmtepomp__W``
preciezer dan hij is.

**Twee dingen, en het tweede is het minst bekende.**

1. Het raster *bij de eindstand*, omgerekend naar watt. Dat is de trap in het afgeleide vermogen.
2. De **rasterbreuk**: passeert de teller tijdens de meetperiode een macht van twee, dan verdubbelt
   het raster middenin de reeks. Dat is een sprong in de ruiskarakteristiek die niets met de woning
   te maken heeft, en elke change-point-detectie pikt hem op.

**Alles komt uit de Parquet-footer**, dus zonder ook maar één rij te lezen. Over 129 miljoen rijen
scheelt dat het verschil tussen seconden en een half uur, en het betekent dat deze scan naast een
lopende verwerking kan draaien.
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from dph_preprocessing.minuut import (
    BRON_STANDAARD,
    DOEL_STANDAARD,
    GJ_NAAR_J,
    J_PER_KWH,
    TELLERS,
    schrijf_atomisch,
)
from dph_preprocessing.opmaak import getal


log = logging.getLogger(__name__)

#: Van de eenheid van de bronteller naar joule, om het raster in watt te kunnen uitdrukken.
#:
#: Dit is NIET de factor uit :data:`~dph_preprocessing.minuut.TELLERS`. Die staat op 1,0 voor de
#: kWh-tellers, want daar geeft hij de eenheid van de ``*_cum__kWh``-kolom en niet de omrekening naar
#: vermogen; ``minuut.py`` vermenigvuldigt bij die tellers apart met ``J_PER_KWH``. Alleen bij de
#: Kamstrup vallen de twee samen.
#:
#: Gas staat bewust op ``None``: ``dsmr_v_gas_consumed`` meet volume en zijn afgeleide is
#: ``g_gebruik__m3_s_1``, geen vermogen. Een raster in watt zou daar een calorische waarde
#: veronderstellen die deze pas niet kent (zie §11 van het hoofdontwerp). De kolom ``raster`` geeft
#: voor gas gewoon de stap in m³ per minuut.
NAAR_J: dict[str, float | None] = {
    "dsmr_e_consumed_low": J_PER_KWH,
    "dsmr_e_consumed_high": J_PER_KWH,
    "dsmr_e_delivered_low": J_PER_KWH,
    "dsmr_e_delivered_high": J_PER_KWH,
    "heatpump_energy": J_PER_KWH,
    "boiler_energy": J_PER_KWH,
    "kamstrup_e_thermal_system": GJ_NAAR_J,
    "dsmr_v_gas_consumed": None,
}

#: De kleinste stap die de meter zelf kan zetten, in de eenheid van de bronkolom. DSMR levert
#: elektriciteit en gas met drie decimalen. Voor de Kamstrup is de tik ons niet bekend; daar blijft
#: het oordeel "te grof of niet" dus leeg en rapporteren we alleen het raster in watt.
METERTIK: dict[str, float | None] = {
    "dsmr_e_consumed_low": 0.001,
    "dsmr_e_consumed_high": 0.001,
    "dsmr_e_delivered_low": 0.001,
    "dsmr_e_delivered_high": 0.001,
    "dsmr_v_gas_consumed": 0.001,
    "heatpump_energy": 0.001,
    "boiler_energy": 0.001,
    "kamstrup_e_thermal_system": None,
}

#: Het interval waarover deze pas differentieert. Staat hier als constante omdat de hele pointe van
#: §6.2 is dat het raster in watt met 1/Δt schaalt; wie het voor het kwartierpad wil weten, zet hier
#: 900 neer en krijgt een vijftien keer zo gunstig getal.
INTERVAL__s = 60.0

#: Boven deze stand is een teller "echt gelopen". Zelfde drempel en zelfde reden als
#: :func:`dph_preprocessing.minuut.markeer_nulmetingen`: ``heatpump_energy`` en
#: ``kamstrup_e_thermal_system`` beginnen legitiem op 0,0, en een minimum van nul zegt dus niets over
#: het raster waar de reeks daadwerkelijk in ligt.
ONTWAAKT_BOVEN = 1.0


def raster(stand: float) -> float:
    """De afstand tussen ``stand`` en de eerstvolgende float32 daarboven.

    Via :func:`numpy.spacing` en niet via ``2**(floor(log2 s) - 23)`` met de hand. Dezelfde uitkomst,
    maar numpy kent de randgevallen die de formule niet kent: precies op een macht van twee, bij
    subnormale getallen, en bij nul. Dezelfde keuze als in de extractierepo, zodat de twee niet uit
    elkaar kunnen lopen.
    """
    if not math.isfinite(stand) or stand <= 0.0:
        return float("nan")
    return float(np.spacing(np.float32(stand)))


def raster__W(stand: float, naar_J: float | None, interval__s: float = INTERVAL__s) -> float:
    """Het raster omgerekend naar de trap in het afgeleide vermogen.

    ``naar_J is None`` betekent dat deze teller geen energie meet; dan bestaat er geen zinnig getal in
    watt en geeft de kolom ``raster`` het antwoord in de eenheid van de teller zelf.
    """
    if naar_J is None:
        return float("nan")
    return raster(stand) * naar_J / interval__s


def drempelstand(metertik: float) -> float:
    """De laagste stand waarboven het float32-raster de metertik evenaart of overtreft.

    Het raster is ``2**(e-23)`` voor een stand in ``[2**e, 2**(e+1))``, dus het haalt de metertik bij
    de kleinste ``e`` met ``2**(e-23) >= metertik``. Voor een tik van 0,001 komt dat op ``e = 14``,
    oftewel een stand van 16.384: daarboven vallen twee verschillende meterstanden op dezelfde
    float32 en is het laatste cijfer van de meter niet meer te vertrouwen.
    """
    return float(2.0 ** math.ceil(23 + math.log2(metertik)))


def machten_van_twee(onder: float, boven: float, vanaf: float) -> list[float]:
    """De machten van twee in ``(onder, boven]`` die minstens ``vanaf`` zijn.

    Elke passage verdubbelt het raster. Alleen de passages vanaf ``vanaf`` tellen mee, want onder die
    grens is het raster nog fijner dan de meter en verandert er aan de bruikbaarheid niets.
    """
    if not (math.isfinite(onder) and math.isfinite(boven)) or boven <= onder:
        return []
    uit = []
    e = math.ceil(math.log2(max(onder, 1e-300)))
    while (macht := 2.0**e) <= boven:
        if macht > onder and macht >= vanaf:
            uit.append(macht)
        e += 1
    return uit


def _standen_uit_footer(pad: Path) -> dict[str, tuple[float, float]]:
    """Per bronteller de laagste en hoogste stand, uit de statistieken van alle row groups.

    Zowel ``_eerste`` als ``_laatste`` meegenomen: samen beschrijven ze de volledige spanwijdte die de
    teller in deze reeks doorloopt, en het is precies die spanwijdte waarin een rasterbreuk zit.
    """
    md = pq.read_metadata(pad)
    namen = [md.schema.column(i).name for i in range(md.num_columns)]
    gezocht = {f"{bron}{achtervoegsel}": bron for bron in TELLERS for achtervoegsel in ("_eerste", "_laatste")}

    grenzen: dict[str, tuple[float, float]] = {}
    for groep in range(md.num_row_groups):
        for i, naam in enumerate(namen):
            bron = gezocht.get(naam)
            if bron is None:
                continue
            st = md.row_group(groep).column(i).statistics
            if st is None or not st.has_min_max or st.min is None:
                continue
            lo, hi = float(st.min), float(st.max)
            if bron in grenzen:
                oud_lo, oud_hi = grenzen[bron]
                grenzen[bron] = (min(oud_lo, lo), max(oud_hi, hi))
            else:
                grenzen[bron] = (lo, hi)
    return grenzen


def eerste_laatste_uit_footer(pad: Path) -> dict[str, tuple[float, float]]:
    """Per bronteller de EERSTE en LAATSTE chronologische stand, uit de footer, geen rij gelezen.

    Verschilt van :func:`_standen_uit_footer` op een punt dat ertoe doet zodra je een energietotaal
    wilt berekenen: dat neemt het GLOBALE min/max over de hele reeks (goed voor het raster, want
    daar gaat het om de spanwijdte), maar een teller met een terugsprong (§5 van
    ``ontwerp-preprocessing-minuut.md``: een tellerwissel, of -- zie ``docs/analyse-bevindingen-
    minuut.md``, de vergelijking met het kwartierpad -- een sentinelwaarde vlak vóór de eerste
    echte uitlezing) maakt "max - min" dan iets anders dan "energie over de opnameperiode".

    De bron is per locatie oplopend gesorteerd op tijd en de row groups overlappen niet
    (geheugenontwerp §3), dus de EERSTE row group bevat de vroegste minuten en de LAATSTE row
    group de laatste. Het MINIMUM van de eerste groep benadert de eerste chronologische stand (de
    kleinste waarde in een vroeg, groot blok is vrijwel altijd de vroegste, want de teller loopt
    op); het MAXIMUM van de laatste groep benadert de laatste stand op dezelfde manier. Dat is een
    schatting en geen garantie -- een terugsprong binnen de eerste of laatste 100.000 rijen zou hem
    alsnog kunnen raken -- maar in de praktijk (getoetst tegen ``dsmr_e_consumed_low`` van
    ``RHON9wor``, dat een sentinelwaarde in de eerste minuten had) haalt het de vervuiling er wel
    uit waar het globale min/max van :func:`_standen_uit_footer` dat niet doet.
    """
    md = pq.read_metadata(pad)
    namen = [md.schema.column(i).name for i in range(md.num_columns)]
    gezocht = {f"{bron}_eerste": bron for bron in TELLERS}
    laatste_groep = md.num_row_groups - 1

    uit: dict[str, tuple[float, float]] = {}
    for i, naam in enumerate(namen):
        bron = gezocht.get(naam)
        if bron is None:
            continue
        st_eerste = md.row_group(0).column(i).statistics
        st_laatste = md.row_group(laatste_groep).column(i).statistics
        if st_eerste is None or st_laatste is None or not st_eerste.has_min_max or not st_laatste.has_min_max:
            continue
        uit[bron] = (float(st_eerste.min), float(st_laatste.max))
    return uit


def beoordeel_teller(bron: str, stand_min: float, stand_max: float) -> dict:
    """Eén teller van één locatie: raster, breuk, en het oordeel tegen de metertik."""
    naam, _ = TELLERS[bron]
    metertik = METERTIK[bron]
    # Een teller die legitiem op 0,0 begint, zegt met dat nulpunt niets over zijn raster. De
    # ondergrens wordt daarom de drempel waarboven hij echt liep; zie ONTWAAKT_BOVEN.
    effectief_min = max(stand_min, ONTWAAKT_BOVEN)

    r = raster(stand_max)
    post = {
        "teller__str": naam,
        "bronkolom__str": bron,
        "stand_min": stand_min,
        "stand_max": stand_max,
        "raster": r,
        "raster__W": raster__W(stand_max, NAAR_J[bron]),
        "metertik": metertik if metertik is not None else float("nan"),
    }
    if metertik is None:
        post["raster_boven_metertik__bool"] = pd.NA
        post["raster_breuk__bool"] = pd.NA
        post["n_verdubbelingen"] = pd.NA
        return post

    vanaf = drempelstand(metertik)
    passages = machten_van_twee(effectief_min, stand_max, vanaf)
    post["raster_boven_metertik__bool"] = bool(math.isfinite(r) and r >= metertik)
    post["raster_breuk__bool"] = bool(passages)
    post["n_verdubbelingen"] = len(passages)
    return post


def scan(bron: Path) -> pd.DataFrame:
    """Alle locaties langs, één regel per locatie per teller."""
    bestanden = sorted(p for p in bron.iterdir() if p.suffix == ".parquet")
    log.info("%d locaties te beoordelen in %s", len(bestanden), bron)

    regels: list[dict] = []
    for i, pad in enumerate(bestanden, 1):
        naam = pad.stem
        home_id = naam[len("location_id=") :] if naam.startswith("location_id=") else naam
        try:
            grenzen = _standen_uit_footer(pad)
        except Exception:  # noqa: BLE001 - een kapot bestand mag de scan niet stoppen
            log.exception("[%3d/%d] %-10s footer niet leesbaar; overgeslagen", i, len(bestanden), home_id)
            continue
        for bron_kolom, (lo, hi) in grenzen.items():
            regel = {"home_id__str": home_id}
            regel.update(beoordeel_teller(bron_kolom, lo, hi))
            regels.append(regel)
        log.info("[%3d/%d] %-10s %d tellers", i, len(bestanden), home_id, len(grenzen))

    if not regels:
        return pd.DataFrame()
    df = pd.DataFrame(regels)
    df["home_id__str"] = df["home_id__str"].astype("string")
    df["teller__str"] = df["teller__str"].astype("string")
    df["bronkolom__str"] = df["bronkolom__str"].astype("string")
    for kolom in ("raster_boven_metertik__bool", "raster_breuk__bool"):
        df[kolom] = df[kolom].astype("boolean")
    df["n_verdubbelingen"] = df["n_verdubbelingen"].astype("Int64")
    return df.sort_values(["teller__str", "home_id__str"]).reset_index(drop=True)


def vat_samen(df: pd.DataFrame) -> str:
    """Het rapport zoals §6.7 het vraagt: de verdeling over de locaties, per teller."""
    if df.empty:
        return "Geen tellerdata gevonden.\n"
    regels = [
        "# Het float32-raster per teller",
        "",
        "Raster in watt is de trap in het afgeleide vermogen bij een interval van "
        f"{INTERVAL__s:.0f} s; zie ontwerp-preprocessing-minuut-geheugen.md §6.",
        "",
        "| teller | locaties | mediaan raster__W | p95 raster__W | max raster__W | te grof | rasterbreuk |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for naam, groep in df.groupby("teller__str", observed=True):
        w = groep["raster__W"].dropna()
        tegrof = groep["raster_boven_metertik__bool"]
        breuk = groep["raster_breuk__bool"]
        regels.append(
            f"| `{naam}` | {getal(len(groep))} | {getal(w.median(), 1)} | {getal(w.quantile(0.95), 1)} "
            f"| {getal(w.max(), 1)} "
            f"| {getal(tegrof.sum(skipna=True)) if tegrof.notna().any() else '-'} "
            f"| {getal(breuk.sum(skipna=True)) if breuk.notna().any() else '-'} |"
        )
    breuken = df[df["raster_breuk__bool"].fillna(False)]
    regels += ["", f"**Locaties met een rasterbreuk: {breuken['home_id__str'].nunique()}.**", ""]
    if len(breuken):
        regels += ["| locatie | teller | van | tot | verdubbelingen |", "|---|---|---:|---:|---:|"]
        for _, r in breuken.iterrows():
            regels.append(
                f"| `{r['home_id__str']}` | `{r['teller__str']}` | {getal(r['stand_min'], 1)} "
                f"| {getal(r['stand_max'], 1)} | {getal(r['n_verdubbelingen'])} |"
            )
    return "\n".join(regels) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bron", default=BRON_STANDAARD, help="map met location_id=*.parquet")
    p.add_argument("--doel", default=DOEL_STANDAARD, help="waar raster.parquet en raster.md komen")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    df = scan(Path(args.bron))
    if df.empty:
        log.warning("Niets gevonden in %s", args.bron)
        return 1

    doel = Path(args.doel)
    doel.mkdir(parents=True, exist_ok=True)
    schrijf_atomisch(df, doel / "raster.parquet")
    (doel / "raster.md").write_text(vat_samen(df), encoding="utf-8")
    print(vat_samen(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
