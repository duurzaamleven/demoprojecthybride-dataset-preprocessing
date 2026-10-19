# SPDX-License-Identifier: EUPL-1.2
"""Genereert ``docs/data-quality.md``, met de vijf punten uit ontwerp-preprocessing.md §7 plus twee
toevoegingen (ontwerp §3, principe 5: "Gegenereerde rapportage" -- met de hand bijhouden mag niet).

De vijf punten uit het ontwerp, in dezelfde volgorde:

1. Aantal woningen, en per woning het aantal complete kwartieren per meetbron.
2. De overlap: in hoeveel kwartieren zijn alle vier de bronnen beschikbaar.
3. De verdeling van de scheefheid uit §2.1 -- is de drempel van vijf minuten realistisch?
4. Hoe vaak tellers teruglopen, teruggeleverd wordt, of springen.
5. Het tijdvak per woning, en hoeveel woningen daadwerkelijk twee stookseizoenen dekken.

Plus punt 6 en 7, die niet uit het ontwerp komen maar uit ``docs/lessen-uit-im3.md``: **waar de
verwerking op een aanname terugvalt, en waar ze niets invult**. Allebei zijn ze in de uitvoer
onzichtbaar, en allebei bepalen ze of een analyse op meetwaarden rust of op iets anders.

6. Hoe vaak ``g_gebruik__W`` de werkelijke calorische gaswaarde gebruikte en hoe vaak de vaste
   terugvalwaarde. Een stille terugval ziet er precies hetzelfde uit als een geslaagde ophaal.
7. Hoe vaak een kwartier géén weerwaarde heeft. Daar wordt niets ingevuld, en dat is de juiste
   keuze, maar wie op het weer joint en lege waarden laat vallen verliest rijen zonder te weten
   hoeveel.

Elke volgende aanname of stil gat hoort hier ook een regel te krijgen.

**Chunk-geschikt.** Het rapport neemt niet de volledige ``measurements``/``quality``-tabellen
als argument: op de volledige ~174 woningen zou dat de hele dataset in pandas laden, precies wat
de chunking wil vermijden. :class:`RapportAccumulator` verzamelt daarom incrementeel,
chunk voor chunk (elke chunk is O(aantal woningen erin) groot, niet O(aantal rijen in de dataset)),
en :func:`build_report` bouwt de tekst uit die accumulator plus de (kleine, 174-rijen) ``homes``-
tabel. Elke woning zit in precies één chunk (chunks partitioneren op woning, nooit op tijd), dus de
PER-WONING statistieken (punt 1 en 5) hoeven nooit over chunks heen samengevoegd te worden -- alleen
de GEPOOLDE tellingen (punt 2, 3, 4) worden chunk voor chunk opgeteld.

**Eén bewuste vereenvoudiging: de scheefheid in punt 3.** De per-BRON
``resolveer_domein``-tussenresultaten (tot 4 losse scheefheidswaarden per kwartier, één per
meetbron) zijn er niet meer tegen de tijd dat het rapport gebouwd wordt (ze zijn per chunk al
verwerkt en vrijgegeven). De scheefheid wordt daarom herleid uit de al weggeschreven
``measurements``-kolommen zelf (``tijdstip_meting - tijdstip_start``) -- dat is de scheefheid van
de ÉÉN gekozen meting per kwartier (na de vaste prioriteit dsmr > kamstrup > heatpump > boiler, zie
tabellen.py), niet die van elke bron apart. Dat is een andere, iets kleinere steekproef (één
sample per kwartier in plaats van tot vier), maar wel degelijk representatief: het is exact de
scheefheid van de tijdstempel die ook daadwerkelijk in ``measurements.tijdstip_meting``
terechtkomt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import gaskwaliteit, opmaak
from .timestamps import SCHEEF_DREMPEL

# Presence-proxykolommen in measurements: één "levend" kolom per bron, notna() ervan == die bron
# had een teller-waarde in dat kwartier (zie tabellen.build_measurements_en_quality).
_BRON_PROXYKOLOM = {
    "dsmr": "e_import_laag_cum__kWh",
    "kamstrup": "q_geleverd_cum__J",
    "heatpump": "e_warmtepomp_cum__kWh",
    "boiler": "e_ketel_cum__kWh",
}

#: De drie gekoppelde weergrootheden in ``derived`` (ontwerp §4), voor de dekkingstelling in punt 7.
WEERKOLOMMEN: tuple[str, ...] = ("temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2")

#: De enige kolommen die dit rapport uit ``derived`` nodig heeft. Die tabel is met ruim 200 MB de
#: grootste van de vijf; hem in zijn geheel inlezen om twee tellingen te doen zou precies het
#: geheugenbeslag terugbrengen dat de chunking wegneemt.
DERIVED_KOLOMMEN: tuple[str, ...] = (
    "home_id__str", gaskwaliteit.BRON_KOLOM, gaskwaliteit.KOLOM, *WEERKOLOMMEN,
)


def _langste_ononderbroken_run(vlag: pd.Series, home_id: pd.Series) -> int:
    """Langste aaneengesloten reeks ``True``-waarden in ``vlag``, per woning apart bepaald (een reeks
    mag niet over een woninggrens heen lopen). Voor punt 4: `teller_nulmeting__bool` als enkel getal
    verbergt dat één woning weken- of maandenlang op 0 kan vaststaan (ontwerp-teller-artefacten.md
    §6, §8) -- dit maakt die langste periode zichtbaar naast het totale aantal rijen.
    """
    s = vlag.fillna(False).astype(bool)
    if not s.any():
        return 0
    werk = pd.DataFrame({"home_id__str": home_id.to_numpy(), "vlag": s.to_numpy()})

    def _max_run(g: pd.Series) -> int:
        run_id = (~g).cumsum()
        return int(g.groupby(run_id).cumsum().max())

    per_woning = werk.groupby("home_id__str", sort=False)["vlag"].apply(_max_run)
    return int(per_woning.max()) if len(per_woning) else 0


def _stookseizoen(tijdstip_start: pd.Series) -> pd.Series:
    """Stookseizoen-jaar: juli t/m juni is één seizoen, genoemd naar het beginjaar (bv. juli 2022
    t/m juni 2023 -> 2022). Ruimer dan het letterlijke stookseizoen (doorgaans okt-apr), maar
    daarmee ook ongevoelig voor het exacte begin/einde ervan -- het gaat hier alleen om "hoeveel
    verschillende stookseizoenen dekt deze woning", niet om het stookseizoen zelf af te bakenen."""
    jaar = tijdstip_start.dt.year
    maand = tijdstip_start.dt.month
    return jaar.where(maand >= 7, jaar - 1)


