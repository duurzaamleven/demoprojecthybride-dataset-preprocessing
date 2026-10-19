# Streamend geheugenontwerp voor de minuutpas

Aanvulling op `ontwerp-preprocessing-minuut.md` §10. Dat ontwerp regelt het tijdvenster (deadline,
hervatbaarheid, volgorde klein naar groot) maar gaat stilzwijgend uit van "één locatie past in het
geheugen". Die aanname sneuvelde in de nacht van 17 september 2026. Dit document vervangt hem door
een begroting die niet meer van de bestandsgrootte afhangt, en beantwoordt en passant de vraag of de
`float64`-conversie in `verwerk_locatie` wel iets oplevert.

## 1. Wat er misging

De run van 17 september kwam tot locatie 14 van 174 en viel om op vier locaties met
`numpy._core._exceptions._ArrayMemoryError`, op allocaties van 1,85 tot 3,14 MiB. Dat is geen te
grote locatie; dat is een machine zonder speling. Ten tijde van de meting stond de commit charge op
20,8 GB van een limiet van 22,3 GB, verdeeld over 355 processen, met 7,8 GB fysiek geheugen.

De volgorde klein naar groot uit §10 maakt dit erger dan het lijkt. De 14 gehaalde locaties zijn de
14 kleinste; samen 0,3 GB van de 7,4 GB invoer. De mediaan is 44 MB en het grootste bestand 73 MB,
tegen 23 MB voor de laatste die lukte. Het zware werk moest nog beginnen.

## 2. Wat het geheugen opeet

Gemeten op `location_id=UigJRsPF.parquet`, 23,1 MB, 359.506 rijen, 57 kolommen; het laatste bestand
dat wél lukte. Piek commit van het hele proces, met en zonder de reparatie die op dat moment
ongecommit in de werkmap stond:

| | piek commit | piek working set | dataframe zelf | per rij |
|---|---|---|---|---|
| `to_pandas()` | 766 MB | 419 MB | 89,8 MB | 2.235 B |
| `to_pandas(self_destruct=True, split_blocks=True)` | 724 MB | 380 MB | 89,8 MB | 2.113 B |

Twee dingen staan hier.

**De reparatie levert 5,5 % op.** Reëel, maar niet de orde van grootte die nodig is. Lineair
geëxtrapoleerd naar het grootste bestand (1.174.876 rijen) komt de piek op 2,1 tot 2,4 GB, en naar
de mediaan op 1,4 tot 1,6 GB. Met de speling van hierboven past de bovenste helft van de set er niet
in.

**De piek is 8,5 keer het dataframe.** 90 MB aan data tegen 766 MB piek; 262 byte per rij aan
dataframe tegen 2.113 byte per rij aan piek. Daar zit het echte probleem, en het is opgebouwd uit
kopieën die allemaal tegelijk bestaan:

| post | byte/rij | waar |
|---|---|---|
| arrow-tabel uit `read_table` | ~210 | `minuut.py:551` |
| pandas-kopie uit `to_pandas` | ~262 | idem |
| volledige kopie door `sort_values` | ~262 | `minuut.py:343` |
| argsort-indexer | 8 | idem |
| `standen`: 8 tellers in float64 | 64 | `minuut.py:379-381` |
| `uit`, kolom voor kolom opgebouwd | ~214 | `minuut.py:349-436` |
| `pa.Table.from_pandas` bij schrijven | ~214 | `minuut.py:492` |

Plus de tijdelijke arrays per teller in `differentieer_snel` en de blokherconsolidatie die pandas
uitvoert bij elke `uit[naam] = ...` op een frame dat al tientallen kolommen heeft.

Eén bevinding apart, want hij is gratis te repareren: de bron heeft 9 `uint16`-kolommen, maar in
pandas komen er zes als `float64` terug. Dat is de nullable-verbreding van pandas op een kolom met
ontbrekende waarden. Zes kolommen die 2 byte horen te zijn, kosten er 8; 36 byte per rij voor niets.

## 3. De bron laat streamen toe

Gecontroleerd op alle 174 bestanden, uitsluitend uit de parquet-footer, zonder één rij te lezen:

| | |
|---|---|
| row groups oplopend in `tijdstip_start` | **174** |
| overlappend | 0 |
| zonder statistieken | 0 |
| grootste bestand | 12 row groups van ~98.000 rijen |

Elk bestand is dus al op tijd gesorteerd, en de row groups overlappen nergens. Dat is de vergunning
voor dit hele ontwerp: `sort_values` over het volledige frame kan vervallen, en de row group wordt
de verwerkingseenheid.

