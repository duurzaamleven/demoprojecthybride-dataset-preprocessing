# Ontwerp: extractie van de fijne meetdata uit het KITE-dashboard

**Status:** ontwerp, gebouwd en beproefd. Twee locaties zijn volledig per minuut geëxtraheerd en de
uitkomst is getoetst tegen de ruwe data van dezelfde locatie: nul verschillen op alle 55
waardekolommen over 43.192 minuten, grootste afwijking 1,5·10⁻⁵ (float32-afronding). De getallen in
§3 en §8 zijn gemeten, niet geschat. Opgesteld 16-09-2026.

**Aanleiding.** Vraag 2 van de melding aan KITE van 07-09-2026 was of de fijne
meetdata ook *als data* te krijgen is, en niet alleen als kwartiergemiddelde. Het antwoord blijkt ja
te zijn zonder dat er iets geleverd hoeft te worden: het KITE-Grafanadashboard staat op een
ClickHouse-datasource waarin de ruwe tabel `hybridpilot_rvo_prod.measurements` volledig bevraagbaar
is. 174 locaties, 37 kolommen, **2.530.560.436 rijen**, 1 januari 2022 tot 1 juni 2024.

De zeven CSV's waar deze repo nu op draait zijn een uitgedunde afgeleide daarvan. De extractie die
hier beschreven wordt vervangt die CSV's niet, maar zet er een tweede, fijnere invoerweg naast.

Alles in §1 tot en met §4 is **gemeten** op 58,6 miljoen ruwe rijen die inmiddels binnen zijn (drie
locaties, waarvan twee compleet), niet beredeneerd. Waar een getal op een steekproef berust die niet
representatief is, staat dat erbij; dat is bij §3 uitdrukkelijk het geval.

---

## 1. Hoe de brontabel in elkaar zit

Eén rij per bericht van één meetbron, niet één rij per tijdstip. De 35 waardekolommen vallen uiteen
in drie groepen die elkaar per rij **uitsluiten**: van 311.290 gecontroleerde rijen had er geen
enkele twee groepen tegelijk gevuld.

| groep | kolommen | bron |
|---|---|---|
| 1 | `location_1_uptime`, `kamstrup_*`, `heatpump_*`, `boiler_*` | warmtemeter, warmtepomp, ketel |
| 2 | `location_2_uptime`, `dsmr_*` | slimme meter (P1) |
| 3 | `location_3_uptime`, `sonoff_*` | binnenklimaat |

Binnen een groep tikken **alle** kolommen op dezelfde rij. Er is dus geen kolom met een eigen,
afwijkend tempo, en per groep is er per rij precies één tijdstempel die voor al die kolommen geldt.
Dat laatste is wat §5 goedkoop maakt.

Drie dingen uit de tabeldefinitie die het gedrag verklaren:

- `ORDER BY (toStartOfDay(timestamp), location_id, timestamp)`. De dag staat vooraan in de
  sorteersleutel, de locatie pas daarna. Een query die op één locatie én een tijdvenster filtert,
  zoals de onze, snoeit daarmee eerst op de dag en dan pas op de locatie. Dat werkt goed, maar het
  verklaart ook waarom een query over één locatie over de hele periode duur is: die raakt elke dag.
- `TTL toDateTime(timestamp) + toIntervalWeek(1) TO VOLUME 'cold'`. Alles ouder dan een week staat op
  koude opslag. De hele historische set staat daar dus, en dat is waar de gemeten scansnelheid
  vandaan komt.
- Eén database, twee tabellen, geen staging en geen materialized view. Zie §4: dat is de reden dat we
  kunnen zeggen dat er hier geen kopie met meer resolutie ligt.

---

## 2. De bemonsteringsintervallen zijn opvallend stabiel, maar niet overal gelijk

**Gecorrigeerd op 17-09-2026** naar aanleiding van
`verkenning-minuutdata.md` in de zusterrepo, die de tellingen per
minuut over **alle 174 locaties** uitleest in plaats van de tijdverschillen op drie locaties. De
oorspronkelijke tabel staat hieronder bewaard, want het verschil is leerzaam.