@dataclass
class RapportAccumulator:
    """Verzamelt de rapportcijfers chunk voor chunk (zie module-docstring). Alles hier is O(aantal
    woningen), op de scheefheids-samples na (O(aantal rijen), maar als kale float32-array van een
    paar bytes per rij -- zie module-docstring in de IM3-zusterrepo voor dezelfde afweging).
    """

    n_rijen_measurements: int = 0
    n_rijen_quality: int = 0
    per_woning_rows: list[dict] = field(default_factory=list)
    n_compleet: int = 0
    n_geobserveerd: int = 0
    n_terug: int = 0
    n_teruglevering: int = 0
    n_sprong: int = 0
    n_beoordeeld: int = 0
    n_initialisatie: int = 0
    n_woningen_initialisatie: int = 0
    n_nulmeting: int = 0
    n_woningen_nulmeting: int = 0
    langste_nulmeting_periode__kwartieren: int = 0
    n_wissel: int = 0
    n_woningen_wissel: int = 0
    scheefheid_chunks: list[np.ndarray] = field(default_factory=list)
    gas_hhv_bron_tellingen: dict[str, int] = field(default_factory=dict)
    gas_hhv_som__J_m_3: float = 0.0
    gas_hhv_n: int = 0
    n_rijen_derived: int = 0
    weer_ontbrekend: dict[str, int] = field(default_factory=dict)
    n_woningen_weer_onvolledig: int = 0

    def voeg_chunk_toe(
        self,
        measurements: pd.DataFrame,
        quality: pd.DataFrame,
        derived: pd.DataFrame | None = None,
    ) -> None:
        """Verwerk één chunk se ``measurements``/``quality`` (zoals :func:`tabellen.
        build_measurements_en_quality` ze teruggeeft, vóór of ná een schijf-rondje maakt niet uit).
        Een chunk bevat een woning nooit gedeeltelijk (chunks partitioneren op woning), dus de
        per-woning cijfers hieronder zijn na deze ene aanroep al compleet voor die woning.

        ``derived`` hoeft alleen :data:`DERIVED_KOLOMMEN` te bevatten -- de enige kolommen die het
        rapport uit die (grootste) tabel nodig heeft, zodat hij niet in zijn geheel gelezen hoeft te
        worden. ``None`` betekent dat de chunk uit code van vóór die kolommen komt; punt 6 en 7 laten
        dat dan zien als "niet vastgelegd" in plaats van als "nul keer".
        """
        self.n_rijen_measurements += len(measurements)
        self.n_rijen_quality += len(quality)

        if derived is not None:
            self.n_rijen_derived += len(derived)
            self._voeg_gaskwaliteit_toe(derived)
            self._voeg_weerdekking_toe(derived)

        for home_id, groep in measurements.groupby("home_id__str", sort=False):
            rij = {"home_id__str": home_id}
            for bron, kolom in _BRON_PROXYKOLOM.items():
                rij[bron] = int(groep[kolom].notna().sum())
            rij["eerste_kwartier"] = groep["tijdstip_start"].min()
            rij["laatste_kwartier"] = groep["tijdstip_start"].max()
            rij["n_stookseizoenen"] = int(_stookseizoen(groep["tijdstip_start"]).nunique())
            self.per_woning_rows.append(rij)

        self.n_compleet += int((~quality["bron_incompleet__bool"].fillna(True)).sum())
        self.n_geobserveerd += int(quality["bron_incompleet__bool"].notna().sum())
        self.n_terug += int(quality["teller_terug__bool"].fillna(False).sum())
        self.n_teruglevering += int(quality["teruglevering__bool"].fillna(False).sum())
        self.n_sprong += int(quality["teller_sprong__bool"].fillna(False).sum())
        self.n_beoordeeld += int(quality["teller_terug__bool"].notna().sum())

        # Drie artefacten uit ontwerp-teller-artefacten.md §4/§7/§8: rijen, woningen (chunks
        # partitioneren op woning, dus geen dubbeltelling over chunks heen), en voor de nulmeting de
        # langste aaneengesloten periode -- een enkel rijentotaal verbergt dat één gasmeterstoring
        # van maanden zwaarder weegt dan honderd losse incidenten (§6, §8).
        for kolom, n_attr, woningen_attr in (
            ("teller_initialisatie__bool", "n_initialisatie", "n_woningen_initialisatie"),
            ("teller_nulmeting__bool", "n_nulmeting", "n_woningen_nulmeting"),
            ("teller_wissel__bool", "n_wissel", "n_woningen_wissel"),
        ):
            vlag = quality[kolom].fillna(False)
            setattr(self, n_attr, getattr(self, n_attr) + int(vlag.sum()))
            setattr(
                self, woningen_attr,
                getattr(self, woningen_attr) + int(quality.loc[vlag, "home_id__str"].nunique()),
            )
        self.langste_nulmeting_periode__kwartieren = max(
            self.langste_nulmeting_periode__kwartieren,
            _langste_ononderbroken_run(quality["teller_nulmeting__bool"], quality["home_id__str"]),
        )

        scheefheid__s = (
            (measurements["tijdstip_meting"] - measurements["tijdstip_start"]).dt.total_seconds().dropna()
        )
        if len(scheefheid__s):
            self.scheefheid_chunks.append(scheefheid__s.to_numpy(dtype="float32"))

    def _voeg_gaskwaliteit_toe(self, derived: pd.DataFrame) -> None:
        """Punt 6: hoe vaak viel de calorische waarde terug op de vaste aanname, en welke waarde is
        er gemiddeld toegepast."""
        if gaskwaliteit.BRON_KOLOM in derived.columns:
            for bron, n in derived[gaskwaliteit.BRON_KOLOM].value_counts().items():
                self.gas_hhv_bron_tellingen[str(bron)] = self.gas_hhv_bron_tellingen.get(str(bron), 0) + int(n)
        if gaskwaliteit.KOLOM in derived.columns:
            geldig = derived[gaskwaliteit.KOLOM].dropna()
            self.gas_hhv_som__J_m_3 += float(geldig.sum())
            self.gas_hhv_n += int(len(geldig))

    def _voeg_weerdekking_toe(self, derived: pd.DataFrame) -> None:
        """Punt 7: hoe vaak heeft een kwartier GEEN weerwaarde.

        Anders dan bij de gaskwaliteit vult de pijplijn hier niets in: een kwartier waarvan het uur
        geen KNMI-waarde heeft, houdt ``NaN``. Dat is de juiste keuze (ontwerp §3: nul is een waarde,
        ontbrekend niet), maar hij is even onzichtbaar als een stille terugval zou zijn -- wie op het
        weer joint en NaN's laat vallen, verliest rijen zonder te weten hoeveel.
        """
        aanwezige = [k for k in WEERKOLOMMEN if k in derived.columns]
        if not aanwezige:
            return
        for kolom in aanwezige:
            self.weer_ontbrekend[kolom] = self.weer_ontbrekend.get(kolom, 0) + int(derived[kolom].isna().sum())
        if "home_id__str" in derived.columns:
            geen_weer = derived[aanwezige].isna().all(axis=1)
            # Chunks partitioneren op woning, dus een woning kan hier nooit dubbel geteld worden.
            self.n_woningen_weer_onvolledig += int(derived.loc[geen_weer, "home_id__str"].nunique())

    def scheefheid_samples__s(self) -> np.ndarray:
        if not self.scheefheid_chunks:
            return np.array([], dtype="float32")
        return np.concatenate(self.scheefheid_chunks)

    def per_woning(self) -> pd.DataFrame:
        return pd.DataFrame(self.per_woning_rows)


