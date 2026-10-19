# Preprocessing van de minuutdata

Ontworpen 17-09-2026, tussen 00:45 en 01:15, met een harde stop op de uitvoering om 07:00 omdat de
NAS daarna tot de avond onbereikbaar is. Dat tijdvak stuurt een paar keuzes hieronder, en waar dat
zo is staat het er expliciet bij.

Dit is een **tweede invoerpad** naast `ontwerp-preprocessing.md`. Dat pad leest `dph-dataset.zip` en
levert een kwartierrooster. Dit pad leest de 174 gecompacteerde parquet-bestanden van de
per-minuut-extractie en houdt het minuutrooster vast. De twee delen de naamgevingsconventie en
`tellers.differentieer_teller`, en verder niets.

Alle getallen hieronder komen uit `verkenning-minuutdata.md` in de zusterrepo, die alle 174 locaties
heeft uitgelezen. De nummers R1 tot R12 verwijzen naar de twaalf preprocessingregels aan het eind van
dat rapport.

---

## 1. Invoer

`//hoftenas/backup/energiedata/DPH-per-minuut/measurements_per_minuut/location_id=<id>.parquet`,
174 bestanden, 128.883.543 rijen, 7,90 GB, 57 kolommen, 25-11-2021 tot 31-05-2024.

**Gemeten leessnelheid over het netwerk: 2,8 MB/s.** Eén volledige leesslag kost dus ongeveer 48
minuten, en dat is de reden dat dit ontwerp alles in *één* pas doet. Elke afgeleide die een tweede
leesslag zou vergen, is hier binnengehaald in de eerste.

## 2. Het rooster blijft de minuut

De kwartierpijplijn zet `floor("15min")` op ruwe tijdstempels. Hier is dat niet aan de orde: de
extractie heeft al op de minuut gegroepeerd en `tijdstip_start` ligt per constructie exact op de
minuutgrens. `resolve_timestamps` en `quality.bouw_tijdas` worden dus niet hergebruikt; dit pad bouwt
zijn eigen tijdas met `freq="1min"`.

## 3. De momentane kolommen zijn hier géén steekproef

Dit is het belangrijkste verschil met de kwartierpijplijn en het rechtvaardigt een afwijking van de
variabelenwoordenlijst. Daar betekent het achtervoegsel `_meting__W` "momentane steekproef, geen
intervalgemiddelde", omdat de kwartierexport één meetwaarde per kwartier overhoudt.

In de minuutdata is `heatpump_power` het **gemiddelde van twaalf metingen** binnen die minuut, en bij
de vaste bemonstering van 5 s valt dat ongewogen gemiddelde samen met het tijdgewogen
intervalgemiddelde (`ontwerp-extractie.md` §2). Het is dus een echt intervalgemiddelde en `_meting__`
zou erover liegen.

Daarom krijgen deze kolommen hier gewoon `__W`, `__degC`, `__V`, `__A`, `__0`, met het aantal
metingen erachter als dekkingsgewicht (R7). Waar dat botst met een gelijknamige kolom uit de
tellerkant, wint de teller de kale naam en krijgt de gemiddelde variant `_gemeten`:

| grootheid | uit de teller | uit de momentane kolom |
|---|---|---|
| warmtepomp | `p_warmtepomp__W` | `p_warmtepomp_gemeten__W` |
| ketel | `p_ketel__W` | `p_ketel_gemeten__W` |
| warmteafgifte | `q_geleverd__W` | `q_geleverd_gemeten__W` |

De teller wint omdat hij energie behoudt: over elk samengesteld interval telt hij exact op tot het
verschil van de randstanden. De momentane kolom doet dat niet, maar hij is er wel op minuten waar de
teller een sprong of een gat heeft. Ze naast elkaar bewaren is goedkoop en maakt R11 mogelijk.

## 4. Tellers: vooruit differentiëren op de eerste stand

Per minuut levert de extractie `<teller>_eerste` en `<teller>_laatste` met hun echte tijdstempel.

