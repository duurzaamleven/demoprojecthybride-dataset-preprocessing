# SPDX-License-Identifier: EUPL-1.2
"""UTC-toekenning en kwartieruitlijning (ontwerp-preprocessing.md §2.1, §2.3).

Twee stappen, allebei expliciet en geen gegeven:

1. **UTC-toekenning** (§2.3): de ruwe ``timestamp``-kolom (bv. ``2022-02-07T11:10:50``) draagt geen
   tijdzone. ``metadata.csv`` documenteert 'm als UTC; die labeling gebeurt hier met opzet, zodat
   er geen naïeve tijdstempel de rest van de pijplijn inglipt (elke functie hieronder werkt
   uitsluitend met tz-aware ``datetime64[ns, UTC]``, en :func:`assert_utc` legt dat vast).
2. **Kwartieruitlijning** (§2.1): woningen die vaker dan per kwartier meten, hebben als tijdstempel
   het EERSTE meetpunt op of ná het kwartier, met de originele tijd. ``tijdstip_start`` is daarom
   een AFGELEIDE (``floor(tijdstip, 15min)``), en de originele tijd blijft bewaard als
   ``tijdstip_meting`` -- dat is de enige plek waar de scheefheid nog zichtbaar is.
"""

from __future__ import annotations

import json

import pandas as pd
import pyarrow as pa

KWARTIER = pd.Timedelta(minutes=15)

#: Tijdzone van de uitvoer. Alle woningen in deze dataset staan in Europees Nederland: ze hangen aan
#: 25 KNMI-stations in het bereik 215-391, en Caribisch Nederland (AST, geen zomertijd) heeft daar
#: geen station in. Geverifieerd op de volledige set, niet aangenomen.
TZ_UITVOER = "Europe/Amsterdam"

# §2.1: het meetpunt lag "meer dan een drempel na de kwartiergrens" -- voorstel uit het ontwerp
# zelf, niet extern bevestigd. De eerste run (docs/data-quality.md) moet laten zien of dit
# realistisch is (ontwerp §7, punt 3).
SCHEEF_DREMPEL = pd.Timedelta(minutes=5)


def assert_utc(serie: pd.Series, naam: str = "tijdstip") -> None:
    """Faalt hard als ``serie`` geen tz-aware UTC-datetimekolom is.

    Dit is de test die ontwerp §2.3 vraagt: "een test legt vast dat er geen naïeve tijdstempel
    doorheen glipt". Wordt aangeroepen op elk punt waar de pijplijn een tijdkolom aanneemt al
    UTC te zijn, niet alleen in de testsuite.
    """
    if not isinstance(serie.dtype, pd.DatetimeTZDtype) or str(serie.dtype.tz) != "UTC":
        raise ValueError(
            f"Kolom {naam!r} is geen tz-aware UTC-datetime ({serie.dtype}); een naïeve of "
            "lokale tijdstempel zou hier stil een verkeerde aanname over de tijdzone maken."
        )


def naar_utc(ruwe_tijdstempel: pd.Series) -> pd.Series:
    """Ken UTC toe aan de ruwe, tz-loze ``timestamp``-kolom (ontwerp §2.3).

    ``utc=True`` op een tz-loze string-/datetimereeks LABELT (in plaats van converteert): een
    naïeve ``2022-02-07T11:10:50`` wordt ``2022-02-07T11:10:50+00:00``, precies de expliciete
    toekenning die het ontwerp vraagt. Zou de invoer al tz-aware zijn (zou hier niet moeten
    voorkomen, zie module-docstring), dan converteert ``pd.to_datetime`` wel degelijk naar UTC in
    plaats van te labelen -- vandaar de expliciete voor-check.
    """
    ruw = pd.to_datetime(ruwe_tijdstempel, errors="raise")
    if isinstance(ruw.dtype, pd.DatetimeTZDtype):
        raise ValueError(
            "Ruwe tijdstempel is al tz-aware; UTC-toekenning zou hier een conversie zijn, geen "
            "expliciete labeling, en dat is niet wat §2.3 bedoelt."
        )
    resultaat = ruw.dt.tz_localize("UTC")
    assert_utc(resultaat)
    return resultaat