Verder blijkt uit het schema dat van de 46 float-kolommen er maar 38 gebruikt worden: 30 momentaan
en 8 tellers op `_eerste`. De 8 `_laatste`-varianten worden nooit gelezen. Kolomselectie bij het
lezen scheelt dus 17 % van de float-payload, zonder dat er iets aan de uitkomst verandert.

## 4. Het ontwerp

Eén row group tegelijk in, één row group tegelijk uit, en tussen de batches alleen een handjevol
draagwaarden. De piek wordt daarmee constant in de bestandsgrootte.

### 4.1 Lezen

```
pf = pq.ParquetFile(pad)
for batch in pf.iter_batches(batch_size=ROWGROUP, columns=NODIG):
```

met `NODIG` = `tijdstip_start` + de 30 momentane + de 8 `*_eerste` + de 9 `OVERNEMEN`, dus 48 van de
57 kolommen. `sort_values` vervalt; in plaats daarvan een goedkope assertie dat de batch oplopend is
en dat zijn eerste tijdstip niet vóór het laatste van de vorige ligt. Faalt die, dan valt die ene
locatie terug op het huidige pad met een waarschuwing in de log. De footer zegt dat dat nooit hoeft
te gebeuren, maar een stille verkeerde uitkomst is duurder dan een terugvalpad.

### 4.2 Draagtoestand tussen de batches

De bewerkingen in `verwerk_locatie` zijn op één na allemaal streambaar, mits dit meegaat:

| draagwaarde | voor | omvang |
|---|---|---|
| laatste rij van de vorige batch (48 waarden) | vooruit differentiëren | verwaarloosbaar |
| lopend maximum per teller (8 scalars) | `markeer_nulmetingen`, de `cummax` | verwaarloosbaar |
| laatste `tijdstip_start` | `delta_t__s`, `bouw_gaten` | verwaarloosbaar |
| lopende tellingen per vlag (5 scalars) | de kenmerken uit §8 | verwaarloosbaar |
| eerste tijdstip, lopend `p_warmtepomp_max__W` | `bezetting__0`, dood kanaal | verwaarloosbaar |
| gatenlijst | `gaten.parquet` | hooguit enkele duizenden rijen |

De vooruitdifferentiatie heeft één rij vooruitkijk nodig: `delta[i] = stand[i+1] - stand[i]`, dus de
laatste rij van batch *k* is pas te berekenen als batch *k+1* binnen is. Standaardoplossing: verwerk
batch *k* op alles behalve zijn laatste rij, en schuif die rij door naar de volgende batch. Op de
allerlaatste batch blijft de laatste rij `NaN`, precies zoals `differentieer_snel` nu al doet.

`markeer_nulmetingen` gebruikt `cummax().shift(1)`; dat wordt het lopende maximum van de vorige
batch als startwaarde. De semantiek blijft letterlijk gelijk: niet "komt deze teller ooit boven 1"
maar "stond hij eerder al boven 1", en dat onderscheid dat de docstring op `minuut.py:164` uitlegt
overleeft het streamen ongeschonden.

### 4.3 De warmtemeterproef is de uitzondering

`bepaal_warmtemeter_bereik` kan niet streamen, want de drempel is 2 % van het **locatiemaximum** van
`q_geleverd_gemeten__W` en dat maximum is pas bekend als alles gezien is. Bovendien lopen de streaks
van tien minuten over batchgrenzen heen.

Oplossing: houd van deze drie kolommen, en alleen van deze drie, de hele locatie vast als
float32-numpy-array. Dat is 12 byte per rij, dus 14 MB voor het grootste bestand. Daarna draait de
bestaande `bepaal_warmtemeter_bereik` ongewijzigd op die drie arrays. Geen tweede leesslag over de
NAS, wat §1 van het hoofdontwerp ook verbiedt, en de proef en `_streaks` blijven regel voor regel
dezelfde code.

### 4.4 Schrijven

`pq.ParquetWriter` één keer open per locatie, `write_table` per batch, sluiten aan het eind. Daarmee
verdwijnt zowel het volledige `uit`-frame als de `pa.Table.from_pandas`-kopie eroverheen. De
row-groupgrootte van de uitvoer wordt gelijk aan die van de invoer, ~98.000 rijen.

**Dit laatste kan niet, en de reden is §7.** De tien referentiebestanden hebben elk één row group
over de hele locatie; dat is wat `pq.write_table` zonder `row_group_size` oplevert. Per batch
schrijven geeft row groups van 100.000 rijen, en dan zijn de bytes anders terwijl elk getal gelijk
is. Daarmee zou de regressietest vervallen, en zouden de tien bestaande bestanden bovendien anders
van vorm zijn dan de 164 die er nog bij komen.

