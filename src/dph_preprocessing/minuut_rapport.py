# SPDX-License-Identifier: EUPL-1.2
"""Kwaliteitsrapport over de minuut-preprocessing (``ontwerp-preprocessing-minuut.md`` §9).

Aparte module, en dat is opzet: hij leest alleen ``kenmerken.jsonl`` en ``gaten.jsonl`` uit de
uitvoermap en raakt de 7,4 GB aan metingen niet aan. Het rapport is daarmee in seconden opnieuw te
maken, ook terwijl de run zelf nog loopt, en dat is precies wat je wilt bij een run van uren met
een harde stop erop.

``python -m dph_preprocessing.minuut_rapport --doel <map>``
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .minuut import DOEL_STANDAARD
from .opmaak import getal, percentage


def lees_jsonl(pad: Path) -> pd.DataFrame:
    if not pad.exists():
        return pd.DataFrame()
    regels = [json.loads(regel) for regel in pad.read_text(encoding="utf-8").splitlines() if regel.strip()]
    return pd.DataFrame(regels)


def _tabel(df: pd.DataFrame, kolommen: list[str]) -> str:
    aanwezig = [k for k in kolommen if k in df.columns]
    kop = "| " + " | ".join(aanwezig) + " |"
    streep = "|" + "|".join(["---"] * len(aanwezig)) + "|"
    regels = [
        "| " + " | ".join("" if pd.isna(rij[k]) else str(rij[k]) for k in aanwezig) + " |"
        for _, rij in df.iterrows()
    ]
    return "\n".join([kop, streep, *regels])


def bouw_rapport(doel: Path) -> str:
    kenmerken = lees_jsonl(doel / "kenmerken.jsonl")
    gaten = lees_jsonl(doel / "gaten.jsonl")
    if kenmerken.empty:
        return "# Kwaliteit van de minuut-preprocessing\n\nNog geen locaties verwerkt.\n"

    kenmerken = kenmerken.drop_duplicates(subset="home_id__str", keep="last")
    n_loc = len(kenmerken)
    n_min = int(kenmerken["n_minuten"].sum())

    delen: list[str] = [
        "# Kwaliteit van de minuut-preprocessing",
        "",
        f"Gemaakt op {datetime.now():%d-%m-%Y %H:%M} uit `kenmerken.jsonl` en `gaten.jsonl` in",
        f"`{doel}`. Opzet en keuzes: `ontwerp-preprocessing-minuut.md`.",
        "",
        f"**{getal(n_loc)} locaties verwerkt, samen {getal(n_min)} minuten.**",
        "",
    ]

    # 1. Wat de warmtemeter meet. Dit is de bevinding die de hele analyseopzet stuurt.
    delen += ["## 1. Wat meet de warmtemeter, per locatie", ""]
    if "warmtemeter_bereik__cat" in kenmerken:
        telling = kenmerken["warmtemeter_bereik__cat"].value_counts()
        for soort in ("systeem", "warmtepomp", "onbeslist"):
            n = int(telling.get(soort, 0))
            woord = "locatie" if n == 1 else "locaties"
            delen.append(f"- **{soort}**: {getal(n)} {woord} ({percentage(n / n_loc)})")
        delen += [
            "",
            "`systeem` betekent dat de Kamstrup ook levert wanneer alleen de ketel draait, en dus",
            "achter beide toestellen zit. Poolen over locaties met verschillende uitkomst mengt",
            "twee meetopstellingen; `onbeslist` is geen restcategorie maar een weigering om te",
            "gokken waar narijdende warmte uit een buffervat niet uit te sluiten is.",
            "",
        ]

    # 2. Het dode warmtepompkanaal.
    if "warmtepompkanaal_dood__bool" in kenmerken:
        dood = kenmerken[kenmerken["warmtepompkanaal_dood__bool"].fillna(False)]
        delen += [
            "## 2. Locaties zonder bruikbaar warmtepompkanaal",
            "",
            f"**{getal(len(dood))} van de {getal(n_loc)} locaties** ({percentage(len(dood) / n_loc)})",
            "halen over de hele meetperiode geen 200 W op `heatpump_power`, terwijl de warmtemeter",
            "er wél levert. Daar is het elektriciteitskanaal defect en niet de warmtemeter. Sluit ze",
            "uit van elke COP- of opdeelanalyse.",
            "",
            "```",
            ", ".join(sorted(dood["home_id__str"])),
            "```",
            "",
        ]

    # 3. Dekking.
    delen += ["## 3. Dekking", ""]
    if "bezetting__0" in kenmerken:
        delen += [
            f"- bezetting, mediaan over de locaties: {percentage(kenmerken['bezetting__0'].median())}",
            f"- laagste bezetting: {percentage(kenmerken['bezetting__0'].min())}",
            f"- grootste gat, mediaan: {getal(int(kenmerken['grootste_gat__min'].median()))} minuten",
            "",
        ]
    dekking = [k for k in kenmerken.columns if k.startswith("dekking_")]
    if dekking:
        overzicht = pd.DataFrame(
            {
                "kolom": [k.removeprefix("dekking_") for k in dekking],
                "mediaan": [percentage(kenmerken[k].median()) for k in dekking],
                "locaties met 0 %": [int((kenmerken[k].fillna(0) == 0).sum()) for k in dekking],
            }
        ).sort_values("kolom")
        delen += [
            "Dekking per kolom, niet per meetgroep: `n_g2 > 0` zegt niets over een gevulde",
            "dsmr-waarde, en de verkenning vond 21 locaties met meer dan 1 % zuivere hartslagrijen.",
            "",
            _tabel(overzicht, ["kolom", "mediaan", "locaties met 0 %"]),
            "",
        ]

    # 4. De vlaggen.
    delen += ["## 4. Vlaggen", ""]
    vlaggen = {
        "onplausibele momentane waarden": "n_onplausibel",
        "teruglopende tellerstanden": "n_teller_terug",
        "foutieve nuluitlezingen": "n_teller_nulmeting",
        "vermoedelijke meterwissels": "n_teller_wissel",
    }
    rijen = []
    for label, kolom in vlaggen.items():
        if kolom in kenmerken:
            totaal = int(kenmerken[kolom].sum())
            rijen.append(
                {
                    "vlag": label,
                    "totaal": getal(totaal),
                    "per miljoen minuten": getal(round(totaal / n_min * 1e6, 1)) if n_min else "",
                    "locaties met minstens één": int((kenmerken[kolom] > 0).sum()),
                }
            )
    if rijen:
        delen += [_tabel(pd.DataFrame(rijen), ["vlag", "totaal", "per miljoen minuten", "locaties met minstens één"]), ""]

    # 5. Gaten.
    if not gaten.empty:
        kort = gaten[gaten["duur__min"] <= 5]
        uitval = gaten[gaten["soort"] == "uitval"]
        gemis = int(gaten["duur__min"].sum())
        delen += [
            "## 5. Gaten",
            "",
            f"- {getal(len(gaten))} gaten, samen {getal(gemis)} ontbrekende minuten",
            f"- tot 5 minuten: {getal(len(kort))} gaten ({percentage(len(kort) / len(gaten))}), "
            f"samen {percentage(int(kort['duur__min'].sum()) / gemis)} van het gemis",
            f"- langer dan een dag: {getal(len(uitval))} gaten ({percentage(len(uitval) / len(gaten))}), "
            f"samen {percentage(int(uitval['duur__min'].sum()) / gemis)} van het gemis",
            "",
            "Dat is het onderscheid waar `ontbrekend` en `uitval` voor bestaan: de korte gaten zijn",
            "overbrugbaar, de lange horen als periode uit de noemer.",
            "",
        ]

    return "\n".join(delen) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--doel", default=DOEL_STANDAARD, help="de uitvoermap van de minuut-preprocessing")
    p.add_argument("--uit", default=None, help="waar het rapport heen moet (standaard <doel>/kwaliteit.md)")
    args = p.parse_args(argv)

    doel = Path(args.doel)
    tekst = bouw_rapport(doel)
    uit = Path(args.uit) if args.uit else doel / "kwaliteit.md"
    uit.parent.mkdir(parents=True, exist_ok=True)
    uit.write_text(tekst, encoding="utf-8")
    print(f"Rapport geschreven naar {uit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