**Het uitvoerschema houdt alleen `_eerste`,** als `*_cum__*`, en differentieert vooruit naar de
`_eerste` van de volgende minuut. Dat is de telescopische keuze: de intervallen sluiten exact op
elkaar aan en over elke samenvoeging tot kwartier, uur of dag blijft de som gelijk aan het verschil
van de randstanden. Zou je `laatste − eerste` binnen de minuut nemen, dan valt het stuk tussen de
laatste meting van deze minuut en de eerste van de volgende buiten de boot, en telt de dag niet meer
op tot de dagstand.

`_laatste` gaat niet mee naar de uitvoer maar wordt tijdens de pas wel gebruikt, voor de
consistentiecontrole van R11 en voor het scheiden van nulmetingen van meterwissels.

De omrekening naar vermogen gebeurt met `tellers.differentieer_teller`, ongewijzigd. Die functie
deelt door de **werkelijke** verstreken tijd en niet door een aangenomen roosterbreedte, dus hij
werkt net zo goed op een minuutrooster als op een kwartierrooster. Dat de laatste rij per locatie
`NaN` krijgt is hier hetzelfde en even bedoeld.

**De sprongdrempels uit `tellers.SPRONG_DREMPEL__W` worden NIET overgenomen.** Ze zijn gemeten op de
p99,99 van kwartiergemiddeld vermogen, en een minuutgemiddelde middelt minder uit; de verdeling is
dus breder en die drempels zouden op het minuutrooster vals alarm geven. Dit pad gebruikt fysische
grenzen per grootheid (§6) en meet de eigen p99,99 tijdens de pas, zodat de drempels voor een
volgende versie onderbouwd kunnen worden in plaats van overgenomen.

## 5. Terugsprongen, nulmetingen en meterwissels (R8, R9)

De verkenning vond 43 terugsprongen op ruim 100 miljoen paren, **geen enkele kleiner dan 1 eenheid**.
De drempeldiscussie is daarmee leeg: `teller_terug__bool` vlagt elke daling, en elke drempel tussen 0
en 1 zou hetzelfde opleveren.

Van die 43 landen er 37 op exact 0,0 met daarna herstel. Dat zijn foutieve uitlezingen, geen nieuwe
meter. Het onderscheid:

- `teller_nulmeting__bool`: de stand is exact 0,0 terwijl dezelfde teller bij deze locatie ooit boven
  1 is geweest. Dan is de 0 fout en mag hij niet als tellerstand gelden.
- `teller_wissel__bool`: de stand daalt naar iets dat niet 0 is, of naar 0 bij een teller die nooit
  boven 1 kwam. Dan is het een echte breuk in de reeks.

**Uitzondering die eerst een fout zou hebben opgeleverd:** `dsmr_e_delivered_low/high` staat bij
woningen zonder teruglevering legitiem op 0,0, ruim 4 miljoen keer in de steekproef. De eis "ooit
boven 1 geweest" vangt dat, want bij die woningen wordt hij nooit waar.

Een genulde minuut krijgt geen vermogen toegekend: de stand wordt op `NaN` gezet vóór het
differentiëren, zodat het interval eromheen als één langer interval wordt overbrugd in plaats van een
enorme negatieve en daarna een enorme positieve piek op te leveren.

## 6. Plausibiliteitsfilter per grootheid (R10)

De verkenning vond fysisch onmogelijke waarden in de momentane kanalen: `boiler_power` tot 809 kW,
`kamstrup_p_thermal_system` tot 164 kW en tot −62 kW, `kamstrup_t_supply` tot 185 °C. Negatief
warmtevermogen komt op 171 van de 174 locaties voor.

**Het filter vlagt en kapt niet af.** Een waarde buiten bereik is een defect en geen extreme meting,
maar wegknippen zonder spoor maakt hem onvindbaar; afkappen op de grens verzint bovendien een getal.
De waarde gaat op `NaN` en `onplausibel__bool` gaat aan, met per grootheid een eigen grens:

| grootheid | ondergrens | bovengrens | waarom |
|---|---:|---:|---|
| `p_warmtepomp_gemeten__W` | −100 | 15.000 | hybride unit voor één woning; de verkenning zag geen gezonde woning boven 3,7 kW |
| `p_ketel_gemeten__W` | −100 | 5.000 | elektrisch verbruik van de ketel, niet het gas; mediane woning blijft onder 56 W |
| `q_geleverd_gemeten__W` | −2.000 | 60.000 | warmteafgifte inclusief ketel; de p99-woning haalt 31,5 kW |
| `temp_aanvoer__degC` | −10 | 100 | water in een cv-systeem |
| `temp_retour__degC` | −10 | 100 | idem |
| `temp_binnen__degC` | −10 | 60 | woonkamer |
| `rv_binnen__0` | 0 | 1 | fractie |
| `u_L1/L2/L3__V` | 150 | 300 | netspanning |

De ondergrens op de warmtekolommen is bewust niet 0. Een warmtemeter die licht negatief uitleest bij
stilstand is een bekend nulpuntseffect en geen defect; −2.000 W scheidt dat van de −62 kW die dat wel
is. Of die kleine negatieve waarden op nul moeten, is een analysekeuze en geen preprocessingkeuze,
dus ze blijven staan met hun teken.

## 7. Gaten zijn twee dingen (R4)

71,4 % van de gaten duurt hoogstens 5 minuten en is samen 0,44 % van het gemis; 659 gaten van langer
dan een dag zijn samen 92,7 %. Eén drempel dekt dat niet, dus er komen twee vlaggen:

- `ontbrekend__bool`: deze minuut staat niet in de bron.
- `uitval__bool`: deze minuut valt binnen een aaneengesloten gat van meer dan 24 uur.

Het verschil in gebruik: een kort gat mag je overbruggen, een uitvalperiode hoort uit de noemer. Een
uitvalperiode meenemen als "nul verbruik" is de fout die dit onderscheid moet voorkomen.

**Omvangsbesluit onder tijdsdruk.** De volledige tijdas per locatie uitschrijven zou 175,4 miljoen
rijen opleveren in plaats van 128,9 miljoen, dus 36 % meer schrijfwerk op een verbinding die 2,8 MB/s
haalt. Dat past niet binnen het venster tot 07:00. Daarom schrijft deze run **alleen de aanwezige
minuten**, met per locatie een aparte gatentabel (`gaten.parquet`: begin, eind, duur, soort). Dat
draagt dezelfde informatie, kost een fractie van de ruimte, en de volledige tijdas is er lokaal uit
te reconstrueren wanneer een analyse hem nodig heeft.

## 8. Per-locatiekenmerken die deze pas erbij levert (R1, R2, R3)

Dit is de winst van het feit dat we toch alles lezen. De verkenning kon vraag 1 op 15 locaties
beantwoorden omdat de volledige kolommen lezen duur is; deze pas leest ze sowieso, dus de
classificatie komt er voor **alle 174** uit en gaat naar `homes_minuut.parquet`:

- `warmtemeter_bereik__cat`: `systeem`, `warmtepomp` of `onbeslist`. Bepaald met de proef uit §1.2
  van de verkenning: minuten met een streak van tien minuten waarin de warmtepomp onder 200 W zit
  terwijl de ketel elektrisch aan staat, en dan het aandeel daarvan met warmtelevering boven 2 % van
  het locatiemaximum. Boven 15 % `systeem`, onder 1 % `warmtepomp`, ertussen `onbeslist`.
- `warmtepompkanaal_dood__bool`: `heatpump_power` komt over de hele periode nooit boven 200 W. Dat
  zijn er 39 van de 174 en daar is het elektriciteitskanaal defect, niet de warmtemeter.
- `bezetting__0`, `grootste_gat__min`, en per kolom de dekkingsfractie. R3 is expliciet: dekking
  hoort per kolom en niet per meetgroep, want `n_g2 > 0` zegt niets over een gevulde dsmr-waarde.