De uitvoer wordt daarom per batch naar arrow omgezet, als losse batches verzameld, en aan het eind
in één keer geschreven. Dat haalt het volledige `uit`-frame en de `from_pandas`-kopie eruit, maar
niet de uitvoer zelf: één row group is per definitie in zijn geheel aanwezig op het moment dat hij
geschreven wordt. **Dat is de ondergrens van dit ontwerp**, en het is de enige post die met de
bestandsgrootte blijft meegroeien.

De keuze om de vorm te laten winnen van de piek is te herzien, maar dan in één keer voor de hele
set: 174 bestanden opnieuw verwerken met een kleinere row group. Zolang dat niet gebeurt is de vorm
van de uitvoer een afspraak en geen detail.

Het lokaal-schrijven-dan-kopiëren uit de huidige `schrijf_atomisch` blijft, inclusief de reden (13 s
naar de NAS tegen 1,5 s als kopie) en de atomaire volgorde `.tmp` dan hernoemen. Wel erbij: ruim bij
het starten van een locatie een achtergebleven `.tmp` op. Er staat er nu één van
`141Q2Shj`, van de afgebroken run.

### 4.5 De begroting

Gemeten op `location_id=ZzY3cd3h`, 1.174.876 rijen, het grootste bestand van de set; piek commit van
het hele proces, met `ARROW_DEFAULT_MEMORY_POOL=system`:

| post | MB |
|---|---|
| interpreter, imports, arrow-pool | 294 |
| verzamelde uitvoer, ~50 kolommen, hele locatie | 311 |
| de drie kolommen voor de warmtemeterproef, hele locatie | 14 |
| batch in, pandas-kopie, uitvoerbatch, schrijfbuffers | ~105 |
| **piek commit** | **725** |

Tegen 2,1 à 2,4 GB voor het volledige pad, en de piek working set is 518 MB. Per rij is dat 366 byte
boven de grondslag, tegen 2.113 byte voor `to_pandas` in §2.

Twee posten groeien nog met de bestandsgrootte: de verzamelde uitvoer met ~265 byte per rij (§4.4) en
de warmtemeterproef met 12 byte per rij (§4.3). De rest is constant. De grootste locatie van de set
is hiermee niet meer de grens: op het krapste moment van de nacht van 17 september was er 1,5 GB
speling, en 725 MB past daarin, waar 2,4 GB dat niet deed.

Eén meting apart, want ze verklaart waarom die instelling in `draai_minuut.cmd` staat. Met de
standaardpool van arrow is de piek op datzelfde bestand **1.171 MB** in plaats van 725 MB, terwijl de
verzamelde data in beide gevallen 311 MB is. De pool geeft vrijgegeven blokken niet aan het systeem
terug, dus de commit charge groeit mee met het **aantal** batches in plaats van met de grootste. Bij
`mimalloc` is het beeld gelijk aan de standaard. Dit is de instelling die §8 "het proberen waard"
noemde; ze is het waard.

## 5. De float64-conversie: verliesvrij maar leeg

Je vermoeden klopt, en scherper dan ik verwachtte.

### 5.1 Er staat geen enkele float64 in de bron

Uit het schema van het grootste bestand: 46 × `float` (float32), 9 × `uint16`, 1 × `string`, 1 ×
`timestamp`. Nul kolommen `double`. **Alle acht tellers staan als float32 in de bron.** De
`astype("float64")` op `minuut.py:379` en de `to_numpy(dtype="float64")` op `minuut.py:357` en
`:224` verbreden dus iets wat al afgerond is.

Die verbreding is op zichzelf verliesvrij: elke float32 is exact een float64. Ze voegt alleen niets
toe. En omdat alle uitvoerkolommen op `minuut.py:365`, `:392`, `:399-405` en `:418-420` weer naar
float32 teruggecast worden, komt er ook niets van in het eindproduct terecht.

### 5.2 Het aftrekken had de float64 sowieso niet nodig

Het argument dat je bij cumulatieve tellers zou verwachten, uitwissing bij het aftrekken van twee
grote bijna gelijke getallen, gaat hier niet op. Het lemma van Sterbenz zegt dat voor `b ≤ a ≤ 2b`
het verschil `a - b` exact representeerbaar is in dezelfde precisie. Twee tellerstanden een minuut na
elkaar verschillen relatief in de orde 1e-6, dus ruim binnen die voorwaarde. `stand[1:] - stand[:-1]`
is in float32 net zo exact als in float64.

De conversie repareert dus niets aan de differentiatie. Wat de resolutie bepaalt is de rastermaat van
de opgeslagen float32, en die is onherroepelijk vóór onze code begint.

### 5.3 En die rastermaat is niet verwaarloosbaar

