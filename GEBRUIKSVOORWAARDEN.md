# Gebruiksvoorwaarden van de Demoproject Hybride-dataset

Deze repository verwerkt de meetdata van het **Demonstratieproject Hybride Warmtepompen**
(circa 175 gemonitorde woningen, 1 januari 2022 tot 1 juni 2024). De ruwe dataset staat **niet** in
deze git-repo — `data/raw/` is gitignored — en wordt niet door of via deze repo verspreid.

## Letterlijke voorwaarden

Uit `readme en licentie.txt` in `demoprojecthybride-dataset.zip`:

> *"De data mag alleen gebruikt worden voor **open verwerking**. U gaat er mee akkoord dat u de
> beoogde toepassing, verkregen inzichten en toegepaste rekenmethoden ook **openbaar deelt onder
> eenzelfde licentie**."*
>
> *"U bent verplicht uw gebruik, rekenmethoden en conclusies op basis van deze dataset te **melden
> via het KITE community portaal** van de RVO."*

De KITE-pagina van het project formuleert het net iets anders, met dezelfde strekking en een tweede
meldadres:

> *"Het delen van de monitoringsdata gaat onder de voorwaarde dat u uw gebruik, **analysemethodiek**
> en conclusies op basis van deze dataset meldt via data@demoprojecthybride.nl of via het KITE
> portaal van de RVO (kite@rvo.nl)."*

**Eigenaar** is de Smart Energy Foundation (SEF), uitvoerder van het project. Dataverwerking en
data-analyse zijn gedaan door Inversable BV. **Versie:** 10 september 2024, de complete dataset
zoals aanwezig bij beëindiging van het project.

## Wat dit betekent voor deze repo

1. **Melden is verplicht**, niet optioneel, en gebeurt vóór publicatie van conclusies. Dit loopt
   onder hetzelfde regime als de Installatiemonitor 3.0-dataset, waarover in september 2026 al
   afspraken met KITE zijn gemaakt.
2. **De methode moet openbaar.** Anders dan bij de Installatiemonitor, waar onduidelijk was of een
   preprocessingpijplijn zelf als "analyse" telt, noemt deze licentie de rekenmethode expliciet.
   Deze repo is dus bedoeld om openbaar te worden; zie
   [Licentie van de code](#licentie-van-de-code) hieronder.
3. **De ruwe data blijft buiten versiebeheer.** De licentie regelt het *gebruik* en verplicht tot
   het delen van *methoden en inzichten*; ze geeft geen recht de dataset zelf te herpubliceren.
   `data/raw/`, `data/interim/` en `data/processed/` zijn daarom alle drie gitignored.
4. **Afgeleide uitkomsten die wél gedeeld worden** (aggregaten, figuren, conclusies) vallen onder
   dezelfde licentie als de bron, en gaan vergezeld van de melding uit punt 1.

## Licentie van de code

De **code** in deze repo valt onder de European Union Public Licence 1.2 (`EUPL-1.2`), zie
[`LICENSE`](LICENSE). Kenniscentrum Duurzaam Leven heeft daartoe op 19-10-2026 besloten. De
**data** en alles wat eruit volgt (inzichten, aggregaten, figuren, conclusies) vallen daar niet
onder, maar onder de voorwaarden van de dataset hierboven.

Daarmee is ook de spanning opgelost die er zat zolang de code alle rechten voorbehield. De dataset
vraagt "toegepaste rekenmethoden" openbaar te delen "onder eenzelfde licentie", en deze
preprocessing ís die rekenmethode. In `notebooks/README.md` van het meegeleverde analysepakket
staat dat die analyse valt onder CC BY-NC 4.0, met dezelfde formulering over delen "under a similar
public license". CC BY-NC is bedoeld voor documenten en data, niet voor software; Creative Commons
raadt zelf af haar licenties op code te gebruiken. De werkbare invulling, met de bedoeling van de
voorwaarde (een methode die openbaar en controleerbaar is): de **code** onder een gangbare
open-sourcelicentie, nu `EUPL-1.2`, en de **inzichten en resultaten** onder de licentie van de
dataset. Die invulling is ter bevestiging voorgelegd in de melding aan KITE van 07-09-2026.

## Hoe je de dataset zelf verkrijgt

Anders dan de Installatiemonitor vraagt deze dataset geen lidmaatschap van een besloten community.
De bestanden staan op een open URL, aangekondigd via de KITE-pagina van het project:

- **CSV's, 15-minuteninterval:**
  <https://data.inversable.cloud/demoprojecthybride/datasets/demoprojecthybride-dataset.zip>
  (393 MB gecomprimeerd, 2,9 GB uitgepakt)
- **Analyse-omgeving met de notebooks van de projectuitvoerder:**
  <https://data.inversable.cloud/demoprojecthybride/demoprojecthybride-analyse.zip>
- **Grafana-dashboard op het hoogst beschikbare meetinterval:** aan te vragen via <kite@rvo.nl>.
  Dit is de enige route naar data fijner dan een kwartier; de CSV-export is uitgedund.

De KITE-projectpagina staat in de community *Kennis- en Dataplatform Individuele Technieken*
op <https://kennisdelen.rvo.nl/>, onder **Demo Project Hybride**. Daar staat ook een rubriek
*Gepubliceerde analyses*, waar werk van anderen — en te zijner tijd het onze — terechtkomt.

**Contact over de data:** <data@demoprojecthybride.nl>.

## Bronrapportage

De projectresultaten zijn gepubliceerd door de Vereniging voor Duurzame Warmte:
*Eindrapportage Demonstratieproject Hybride Warmtepompen*, 14 januari 2025, met een Engelse
vertaling. Daarnaast bestaat een tussenrapportage *Twee winters met tweehonderd hybrides*.
