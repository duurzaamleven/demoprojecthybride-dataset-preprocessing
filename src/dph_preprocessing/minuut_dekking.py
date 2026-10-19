# SPDX-License-Identifier: EUPL-1.2
"""Dekkings- en reeksanalyse op het minuutrooster (``ontwerp-interpolatie-en-dekking.md`` §4, §5).

Beantwoordt "hoeveel aaneengesloten bruikbare tijd houdt een locatie over als je gaten tot k
minuten overbrugt", zonder ook maar één meting aan te raken: alles hieronder rekent uitsluitend op
``gaten.parquet`` (de gatenlijst per locatie) en de tijdspanne uit ``homes_minuut.parquet``
(``eerste_minuut``, ``laatste_minuut``). Dat is een bewuste keuze en geen kortere weg: het
interpolatieontwerp §2 verbiedt al om overbrugde waarden in de metingen zelf te zetten, en deze
module levert het kwaliteitsartefact dat daarnaast hoort te staan, niet de overbrugging zelf.

**De aanname, en waar ze hapert.** ``gaten.parquet`` kent alleen RIJdekking (deze minuut staat wel
of niet in de bron); de zeven momentane grootheden uit §4 hebben in principe hun EIGEN dekking
binnen een aanwezige rij. Voor de vijf Kamstrup/warmtepompkolommen is dat verschil verwaarloosbaar
(``dekking_<kolom>`` uit ``homes_minuut.parquet`` zit op de meeste locaties op 99,4-100 % van de
aanwezige rijen, zie ``docs/analyse-bevindingen-minuut.md`` B5). Voor `temp_binnen__degC` en
`rv_binnen__0` (de losse Sonoff-sensor) is dat zwakker: 58 van de 174 locaties zitten onder 95 %,
enkele op 0 % (kapotte sensor). Deze module rapporteert dus een BOVENGRENS op de dekking van die
twee kolommen; voor de vijf overige is de rijdekking een goede stand-in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: De overbruggingsgrenzen uit ontwerp-interpolatie-en-dekking.md §4, gemeten met de ponsmeting
#: van 17-09-2026 (twaalf locaties, 36.000 steekproefposities per kolom, seed 42). 0,0 betekent
#: "niet overbruggen": bij `p_warmtepomp_gemeten__W` en `q_geleverd_gemeten__W` is de fout na één
#: minuut al groter dan de kwantiseringsstap van hun tellerafgeleide tegenhanger.
OVERBRUGGINGSGRENS__min: dict[str, float] = {
    "temp_binnen__degC": 60.0,
    "rv_binnen__0": 60.0,
    "temp_retour__degC": 3.0,
    "temp_aanvoer__degC": 2.0,
    "debiet__dm3_s_1": 1.0,
    "q_geleverd_gemeten__W": 0.0,
    "p_warmtepomp_gemeten__W": 0.0,
}

#: De twee kolommen die samen de COP bepalen (§5: "voor een COP-analyse is dat p_warmtepomp_gemeten__W
#: en q_geleverd_gemeten__W tegelijk"). Allebei op grens 0, dus de combinatie is hier -- onder de
#: rijdekkingsaanname hierboven -- gelijk aan elk van de twee apart; zie analyse_cop_combo.
COP_KOLOMMEN: tuple[str, str] = ("p_warmtepomp_gemeten__W", "q_geleverd_gemeten__W")

#: Bakken voor de reeksduur, in minuten. Dezelfde grenzen als het kwartierpad se B5
#: (``analyses.B5_STREAK_BINS__S``, in seconden [900, 3600, 86400, 604800, 2_592_000]), zodat de
#: twee paden vergelijkbaar blijven; hier begint de eerste bak bij een kwartier (15 min) in plaats
#: van bij de kwartiergrid-eenheid van het kwartierpad zelf.
STREAK_BINS__min = [15.0, 60.0, 1440.0, 10080.0, 43200.0, np.inf]
STREAK_LABELS = ["kwartier_tot_uur", "uur_tot_dag", "dag_tot_week", "week_tot_maand", "meer_dan_maand"]

#: Drempels die standaard in dekking.parquet komen: 0 als referentie (ontwerp §5) plus alle
#: gemeten grenzen uit §4. Elke drempel één keer: twee van die grenzen zijn zelf al 0.
STANDAARD_DREMPELS__min: tuple[float, ...] = tuple(sorted({0.0, *OVERBRUGGINGSGRENS__min.values()}))


def gedekte_tijd__min(gaten_home: pd.DataFrame, span__min: float, max_gat__min: float) -> float:
    """Aaneengesloten *of overbrugbaar* bruikbare tijd (in minuten) bij overbruggingsgrens ``k``.

    ``duur__min`` in een gatenrij is al het aantal ONTBREKENDE roosterposities (``bouw_gaten``:
    ``duur = verschil - 1``, en ``verschil`` is het aantal minuutstappen tussen twee aanwezige
    buren) -- dus de som van ``duur__min`` over ALLE gaten van een locatie is precies
    ``span__min - n_minuten``. Gaten van hoogstens ``k`` minuten worden overbrugd (tellen mee als
    gedekt); langere gaten niet.

    Bij ``k=0`` geeft dit exact ``n_minuten`` terug: geen enkel gat is dan kort genoeg om
    overbrugd te worden, dus de uitkomst is de rauwe rijaanwezigheid. Dat is de sanity check
    waarmee deze functie tegen ``homes_minuut.parquet`` te toetsen is.
    """
    if gaten_home.empty:
        return span__min
    uitgesloten = gaten_home.loc[gaten_home["duur__min"] > max_gat__min, "duur__min"]
    return span__min - float(uitgesloten.sum())


def segmenten(eerste: pd.Timestamp, laatste: pd.Timestamp, gaten_home: pd.DataFrame, max_gat__min: float) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """De aaneengesloten (na overbrugging) bruikbare stukken van één locatie, als (begin, eind).

    Twee aanwezige stukken die door een gat van hoogstens ``max_gat__min`` gescheiden zijn, worden
    hier tot ÉÉN stuk samengevoegd: dat gat is per definitie overbrugbaar, dus voor "aaneengesloten
    bruikbaar" telt het niet als knip.
    """
    if pd.isna(eerste) or pd.isna(laatste):
        return []
    lang = gaten_home.loc[gaten_home["duur__min"] > max_gat__min].sort_values("begin")
    # .tolist() in plaats van DataFrame.iterrows(): bij duizenden gaten per locatie (de drukste
    # heeft er ruim 5.000) kost het per-rij aanmaken van een Series in iterrows() een veelvoud van
    # wat kale Timestamp-scalars kosten, en dat loopt op 174 locaties x 7 grootheden (plus de
    # COP-combinatie) op tot minuten CPU-tijd voor niets. tolist() geeft op een tz-aware kolom al
    # kale pd.Timestamp-objecten terug, dus geen numpy-omweg nodig.
    één_minuut = pd.Timedelta(minutes=1)
    uit: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    huidig_begin = eerste
    for gat_begin, gat_eind in zip(lang["begin"].tolist(), lang["eind"].tolist()):
        stuk_eind = gat_begin - één_minuut
        if stuk_eind >= huidig_begin:
            uit.append((huidig_begin, stuk_eind))
        huidig_begin = gat_eind
    if laatste >= huidig_begin:
        uit.append((huidig_begin, laatste))
    return uit


def streak_bakken__min(stukken: list[tuple[pd.Timestamp, pd.Timestamp]]) -> dict[str, float]:
    """Groepeer de lengte van elk stuk uit :func:`segmenten` in de bakken van :data:`STREAK_LABELS`."""
    uit: dict[str, float] = {}
    for begin, eind in stukken:
        lengte__min = (eind - begin).total_seconds() / 60.0 + 1.0
        bak = STREAK_LABELS[int(np.searchsorted(STREAK_BINS__min, lengte__min, side="right") - 1)] \
            if lengte__min >= STREAK_BINS__min[0] else None
        if bak is None:
            continue
        uit[bak] = uit.get(bak, 0.0) + lengte__min
    return uit


@dataclass
class _Span:
    eerste: pd.Timestamp
    laatste: pd.Timestamp
    span__min: float


def _spans(homes_minuut: pd.DataFrame) -> dict[str, _Span]:
    return {
        r["home_id__str"]: _Span(
            r["eerste_minuut"], r["laatste_minuut"],
            (r["laatste_minuut"] - r["eerste_minuut"]).total_seconds() / 60.0 + 1.0,
        )
        for _, r in homes_minuut.iterrows()
        if pd.notna(r["eerste_minuut"]) and pd.notna(r["laatste_minuut"])
    }


def analyse_b5_minuut(
    gaten: pd.DataFrame,
    homes_minuut: pd.DataFrame,
    drempels: dict[str, float] | None = None,
) -> pd.DataFrame:
    """B5 op het minuutrooster: aaneengesloten bruikbare tijd per locatie per grootheid.

    Lange tabel, één rij per (``home_id__str``, ``grootheid``): ``totale_tijd__min``,
    ``gedekte_tijd__min`` bij referentie (``k=0``) en bij de gemeten grens uit §4,
    ``aandeel_gedekt`` (bij de gemeten grens), en de reeksverdeling ``streak__<bak>__min`` (na
    overbrugging bij de gemeten grens).
    """
    drempels = drempels or OVERBRUGGINGSGRENS__min
    spans = _spans(homes_minuut)
    per_home_gaten = {h: g for h, g in gaten.groupby("home_id__str")}
    leeg_gaten = gaten.iloc[0:0]

    rijen: list[dict] = []
    for home_id, sp in spans.items():
        g = per_home_gaten.get(home_id, leeg_gaten)
        for grootheid, k in drempels.items():
            referentie = gedekte_tijd__min(g, sp.span__min, 0.0)
            gedekt = gedekte_tijd__min(g, sp.span__min, k)
            rij = {
                "home_id__str": home_id,
                "grootheid": grootheid,
                "drempel__min": k,
                "totale_tijd__min": sp.span__min,
                "gedekte_tijd__min_referentie": referentie,
                "gedekte_tijd__min": gedekt,
                "aandeel_gedekt": gedekt / sp.span__min if sp.span__min else np.nan,
            }
            for bak, duur in streak_bakken__min(segmenten(sp.eerste, sp.laatste, g, k)).items():
                rij[f"streak__{bak}__min"] = duur
            rijen.append(rij)
    return pd.DataFrame(rijen)


def analyse_cop_combo(
    gaten: pd.DataFrame,
    homes_minuut: pd.DataFrame,
) -> pd.DataFrame:
    """De COP-combinatie uit §5: `p_warmtepomp_gemeten__W` EN `q_geleverd_gemeten__W` tegelijk,
    zonder de 39 locaties met een dood warmtepompkanaal.

    Beide kolommen staan op overbruggingsgrens 0 (§4), dus onder de rijdekkingsaanname van deze
    module (zie de moduledocstring) valt de combinatie samen met elke kolom apart: een minuut die
    voor de ene telt, telt onder die aanname ook voor de andere. Wat overblijft na het uitsluiten
    van de dode kanalen is daarom de interessante stap, niet een aparte AND-berekening.
    """
    levend = homes_minuut.loc[~homes_minuut["warmtepompkanaal_dood__bool"].fillna(False)]
    b5 = analyse_b5_minuut(gaten, levend, drempels={k: 0.0 for k in COP_KOLOMMEN})
    return b5[b5["grootheid"] == COP_KOLOMMEN[0]].drop(columns="grootheid")


def bouw_dekking_tabel(
    gaten: pd.DataFrame,
    homes_minuut: pd.DataFrame,
    drempels__min: tuple[float, ...] = STANDAARD_DREMPELS__min,
) -> pd.DataFrame:
    """``dekking.parquet`` (ontwerp-interpolatie-en-dekking.md §5): per locatie per kolom per
    drempel de aaneengesloten bruikbare tijd, plus de COP-combinatie met de dode kanalen eruit.

    Eén platte tabel in plaats van :func:`analyse_b5_minuut`'s vaste-drempel-per-kolomtabel, want
    dekking.parquet is bedoeld als kwaliteitsartefact naast de data en niet als rapporttabel: een
    analyse die een andere drempel wil dan de gemeten default, moet die er zelf uit kunnen kiezen.
    """
    spans = _spans(homes_minuut)
    per_home_gaten = {h: g for h, g in gaten.groupby("home_id__str")}
    leeg_gaten = gaten.iloc[0:0]
    kolommen = list(OVERBRUGGINGSGRENS__min)

    rijen: list[dict] = []
    for home_id, sp in spans.items():
        g = per_home_gaten.get(home_id, leeg_gaten)
        for kolom in kolommen:
            for k in drempels__min:
                gedekt = gedekte_tijd__min(g, sp.span__min, k)
                rijen.append({
                    "home_id__str": home_id,
                    "kolom__str": kolom,
                    "drempel__min": k,
                    "totale_tijd__min": sp.span__min,
                    "gedekte_tijd__min": gedekt,
                    "aandeel_gedekt": gedekt / sp.span__min if sp.span__min else np.nan,
                })
    dekking = pd.DataFrame(rijen)

    combo = analyse_cop_combo(gaten, homes_minuut)
    combo = combo.assign(kolom__str="cop_combo__p_warmtepomp_en_q_geleverd")[
        ["home_id__str", "kolom__str", "drempel__min", "totale_tijd__min", "gedekte_tijd__min", "aandeel_gedekt"]
    ]
    dekking = pd.concat([dekking, combo], ignore_index=True)
    dekking["home_id__str"] = dekking["home_id__str"].astype("string")
    dekking["kolom__str"] = dekking["kolom__str"].astype("string")
    return dekking.sort_values(["kolom__str", "home_id__str", "drempel__min"]).reset_index(drop=True)