Hier zit de eigenlijke schijnprecisie, en niet in het dtype. De afstand tussen twee opeenvolgende
float32 rond een stand *S* is `2^(floor(log2 S) - 23)`. Omdat wij per minuut differentiëren, vertaalt
die afstand zich rechtstreeks in een ondergrens op het afgeleide vermogen:

`P_stap = 2^(floor(log2 S_max) - 23) × factor / 60 s`

Voor `location_id=ZzY3cd3h`, met de maxima uit de footer. **Let op: dit is een gunstige locatie.**
Zijn importteller staat op 10.778 kWh en dat is onder de mediaan van de set; §6.1 geeft de cijfers
over alle 174 en die zijn een factor vier ongunstiger.

| teller | max stand | float32-raster | **stap in afgeleid vermogen** |
|---|---|---|---|
| `dsmr_e_consumed_low` | 10.778,46 kWh | 0,000977 kWh | **58,6 W** |
| `dsmr_e_consumed_high` | 8.234,47 kWh | 0,000977 kWh | **58,6 W** |
| `dsmr_e_delivered_high` | 10.309,81 kWh | 0,000977 kWh | **58,6 W** |
| `dsmr_e_delivered_low` | 4.727,22 kWh | 0,000488 kWh | **29,3 W** |
| `heatpump_energy` | 7.844,46 kWh | 0,000488 kWh | **29,3 W** |
| `kamstrup_e_thermal_system` | 120,36 GJ | 7.629 J | **127,2 W** |
| `boiler_energy` | 118,93 kWh | 0,00000763 kWh | **0,46 W** |
| `dsmr_v_gas_consumed` | 2.982,54 m³ | 0,000244 m³ | 0,244 dm³/min |

Lees die tabel goed. `p_warmtepomp__W` van deze locatie komt van een teller die op 7.844 kWh staat en
heeft daardoor een trap van 29,3 W; `p_ketel__W` komt van een teller op 118,93 kWh en heeft een trap
van 0,46 W. Een factor 64 verschil tussen twee kolommen in hetzelfde bestand, puur door de
**stand** van de teller en niet door de meter of het verschijnsel. En `q_geleverd__W` uit de Kamstrup
heeft met 127 W de grofste trap van allemaal.

Twee gevolgen die de analyse moet kennen:

1. **De trap verschilt per locatie.** Een woning waarvan de importteller op 3.000 kWh staat heeft
   14,6 W, een op 12.000 kWh heeft 58,6 W. Elke vergelijking van laagvermogengedrag tussen locaties
   vergelijkt dus ook meetrasters.
2. **Onder de trap is er niets.** Een sluipverbruik van 40 W is op een teller van 10.778 kWh niet te
   onderscheiden van 0 of van 58,6 W; het wordt een blokgolf tussen die twee. Dit is precies het
   soort artefact waar analyse A4 naar zocht (`06a9f5a`, modulusartefacten, geen gevonden). A4 keek
   naar een deler in de brondata; dit is een raster in de opslag, en dat is een ander verschijnsel
   met dezelfde signatuur.

Bij déze locatie is de float32-opslag nog nét toereikend voor de meter zelf: DSMR levert kWh met drie
decimalen, dus stappen van 0,001 kWh, en het raster van 0,000977 kWh ligt daar 2 % onder. Geen twee
verschillende meterstanden vallen hier op dezelfde float32.

Die marge van 2 % is geen eigenschap maar een houdbaarheidsdatum, en voor het grootste deel van de
set is hij al verlopen. Zie §6.1.

### 5.4 Eén plek waar float64 wél moet blijven

Het elektrasaldo op `minuut.py:414-417`:

```
saldo = sum(invoer[1:], invoer[0])   # tot ~19.012 kWh
for reeks in uitvoer:
    saldo = saldo - reeks
```

Hier worden vier tellers opgeteld tot boven de 19.000 kWh. Het float32-raster is daar 0,00195 kWh,
oftewel 117 W. In float64 is de som van vier float32-waarden exact (vier mantissen van 24 bits passen
ruim in de 53 van float64), en houdt het saldo het fijnste raster van zijn bijdragen, 58,6 W. De
float64 halveert daar dus echt de trap op `e_net__W`.

Dit is de enige plek. Bij de acht individuele tellers verandert de conversie niets aan de uitkomst;
bij het saldo wel.

### 5.5 Wat ik voorstel

Niet het dtype van de rekenstap veranderen, maar de bewaartermijn ervan:

- **`standen` niet meer als float64 over de hele locatie bewaren.** Die dict is 64 byte per rij en
  bestaat alleen om het saldo mee te maken. In het streamende ontwerp wordt het saldo per batch
  opgebouwd, in float64, en daarna weggegooid.