Het robuuste getal is het aantal metingen per minuut, want dat is over de hele set te meten zonder
de ruwe tijdstempels opnieuw aan te raken. Mediaan per locatie, geteld over 128.883.543 minuten:

| groep | metingen per minuut | interval | geldt voor |
|---|---:|---:|---|
| 1 warmte | **12** | 5 s | 173 van de 174 |
| 2 slimme meter | **6** | **10 s** | 165 van de 174 |
| 3 binnenklimaat | **2** | 30 s | 173 van de 174 |

De uitzonderingen zitten vrijwel allemaal in groep 2: drie locaties lopen op 59 metingen per minuut
(1 Hz), en vijf zitten op 1, 2, 3 of 5. In groep 1 en 3 wijkt telkens één locatie af.

**De oorspronkelijke meting, en waarom hij misleidde.** Gemeten over 2,5 jaar op drie locaties, als
tijdverschil tussen opeenvolgende rijen:

| groep | mediaan | p01 | p25 | p75 | p99 | binnen ±50 % van de mediaan |
|---|---:|---:|---:|---:|---:|---:|
| 1 warmte | 5,02 s | 4,96 | 5,01 | 5,03 | 5,1 | 99,8 % |
| 2 slimme meter | ~~1,01 s~~ | 0,88 | 1,00 | 1,02 | 10,1 | 96,9 % |
| 3 binnenklimaat | 30,00 s | 28,91 | 29,99 | 30,01 | 31,2 | 99,7 % |

Die 1,01 s klopt voor de drie gemeten locaties en voor niets anders: het zijn er precies drie die op
1 Hz lopen, en de steekproef bestond uit de drie die het eerst geëxtraheerd waren. Dat is dezelfde
fout als in §3 hieronder, in hetzelfde document, en ik heb hem bij het corrigeren van §3 niet
doorgetrokken naar deze paragraaf. Voor groep 1 en 3 blijven de getallen wel staan; die komen op
12 respectievelijk 2 metingen per minuut uit, precies zoals de brede telling laat zien.

Per maand uitgesplitst wijkt de mediaan geen enkele maand af: maand in maand uit dezelfde waarden.
De enige instabiliteit is uitval, dus hele periodes zonder rijen, en niet een wisselend tempo.

**Gevolg voor de aggregatie.** Bij die regelmaat valt het ongewogen gemiddelde over een minuut samen
met het tijdgewogen gemiddelde. Een `avg()` per minuut is hier dus geen benadering die verdedigd moet
worden, maar het intervalgemiddelde zelf. Dat is een ander regime dan §4.1 van
`ontwerp-intervalsemantiek.md` beschrijft: daar moest uit één meting per kwartier een
intervalgemiddelde gereconstrueerd worden, hier zitten er twaalf tot zestig metingen in het interval.

---

## 3. De samenstelling per locatie

Gemeten met één aggregatiequery over een representatieve winterweek (9 tot 16 januari 2023), die 2,8
seconden kostte. 144 van de 174 locaties waren die week actief.

| | aantal |
|---|---:|
| locaties met groep 1 (warmte) | 144 |
| locaties met groep 3 (binnenklimaat) | 142 |
| locaties met dsmr-rijen | 139 |
| locaties met echte dsmr-**waarden** | 136 |
| locaties met dsmr-rijen maar geen waarden (pure hartslag) | 3 |

Aandeel bronrijen per groep: 59,3 % groep 1, 31,2 % groep 2, 9,5 % groep 3. Van alle bronrijen draagt
26,8 % een slimme-meterwaarde.

De bezetting in die week is hoog: **95,4 % van alle minuutvakjes van die 144 locaties bevat data**.
De reductie naar minuutrijen is daarmee **19,8× gemeten over alles**, met een mediaan van 19,7 per
locatie en een spreiding van 1,5 tot 72,8. Dat laatste getal hoort bij de locaties met een 1 Hz-bron.

