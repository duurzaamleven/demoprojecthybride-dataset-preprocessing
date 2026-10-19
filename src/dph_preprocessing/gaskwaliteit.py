# SPDX-License-Identifier: EUPL-1.2
"""De werkelijke calorische waarde van geleverd gas ophalen, in plaats van één vaste constante voor
de hele dataset (ontwerp-preprocessing.md §2.4).

``derived.g_gebruik__W`` rekent ``v_gas_consumed`` (m³) om naar vermogen, en daarvoor is de
**calorische bovenwaarde** van het geleverde gas nodig. Die varieert per netgebied en per uur. Deze
module haalt de werkelijke, per uur gepubliceerde waarde op; lukt dat niet, dan valt de omrekening
terug op :data:`GAS_CALORISCHE_WAARDE_FALLBACK__J_M3` en wordt dat **per rij vastgelegd** in
``gas_hhv_bron__cat``, zodat het kwaliteitsrapport kan tellen hoe vaak de aanname nodig was.

**Bron:** `mijnenergiedata.nl/calorische-gaswaarden
<https://www.mijnenergiedata.nl/calorische-gaswaarden/>`_ (EDSN en de regionale netbeheerders,
maandelijks bijgewerkt). Dit is een **niet publiek gedocumenteerde** API, in de IM3-zusterrepo
gevonden door de JS-bundel van de site te inspecteren: ``GET .../api/v1/calorificValues?startMonth=
YYYY-MM&endMonth=YYYY-MM``, die zonder ``gridArea``-parameter alle netgebieden van één maand
tegelijk teruggeeft als CSV. Hij kan zonder aankondiging wijzigen, en dat is precies waarom de
terugvalwaarde en de telling bestaan.

**Netwerk in de pijplijn is geen breuk met ontwerpprincipe 4.** Dat principe ("netwerkvrij bij het
lezen") gaat over de **afnemer** van de tabellen, niet over de verwerking: wat hier uit komt is een
Parquet-bestand dat zonder netwerk te lezen is. De IM3-zusterrepo downloadt in zijn eigen verwerking
zowel KNMI-data als de gaskwaliteit en voldoet daar nog steeds aan. De eerdere lezing, waarin ook de
verwerking netwerkvrij moest zijn, was te ruim en was de enige reden dat hier een vaste aanname
stond.

**Geen netgebied per woning, dus een landelijk gemiddelde.** ``household.csv`` heeft geen
netbeheerder, postcode of regio (17 kenmerken, geen daarvan geografisch), en ``knmi.csv`` geeft
alleen het dichtstbijzijnde weerstation. Een weerstation is geen netgebied, en een afbeelding van
het een op het ander zou een gok zijn die er in de uitvoer net zo uitziet als een meting. Daarom
hetzelfde landelijke gemiddelde per uur als IM3, met dezelfde beperking: nauwkeuriger dan een vaste
jaarconstante, geen vervanging voor een echte netgebied-specifieke waarde. Wordt er ooit een
netgebied per woning bekend, dan kan dezelfde API met een ``gridArea``-parameter preciezer.

**Hoogcalorische netgebieden tellen niet mee.** Nederlandse woningen krijgen geen H-gas. Een
kleinverbruikersaansluiting krijgt altijd gas van Groningen-kwaliteit; hoogcalorisch gas dat voor
huishoudens bestemd is wordt eerst met stikstof teruggemengd naar G-gas. Een huishoudelijke gasmeter
rekent dus nooit af tegen 41 MJ/m³, en een netgebied dat die waarde publiceert levert niet aan
woningen. In een gemiddelde dat op een woningmeting wordt toegepast horen ze niet thuis, en dat
geldt voor elke dataset van woningmetingen, deze en de IM3-zusterrepo allebei.

Ze zijn meteen herkenbaar. Over alle 21.167 opgehaalde uurwaarden (29 gasmaanden, januari 2022 t/m
mei 2024) deden 161 tot 170 gebieden mee en vielen er **elk uur precies 7** af tussen 41 en
43 MJ/m³, met niets tussen 37 en 41. :data:`G_GAS_BOVENGRENS__MJ_M3` ligt in dat lege gat, dus de
drempel is niet kritisch gekozen; het aantal uitgesloten gebieden komt per uur mee in de opgehaalde
tabel, zodat het opvalt als de verdeling ooit verandert.

De IM3-zusterrepo middelt nog wél over alle netgebieden en komt daardoor 0,2 MJ/m³ (~0,6%) te hoog
uit. Zie ``docs/lessen-uit-im3.md``; dat is daar te repareren, niet hier af te wegen.

**Wat dit voor de vergelijkbaarheid betekent.** Het meegeleverde analysepakket van de
projectuitvoerder rekent met 9,77 kWh/m³ = 35,17 MJ/m³, gelijk aan onze terugvalwaarde. Onze
``g_gebruik__W`` wijkt daar dus vanaf zodra de werkelijke waarde beschikbaar is: over de volledige
run 1,57% ongewogen over rijen en 1,72% gewogen naar afgezet volume (het verschil is een
seizoenseffect, zie ontwerp-preprocessing.md §2.4). Dat is de bedoeling, maar het is wel de reden
dat de toegepaste waarde als eigen kolom in ``derived`` staat: wie onze cijfers naast die van de
projectuitvoerder legt, kan het verschil exact terugrekenen in plaats van het te moeten raden.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .timestamps import TZ_UITVOER, assert_utc

log = logging.getLogger(__name__)

API_URL = "https://www.mijnenergiedata.nl/calorische-gaswaarden/api/v1/calorificValues"

#: Naam van de toegepaste calorische waarde in ``derived``. Bewust IDENTIEK aan die van de
#: IM3-zusterrepo (en aan ``nfh_utils``), conform ontwerpprincipe 6: dezelfde grootheid heet in
#: beide repo's hetzelfde, zodat een analyse met minimale wijziging op beide draait.
KOLOM = "actual_gas_std_hhv__J_m_3"

#: Naam van de herkomstkolom in ``derived``, met :data:`BRON_ACTUEEL` of :data:`BRON_FALLBACK`.
BRON_KOLOM = "gas_hhv_bron__cat"
BRON_ACTUEEL = "mijnenergiedata_actueel"
BRON_FALLBACK = "vast_gemiddelde_fallback"

#: Publieke, gestandaardiseerde terugvalwaarde (Gaswet-referentiewaarde voor Groningen-kwaliteit
#: gas), ALLEEN gebruikt voor rijen waarvoor de ingest geen dekking heeft. Zelfde getal als IM3's
#: ``im3_preprocessing.gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3`` en als de 9,77 kWh/m³
#: waarmee het meegeleverde analysepakket van de projectuitvoerder rekent (notebook 4).
GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 = 35.17e6

#: Bovengrens waarboven een netgebied hoogcalorisch gas (H-gas) levert en dus niet meedoet in het
#: landelijke gemiddelde: Nederlandse woningen krijgen geen H-gas (zie de module-docstring). De
#: gemeten verdeling is tweetoppig met een LEEG gebied tussen 37 en 41 MJ/m³, dus deze drempel is
#: niet kritisch gekozen -- hij ligt in dat gat.
G_GAS_BOVENGRENS__MJ_M3 = 38.0

MJ_NAAR_J = 1e6

#: Kolommen van de tabel die :func:`fetch_actual_gas_hhv` teruggeeft en die per maand gecacht wordt.
GAS_HHV_KOLOMMEN: tuple[str, ...] = ("tijdstip", KOLOM, "n_gebieden", "n_gebieden_uitgesloten")

#: De gepubliceerde "maand" is een GASMAAND: hij loopt van de eerste van de maand 06:00 lokale tijd
#: tot de eerste van de volgende maand 06:00. Geverifieerd op januari en februari 2023: 744 en 672
#: aaneensluitende uurwaarden zonder gaten, met de maandgrens op 06:00 lokaal. Vandaar dat de
#: gasmaand van een tijdstip die van ``lokale tijd - 6 uur`` is, en niet de kalendermaand.
GASDAG_START__UUR = 6


def lege_gas_hhv() -> pd.DataFrame:
    """Een lege tabel met het schema van :func:`fetch_actual_gas_hhv` (voor ``--skip-gaskwaliteit``
    en voor het geval elke ophaal mislukt): :func:`koppel_gas_hhv` valt daarop volledig terug op de
    vaste waarde, in plaats van te falen."""
    leeg = pd.DataFrame({naam: pd.Series(dtype="float32") for naam in GAS_HHV_KOLOMMEN})
    leeg["tijdstip"] = pd.Series(dtype="datetime64[ns, UTC]")
    return leeg[list(GAS_HHV_KOLOMMEN)]


def gasmaanden(start: pd.Timestamp, eind: pd.Timestamp) -> list[str]:
    """De gasmaanden (``"YYYY-MM"``) die het venster ``[start, eind]`` overlappen.

    Beide grenzen zijn tz-aware UTC. Zie :data:`GASDAG_START__UUR`: de gasmaand van een tijdstip is
    de kalendermaand van dat tijdstip in lokale tijd, zes uur teruggeschoven. Zo hoort 1 februari
    01:00 lokaal nog bij de januari-publicatie, en dat is precies de rij die anders stil op de
    terugvalwaarde zou landen.
    """
    verschoven = pd.DatetimeIndex([start, eind]).tz_convert(TZ_UITVOER) - pd.Timedelta(
        hours=GASDAG_START__UUR
    )
    periodes = pd.period_range(verschoven[0], verschoven[1], freq="M")
    return [p.strftime("%Y-%m") for p in periodes]


def _fetch_maand(maand: str) -> pd.DataFrame:
    """Haal één gasmaand op en verdicht hem tot één landelijke waarde per uur.

    Retourneert :data:`GAS_HHV_KOLOMMEN`. ``n_gebieden`` is het aantal netgebieden dat in het
    gemiddelde van dat uur meedeed, ``n_gebieden_uitgesloten`` het aantal dat als H-gas is
    afgevallen (zie :data:`G_GAS_BOVENGRENS__MJ_M3`).
    """
    import requests

    resp = requests.get(
        API_URL, params={"startMonth": maand, "endMonth": maand}, headers={"Accept": "*/*"}, timeout=60
    )
    resp.raise_for_status()
    ruw = pd.read_csv(io.StringIO(resp.text))
    ruw["date_time"] = pd.to_datetime(ruw["date_time"], utc=True)

    is_g_gas = ruw["value"] < G_GAS_BOVENGRENS__MJ_M3
    per_uur = ruw[is_g_gas].groupby("date_time")["value"]
    gemiddeld__MJ_m3 = per_uur.mean()
    uitgesloten = ruw[~is_g_gas].groupby("date_time").size()

    resultaat = pd.DataFrame(
        {
            "tijdstip": gemiddeld__MJ_m3.index,
            KOLOM: (gemiddeld__MJ_m3.to_numpy() * MJ_NAAR_J).astype("float32"),
            "n_gebieden": per_uur.size().to_numpy().astype("int32"),
        }
    )
    resultaat["n_gebieden_uitgesloten"] = (
        uitgesloten.reindex(resultaat["tijdstip"]).fillna(0).to_numpy().astype("int32")
    )
    return resultaat[list(GAS_HHV_KOLOMMEN)]


def fetch_actual_gas_hhv(
    start: pd.Timestamp, eind: pd.Timestamp, cache_dir: str | Path | None = None
) -> pd.DataFrame:
    """De werkelijke, landelijk gemiddelde calorische waarde per uur voor ``[start, eind]``.

    Eén request per gasmaand (de API laat zonder ``gridArea`` maar één maand per keer toe). Met
    ``cache_dir`` wordt elke opgehaalde maand daar als ``<YYYY-MM>.parquet`` bewaard en bij een
    volgende aanroep daaruit gelezen. Dat doet twee dingen die hier beide nodig zijn: de gechunkte
    verwerking haalt dezelfde maanden niet per chunk opnieuw op, en een hervatte run rekent met
    exact dezelfde waarden als de afgebroken run, ook als de niet-gedocumenteerde API inmiddels iets
    anders zou teruggeven.

    Een maand die niet op te halen is, levert een **waarschuwing** en wordt overgeslagen; de rijen
    in die maand vallen dan in :func:`koppel_gas_hhv` terug op de vaste waarde en worden daar
    geteld. Dat is een resultaat, niet een fout, zolang het rapport het meldt.
    """
    assert_utc(pd.Series([start, eind]), "gaskwaliteit-venster")
    cache_dir = Path(cache_dir) if cache_dir is not None else None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for maand in gasmaanden(start, eind):
        pad = cache_dir / f"{maand}.parquet" if cache_dir is not None else None
        if pad is not None and pad.is_file():
            frames.append(pd.read_parquet(pad))
            continue
        try:
            maand_frame = _fetch_maand(maand)
        except Exception as exc:  # netwerkfout, of een formaatwijziging van de ongedocumenteerde API
            log.warning("Calorische gaswaarde voor %s niet opgehaald (%s); overgeslagen.", maand, exc)
            continue
        if pad is not None:
            tmp = pad.with_suffix(".parquet.tmp")
            maand_frame.to_parquet(tmp, index=False)
            tmp.replace(pad)
        frames.append(maand_frame)

    if not frames:
        log.warning(
            "Geen enkele gasmaand opgehaald; g_gebruik__W gebruikt overal de vaste waarde van "
            "%.2f MJ/m3.", GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / MJ_NAAR_J,
        )
        return lege_gas_hhv()

    gas_hhv = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates("tijdstip")
        .sort_values("tijdstip")
        .reset_index(drop=True)
    )
    log.info(
        "Calorische gaswaarde: %d uurwaarden (%s t/m %s), gemiddeld %.3f MJ/m3 over %d-%d "
        "netgebieden per uur; %d-%d gebieden per uur uitgesloten als H-gas (>%.0f MJ/m3).",
        len(gas_hhv), gas_hhv["tijdstip"].min(), gas_hhv["tijdstip"].max(),
        float(gas_hhv[KOLOM].mean()) / MJ_NAAR_J,
        int(gas_hhv["n_gebieden"].min()), int(gas_hhv["n_gebieden"].max()),
        int(gas_hhv["n_gebieden_uitgesloten"].min()), int(gas_hhv["n_gebieden_uitgesloten"].max()),
        G_GAS_BOVENGRENS__MJ_M3,
    )
    return gas_hhv


def koppel_gas_hhv(tijdstip_start: pd.Series, gas_hhv: pd.DataFrame | None) -> pd.DataFrame:
    """Koppel de landelijke uurreeks aan kwartierrijen: welke calorische waarde geldt per rij?

    Retourneert een DataFrame met dezelfde index als ``tijdstip_start`` en twee kolommen:
    :data:`KOLOM` (``float32``, nooit leeg) en :data:`BRON_KOLOM` (``category``).

    **Het uur waarin het kwartier valt, zonder interpolatie** (``floor("h")``), gelijk aan hoe deze
    pijplijn het weer koppelt (:func:`~dph_preprocessing.tabellen.build_derived`). IM3 interpoleert
    hier wel, maar dat komt omdat IM3 vier intervaltypen kent (``q``/``h``/``d``/``m``) en de
    kwartierrijen daar tussen twee uurwaarden moeten worden ingepast; DPH is uitsluitend
    kwartierdata. Bovendien is de gepubliceerde waarde een waarde VOOR dat uur, dus een trapfunctie
    is hier de letterlijke lezing van de bron en niet een benadering ervan: de reeks begint precies
    op de gasdaggrens van 06:00 lokaal, dus de tijdstempel labelt het BEGIN van het uur.
    """
    assert_utc(tijdstip_start, "tijdstip_start")
    hhv = pd.Series(np.nan, index=tijdstip_start.index, dtype="float64")

    if gas_hhv is not None and not gas_hhv.empty:
        assert_utc(gas_hhv["tijdstip"], "gas_hhv.tijdstip")
        reeks = gas_hhv.drop_duplicates("tijdstip").set_index("tijdstip")[KOLOM].sort_index()
        uur = tijdstip_start.dt.floor("h")
        hhv = pd.Series(reeks.reindex(uur).to_numpy(), index=tijdstip_start.index)

    valt_terug = hhv.isna()
    hhv = hhv.fillna(GAS_CALORISCHE_WAARDE_FALLBACK__J_M3)

    return pd.DataFrame(
        {
            KOLOM: hhv.astype("float32"),
            BRON_KOLOM: pd.Categorical(
                np.where(valt_terug.to_numpy(), BRON_FALLBACK, BRON_ACTUEEL),
                categories=[BRON_ACTUEEL, BRON_FALLBACK],
            ),
        },
        index=tijdstip_start.index,
    )