- **De rekenstap in `differentieer_snel` in float64 laten.** Per batch zijn de drie tijdelijke arrays
  nog maar 2,4 MB, dus het kost niets meer, en zo blijft de uitvoer bit-voor-bit gelijk aan wat er nu
  uitkomt. Dat is de regressietest van §7 waard.
- **De `.astype("float64")` op de acht tellers laten staan met een comment dat hij verliesvrij maar
  leeg is**, met een verwijzing naar §5.2 hierboven. Anders haalt de volgende lezer hem weg in de
  veronderstelling dat hij precisie wint, of zet hem juist terug in de veronderstelling dat hij hem
  redt.
- **De zes verbrede `uint16`-kolommen als `uint16` houden.** Die horen bij `OVERNEMEN` en gaan
  ongewijzigd naar de uitvoer; ze kunnen rechtstreeks van de arrow-batch naar de writer, zonder
  pandas-tussenstap en zonder nullable-verbreding.
- **Een kwaliteitsveld per locatie per teller toevoegen:** `raster_<naam>__W`, berekend als
  `2^(floor(log2 S_max) - 23) × factor / 60`. Het is één scalar per teller, het komt uit het lopende
  maximum dat we voor `markeer_nulmetingen` toch al bijhouden, en het is het enige eerlijke antwoord
  op "hoe fijn is dit vermogen eigenlijk". Naar `homes_minuut.parquet`, en naar `kwaliteit.md`.

Dat laatste punt is het echte antwoord op je vraag. De schijnprecisie zit niet in de conversie, want
die is verliesvrij; ze zit erin dat de uitvoer een kolom `p_warmtepomp__W` heet zonder ergens te
vermelden dat hij bij deze locatie in stappen van 29,3 W komt.

## 6. Wat het float32-raster voor de analyses betekent

§5 gaat over wat de preprocessing met de tellers moet doen. Deze sectie gaat over wat de analyse er
daarna wel en niet mee mag, want dat is een andere vraag met een ongemakkelijker antwoord.

### 6.1 De cijfers over de hele set

De tabel in §5.3 is één locatie en een gunstige. Over alle 174 woningen, uit
het antwoord aan KITE van 16-09-2026 en berekend in
`demoprojecthybride-dataset-extractie/tools/getallen_voor_kite_mail.py`:

| `dsmr_e_consumed_low` | stand | float32-raster | tegen een metertik van 0,001 |
|---|---:|---:|---|
| mediaan | 12.869 kWh | 0,00098 | precies op de grens |
| 95e percentiel | 36.326 kWh | 0,0039 | **bijna 4× te grof** |
| hoogste | 63.766 kWh | 0,0039 | bijna 4× te grof |

Het raster verdubbelt bij elke macht van twee:

| tellerstand | raster | factor t.o.v. de metertik |
|---|---|---|
| tot 8.192 | < 0,001 | fijner dan de meter |
| 8.192 tot 16.384 | 0,00098 | op de grens |
| 16.384 tot 32.768 | 0,00195 | 2× te grof |
| 32.768 tot 65.536 | 0,0039 | 4× te grof |

De mediane woning staat op de grens en de bovenste vijf procent staat op vier keer te grof. Dit is
dus geen randgeval van de set maar de set.

### 6.2 Waarom juist het minuutrooster geraakt wordt

Het afgeleide vermogen is `Δteller × 3,6·10⁶ / Δt`, dus de kwantiseringsstap schaalt met **1/Δt**:

| interval | mediane woning | 95e percentiel |
|---|---|---|
| 1 min | 58,6 W | **234 W** |
| 5 min | 11,7 W | 46,9 W |
| 15 min | 3,9 W | 15,6 W |
| 60 min | 1,0 W | 3,9 W |

Daar staat de hele afweging in. Het minuutrooster wint een factor 15 aan tijdresolutie ten opzichte
van het kwartierpad en betaalt exact diezelfde factor 15 in vermogensresolutie. Dat is precies de
reden dat trage verschijnselen hier geen last van hebben en snelle wel.

Voor het kwartierpad van `dph_preprocessing.pipeline` is dit daarmee geen onderwerp: 3,9 W mediaan en
15,6 W op p95 valt weg tegen elk vermogen dat daar bestudeerd wordt. De eerder verwerkte
kwartierdata hoeft niet herzien te worden.

### 6.3 Wat onaangetast blijft

