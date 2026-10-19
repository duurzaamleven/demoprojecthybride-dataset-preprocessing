# Werkafspraken voor deze repo

Preprocessing van de meetdata van het **Demonstratieproject Hybride Warmtepompen**: van zeven ruwe
CSV's naar vijf getypeerde, herleidbare Parquet-tabellen, met een kwaliteitsrapport. Het is
**geen analyse** — hier wordt niets geconcludeerd over warmtepompprestaties.

Begin met [`README.md`](README.md) en [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md).
Openstaand werk staat in [`docs/lessen-uit-im3.md`](docs/lessen-uit-im3.md).

## Draaien

```bash
pip install -e ".[dev]"
pytest -q                 # de testsuite is de betrouwbaarste documentatie die er is
bash draai_volledig.sh    # de volledige verwerking, hervatbaar
```

De verwerking is **chunked en hervatbaar**: deelbestanden per blok woningen, en een herstart slaat
over wat al klaar is. Bij een wijziging aan de uitvoer hoort `UITVOER_CONTRACT_VERSIE` omhoog, want
anders wordt een oude cache stilzwijgend hergebruikt.

## Vijf dingen die niet ter discussie staan

1. **Nederlands.** README's, commentaar, docstrings en variabelenamen.
2. **`physiquant__unit`-naamgeving.** De eenheid staat in de naam na een dubbele underscore
   (`g_gebruik__W`, `temp_aanvoer__degC`). `_cum` betekent een meterstand op een moment; zonder
   `_cum` is het een gemiddelde over het interval. Conventie:
   <https://github.com/energietransitie/physiquant__unit>.
3. **Deze repo staat op zichzelf.** Hij kan publiek worden en moet bruikbaar zijn voor iedereen die
   met deze dataset werkt. Verwijs dus **niet** naar de afnemende repo van Kenniscentrum Duurzaam Leven, niet bij
   naam en niet met een link — schrijf "de afnemende repo" of "de afnemende simulatie". Een
   verwijzing naar een privérepo is voor een buitenstaander niet te volgen en suggereert een
   afhankelijkheid die er niet is.
4. **De ruwe data blijft buiten git.** `data/` is gitignored. De dataset heeft eigen
   gebruiksvoorwaarden met een meldplicht; zie [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md)
   vóór je iets publiceert of deelt.
5. **Getallen zonder herkomst zijn schuld.** Neem je een waarde over, leg dan vast wélke bron, welke
   versie en welk peiljaar — niet alleen het getal.

## Schrijf voor iemand die er nog niet was

Een datum hoort in de tekst als hij **iets vastlegt**: wanneer een meting is gedaan, wanneer een
bron is opgehaald, de peildatum van een tussenstand. Hij hoort er **niet** in als hij nieuws meldt
of vertelt sinds wanneer een functie bestaat — *"sinds 26-08-2026 gebruikt X de werkelijke waarde"*
is voor de schrijver een mijlpaal en voor de lezer ruis. Zeg wat er **is**; wat er wás staat in de
git-geschiedenis.

Uitzondering: een datum bij een **externe** ontwikkeling blijft staan, want daar kun je niet in onze
git-geschiedenis kijken.

## Commits

Nederlandstalige commitboodschappen die uitleggen **waarom**, niet alleen wat. Eén onderwerp per
commit.