`warmtemeter_bereik__cat` is bewust drieledig. Een tweedeling zou de locaties tussen 2,7 en 8,5 %
ergens in duwen terwijl de verkenning niet kon uitsluiten dat dat narijdende warmte uit een buffervat
is. `onbeslist` is hier het eerlijke antwoord en dwingt de analyse tot een keuze.

## 9. Uitvoer

Naar `//hoftenas/backup/energiedata/DPH-per-minuut-verwerkt/`:

| bestand | sleutel | inhoud |
|---|---|---|
| `metingen/location_id=<id>.parquet` | `home_id__str`, `tijdstip_start` | per locatie: 8 `*_cum__*`, de afgeleide `__W`, de momentane kolommen, `n_g1/2/3`, de zes offsets, de vlaggen |
| `gaten.parquet` | `home_id__str`, `begin` | alle gaten met duur en soort |
| `homes_minuut.parquet` | `home_id__str` | de kenmerken uit §8 |
| `dekking.parquet` | `home_id__str`, `kolom__str`, `drempel__min` | aaneengesloten bruikbare tijd per kolom en overbruggingsgrens (`ontwerp-interpolatie-en-dekking.md` §5), uit `gaten.parquet` en `homes_minuut.parquet` |
| `kwaliteit.md` | | rapport met de tellingen per vlag, per locatie en gepoold |
| `contract.json` | | de contractversie waarmee de metingen geschreven zijn (`MINUUT_CONTRACT_VERSIE`) |

Elke tijdkolom (`tijdstip_start`, `begin`, `eind`, `eerste_minuut`, `laatste_minuut`, ook in de
jsonl's) staat tz-aware in `Europe/Amsterdam`, net als in het kwartierpad; intern rekent dit pad
in UTC. Een run weigert te hervatten in een map met metingen van een ander contract, want hij slaat
elke locatie over waarvan het bestand al bestaat en zou oude en nieuwe uitvoer anders mengen.

Per locatie atomisch: eerst `.tmp`, dan hernoemen. De compactieslag van gisteravond sneuvelde na 24
minuten op een `OSError` van de netwerkschijf, dus dat gaat hier niet nog een keer een halve run
kosten.

## 10. Uitvoering binnen het venster

- **Harde stop.** De runner controleert vóór elke locatie de klok en stopt schoon bij het bereiken
  van de deadline, standaard 06:45. Dat is een kwartier vóór 07:00 zodat de laatste locatie nog kan
  afschrijven.
- **Hervatbaar per locatie.** Een locatie waarvan het definitieve bestand bestaat, wordt
  overgeslagen. Wat de deadline niet haalt, loopt vanavond door zonder iets over te doen.
- **Volgorde klein naar groot.** Bij een deadline is het aantal afgemaakte locaties wat telt, niet de
  hoeveelheid bytes. Klein naar groot maximaliseert dat aantal, en het is bovendien het omgekeerde
  van de extractievolgorde, wat elke steekproef uit "de eerste die klaar zijn" meteen minder scheef
  maakt dan de steekproef die §2 van `ontwerp-extractie.md` de das om deed.
- **Losgekoppeld van deze sessie**, zodat het sluiten van VS Code de run niet meeneemt.

## 11. Wat dit pad expliciet NIET doet

- Geen gaskwaliteit. De koppeling per uur werkt (`gaskwaliteit.koppel_gas_hhv` rondt af op het uur en
  is roosteronafhankelijk), maar hij vergt netwerk tijdens de run en `g_gebruik__W` hangt eraan. In
  deze pas blijft gas in m³ staan als `g_gebruik_cum__m3` plus `g_gebruik__m3_s_1`; de omrekening
  naar W is een tweede, goedkope slag op de uitvoer.
- Geen weerkoppeling. KNMI zit in een andere tabel en is niet per minuut; dat is een losse slag.
- Geen meterwisselreparatie. Vlaggen wel, repareren niet, net als in de kwartierpijplijn; dat is A3
  daar en hoort hier hetzelfde te blijven.
- Geen COP. Dat hangt aan `warmtemeter_bereik__cat` en aan het uitsluiten van de 39 dode kanalen, en
  is dus pas na deze pas te maken.