**Alles wat opgeteld wordt.** De fout in `Δ_i` is `e_{i+1} - e_i`, dus bij sommeren telescopeert de
reeks en blijft `e_N - e_0` over: hooguit één raster, ongeacht over hoeveel intervallen. Een dagtotaal
van 10 kWh heeft bij p95 een fout van 0,0039 kWh, oftewel 0,04 %. Energiebalansen, seizoens-COP,
maand- en jaarverbruiken en de verdeling warmtepomp tegen ketel zijn ongemoeid. Dit is ook waarom
tellergebaseerde metering voor facturering deugt.

**De 30 momentane kolommen.** Daar telt de relatieve nauwkeurigheid en zijn de waarden klein; bij
3.000 W is het raster 0,00024 W. Temperaturen, spanningen, stromen, debiet en de gemeten vermogens
zijn prima, en het zijn bovendien intervalgemiddelden over 12, 6 of 2 metingen per minuut.

Dat tweede punt is de uitweg, want voor elk tellerafgeleid vermogen bestaat een gemeten tegenhanger:

| tellerafgeleid: grof per minuut, exact bij optellen | gemeten: fijn per minuut, niet exact integreerbaar |
|---|---|
| `p_warmtepomp__W` | `p_warmtepomp_gemeten__W`, `_min`, `_max` |
| `p_ketel__W` | `p_ketel_gemeten__W`, `_min`, `_max` |
| `q_geleverd__W` | `q_geleverd_gemeten__W`, `_min`, `_max` |

**Snelle verschijnselen op de gemeten kolommen, hoeveelheden op de tellerkolommen.** Ze zijn precies
complementair, en de `_min`/`_max`-varianten geven zelfs gedrag binnen de minuut.

### 6.4 Het gevaarlijkste: het is geen ruis maar een patroon

Kwantiseringsfout gedraagt zich alleen als witte ruis wanneer het signaal veel rasterstappen per
monster doorloopt; dat is de voorwaarde uit de kwantiseringstheorie van Widrow. Bij laag vermogen
doorloopt de teller **minder dan één stap per minuut**, en dan is de fout niet stochastisch maar
deterministisch en patroonvormig: de idle tones of limietcycli die uit AD-omzetters en digitale
filters bekend zijn.

Concreet: een sluipverbruik van 40 W op een raster van 234 W levert een reeks die minutenlang 0 W
aangeeft en dan één minuut 234 W. Dat ziet eruit als regelmatig aan- en uitschakelen. **Een
kwantiseringsartefact dat zich voordoet als cyclusgedrag is precies het valse positief waar
minuutonderzoek naar cycling op stukloopt.**

Dit is een ander verschijnsel dan waar analyse A4 naar zocht (`06a9f5a`, modulusartefacten, geen
gevonden). A4 keek naar een deler in de brondata; dit is een raster in de opslag. Dezelfde
signatuur, een andere oorzaak, en A4 zou hem niet gevonden hebben.

### 6.5 De risicolijst

⚠️ **Deze lijst is opgesteld vóór de meting van §6.6a en is daar op twee punten door gecorrigeerd.**
De kolom "ernst" hieronder is bijgewerkt; de oorspronkelijke inschatting staat in de laatste kolom
waar die afweek.

| risico | ernst | waarom | was |
|---|---|---|---|
| COP per minuut | **hoog** | maar de **warmtekant** is de knellende factor, niet de elektrische: 127 W tegen 15 W mediaan (§6.6a) | hoog, om de verkeerde reden |
| `e_net__W` per minuut | **hoog** | opgebouwd uit de vier DSMR-registers, en dat zijn precies de vier met de breuken (§6.6a) | stond er niet in |
| sluipverbruik, standby | **hoog** | ligt bij p95 volledig onder één rasterstap |
| vaste vermogensdrempels op tellerkolommen | hoog | een drempel van 200 W is zinloos bij een stap van 234 W |
| spectrale analyse | midden | differentiëren is hoogdoorlaat en duwt de fout naar precies de hoge frequenties |
| change-point-detectie | midden | zie §6.6 en §6.6a |
| energiebalans per minuut | midden | verschillen van gekwantiseerde grootheden versterken elkaar |
| modulatiediepte | midden | bij 500 W blijven er op p95 twee niveaus over |
| cycling- en pakketdetectie op `p_warmtepomp__W` | **laag** | de warmtepompteller blijkt schoon: 14,6 W mediaan, 58,6 W maximum, nul breuken (§6.6a) | hoog |
| dagtotalen, seizoens-COP, jaarverbruik | **geen** | telescopeert weg (§6.3) |
| alles op de momentane kolommen | **geen** | relatieve precisie volstaat (§6.3) |

De warmtemeterproef van §8 van het hoofdontwerp gebruikt `p_warmtepomp_gemeten__W` en
`p_ketel_gemeten__W` en staat dus aan de veilige kant. Dat is geluk, geen ontwerp; elke nieuwe
drempelanalyse moet die keuze bewust herhalen.