**Let op de reikwijdte van die 95,4 %, en gebruik hem niet als bezetting van de dataset.** Hij is
gemeten over één winterweek en alleen over de locaties die die week actief waren. Over de volledige
meetperiode per locatie is de bezetting **73,5 %**: 128.883.543 aanwezige tegen 46.520.367
ontbrekende minuten, met een mediaan van 76,5 % per locatie. Het verschil zit niet in korte
haperingen maar in uitval: 92,7 % van alle ontbrekende minuten zit in 659 gaten van langer dan een
dag, en het langste gat per locatie is mediaan 133 dagen. Een week die voor 144 locaties actief was,
laat die uitval per definitie niet zien.

Voor de kostenraming in §8 maakt het niets uit, want die rekent met het werkelijke aantal
geëxtraheerde rijen. Voor elke uitspraak over dekking maakt het alles uit. Zie
`verkenning-minuutdata.md` in de zusterrepo voor de opbouw van de gaten.

Een mediaan van 19,7 rijen per minuut komt neer op groep 1 (12 per minuut, 5 s), groep 3 (2 per
minuut, 30 s) en groep 2 op ongeveer 10 s. Dat sluit aan op wat de melding aan KITE als "tien
seconden" beschreef.

**Een eerdere versie van dit stuk zat hier mis**, en het is leerzaam waarom. De eerste steekproef
bestond uit de drie locaties die het eerst binnen waren, en de export werkt locaties van groot naar
klein af. Twee van die drie bleken tot de vijf uitzonderingen met een 1 Hz-bron te horen, waardoor de
geschatte reductie op 50 tot 73× uitkwam in plaats van op 19,8×. De algemene les staat al in §5 van
`ontwerp-intervalsemantiek.md` en geldt hier onverkort: elke
statistiek over deze dataset moet per locatie voordat hij gepoold wordt. Deze paragraaf is daar een
tweede voorbeeld van, met de spiegelbeeldige fout: niet één kapotte locatie die het gepoolde getal
bederft, maar een steekproef uit de kop van een gesorteerde lijst die voor het geheel werd
aangezien.

---

## 4. De cumulatieve tellers zijn Float32, en dat is te krap

De acht tellerkolommen staan in de brontabel als `Float32` en tikken in stappen van 0,001 (1 Wh,
1 dm³). Bij de standen die deze meters inmiddels hebben bereikt, is dat te weinig. Gemeten als
hoogste stand over alles wat binnen is, afgezet tegen de afstand tussen twee opeenvolgende
representeerbare `Float32`-waarden daar:

| teller | hoogste stand | float32-stap daar | niveaus per tellerstap |
|---|---:|---:|---:|
| `dsmr_e_delivered_high` | 17.709 kWh | 0,00195 | **0,5** |
| `dsmr_e_consumed_high` | 16.623 kWh | 0,00195 | **0,5** |
| `dsmr_e_consumed_low` | 16.042 kWh | 0,00098 | 1,0 |
| `dsmr_v_gas_consumed` | 15.135 m³ | 0,00098 | 1,0 |
| `dsmr_e_delivered_low` | 7.675 kWh | 0,00049 | 2,0 |
| `heatpump_energy` | 5.783 kWh | 0,00049 | 2,0 |
| `kamstrup_e_thermal_system` | 102,6 GJ | 0,0000076 | 131 |
| `boiler_energy` | 38,8 kWh | 0,0000038 | 262 |

Boven de 16.384 kan `Float32` een stap van 0,001 niet meer weergeven. Twee tellers zitten daarboven
en kunnen hun eigen laatste significante cijfer dus niet meer dragen: opeenvolgende stappen van 1 Wh
worden afwisselend ingeslikt en verdubbeld. Vier andere zitten op 1 tot 2 niveaus per stap en hebben
daarmee geen marge meer.

Drie gevolgen, en het derde is de reden dat deze paragraaf hier staat en niet alleen in het rapport:

1. **Differentiëren over korte intervallen is bij laag vermogen kwantisatie-gedomineerd.** Bij 100 W
   accumuleert er per minuut minder dan één representeerbaar niveau. Over een kwartier is dat
   opgelost. Het is dus een argument om per minuut te *extraheren* en pas in de verwerking naar het
   analyse-interval te gaan, niet om per minuut te analyseren.