def build_report(homes: pd.DataFrame, acc: RapportAccumulator, is_steekproef: bool = True) -> str:
    n_woningen = homes["home_id__str"].nunique()
    per_woning = acc.per_woning()

    lines: list[str] = []
    lines.append("# Datakwaliteitsrapport")
    lines.append("")
    lines.append(
        "**Gegenereerd door** `dph_preprocessing.rapport`, niet handmatig bijgehouden "
        "(ontwerp-preprocessing.md §3)."
    )
    if is_steekproef:
        lines.append(
            f"\n> **Dit is een steekproef-run** ({n_woningen} woning(en)), geen run over de volle "
            "~174 woningen. De patronen hieronder zijn representatief voor de aanpak, maar de "
            "percentages/aantallen moeten herberekend worden op de volledige dataset vóór ze als "
            "eindconclusie gelden."
        )
    lines.append("")
    lines.append(f"- Aantal woningen: {n_woningen}")
    lines.append(
        "- Aantal measurement-rijen (kwartieren met >=1 van de vier tellerbronnen): "
        f"{opmaak.getal(acc.n_rijen_measurements)}"
    )
    lines.append(f"- Aantal quality-rijen (volledig kwartierrooster per woning): {opmaak.getal(acc.n_rijen_quality)}")
    lines.append("")

    # --- §7 punt 1: per woning, per bron -----------------------------------------------------
    lines.append("## 1. Aantal complete kwartieren per meetbron, per woning")
    lines.append("")
    lines.append("| home_id | dsmr | kamstrup | heatpump | boiler |")
    lines.append("|---|---:|---:|---:|---:|")
    per_bron_totaal = {bron: 0 for bron in _BRON_PROXYKOLOM}
    for _, r in per_woning.sort_values("home_id__str").iterrows():
        lines.append(
            f"| {r['home_id__str']} | {opmaak.getal(r['dsmr'])} | {opmaak.getal(r['kamstrup'])} | "
            f"{opmaak.getal(r['heatpump'])} | {opmaak.getal(r['boiler'])} |"
        )
        for bron in _BRON_PROXYKOLOM:
            per_bron_totaal[bron] += int(r[bron])
    lines.append("")
    lines.append(
        "Totaal over alle woningen: "
        + ", ".join(f"{b}={opmaak.getal(n)}" for b, n in per_bron_totaal.items())
    )
    lines.append("")

    # --- §7 punt 2: overlap van de vier bronnen -----------------------------------------------
    lines.append("## 2. Overlap van de vier bronnen (bron_incompleet__bool)")
    lines.append("")
    lines.append(
        f"- Kwartieren met alle vier de bronnen tegelijk beschikbaar (basis voor een "
        f"COP-berekening): {opmaak.aandeel(acc.n_compleet, acc.n_geobserveerd)} van de kwartieren met >=1 bron."
    )
    lines.append(
        "- Dit is de belangrijkste openstaande onbekende uit het ontwerp (§5): zonder deze overlap "
        "is een COP per bedrijfspunt niet te berekenen."
    )
    lines.append("")

    # --- §7 punt 3: verdeling van de scheefheid ------------------------------------------------
    lines.append("## 3. Verdeling van de scheefheid (§2.1)")
    lines.append("")
    scheefheid_samples__s = acc.scheefheid_samples__s()
    if len(scheefheid_samples__s):
        percentielen = np.percentile(scheefheid_samples__s, [50, 90, 95, 99, 100])
        drempel_s = SCHEEF_DREMPEL.total_seconds()
        n_boven_drempel = int((scheefheid_samples__s > drempel_s).sum())
        lines.append(
            f"- Aantal (kwartier, gekozen bron)-metingen met een scheefheid: {opmaak.getal(len(scheefheid_samples__s))} "
            "(de scheefheid van de ÉÉN meting die `tijdstip_meting` haalt, zie module-docstring)."
        )
        lines.append(
            "- Percentielen (seconden na de kwartiergrens): "
            f"mediaan={opmaak.getal(percentielen[0])}, p90={opmaak.getal(percentielen[1])}, "
            f"p95={opmaak.getal(percentielen[2])}, p99={opmaak.getal(percentielen[3])}, "
            f"max={opmaak.getal(percentielen[4])}"
        )
        lines.append(
            f"- Boven de voorgestelde drempel van {opmaak.getal(drempel_s)} s (5 min): "
            f"{opmaak.aandeel(n_boven_drempel, len(scheefheid_samples__s))}."
        )
        lines.append(
            "- **Open vraag uit het ontwerp**: is deze drempel realistisch? Bovenstaande "
            "percentage is het antwoord op een steekproef; op de volledige dataset herberekenen "
            "vóór de drempel als definitief te beschouwen."
        )
    else:
        lines.append("- Geen metingen om de scheefheid van te bepalen.")
    lines.append("")

    # --- §7 punt 4: tellers die teruglopen, teruggeleverd worden, of springen -------------------
    # ontwerp-teller-artefacten.md §7/§8: drie afzonderlijke artefacten (initialisatietelegram,
    # nulmeting, wissel), elk met rijen en woningen.
    lines.append("## 4. Tellers die teruglopen, teruggeleverd worden, of springen")
    lines.append("")
    lines.append(
        f"- `teller_initialisatie__bool` (het DSMR-initialisatietelegram vóór de P1-koppeling, "
        "herkend op de handtekening van vijf sentinelwaarden tegelijk -- herkomst: eerste rij van "
        "`dsmr.csv`, woning `-ORiFQC6`, 2022-02-07T11:10:58, zie `ontwerp-teller-artefacten.md` §3): "
        f"{opmaak.getal(acc.n_initialisatie)} rijen bij {opmaak.getal(acc.n_woningen_initialisatie)} "
        "woningen."
    )
    lines.append(
        f"- `teller_nulmeting__bool` (uitval met herstel: de stand valt terug naar 0 en komt later "
        f"terug op zijn spoor): {opmaak.getal(acc.n_nulmeting)} rijen bij "
        f"{opmaak.getal(acc.n_woningen_nulmeting)} woningen. Langste aaneengesloten periode bij één "
        f"woning: {opmaak.getal(acc.langste_nulmeting_periode__kwartieren)} kwartieren -- een enkel "
        "rijentotaal verbergt dat dit typisch één langdurige storing is (bijvoorbeeld een "
        "gasmeterstoring van maanden), niet honderd losse incidenten."
    )
    lines.append(
        f"- `teller_wissel__bool` (een echte breuk: de stand valt terug naar iets anders dan 0, "
        f"typisch een vervangen meter): "
        f"{opmaak.getal(acc.n_wissel)} rijen bij {opmaak.getal(acc.n_woningen_wissel)} woningen."
    )
    lines.append(
        f"- `teller_terug__bool` (de OR van de twee vlaggen hierboven, `e_net` telt hier niet mee "
        "-- ontwerp §8 B3): "
        f"{opmaak.aandeel(acc.n_terug, acc.n_beoordeeld)}. Kleiner dan nulmeting + wissel samen "
        "alleen als beide op dezelfde rij vallen. Een initialisatierij telt hier niet mee: daar "
        "bestaat geen tellerstand, dus ook geen daling."
    )
    lines.append(
        f"- `teruglevering__bool` (de exportteller stijgt: zonnestroom teruggeleverd dit kwartier): "
        f"{opmaak.aandeel(acc.n_teruglevering, acc.n_beoordeeld)}."
    )
    lines.append(f"- `teller_sprong__bool` (fysisch onmogelijke sprong): {opmaak.aandeel(acc.n_sprong, acc.n_beoordeeld)}.")
    lines.append(
        "- De sprong-drempels per teller (`dph_preprocessing.tellers.SPRONG_DREMPEL__W`) zijn "
        "voorlopige aannames van deze implementatie, niet uit het ontwerp zelf afgeleid -- zie de "
        "kanttekening bij de implementatie."
    )
    lines.append("")

    # --- §7 punt 5: tijdvak per woning + stookseizoenen ----------------------------------------
    lines.append("## 5. Tijdvak per woning en aantal stookseizoenen")
    lines.append("")
    n_twee_of_meer = int((per_woning["n_stookseizoenen"] >= 2).sum()) if len(per_woning) else 0
    lines.append("| home_id | eerste kwartier | laatste kwartier | # stookseizoenen (jul-jun) |")
    lines.append("|---|---|---|---:|")
    for _, r in per_woning.sort_values("home_id__str").iterrows():
        lines.append(
            f"| {r['home_id__str']} | {r['eerste_kwartier']} | {r['laatste_kwartier']} | "
            f"{int(r['n_stookseizoenen'])} |"
        )
    lines.append("")
    lines.append(
        f"- Woningen die >=2 stookseizoenen dekken: {opmaak.aandeel(n_twee_of_meer, len(per_woning))}."
    )
    lines.append(
        "- \"Stookseizoen\" is hier gedefinieerd als juli t/m juni (zie `_stookseizoen` in "
        "`dph_preprocessing.rapport`), niet het smallere okt-apr: dat maakt de telling "
        "ongevoelig voor het exacte begin/einde van het stookseizoen zelf."
    )
    lines.append(
        "- **Let op**: dit telt seizoensjaren die de woning AANRAAKT, niet dekt (ontwerp §8, B8) -- "
        "een woning met data van juni tot januari raakt drie seizoensjaren aan met nul volledig "
        "gedekte. Herdefiniëren met een dekkingseis is nog niet gedaan, zie het ontwerp."
    )
    lines.append("")

    # --- punt 6: waar de verwerking op een aanname terugviel ------------------------------------
    lines.append("## 6. Calorische gaswaarde: werkelijke waarde of terugval?")
    lines.append("")
    lines.append(
        "`g_gebruik__W` rekent m³ gas om naar vermogen met de **werkelijke, per uur gepubliceerde** "
        "calorische waarde, via `mijnenergiedata.nl/calorische-gaswaarden` (zie `gaskwaliteit.py`). "
        "Dat is het landelijk gemiddelde over de netgebieden met Groningen-kwaliteit gas: de enige "
        "kwaliteit die een Nederlandse woning geleverd krijgt, want hoogcalorisch gas wordt vóór "
        "levering aan huishoudens teruggemengd. Lukt het ophalen "
        "voor een uur niet, dan valt die rij terug op de vaste waarde van "
        f"{opmaak.getal(gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / gaskwaliteit.MJ_NAAR_J, 2)}"
        " MJ/m³. Beide gevallen staan per rij in `derived.gas_hhv_bron__cat`, en de toegepaste "
        "waarde zelf in `derived.actual_gas_std_hhv__J_m_3`."
    )
    if acc.gas_hhv_bron_tellingen:
        n_totaal = sum(acc.gas_hhv_bron_tellingen.values())
        n_fallback = acc.gas_hhv_bron_tellingen.get(gaskwaliteit.BRON_FALLBACK, 0)
        lines.append("")
        for bron, n in sorted(acc.gas_hhv_bron_tellingen.items()):
            lines.append(f"- `{bron}`: {opmaak.aandeel(n, n_totaal)} van de derived-rijen.")
        lines.append(
            f"- **Een terugval hoort een uitzondering te zijn.** Is `{gaskwaliteit.BRON_FALLBACK}` "
            "hier een substantieel deel, dan is dat geen detail: het model rekent dan voor die rijen "
            "op een constante in plaats van op een gepubliceerde waarde, en dat ziet er in de uitvoer "
            "precies hetzelfde uit. Controleer dan of de ingest is overgeslagen "
            "(`--skip-gaskwaliteit`), of de niet-gedocumenteerde API van vorm is veranderd, en of "
            "het opgehaalde venster het meetvenster wel dekt."
            if n_fallback
            else f"- Geen enkele rij viel terug op de vaste waarde ({opmaak.getal(0)} van "
            f"{opmaak.getal(n_totaal)}): de ingest was deze run volledig dekkend."
        )
    else:
        lines.append("")
        lines.append(
            "- De herkomst is voor deze run **niet vastgelegd**: er waren geen `derived`-"
            "deelbestanden met `gas_hhv_bron__cat`. Zonder die telling is niet te zeggen of "
            "`g_gebruik__W` op meetwaarden of op een constante rust; herverwerk met `--opnieuw`."
        )
    lines.append("")
    lines.append(
        "- **Twee beperkingen die blijven.** Deze dataset geeft geen netbeheerder of netgebied per "
        "woning, dus dit is een landelijk gemiddelde en geen woningspecifieke waarde. En het is een "
        "gemiddelde over netgebieden, niet gewogen naar afgezet volume."
    )
    regel = (
        "- **Onze `g_gebruik__W` wijkt hierdoor af van het meegeleverde analysepakket** van de "
        "projectuitvoerder, dat met een vaste 9,77 kWh/m³ (= 35,17 MJ/m³) rekent."
    )
    if acc.gas_hhv_n:
        gemiddeld__MJ_m3 = acc.gas_hhv_som__J_m_3 / acc.gas_hhv_n / gaskwaliteit.MJ_NAAR_J
        afwijking = gemiddeld__MJ_m3 / (gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / gaskwaliteit.MJ_NAAR_J) - 1
        regel += (
            f" Gemiddeld over de rijen in deze run is de toegepaste waarde "
            f"{opmaak.getal(gemiddeld__MJ_m3, 3)} MJ/m³, dus "
            f"{opmaak.percentage(afwijking, 2)} hoger. Dat is ongewogen over rijen; naar afgezet "
            "gasvolume gewogen valt het hoger uit, want er wordt gestookt in de maanden waarin het "
            "gas ook rijker is (ontwerp §2.4)."
        )
    regel += " Wie de twee naast elkaar legt, kan het verschil exact terugrekenen met `actual_gas_std_hhv__J_m_3`."
    lines.append(regel)
    lines.append("")

    # --- punt 7: dekking van de weerkoppeling ---------------------------------------------------
    lines.append("## 7. Weerkoppeling: hoe vaak is er geen weer bij een kwartier?")
    lines.append("")
    lines.append(
        "Het weer wordt gekoppeld via het eigen KNMI-station van de woning en het uur waarin het "
        "kwartier valt. Heeft dat uur geen KNMI-waarde, dan blijft de weerkolom **leeg**; er wordt "
        "niets ingevuld en niets geïnterpoleerd. Dat is de bedoeling (ontwerp §3: nul is een waarde, "
        "ontbrekend niet), maar het is even onzichtbaar als een stille aanname zou zijn: wie op het "
        "weer joint en lege waarden laat vallen, verliest rijen zonder te weten hoeveel. Vandaar deze "
        "telling."
    )
    if acc.weer_ontbrekend and acc.n_rijen_derived:
        lines.append("")
        for kolom in WEERKOLOMMEN:
            if kolom in acc.weer_ontbrekend:
                lines.append(
                    f"- `{kolom}` leeg: {opmaak.aandeel(acc.weer_ontbrekend[kolom], acc.n_rijen_derived)} "
                    "van de derived-rijen."
                )
        lines.append(
            f"- Woningen met ten minste één kwartier zonder enige weerwaarde: "
            f"{opmaak.getal(acc.n_woningen_weer_onvolledig)} van {opmaak.getal(n_woningen)}."
        )
        lines.append(
            "- `ghi__W_m_2` ontbreekt vaker dan de andere twee: KNMI's `Q` (globale straling) is een "
            "afgeleid veld dat niet elk station elk uur levert, terwijl `T` en `FH` dat wel doen. Een "
            "analyse die op instraling leunt heeft dus een kleinere bruikbare set dan een die dat niet doet."
        )
    else:
        lines.append("")
        lines.append(
            "- De weerdekking is voor deze run **niet vastgelegd**: er waren geen `derived`-"
            "deelbestanden met de weerkolommen. Herverwerk met `--opnieuw`."
        )
    lines.append("")

    return "\n".join(lines) + "\n"


def write_report(pad: str | Path, homes: pd.DataFrame, acc: RapportAccumulator, is_steekproef: bool = True) -> None:
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(build_report(homes, acc, is_steekproef=is_steekproef), encoding="utf-8")
