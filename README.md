# demoprojecthybride-dataset-preprocessing

Van de ruwe meetdata van het **Demonstratieproject Hybride Warmtepompen** naar vijf getypeerde,
herleidbare Parquet-tabellen. De preprocessing staat op zichzelf: wat hier uit komt is bruikbaar
voor iedereen die met deze dataset aan de slag gaat, ongeacht welke analyse erop volgt. Bij Kenniscentrum Duurzaam
Leven is dat een simulatiemodel dat de tabellen afneemt, maar deze repo veronderstelt dat niet.

> **Lees eerst [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md).** De dataset mag alleen voor
> open verwerking gebruikt worden, gebruik en analysemethodiek moeten gemeld worden, en de ruwe
> data staat niet in deze repo en wordt er ook niet via verspreid.

## Wat dit is

Circa 175 woningen met een hybride warmtepomp, gemeten van 1 januari 2022 tot 1 juni 2024 op
kwartierbasis. Anders dan bij de Installatiemonitor zit hier per woning een **aparte meting van de
warmtepompelektriciteit én van de geleverde warmte** — daarmee is een COP een quotiënt van twee
metingen in plaats van een modeluitkomst.

Deze repo doet daar niets mee. Hij zet de zeven ruwe CSV's om naar:

| tabel | inhoud |
|---|---|
| `homes` | één rij per woning: 17 kenmerken, inclusief het gas- en elektriciteitsverbruik van de twee jaren vóór installatie |
| `measurements` | cumulatieve meterstanden per kwartier |
| `derived` | gemiddeld vermogen per kwartier, plus de momentane steekproeven, plus gekoppeld weer |
| `weer` | KNMI-uurwaarden van het dichtstbijzijnde station |
| `quality` | een vlag per controle, per kwartier |

De kolomnamen volgen die van de Installatiemonitor waar de grootheid dezelfde is, zodat een analyse
die daarop draait met minimale wijziging hier op draait. Zie
[`docs/variable-dictionary.md`](docs/variable-dictionary.md).

## Beginnen

```
pip install -e ".[dev]"
```

Zet de dataset in `data/raw/` (zie GEBRUIKSVOORWAARDEN.md voor waar je hem vandaan haalt) en draai
de pijplijn. De uitvoer landt in `data/processed/`; `docs/data-quality.md` wordt door de pijplijn
zelf geschreven.

De verwerking haalt één ding van internet: de **werkelijke calorische waarde van het geleverde gas**,
per uur, nodig om m³ naar vermogen om te rekenen (zie hieronder). Dat vraagt `requests`, dat in de
`dev`-extra meekomt en anders los in `".[gaskwaliteit]"` zit. Zonder netwerk draaien kan met
`--skip-gaskwaliteit`; dan rekent `g_gebruik__W` met een vaste waarde en zegt het rapport hoeveel
rijen dat raakt. **Lezen** van de uitvoer vraagt nooit netwerk.

## Documenten

| document | waarover |
|---|---|
| [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md) | de licentie, de meldplicht, en hoe je de dataset zelf verkrijgt |
| [`LICENSE`](LICENSE) | de licentie van de **code**: `EUPL-1.2` (de data valt daar niet onder) |
| [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md) | wat deze pijplijn doet en waarom, inclusief zes geverifieerde bevindingen over de vorm van de data en het analyseprogramma richting KITE |
| [`ontwerp-intervalsemantiek.md`](ontwerp-intervalsemantiek.md) | wat een waarde bij een `tijdstip_start` betekent, en drie plekken waar de output dat nu breekt |
| [`docs/variable-dictionary.md`](docs/variable-dictionary.md) | ruw → gestandaardiseerd, kolom voor kolom |
| [`docs/datacatalogus.md`](docs/datacatalogus.md) | de uitvoer van beide paden: tabellen, kolommen, tijdconventies, de regel per kwaliteitsvlag en bekende beperkingen, met bronnen |
| [`datapackage.json`](datapackage.json) | dezelfde uitvoer machineleesbaar (Frictionless Data Package), gegenereerd uit de code |
| `docs/data-quality.md` | gegenereerd rapport over de volledigheid per woning en per bron |