2. **Interpoleren van een tellerstand naar een intervalgrens verzint precisie die er niet is.** Zie
   §5: dat is de doorslaggevende reden om die interpolatie niet in de extractie te doen.
3. **Het is een bronprobleem, niet op te lossen aan onze kant, en mogelijk al te laat.** Dit is de
   belangrijkste nuance en hij stond er eerst niet in. Een `ALTER` naar een ruimer type **repareert de
   historie niet**: die zet de al afgeronde waarden om, en de weggevallen bits komen niet terug. Of
   de bestaande 2,5 jaar te redden is hangt er dus aan of er stroomopwaarts van ClickHouse nog een
   plek is waar de oorspronkelijke waarde staat, bijvoorbeeld de ruwe P1-telegrammen.

   Wat wij daarover kunnen vaststellen: **in de database die wij zien is die plek er niet.** De hele
   instantie bevat één database met twee tabellen, `measurements` en `knmi`, zonder staging-tabel en
   zonder materialized view. Wat daarvóór gebeurt is van buitenaf niet te zien, en het is ook niet
   duidelijk of KITE of Inversable daarover gaat. Daarom staan er in de mail drie vragen in plaats van
   één verzoek: wie beheert het schema, bestaat de oorspronkelijke waarde nog ergens, en pas dan het
   type.

   **Welk type dan wel.** `Decimal32(3)` is het enige écht exacte type (een meterstand ís een
   decimaal getal met drie decimalen) en kost dezelfde vier bytes als `Float32`. Toch is `Float64`
   hier het betere verzoek, en dat is een afweging die de eerste versie van dit stuk verkeerd maakte:

   - `Float64` is voor deze grootheden praktisch exact. Bij 16.623 kWh liggen twee waarden
     3,6·10⁻¹² uit elkaar, oftewel een miljardste van de metertik; bij een miljoen kWh nog steeds
     1,2·10⁻¹⁰.
   - `Decimal` verandert de semantiek voor álles wat de tabel leest, dus ook voor hun eigen
     dashboards en de CSV-levering.
   - En de exactheid overleeft de keten niet: pandas en numpy kennen geen decimaal type, dus elke
     analist maakt er alsnog een `Float64` van.

   Let op: onze eigen `arrow_type()` kent `Decimal` niet en zou zo'n kolom als tekst wegschrijven,
   met een waarschuwing. Verandert het brontype ooit, dan is dat het eerste wat aangepast moet
   worden.

---

## 5. Wat de extractie met tellers doet, en vooral wat niet

De regel uit `ontwerp-intervalsemantiek.md` §1 blijft leidend: een waarde bij een `tijdstip_start` is
het gemiddelde over dat interval. En §6 blijft de uitzondering: **een tellerstand is een toestand op
een moment, geen intervalwaarde.**

De vraag is dan welke tellerstand bij een interval hoort. Er zijn twee kandidaten: de eerste meting
ín het interval, of de lineaire interpolatie tussen de laatste meting ervóór en de eerste erin.

**Dat is een kleinere vraag dan hij lijkt.** Zolang er per intervalgrens één waarde wordt gebruikt,
telescopeert de som: het verschil over de hele reeks is exact `F(eind) − F(begin)`, ongeacht welke
waarde er per grens gekozen is. De keuze verdeelt energie tussen twee buurintervallen, maar maakt en
vernietigt niets. Wat overblijft is een tijdfout van hooguit één bemonsteringsinterval, dus 5 s op
een minuut en 5 s op een kwartier.

**Daarom kiest de extractie niet.** Ze levert de gegevens waarmee de verwerking elke keuze nog kan
maken, en alle drie de redenen wijzen dezelfde kant op:

- Interpolatie is een modelaanname (constante flow tussen twee metingen), en die hoort niet in een
  stap die zichzelf "extractie" noemt.
- Interpolatie is onomkeerbaar, en heruitvoeren kost uren tot een nacht (§8).
- Bij de kwantisatie uit §4 interpoleert ze over een trap waarvan de treehoogte zelf al onzeker is.