### 6.6 Een rasterbreuk middenin een reeks

Passeert een teller tijdens de meetperiode een macht van twee, dan verdubbelt het raster middenin de
reeks. Met een mediaan van 12.869 kWh, 2,5 jaar meting en ruwweg 1.500 kWh per jaar per register
passeert een deel van de set gegarandeerd 16.384.

Het gevolg is een sprong in de ruiskarakteristiek die niets met de woning te maken heeft. Elke
change-point-detectie pikt hem op, en elke vergelijking van "voor" en "na" binnen zo'n reeks
vergelijkt ook meetrasters.

Te vinden zonder één rij te lezen: per locatie per teller de `min` en `max` uit de
footer-statistieken, en dan `floor(log2(min)) != floor(log2(max))`. Dat levert meteen de lijst met
reeksen waarin het raster verspringt, en het hoort als vlag mee naar `homes_minuut.parquet`.

### 6.6a Gemeten over alle 174, en de scheidslijn valt gunstig

Gedraaid op 17-09-2026 met `dph_preprocessing.minuut_raster` over alle 174 locaties; 86 seconden,
uitsluitend footer, geen rij gelezen. 1.372 teller-locatiecombinaties.

**62 van de 174 locaties (36 %) hebben minstens één rasterbreuk**, samen 96 combinaties: 90 keer één
verdubbeling, vijf keer twee, en één locatie zes keer.

| teller | n | raster mediaan | raster max | te grof | breuk |
|---|---:|---:|---:|---:|---:|
| `e_import_laag_cum__kWh` | 170 | 58,6 W | 234,4 W | 60 | **37** |
| `e_import_hoog_cum__kWh` | 170 | 58,6 W | 234,4 W | 51 | **32** |
| `e_export_hoog_cum__kWh` | 170 | 29,3 W | 234,4 W | 26 | **15** |
| `g_gebruik_cum__m3` | 170 | n.v.t. | n.v.t. | 25 | **11** |
| `e_export_laag_cum__kWh` | 170 | 14,6 W | 117,2 W | 2 | 1 |
| `e_warmtepomp_cum__kWh` | 174 | **14,6 W** | **58,6 W** | **0** | **0** |
| `e_ketel_cum__kWh` | 174 | **0,2 W** | 29,3 W | **0** | **0** |
| `q_geleverd_cum__J` | 174 | 127,2 W | 254,3 W | onbekende metertik | idem |

**De scheidslijn loopt precies tussen de metertellers en de toesteltellers, en dat is geen toeval.**
De DSMR-registers tikken door sinds de meter geplaatst is; de warmtepomp- en keteltellers pas sinds
de proef begon. Alle schade zit daardoor aan de kant van de woningmeter en geen enkele aan de kant
van het toestel.

Drie gevolgen, en twee ervan corrigeren §6.5:

1. **`p_warmtepomp__W` is schoon.** Nul te grove gevallen, nul breuken, mediaan 14,6 W. De schatting
   van 29,3 W in §5.3 kwam uit één locatie en was pessimistisch. Cyclus- en modulatieanalyse op de
   tellerafgeleide warmtepompvermogens is daarmee een laag risico in plaats van een hoog.
2. **Voor de COP is de wármtekant de knellende factor.** `q_geleverd_cum__J` zit op 127,2 W mediaan
   tegen 14,6 W voor het elektrische deel, een factor negen. §6.5 suggereerde het omgekeerde.
3. **`e_net__W` is de zwaarst getroffen afgeleide kolom**, want die wordt opgebouwd uit precies de
   vier registers met de breuken. Bij 60 respectievelijk 51 locaties boven de metertik is dat geen
   randgeval maar de hoofdregel.

Zeven locaties hebben drie getroffen tellers tegelijk (`5NNgThim`, `Mz219wDb`, `ooQJGe15`,
`cfs3OE3j`, `cXHtdNjQ`, `bep7sbGN`, `pv_IsvbE`); daar verspringt de ruiskarakteristiek van de hele
elektriciteitskant binnen de reeks.

Eén losse bevinding om na te lopen: **vier locaties missen de DSMR-tellers volledig** (170 in plaats
van 174 bij alle vier de elektriciteitsregisters en bij gas). Dat staat los van het raster en hoort
in het kwaliteitsrapport.

✅ Doorgevoerd: de regressietest van §7 verviel al door de nulspanningsreparatie, en dat was het
moment om zowel deze vlag als de `uint16`-reparatie uit §5.5 alsnog in `homes_minuut.parquet` te
zetten. Zie `_raster_kenmerken` in `minuut.py`.