**Tijd.** Beide paden schrijven elke tijdkolom tz-aware in `Europe/Amsterdam`
(`timestamps.TZ_UITVOER`), gelijk aan de Installatiemonitor-preprocessing; intern rekenen ze in UTC.
De zomertijdwissels in de minuutset zijn gecontroleerd op 24-09-2026, over de brondata rond alle
vijf wissels van maart 2022 tot en met maart 2024: het aantal minuten per UTC-uur is vlak, en bij de
oktoberwissels staan beide lokale uren 02:00-02:59 er volledig in. De loggers registreerden dus in
UTC, en er valt geen uur weg.

**Stand van de minuutset.** De verwerkte minuutset is opnieuw gemaakt op 24-09-2026 (174 van 174
locaties, contract `2026-09-24-lokale-tijd` in `contract.json`), met de maskering van het
wissel-interval (A2, `ontwerp-teller-artefacten.md` §10) en in lokale tijd; de oudere uitvoer in UTC
staat apart. Bij woning `W5J0QUUq` loopt `q_geleverd__W` nu van 0 tot 33,3 kW.
`dekking.parquet` is op 26-09-2026 opnieuw gemaakt met `minuut._schrijf_dekking`, zonder de dubbele
drempel 0 van de eerste versie.

**Machineleesbare beschrijving.** [`docs/datacatalogus.md`](docs/datacatalogus.md) beschrijft de
uitvoer van beide paden zoals een gebruiker die aantreft: per tabel het bestand, het aantal rijen en
woningen, per kolom type, eenheid en bronkolom, de tijdconventies en de exacte regel waarop elke
kwaliteitsvlag aan gaat, met een bron per bewering. [`datapackage.json`](datapackage.json) zegt
hetzelfde machineleesbaar, volgens de [Frictionless Data Package](https://datapackage.org/)-standaard.
Het wordt gegenereerd uit de schema's in de code (`python -m dph_preprocessing.datapackage`), en elke
run zet zijn eigen helft in zijn eigen uitvoermap; `tests/test_datapackage.py` borgt dat code,
schema en datapackage niet uit de pas lopen. De licentie erin verwijst naar
`GEBRUIKSVOORWAARDEN.md`, want de data is niet vrij herverspreidbaar.

## Vier dingen om te weten voordat je hier iets mee doet

1. **De tijdstempels liggen niet op het kwartier.** Waar vaker gemeten is, is het eerste meetpunt
   op of ná het kwartier genomen, met de originele tijdstempel. Gemeten op de proefrun is die
   afwijking meestal verwaarloosbaar (mediaan 2 s, p95 8 s) maar loopt hij uit tot bijna een heel
   kwartier. Deze pijplijn lijnt uit en bewaart het origineel.
2. **De momentane kolommen zijn steekproeven, geen intervalgemiddelden.** Voor energie gebruik je
   de cumulatieve tellers. Kolommen met `_meting` in de naam zijn steekproeven. Zie
   [`ontwerp-intervalsemantiek.md`](ontwerp-intervalsemantiek.md) voor welke daarvan alsnog een echt
   intervalgemiddelde kunnen worden, en welke uitdrukkelijk niet.
3. **Een ontbrekend kwartier betekent geen meting, niet nul.**
4. **`g_gebruik__W` bevat een omrekening die niet in de dataset zat.** Van m³ naar vermogen vergt de
   calorische waarde van het gas, en die varieert per netgebied en per uur. Wij halen de werkelijke,
   per uur gepubliceerde waarde op; welke waarde per rij is toegepast en of het de gepubliceerde of
   de terugvalwaarde was, staat in `derived.actual_gas_std_hhv__J_m_3` en
   `derived.gas_hhv_bron__cat`. Reken je onze cijfers na tegen die van de projectuitvoerder, begin
   dan daar: hun notebooks gebruiken één vaste waarde, over de volledige run 1,57% lager (1,72% als
   je naar afgezet gasvolume weegt). Punt 6 van `docs/data-quality.md` geeft het verschil van de
   laatste run.

Alle vier staan uitgewerkt in [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md) §2.

## Licentie

De code valt onder de European Union Public Licence 1.2 (`EUPL-1.2`), zie [`LICENSE`](LICENSE).
Copyright © 2026 Kenniscentrum Duurzaam Leven, Stichting Milieu Centraal.

De licentie van de **data** staat daar los van: de dataset is niet vrij herverspreidbaar, en
inzichten en resultaten vallen onder de voorwaarden van de dataset. De ruwe data staat niet in deze
repo. Zie [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md).