Concreet levert de extractie per minuut en per groep de **eerste** en de **laatste** tellerstand plus
de bijbehorende echte tijdstempels. Daarmee liggen de twee metingen rond elke minuutgrens hooguit 5 s
uit elkaar, en kan de verwerking later alsnog exact op de grens interpoleren als ze dat wil. Dit
sluit aan op wat deze repo al doet: `tijdstip_meting` wordt naast `tijdstip_start` bewaard, "om de
scheefheid zichtbaar te houden" (`docs/variable-dictionary.md`).

**Terugspringende tellers krijgen in de extractie geen `NaN`.** Een teruggesprongen teller, een
ontbrekende meting en een meterwissel zijn drie verschillende dingen met drie verschillende
vervolgacties, en `NaN` maakt ze alle drie hetzelfde. De extractie registreert; `teller_terug__bool`
en `teller_sprong__bool` in de verwerking oordelen.

**Achteraf gemeten, en het pakt gunstiger uit dan verwacht.** Op ruim 100 miljoen opeenvolgende
minuutparen over 21 locaties staan **43 terugsprongen, en geen enkele kleiner dan 1 eenheid**. De
vrees uit §4 dat Float32-kwantisatie een waas van schijnbare terugsprongen zou opleveren komt dus
niet uit, en de drempel waar de verwerking over zou moeten beslissen bestaat feitelijk niet: elke
waarde tussen 0 en 1 geeft hetzelfde resultaat. Van die 43 landen er 37 op exact 0,0 met daarna
herstel, dus dat zijn foutieve uitlezingen; 7 zijn een echte meterwissel, bij 3 locaties. De
groep 1-tellers hebben er samen één. Zie §6 van
`verkenning-minuutdata.md` in de zusterrepo.

---

## 6. Het uitvoerschema

Eén rij per (locatie, minuut). De minuut is de UTC-minuutgrens en is `tijdstip_start`; de
intervallengte is vast 60 s en hoeft dus niet per rij mee.

| kolommen | aantal | type | inhoud |
|---|---:|---|---|
| `location_id`, `tijdstip_start` | 2 | string, timestamp[ms, UTC] | sleutel |
| de 24 momentane grootheden | 24 | float32 | `avg()` over de minuut, dus het intervalgemiddelde |
| de 8 tellers, eerste stand | 8 | float32 | toestand aan het begin van het interval |
| de 8 tellers, laatste stand | 8 | float32 | maakt een sprong bínnen de minuut lokaliseerbaar |
| `offset_eerste_g1/g2/g3__ms` | 3 | uint16 | ms na de minuutgrens van de eerste meting, 0 tot 59999 |
| `offset_laatste_g1/g2/g3__ms` | 3 | uint16 | idem voor de laatste |
| `n_g1`, `n_g2`, `n_g3` | 3 | uint16 | aantal ruwe metingen achter dit gemiddelde |
| `heatpump_power_min/max`, `boiler_power_min/max`, `kamstrup_p_thermal_system_min/max` | 6 | float32 | het aan- en afslaan binnen de minuut, zie hieronder |

57 kolommen. De drie tellingen zijn wat een gemiddelde van een lege minuut onderscheidt van een
gemiddelde over één losse meting, en ze zijn de basis voor de dekkingskolom die
`ontwerp-intervalsemantiek.md` §4.4 voorstelt.

De offsets staan als milliseconden sinds de minuutgrens en niet als volledige tijdstempels: het
bereik 0 tot 59999 past exact in een `uint16`, het is exact terug te rekenen, en het scheelt 36 bytes
per rij op een tabel van ruim honderd miljoen rijen.

**`min()` en `max()` per minuut op de drie vermogenskolommen gaan mee.** Een minuutgemiddelde middelt
het aan- en afslaan binnen de minuut weg, en juist dat gedrag was de reden dat vraag 2 van de
KITE-melding om fijnere data vroeg. De afweging is asymmetrisch: ze meenemen kost zes kolommen, ze
later alsnog willen kost een volledige heruitvoer (§8). Ze weglaten blijft daarna triviaal, ze
toevoegen niet.

De naamgeving volgt bij de omzetting naar deze repo de `physiquant__unit`-conventie, met `_cum` op de
tellerstanden. In de extractie zelf blijven de bronnamen staan, zodat de vertaalslag op één plek zit
(`docs/variable-dictionary.md`) in plaats van op twee.