### 6.7 Wat de preprocessing hieraan moet doen

Bovenop `raster_<naam>__W` uit §5.5:

1. **Een vlag `raster_breuk_<naam>__bool`** per locatie per teller, uit de toets van §6.6.
2. **Maskeren wat niet opgelost is.** Onder drie rasterstappen geen getal maar `NaN` plus een vlag.
   Een blokgolf doorgeven is erger dan een gat, want een gat is zichtbaar en een blokgolf niet.
3. **Differentiëren met variabele lag** als optie naast de vaste minuut: de kortste lag die minstens
   k rasterstappen oplevert. Dat geeft fijne tijdresolutie waar het vermogen hoog is en automatisch
   grovere waar het laag is, in plaats van overal dezelfde schijnnauwkeurigheid. Dit is een
   uitbreiding en geen vervanging; de vaste minuut blijft de standaarduitvoer.
4. **In `kwaliteit.md` een paragraaf** met de verdeling van `raster_<naam>__W` over de locaties, zodat
   wie de dataset gebruikt het getal tegenkomt zonder ernaar te zoeken.

### 6.8 De echte oplossing ligt bovenstrooms

Het verlies zit niet bij ons. De kolommen staan in ClickHouse al als `Nullable(Float32)`
(`ontwerp-ruwe-export.md:148`) en de extractie geeft dat verliesvrij door; daar is een test voor
(`test_grafana_export.py:162`). Er valt in onze keten niets terug te winnen.

De vraag of Kite de acht cumulatieve tellers als `Float64` kan aanleveren ligt er al. Komt dat er,
dan vervalt deze hele sectie behalve als verklaring voor wat er met de tot dan toe gedane analyses
moet gebeuren. Zolang dat niet zo is, is alles hierboven de eerlijke omgang met wat we hebben.

## 7. Wat niet verandert, en hoe we dat bewijzen

Het uitvoerformaat, de kolomnamen, de semantiek van §2 tot §9 van het hoofdontwerp: allemaal
ongewijzigd. Dit is een uitvoeringsontwerp, geen herziening.

De regressietest ligt al klaar. De run van vannacht heeft **10 definitieve bestanden** op
`DPH-per-minuut-verwerkt/` gezet, geproduceerd door de gecommitte code. Het streamende pad moet die
tien bit-voor-bit reproduceren. Daarom blijft de rekenstap in float64: zodra je daar float32 van
maakt, verschillen de afgeleide kolommen in de laatste ulp en is die test weg.

Werkvolgorde:

1. De tien bestanden veiligstellen als referentie (kopie buiten de doelmap, anders slaat de
   hervatting ze over en test je niets).
2. Het streamende pad bouwen naast `verwerk_locatie`, niet erin. `verwerk_locatie` blijft als
   referentie-implementatie bestaan en `test_minuut.py` blijft hem toetsen.
3. Gelijkheidstest op de tien, plus op de kleinste locatie waar `verwerk_locatie` nog gewoon in het
   geheugen past.
4. Pas daarna de oude weg uit de runner halen, of laten staan achter een vlag voor het geval een
   locatie de sorteerassertie niet haalt.

## 8. Wat dit niet oplost

De machine. 225 MB piek past in de huidige speling van 1,5 GB, maar die speling is niet van ons: hij
hangt af van hoeveel Code-, Edge- en Office-processen er op dat moment leven. Het ontwerp maakt de
run bestand tegen een krappe machine; het maakt hem niet bestand tegen een machine die al vol is
voordat python start. De geplande taak van 23:59 loopt nog steeds in een volle machine als er niets
afgesloten wordt.

Een ondergrens is er ook. De 294 MB voor interpreter, pandas, pyarrow en de arrow-geheugenpool staat
los van de data. Gemeten is dat de commit charge ongeveer 2,2 keer de working set is, wat erop wijst
dat de arrow-pool vrijgegeven blokken niet aan het systeem teruggeeft; `ARROW_DEFAULT_MEMORY_POOL=system`
is het proberen waard, maar het is een instelling en geen ontwerp, en dus geen onderdeel hiervan.

Het was het waard: 1.171 MB tegen 725 MB op het grootste bestand (§4.5). Hij staat daarom in
`draai_minuut.cmd` en niet in de code, want de vaststelling erboven blijft kloppen; dit is een knop
van de omgeving.

En de tweede helft van de vaststelling blijft ook staan: de row group van de uitvoer moet in zijn
geheel in het geheugen passen (§4.4), dus constant in de bestandsgrootte is dit ontwerp niet
geworden. Het is constant in de **invoer**, en dat was waar het omviel.
