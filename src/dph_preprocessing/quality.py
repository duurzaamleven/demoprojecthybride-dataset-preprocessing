# SPDX-License-Identifier: EUPL-1.2
"""De kwaliteitsvlaggen uit ontwerp-preprocessing.md §5, plus ``teruglevering__bool`` (§8, B3).

Elke vlag hier is precies één kolom in ``quality`` (``ontbrekend__bool``, ``scheef__bool``,
``teller_terug__bool``, ``teruglevering__bool``, ``teller_sprong__bool``, ``bron_incompleet__bool``),
zoals opgesomd in ``docs/variable-dictionary.md``. Waar één (woning, kwartier)-rij meerdere
tellers/bronnen heeft, is de vlag hier de OR daarover (:func:`or_vlaggen`), met NA voor "niets om
over te oordelen" in plaats van een stille False.

**``teller_terug__bool`` is wél per-teller bepaald, maar geen per-teller-gesplitste
OUTPUTkolom** zoals bij IM3
(``e_net_uitschieter__bool`` naast ``g_gebruik_uitschieter__bool``): de acht echte bronttellers
worden intern apart gedifferentieerd en gemaskeerd (:mod:`dph_preprocessing.tabellen`), maar dat OR
landt in ÉÉN ``teller_terug__bool``-kolom. Cruciaal is dat de SAMENGESTELDE teller ``e_net`` daar
NIET in meetelt: die daalt legitiem bij teruglevering van zonnestroom (ontwerp §8, B3 -- gemeten:
alle 39.612 dalingen van ``e_net`` op de steekproef vielen samen met een stijgende exportteller).
``teruglevering__bool`` maakt die weggelaten informatie (de exportteller stijgt dit kwartier) apart
bruikbaar.

Dit produceert vlaggen, geen cleaning-beslissingen (ontwerp §3): niets wordt hier gefilterd of
geïmputeerd.
"""

from __future__ import annotations

import pandas as pd

from .timestamps import SCHEEF_DREMPEL

#: De vier meetbronnen waarop ``bron_incompleet__bool`` let (ontwerp §5): dit is de vlag die
#: bepaalt of een COP-berekening voor dat kwartier zinvol is. ``room`` (binnentemperatuur) en
#: ``knmi`` (weer) doen hier bewust NIET aan mee.
COP_BRONNEN = ("dsmr", "kamstrup", "heatpump", "boiler")


def bouw_tijdas(gezien: pd.DataFrame) -> pd.DataFrame:
    """Volledig, regelmatig kwartierrooster per woning: van de eerst tot de laatst waargenomen
    ``tijdstip_start`` over de vier COP-bronnen (``gezien`` = die unie, met kolommen
    ``home_id__str``, ``tijdstip_start``).

    Dit is de enige plek waar een kwartier dat NERGENS een meting heeft toch als expliciete rij
    verschijnt (ontwerp §5: "een ontbrekend kwartier betekent geen meting, niet nul" -- dat is
    alleen zichtbaar te maken als de rij zelf bestaat, mét de vlag, in plaats van gewoon te
    ontbreken uit de tabel). Buiten [eerst geziene kwartier, laatst geziene kwartier] van een
    woning wordt niets verondersteld: dat is vóór de start, of ná het einde, van de meting bij die
    woning, niet een gat erbinnen.
    """
    if gezien.empty:
        return pd.DataFrame(columns=["home_id__str", "tijdstip_start"])

    rijen = []
    for home_id, groep in gezien.groupby("home_id__str", sort=False):
        start, eind = groep["tijdstip_start"].min(), groep["tijdstip_start"].max()
        rooster = pd.date_range(start, eind, freq="15min", tz="UTC")
        rijen.append(pd.DataFrame({"home_id__str": home_id, "tijdstip_start": rooster}))
    return pd.concat(rijen, ignore_index=True)


def scheef_masker(scheefheid__s: pd.Series, drempel: pd.Timedelta = SCHEEF_DREMPEL) -> pd.Series:
    """True waar een meetpunt meer dan ``drempel`` na zijn kwartiergrens lag (ontwerp §2.1/§5).

    Nullable ``boolean``: waar ``scheefheid__s`` zelf ontbreekt (die bron had geen meting dit
    kwartier) is "lag dit scheef" niet te beantwoorden.
    """
    return (scheefheid__s > drempel.total_seconds()).astype("boolean").mask(scheefheid__s.isna())


def or_vlaggen(*vlaggen: pd.Series) -> pd.Series:
    """OR van meerdere nullable-``boolean``-vlagreeksen (zelfde index).

    NA telt niet mee als True. Als ALLE inputs op een rij NA zijn, is de uitkomst ook NA: er is dan
    niets om over te oordelen, en dat is iets anders dan "geen van de bronnen vlagde het".
    """
    gestapeld = pd.concat(vlaggen, axis=1)
    resultaat = gestapeld.fillna(False).any(axis=1).astype("boolean")
    resultaat[gestapeld.isna().all(axis=1)] = pd.NA
    return resultaat


def bron_incompleet_masker(*aanwezig: pd.Series) -> pd.Series:
    """True als niet alle opgegeven bronnen (in de praktijk: :data:`COP_BRONNEN`) een waarde
    hebben in dit kwartier (ontwerp §5). ``aanwezig``: booleans, één per bron, True = bron had een
    teller-waarde in deze rij. Dit is de vlag die bepaalt of een COP-berekening zinvol is."""
    gestapeld = pd.concat(aanwezig, axis=1)
    return (~gestapeld.all(axis=1)).astype("boolean")