---

## 7. De query

Per (locatie, tijdvenster), met dezelfde chunking en hervatting als de ruwe extractie al heeft:

```sql
SELECT toStartOfMinute(timestamp) AS minuut,
       countIf(location_1_uptime IS NOT NULL)          AS n_g1,
       avg(kamstrup_t_supply)                          AS kamstrup_t_supply,
       ...
       argMinIf(heatpump_energy, timestamp, heatpump_energy IS NOT NULL) AS heatpump_energy_eerste,
       argMaxIf(heatpump_energy, timestamp, heatpump_energy IS NOT NULL) AS heatpump_energy_laatste,
       ...
FROM hybridpilot_rvo_prod.measurements
WHERE location_id = {locatie} AND timestamp >= {start} AND timestamp < {eind}
GROUP BY minuut ORDER BY minuut
```

ClickHouse slaat `NULL` over bij aggregatie, dus "het gemiddelde van alle metingen in de minuut, als
die er zijn" komt er vanzelf uit, en een minuut zonder metingen geeft `NULL` in plaats van nul. Dat
is precies het gewenste gedrag.

Beide onzekerheden die hier stonden zijn in de implementatie niet beantwoord maar **weggenomen**. De
tellers gebruiken uitsluitend de `If`-variant, dus het kale NULL-gedrag van `argMin`/`argMax` doet
niet meer ter zake. En `toStartOfMinute` wordt nergens aangeroepen: de minuutgrens en de offsets komen
uit `intDiv` en `%` op `toUnixTimestamp64Milli`, waarvan de schaal vastligt. Een preflight toetst vóór
de eerste chunk of die functies op de draaiende serverversie (25.8.11.66) doen wat de SQL aanneemt.

**Eén val die de eerste echte run blootlegde en die in de query zichtbaar moet blijven.** Elke
kolomverwijzing is gekwalificeerd met een tabel-alias (`m.heatpump_power`). Zonder die kwalificatie
lost ClickHouse `heatpump_power` binnen `min()` op naar de ALIAS van `avg(heatpump_power)` die
eerder in dezelfde SELECT staat, en weigert de query met `ILLEGAL_AGGREGATION`. De min/max-kolommen
liepen er als eerste tegenaan. Dat is geen opsmuk maar de reparatie.

De `GROUP BY` houdt serverzijdig toestand vast voor alle minuten in het venster. Bij 200.000 minuten
en 51 aggregaties is dat ordegrootte 115 MB. Dat is een reden om het venster te begrenzen, niet om
het anders te doen.

---

## 8. Wat het kost en wat het oplevert

De ruwe extractie is gemeten: 33 miljoen rijen per uur bij één werker, dus **ongeveer 75 uur** voor
de volle 2,53 miljard rijen. De bottleneck is aantoonbaar niet de database maar het serialiseren en
parsen van JSON door de Grafana-proxy: 315.000 rijen kosten 20 s, oftewel 1,3 MB/s, wat voor een
netwerkverbinding absurd traag is en voor per-waarde CPU-werk normaal. Serverzijdig aggregeren haalt
precies dat weg.

De per-minuut-modus is gemeten op twee volledige locaties, met `--doelrijen 800000`:

| locatie | bronrijen | minuutrijen | wandklok | bronrijen/s |
|---|---:|---:|---:|---:|
| `UkhY0kLf` (normaal) | 25.483.156 | 865.405 | **3,8 min** | 110.316 |
| `Jr9PJjgK` (1 Hz, augustus 2023) | 3.263.555 | 44.632 | 52 s | 62.760 |

Tegen de 9.200 bronrijen per seconde van de ruwe export is dat een factor **twaalf**. Van de
wandklok zit 89 % in de query's, dus de server is nu de bottleneck en niet meer het parsen; dat is
precies de omslag die het aggregeren moest bewerkstelligen.

Doorgerekend naar de hele dataset, met de gemeten reductie van 19,8×:

| | ruw | per minuut |
|---|---:|---:|
| rijen | 2.530 mln | **~128 mln** |
| op schijf | ~22 GB | **~8 GB** (65 B/rij gemeten) |
| looptijd, één werker | ~75 uur | **6,5 tot 9,5 uur** |
| looptijd, twee werkers | ~38 uur | **3 tot 5 uur** |

De bandbreedte in de looptijd komt doordat de tijd deels met de ingelezen bronrijen meeloopt en
deels met de weggeschreven minuutrijen; de gemeten locatie had een gunstiger verhouding (29×) dan het
gemiddelde (19,8×). Hoe dan ook: van tien nachten naar één nacht, en waarschijnlijk naar één avond.

---

## 9. Waar deze code hoort

De extractietool staat nu buiten deze repo, omdat hij daar ontstond. Dat is niet de goede plek.

`ontwerp-preprocessing.md` §9 stelt voor om de CSV-naar-Parquet-omzetting als eigen, bewaarde stap
vóór de verwerking te zetten, met een manifest dat alleen ongeldig wordt als de bron verandert. Dat
voorstel en deze extractie zijn hetzelfde voorstel, met een andere bron: hier is de bron geen zip met
CSV's maar een API, en het manifest bestaat al. De hervatting, de padcontrole, de chunkplanning en
het manifest zijn geschreven en getest; alleen de query en de chunkmaat veranderen.

**Besloten: een eigen repository, `demoprojecthybride-dataset-extractie`, en niet deze.** Een eerdere
versie van deze paragraaf adviseerde de tool hierheen te halen. Drie argumenten wegen zwaarder:

1. **De extractie vraagt toegang tot het KITE-dashboard**, en die heeft niet iedereen. In deze repo
   zou dat een tweede, bevoorrechte route naast de CSV-levering zetten, terwijl juist die CSV-weg de
   gedocumenteerde standaardweg moet blijven.
2. **Het is een brug, geen bestanddeel.** Als KITE de minuutversie zelf beschikbaar stelt, is die
   code precies één keer nodig geweest en mag hij gearchiveerd worden. Dat wil je niet verweven
   hebben met een repo die blijft.
3. **De methode blijft hier.** Dit document is de methode: de intervalsemantiek, de behandeling van
   tellers, de Float32-bevinding. Dat hoort openbaar en het staat openbaar. De code die het uitvoert
   hoeft dat niet te zijn, en de licentie van die repo legt uit waarom dat geen tegenspraak is.

**Over hernoemen van deze repo: niet doen.** Met de extractie elders dekt "preprocessing" weer
precies wat er staat. Bovendien heet de zusterrepo symmetrisch
`installatiemonitor-dataset-preprocessing`, verwijzen de twee in vier documenten over en weer naar
elkaar, en raakt een hernoeming ook verwijzingen daarbuiten.

---

## 10. Volgorde

1. **De query uit §3**, die vaststelt welke bronnen per locatie draaien en hoeveel minuutrijen het
   werkelijk worden. Read-only, seconden werk, en hij bepaalt of §8 op 35 of op 156 miljoen uitkomt.
2. **De tweede meting**: één geaggregeerde chunk op één locatie, om de doorvoer op volle rijen te
   meten en het grootste veilige venster onder de plugintimeout te vinden.
3. **Implementatie**, met een eigen uitvoermap en een eigen manifest naast de ruwe extractie, zodat
   de hervatting van de twee niet door elkaar loopt.
4. **Droogloop**, daarna een testrun op één locatie, afgezet tegen de ruwe extractie van diezelfde
   locatie die al binnen is. Die vergelijking is een echte gelijkwaardigheidstest: het
   minuutgemiddelde uit de aggregatie moet gelijk zijn aan het minuutgemiddelde dat lokaal uit de
   ruwe Parquet te rekenen is.
5. Pas daarna de volledige run, en pas daarna de beslissing of de ruwe extractie van 2,53 miljard
   rijen nog moet.

Stap 4 is de reden om de ruwe extractie van Jr9PJjgK te bewaren: 42,7 miljoen ruwe rijen van één
locatie zijn precies het ijkpunt waartegen de geaggregeerde uitvoer te controleren is.