def naar_lokale_tijdzone(df: pd.DataFrame) -> pd.DataFrame:
    """Zet elke tz-aware tijdkolom om naar :data:`TZ_UITVOER`, vlak vóór het wegschrijven.

    **Intern blijft de pijplijn in UTC rekenen** -- eenduidig voor joins, floor() en interpolatie --
    en pas hier verandert de weergave. ``tz_convert`` raakt het instant niet aan, alleen het label:
    UTC blijft één ``.dt.tz_convert("UTC")`` verderop. Een lokale tz-aware kolom draagt dus strikt
    meer informatie dan een kale UTC-kolom, niet minder.

    **Waarom lokale tijd.** Menselijk gedrag hangt aan de klok, niet aan UTC: koken, douchen, de
    thermostaat lager zetten, een klokprogramma. Wie op UTC groepeert per uur-van-de-dag, smeert
    hetzelfde gedrag over twee uren uit zodra de zomertijd wisselt. Dit is ook wat de
    IM3-zusterrepo doet (§12.10 daar); die twee moeten gelijk zijn, want ontwerpprincipe 6 belooft
    dat een analyse die op IM3 draait hier met minimale wijziging draait.

    De kwartierafronding blijft geldig: Nederlandse offsets zijn hele uren (+01:00 en +02:00), dus
    een kwartiergrens in UTC is ook een kwartiergrens lokaal.
    """
    uit = df.copy()
    for kolom in uit.columns:
        if isinstance(uit[kolom].dtype, pd.DatetimeTZDtype):
            uit[kolom] = uit[kolom].dt.tz_convert(TZ_UITVOER)
    return uit


def naar_lokale_tijdzone_arrow(tabel: pa.Table) -> pa.Table:
    """Als :func:`naar_lokale_tijdzone`, maar voor een ``pa.Table`` en zonder pandas-kopie.

    Het minuutpad heeft zijn uitvoer al in arrow staan (``minuut.verwerk_locatie_streamend``), en
    een omweg via pandas zou de kopie terugbrengen die dat pad juist weghaalt. Arrow bewaart een
    tijdstempel altijd als UTC-instant; een andere tijdzone is alleen een ander type, dus de cast
    raakt geen enkele waarde.

    **De pandas-metadata moet mee.** Een tabel die uit pandas komt draagt in zijn schema per kolom
    ook een ``timezone``, en ``to_pandas`` gaat daarop af in plaats van op het arrow-type. Zonder
    die bij te werken komt een kolom van type ``timestamp[ms, tz=Europe/Amsterdam]`` bij het
    teruglezen gewoon weer als UTC binnen.
    """
    omgezet: set[str] = set()
    for i, veld in enumerate(tabel.schema):
        if pa.types.is_timestamp(veld.type) and veld.type.tz is not None:
            nieuw_type = pa.timestamp(veld.type.unit, tz=TZ_UITVOER)
            tabel = tabel.set_column(i, veld.with_type(nieuw_type), tabel.column(i).cast(nieuw_type))
            omgezet.add(veld.name)
    pandas_meta = tabel.schema.pandas_metadata
    if omgezet and pandas_meta is not None:
        for kolom in pandas_meta.get("columns", []):
            if kolom.get("field_name") in omgezet and isinstance(kolom.get("metadata"), dict):
                kolom["metadata"]["timezone"] = TZ_UITVOER
        metadata = dict(tabel.schema.metadata)
        metadata[b"pandas"] = json.dumps(pandas_meta).encode("utf-8")
        tabel = tabel.replace_schema_metadata(metadata)
    return tabel


def resolve_timestamps(ruwe_tijdstempel: pd.Series) -> pd.DataFrame:
    """UTC-toekenning + kwartieruitlijning in één stap.

    Retourneert een DataFrame met ``tijdstip_start`` (``floor(tijdstip, 15min)``, tz-aware UTC),
    ``tijdstip_meting`` (de UTC-toegekende ORIGINELE tijd, ongewijzigd) en ``scheefheid__s`` (het
    verschil in seconden, altijd >= 0: het meetpunt ligt per definitie op of ná zijn kwartier,
    nooit ervoor -- zie ontwerp §2.1).
    """
    tijdstip_meting = naar_utc(ruwe_tijdstempel)
    tijdstip_start = tijdstip_meting.dt.floor("15min")
    scheefheid_s = (tijdstip_meting - tijdstip_start).dt.total_seconds()
    if (scheefheid_s < 0).any():
        raise ValueError(
            "Negatieve scheefheid aangetroffen: een meetpunt lag VOOR zijn kwartiergrens, wat "
            "ontwerp §2.1 als niet-voorkomend beschrijft. Zou dit toch gebeuren, is floor() het "
            "verkeerde uitlijnpunt en moet dit heroverwogen worden, niet stil doorgelaten."
        )
    return pd.DataFrame(
        {
            "tijdstip_start": tijdstip_start,
            "tijdstip_meting": tijdstip_meting,
            "scheefheid__s": scheefheid_s.astype("float32"),
        }
    )
