# Ontwerp: drie teller-artefacten in het kwartierpad

**Status 22-09-2026: de metingen zijn gedaan, het ontwerp staat (na twee reviewcorrecties in §10:
geen bridging/piek bij gemaskeerde intervallen, en 4.3 hoort ook in het minuutpad), de implementatie
nog niet.**

"De teller daalt" is in de huidige code één verschijnsel. Het zijn er drie, en ze vragen elk een
andere ingreep:

1. een **initialisatietelegram** van vóór de P1-koppeling, dat een vaste onzin-startwaarde meegeeft;
2. **uitval met herstel**: de stand valt terug naar 0 en komt later weer terug op zijn oude spoor;
3. een **echte tellerwissel**: de stand valt terug naar iets anders dan 0, want de meter is vervangen.

Het kwartierpad behandelt op dit moment geen van de drie: het initialisatietelegram wordt als
gewone meting doorgegeven, uitval-met-herstel wordt niet onderscheiden van een echte wissel, en geen
van beide wordt ooit gemaskeerd. `teller_terug__bool` (`tellers.py:133-139`) vlagt elke daling, maar
`differentieer_teller` (`tellers.py:77-130`) zet nooit iets op `NaN`. Het gevolg staat al in de
uitvoer: bij lVK0bORa is `p_ketel__W` = -84.568 en `g_gebruik__W` = -3,68e8, allebei binnen het
huidige kwartierpad.

## 1. Wat al vaststond, en niet opnieuw gemeten is

- In `data/raw/dph-dataset.zip`/`dsmr.csv` staat bij 166 van de 174 woningen letterlijk dezelfde
  beginwaarde voor vijf registers tegelijk (zie §2 voor de vindplaats en de exacte waarden).
- `bron.py` (`KOLOM_HERNOEM_RUW`, regel 54-57) en `tabellen.py` (regel 189-198, 233-257, 366-372)
  zijn doorgeefluiken: geen van beide voegt de sentinelwaarde toe. Ze komt onveranderd uit de bron.
- De allereerste rij van `dsmr.csv` (woning `-ORiFQC6`, 2022-02-07T11:10:58) heeft de vijf
  sentinelwaarden **én** `u_L1=u_L2=u_L3=0,0 V` **én** `i_L1=i_L2=i_L3=4 A`. Vier ampère bij nul
  volt kan niet: dit is een initialisatietelegram, geen meting.
- De positie is niet vast: bij de meeste woningen een leidende reeks van 1 tot 4 rijen, maar bij
  `OMa7vZ0x` staat hij niet vooraan en keert hij vier keer verderop terug, en bij `uQLTOCT9` (op
  beide paden de slechtst gedekte woning, 0,48 %) keert hij 95 keer verspreid door de reeks terug.
- Negatieve delta's blijven in de uitvoer staan op beide paden. Het minuutpad zet een nulmeting wel
  op `NaN` vóór het differentiëren (`minuut.py:274-277`, via `markeer_nulmetingen`,
  `minuut.py:215-231`), maar doet dat niet voor een echte wissel (`minuut.py:464-483` en
  `minuut.py:707-721`: `wissel` wordt gevlagd, niet gemaskeerd). Het kwartierpad kent alleen
  `teller_terug__bool` en maskeert nooit.

## 2. Zit de sentinel ook in het minuutpad? (M1)

De ruwe bron van het minuutpad is niet `dsmr.csv` maar de per-locatie parquet op
`//hoftenas/backup/energiedata/DPH-per-minuut/measurements_per_minuut/location_id=<id>.parquet`,
met de vijf registers als `dsmr_e_consumed_low/high_eerste`, `dsmr_e_delivered_low/high_eerste` en
`dsmr_v_gas_consumed_eerste` (plus hun `_laatste`-tegenhangers).

**Gemeten op 18 woningen**, waaronder de drie verplichte (`RHON9wor`, `OMa7vZ0x`, `uQLTOCT9`) plus
vijftien verspreid over de bestandsgrootte (van de kleinste, `uQLTOCT9` op 1417 rijen, tot de
grootste in de steekproef, `bB9dwLYE` op ruim 1,1 miljoen rijen): **geen enkele rij** heeft de vijf
sentinelwaarden, op geen van de 18 locaties, in `_eerste` noch in `_laatste`. Ook een tolerantietoets
van 0,001 op elk register apart bracht op de drie verplichte woningen niets naar boven (op één
toevallige, irrelevante treffer na: OMa7vZ0x heeft één rij met `e_delivered_low_eerste` = 1743,95,
niet in de buurt van de sentinel 3433,300).

**Conclusie: de sentinel zit alleen in het kwartierpad.** De extractie naar de per-minuut-parquet
draait kennelijk niet over hetzelfde ruwe DSMR-telegramarchief als `dsmr.csv`, of het
initialisatietelegram is daar al eerder weggefilterd. De reparatie in dit ontwerp hoeft dus alleen
in het kwartierpad te gebeuren; het minuutpad (`minuut.py`) heeft dit specifieke probleem niet.

## 3. Handtekening versus losse regel (M2)

De vijf sentinelwaarden, met hun herkomst:

| register | waarde | `physiquant__unit`-naam |
|---|---:|---|
| `e_consumed_low` | 8969,994 | `e_import_laag_cum__kWh` |
| `e_consumed_high` | 8789,167 | `e_import_hoog_cum__kWh` |
| `e_delivered_low` | 3433,300 | `e_export_laag_cum__kWh` |
| `e_delivered_high` | 8299,146 | `e_export_hoog_cum__kWh` |
| `v_gas_consumed` | 5059,199 | `g_gebruik_cum__m3` |

**Herkomst: eerste rij van `dsmr.csv` in `data/raw/dph-dataset.zip`, woning `-ORiFQC6`,
2022-02-07T11:10:58.** Dat is de plek waar de vijf waarden voor het eerst zijn afgelezen, en in de
implementatie hoort dit een **benoemde constante te worden met deze bronvermelding erbij** (bestand,
rij, woning, tijdstip) -- niet vijf losse getallen in een expressie. Zonder die herkomst is dit over
een jaar een magisch getal dat niemand meer kan verifiëren (ontwerp-preprocessing.md §3, principe 5:
"getallen zonder herkomst zijn schuld").

**Gemeten over de volledige `dsmr.csv`** (7.866.691 rijen, 174 woningen):

| regel | rijen | woningen |
|---|---:|---:|
| **Strikte handtekening** (alle vijf tegelijk) | 1896 | 167 |
| **Losse regel** (unie: >=1 register op zijn sentinelwaarde) | 1898 | 167 |
| **Vals-positieve marge** | **2** | **0** |

De marge is klein, maar dat is geen argument vóór de losse regel: de twee extra rijen zijn precies
het scenario waar §1 van het opdracht al voor waarschuwt. Beide zijn woningen (`df79ygat`,
`A0JoUuz-`) waar `e_consumed_low` toevallig exact 8969,994 uitleest terwijl de andere vier registers
gewone, onderling verschillende waarden hebben -- een echte meting die toevallig op de sentinelwaarde
staat, geen initialisatietelegram. Zie §9 voor de volledige uitwerking. De strikte handtekening (alle
vijf tegelijk) vangt dat automatisch op; de losse regel zou deze twee rijen ten onrechte hebben
gemaskeerd. Dat de marge hier klein uitpakt (2 van 8 miljoen rijen) is toeval van deze dataset, geen
garantie voor de volgende: het principe -- vijf onafhankelijke registers die tegelijk op een exacte
waarde staan is geen toeval, één register wel -- blijft de reden om de strikte handtekening te
gebruiken, ook al was de meting hier vergevingsgezind.

## 4. Drie artefacten, drie ingrepen

### 4.1 Initialisatietelegram (de sentinel)

**Herkenning: op handtekening, niet op positie of waarde alleen.** Alle vijf registers tegelijk op
hun sentinelwaarde (§3). Twee alternatieven zijn expliciet afgewezen:

- **Alleen op waarde filteren mag niet.** Eén register alleen (bijvoorbeeld
  `e_import_laag_cum__kWh == 8969,994`) is geen bewijs: een echte meter kan ooit werkelijk op die
  stand staan, en §3 laat zien dat dit ook echt gebeurt (`df79ygat`, `A0JoUuz-`).
- **Alleen de eerste rij weggooien mag ook niet.** `OMa7vZ0x` en `uQLTOCT9` laten zien dat de
  sentinel niet altijd vooraan staat en meermaals kan terugkeren.

**Ingreep:** de tellerstanden van een rij die aan de handtekening voldoet, gaan op `NaN` vóór het
differentiëren -- op elke positie in de reeks, niet alleen de eerste rij. Omdat de stand zelf
verdwijnt (niet alleen de afgeleide waarde), worden automatisch **beide** aangrenzende intervallen
overbrugd: het interval dat op deze rij eindigt én het interval dat erop begint. Precies dat
dubbelzijdige effect is nodig, want een sentinelrij ergens middenin de reeks (`OMa7vZ0x`,
`uQLTOCT9`) verstoort de aflezing aan weerskanten.

**Nulspanning als extra bevestiging: bewust NIET opgenomen in de handtekening.** De eerste rij van
`dsmr.csv` heeft naast de vijf sentinelwaarden ook `u_L1=u_L2=u_L3=0,0 V` bij `i_L1=i_L2=i_L3=4 A`,
en dat is op zichzelf al fysisch onmogelijk (§1). Toch hoort dit niet bij de herkenning van latere,
terugkerende sentinelrijen (`OMa7vZ0x`, `uQLTOCT9`): een spanning van exact 0,0 is bij deze dataset
al apart geïnterpreteerd als "afwezig, niet onplausibel" (`ontwerp-preprocessing-minuut.md`,
vergelijkbare aanname elders), en er is geen garantie dat een teruggekeerde initialisatiewaarde
midden in de reeks ook een spanningsuitval in hetzelfde kwartier meebrengt -- dat hangt af van
hoe de herhaling ontstaat, en dat is niet onderzocht. De vijf-registers-handtekening is op zichzelf
al voldoende specifiek (167 woningen, 2 rijen vals-positieve marge in de losse variant, 0 in de
strikte); een extra voorwaarde die soms niet klopt zou treffers laten liggen zonder de precisie
merkbaar te verbeteren. Wint dus: **vijf registers, geen spanningsvoorwaarde.**

### 4.2 Uitval met herstel

Stand valt terug naar 0 en komt later terug op (ongeveer) het spoor van vóór de uitval. Het
onderscheidende criterium: de teller heeft **eerder al boven 1 gestaan** (`TELLER_ONTWAAKT_BOVEN`,
`minuut.py:55`) -- een lopend maximum, cummax, geshift met één positie zodat de rij zelf niet
meetelt.

**Ingreep: BEIDE helften op `NaN`.** Als je alleen de negatieve delta weghaalt, blijft de positieve
herstelsprong staan en tel je de energie dubbel -- eenmaal als (valse) negatieve dip, eenmaal als
(valse) positieve sprong terug. Dit bestaat al in het minuutpad als `markeer_nulmetingen`
(`minuut.py:215-231`, cummax-criterium) en moet, ongewijzigd qua criterium, naar het kwartierpad.
Belangrijk: dit criterium markeert **elke rij** die aan de voorwaarde voldoet, niet alleen de
overgangsrij. Staat een teller weken- of maandenlang vast op 0 voordat hij herstelt, dan gaat elke
rij in die periode op `NaN` -- terecht, want elke rij in die periode is een even ongeldige aflezing
als de eerste (zie §6, waar dit een orde van grootte groter blijkt dan de huidige
`teller_terug__bool`-telling laat vermoeden).

### 4.3 Echte tellerwissel

Stand valt terug naar iets dat niet 0 is (of naar 0 bij een teller die nooit boven 1 kwam): een
echte breuk in de reeks, typisch een vervangen meter.

**Ingreep: vlaggen, en alleen dat ene onmogelijke interval op `NaN`.** Niet de stand zelf, want de
nieuwe stand na de wissel is de juiste beginwaarde van een nieuwe telling en moet blijven staan.
**Geen segmentgebaseerde reparatie.** Dit is expliciet verboden in twee documenten:

> "Geen meterwisselreparatie. Vlaggen wel, repareren niet, net als in de kwartierpijplijn; dat is A3
> daar en hoort hier hetzelfde te blijven." (`ontwerp-preprocessing-minuut.md`, §11)

> "Wat er wél is: 334 van 620 (53,9 %) van de dalingen gaat naar (vrijwel) nul terwijl de stand
> ervóór nergens in de buurt van een macht van tien lag. Dat is een teller die uitvalt en nul gaat
> melden, niet een die omslaat, en A3 laat zien dat hij daarna meestal gewoon terugkomt op zijn oude
> stand (spiegelparen). Een modulo-correctie zou hier dus niets repareren en wel echte uitval
> wegpoetsen." (`docs/analyse-bevindingen.md`, A4)

A4 heeft bovendien op 620 dalingen **nul** omslag-kandidaten gevonden (een teller die van 9999,9 naar
0 springt, zoals bij IM3): dat vierde artefact komt in deze dataset niet voor. De drie hierboven zijn
dus uitputtend voor wat hier gemeten is.

## 5. Volgorde doet ertoe: een vondst tijdens het meten

Bij het meten van §6 bleek de volgorde van de drie ingrepen niet vrijblijvend. Wordt het
cummax-criterium van §4.2 toegepast **vóórdat** de sentinel (§4.1) is weggehaald, dan explodeert het
aantal treffers: `e_export_laag_cum__kWh` gaf dan 542.507 in plaats van 361 nulmeting-rijen, en
`e_export_hoog_cum__kWh` 622.642 in plaats van 5509.

De oorzaak: bij 146 van de 174 woningen begint `e_export_laag_cum__kWh` op de sentinelwaarde
3433,300 -- ruim boven de drempel van 1. Voor een woning zonder teruglevering (geen zonnepanelen)
is de ware stand daarna structureel 0,0. Blijft de sentinel meetellen in het lopende maximum, dan
denkt het criterium dat de teller "ooit boven 1 heeft gestaan" puur door het initialisatietelegram,
en vlagt het vervolgens **elke** latere, legitieme 0,0-aflezing van die woning als uitval-met-herstel.
Dat is geen randgeval: 8 van de 146 woningen hebben na de sentinelrij een reeks die voor meer dan de
helft uit exacte nullen bestaat.

**Consequentie voor de implementatie: ingreep 1 (sentinel op `NaN`) moet vóór ingreep 2 (cummax)
uitgevoerd worden**, zodat het lopende maximum op de schone reeks wordt berekend. De cijfers in §6
zijn al op de juiste volgorde gemeten.

## 6. Impact in het kwartierpad (M3)

Gemeten op `data/processed/measurements.parquet` (de huidige, ongerepareerde uitvoer: 8.637.833
rijen, 174 woningen), met de sentinel-fix toegepast vóór het cummax-criterium (§5).

**(1) Initialisatietelegram:** 1896 rijen, 167 woningen (zelfde telling als §3, nu op het
kwartierrooster in plaats van de ruwe CSV). De energie die dit foutief in de uitvoer zet
(dubbelzijdig: het interval ervoor én erna), per register:

| register | energie (dubbelzijdig) |
|---|---:|
| `e_import_laag_cum__kWh` | 683.375 kWh |
| `e_import_hoog_cum__kWh` | 612.733 kWh |
| `e_export_laag_cum__kWh` | 274.782 kWh |
| `e_export_hoog_cum__kWh` | 649.827 kWh |
| `g_gebruik_cum__m3` | 617.121 m³ |

**(2) Uitval met herstel:** 33.455 rijen (unie over de acht bronttellers), 42 woningen.

**(3) Echte tellerwissel:** 30 rijen (unie), 10 woningen.

Per teller uitgesplitst (2 en 3, na de sentinel-fix):

| teller | (2) rijen | (2) energie | (3) rijen | (3) energie |
|---|---:|---:|---:|---:|
| `e_import_laag_cum__kWh` | 30 | 145.540 kWh | 6 | 52.389 kWh |
| `e_import_hoog_cum__kWh` | 6858 | 195.202 kWh | 3 | 33.098 kWh |
| `e_export_laag_cum__kWh` | 361 | 22.266 kWh | 4 | 6481 kWh |
| `e_export_hoog_cum__kWh` | 5509 | 69.821 kWh | 2 | 68 kWh |
| `g_gebruik_cum__m3` | 32.203 | 699.352 m³ | 5 | 404.189 m³ |
| `e_warmtepomp_cum__kWh` | 13 | 67.741 kWh | 0 | 0 |
| `e_ketel_cum__kWh` | 223 | 17.633 kWh | 0 | 0 |
| `q_geleverd_cum__J` | 0 | 0 | 19 | 88.000.512 J (≈ 24,4 kWh) |

**Twee dingen die hieruit opvallen.** Ten eerste: (2) is groter dan de huidige
`teller_terug__bool`-telling (384 van 8.637.503, `docs/data-quality.md` §4) doet vermoeden, met een
factor van bijna honderd. Dat komt doordat `teller_terug__bool` alleen de **overgang** naar 0 vlagt
(één rij per uitvalperiode), terwijl §4.2 vereist dat **elke** rij in een langdurige 0-periode als
ongeldig wordt gezien -- bij `g_gebruik_cum__m3` betreft dat één woning met kennelijk een
gasmeterstoring van maanden. Ten tweede: (3), de categorie die daadwerkelijk om reparatie zou kunnen
vragen als je (ten onrechte) segmentgebaseerd zou repareren, is juist de kleinste: 30 rijen over 10
woningen. Dat onderstreept waarom `ontwerp-preprocessing-minuut.md` en A4 hier terecht vlaggen zonder
te repareren: er is weinig te repareren, en wat er is (een echte wissel) is geen reparatiekandidaat
maar een nieuw beginpunt.

## 7. Wat er verandert in `measurements.parquet` en `quality.parquet`

**`measurements.parquet`:** geen nieuwe kolommen. De acht bestaande `*_cum__*`-kolommen krijgen meer
`NaN`-waarden, op precies de rijen die in §4.1 en §4.2 worden gemaskeerd (§4.3 maskeert de stand
zelf niet, alleen de afgeleide). Dit is geen stille correctie (ontwerp-preprocessing.md §3, principe
2: "Geen stille correcties"): elke gemaskeerde rij krijgt in `quality` een vlag die verklaart waarom.

**`quality.parquet`:** drie vlaggen komen erbij of veranderen:

- **`teller_initialisatie__bool`** (nieuw): True op de 1896 rijen uit §4.1/§6.
- **`teller_nulmeting__bool`** (nieuw in het kwartierpad, bestaat al identiek in het minuutpad):
  True op de 33.455 rijen uit §4.2/§6.
- **`teller_wissel__bool`** (nieuw in het kwartierpad, naam bestaat al in het minuutpad maar
  daar ongemaskeerd): True op de 30 rijen uit §4.3/§6.
- **`teller_terug__bool`** (bestaat al): blijft bestaan als optelling (OR) van
  `teller_nulmeting__bool` en `teller_wissel__bool`, en verliest de sentinel-overgangen die er nu
  soms nog inzitten -- die zijn na de fix geen "daling" meer, want de sentinelrij bestaat dan niet
  meer als tellerstand.

Alle drie de nieuwe/gewijzigde vlaggen horen in `docs/variable-dictionary.md` §`quality` bij te
komen, naast de bestaande opsomming.

## 8. Wat er in het kwaliteitsrapport bij moet

`docs/data-quality.md` §4 ("Tellers die teruglopen, teruggeleverd worden, of springen") telt nu alleen
`teller_terug__bool` als één getal. Dat moet uiteenvallen in drie regels, één per artefact, plus een
regel voor het initialisatietelegram die er nu helemaal niet is:

- aantal rijen/woningen met `teller_initialisatie__bool` (met de bronvermelding uit §3 erbij);
- aantal rijen/woningen met `teller_nulmeting__bool`, en een aparte vermelding van de langste
  aaneengesloten uitvalperiode (het gasvoorbeeld uit §6 is anders onzichtbaar in een enkel getal);
- aantal rijen/woningen met `teller_wissel__bool`, ONgewijzigd qua betekenis;
- een expliciete regel dat `teller_terug__bool` de optelling is van de laatste twee, zodat een lezer
  die het oude gedrag verwacht niet verrast wordt door een kleiner getal (de sentinel-overgangen
  verdwijnen eruit, zie §7).

## 9. Vals-positieven

De vals-positieve marge tussen de strikte handtekening en een losse, per-register regel is klein op
deze dataset: 2 rijen op 8 miljoen, 0 woningen (§3). Dat is geen vrijbrief om de losse regel te
gebruiken. De twee treffers zijn zelf het bewijs waarom niet: `df79ygat` (2023-07-08T23:45:05) en
`A0JoUuz-` (2024-04-25T04:45:03) hebben allebei `e_consumed_low` = 8969,994, maar op momenten diep in
hun meetreeks (niet aan het begin) en met de andere vier registers op heldere, onderling
verschillende waarden (bijvoorbeeld `A0JoUuz-`: `e_consumed_high`=8975,163, `e_delivered_high`=
14.182,572, `e_delivered_low`=6381,683, `v_gas_consumed`=8894,696 -- niets daarvan is een
sentinelwaarde). Dit zijn twee echte meters die toevallig door exact 8969,994 kWh heen liepen. Een
regel die op één register alleen let, had deze twee kwartieren ten onrechte op `NaN` gezet en zo
echte, bruikbare metingen weggegooid. De marge is hier klein omdat de dataset toevallig meewerkt
(geen enkele woning heeft toevallig een tweede register op zijn sentinelwaarde tegelijk); dat is een
eigenschap van deze steekproef, niet van de regel, en de handtekening (vereis alle vijf) blijft om
die reden de juiste keuze, ook al was de winst er ditmaal klein.

## 10. Wat deze notitie niet oplost

- **Geen reparatie van echte tellerwissels.** §4.3 vlagt en maskeert één interval; de reeks blijft
  daarna in twee stukken, en dat is bewust (§4.3, A4).
- **Geen oordeel over de sprongdrempels** (`tellers.SPRONG_DREMPEL__W`, `teller_sprong__bool`). Dat
  is een apart, al lopend traject (`docs/analyse-bevindingen.md` B7).
- **Geen sentinel- of nulmeting-fix in het minuutpad.** M1 (§2) laat zien dat de sentinel daar niet
  voorkomt, en `markeer_nulmetingen` bestaat er al (M1 laat zien dat het minuutpad die niet nodig
  heeft toegevoegd, want hij is er al). Deze twee ingrepen (4.1, 4.2) blijven dus kwartierpad-only.
- **Wél een wijziging aan het minuutpad, voor 4.3.** Bij reviewpunt A2 bleek dat `teller_wissel__bool`
  in het minuutpad weliswaar gevlagd wordt (`minuut.py:480` en `minuut.py:718`,
  `wissel |= daalt & ~volgende_is_nul`), maar dat het betrokken interval niet gemaskeerd wordt: de
  `afgeleid["delta"]`/`afgeleid["vermogen__W"]` van dat ene interval blijven ongewijzigd in de
  uitvoer terechtkomen (`minuut.py:464-483` voor het batchpad, `minuut.py:707-721` voor het
  streamende pad). Dat is zichtbaar in de bestaande uitvoer: `q_geleverd__W` = -100.000,7 bij woning
  `W5J0QUUq`. Ingreep 4.3 (vlaggen, en alleen dat ene interval op `NaN`, niet de stand) hoort dus in
  BEIDE paden, met dezelfde motivatie als in §4.3: dit is geen reparatie, alleen het onmogelijke
  interval verdwijnt uit de uitvoer. §12 is hierop aangepast.
- **Geen bridging van gemaskeerde intervallen -- deze notitie beweerde dat eerst ten onrechte.**
  Oorspronkelijk stond hier dat een gemaskeerd interval, net als elk ander gat, "overbrugd" wordt
  doordat `differentieer_teller`/`differentieer_snel` de eerstvolgende geldige aflezing pakt. Dat is
  **gecontroleerd en onjuist gebleken** (reviewpunt A1). Wat er feitelijk gebeurt:

  `tellers.differentieer_teller` (`tellers.py:119-121`) berekent `delta` met een `groupby(...).shift(-1)`
  over de aanwezige RIJEN, niet over een tijdsraster: `volgende_waarde = grouped["waarde"].shift(-1)`
  gevolgd door `delta = volgende_waarde - gesorteerd["waarde"]`. Dat "springt" alleen over een gat
  als de tussenliggende kwartieren als RIJ ontbreken (`ontwerp-interpolatie-en-dekking.md` §2: "een
  gat wordt overbrugd als één langer interval" -- dat gaat over ontbrekende rijen). Zet je in plaats
  daarvan de `waarde` van een AANWEZIGE rij op `NaN` (wat 4.1 en 4.2 doen), dan blijft die rij in de
  groupby zitten en NaN propageert simpelweg door de aftrekking: de rij vóór de gemaskeerde rij krijgt
  `delta = NaN - echte_waarde = NaN` (haar "volgende" waarde is nu NaN), en de gemaskeerde rij zelf
  krijgt `delta = volgende_echte_waarde - NaN = NaN`. Er wordt niets bij elkaar opgeteld en er
  verschijnt geen piek; beide grensintervallen worden gewoon `NaN`, verder gebeurt er niets. Hetzelfde
  geldt positioneel voor `minuut.differentieer_snel` (`minuut.py:250-259`, `delta[:-1] = stand[1:] -
  stand[:-1]`): een `NaN` op positie *i* maakt zowel `delta[i-1]` als `delta[i]` `NaN`, ook bij een
  lange aaneengesloten reeks gemaskeerde rijen (elke tussenliggende `delta` is dan `NaN - NaN = NaN`).

  **Empirisch bewijs** (zes rijen, één woning, een 3-kwartier "storing" die terugvalt op 0 en herstelt
  op een stand ver boven de oude; script in de sessie-scratchpad, functies rechtstreeks uit
  `tellers.py`/`minuut.py` aangeroepen):

  | stand (ruw) | 100 | 110 | 0 | 0 | 0 | 250 |
  |---|---:|---:|---:|---:|---:|---:|
  | stand (rij 2-4 gemaskeerd op NaN) | 100 | 110 | NaN | NaN | NaN | 250 |
  | `delta` (`differentieer_teller`, gemaskeerd) | 10 | **NaN** | NaN | NaN | **NaN** | (laatste rij: NaN) |

  Rij 1 (110 -> volgende=NaN) en rij 4 (NaN -> 250) worden allebei `NaN`, niet `140` over een
  interval van 3 kwartier en niet een sprong van `250`. Ter vergelijking: verwijder je diezelfde drie
  rijen in plaats van ze op `NaN` te zetten (dus een ECHT ontbrekende rij, geen gemaskeerde waarde),
  dan krijgt rij 1 wél `delta=140` over `delta_t__s=2700`, exact de bridging die
  `ontwerp-interpolatie-en-dekking.md` §2 bedoelt -- maar dat scenario is niet van toepassing hier:
  4.1/4.2 zetten een AANWEZIGE rij op `NaN`, ze verwijderen geen rij.

  **Conclusie: scenario (ii) uit de reviewopdracht.** Er is geen piek om tegen te beschermen en er is
  dus geen maximale overbruggingslengte nodig; §4.1 en §4.2 hierboven blijven ongewijzigd correct. De
  eerdere tekst in deze paragraaf ("overbrugd... net als elk ander gat") was gewoon fout opgeschreven
  en is hiermee gecorrigeerd. Ter zijde: dezelfde onjuiste bewering stond (met net iets andere
  woorden) ook al in de docstring van `verwerk_teller` (`minuut.py:270-272`, "het interval eromheen
  wordt overbrugd als één langer interval") -- ook dat is een woordkeuze die de code niet waarmaakt,
  al is het effect (geen valse piek) wel het gewenste.
- **Geen validatie op de andere zes bronbestanden.** De sentinel is alleen aangetoond in `dsmr.csv`;
  `kamstrup.csv`, `heatpump.csv` en `boiler.csv` zijn hier niet los op eenzelfde patroon onderzocht.

## 11. `measurements.parquet` is nog niet geleverd

`measurements.parquet` is tot nu toe niet aan een afnemer geleverd. De wijzigingen hierboven zijn
dus een gewone verbetering van een tussenresultaat, geen herlevering met de gevolgen die dat zou
hebben (afnemers die hun eigen verwerking opnieuw moeten draaien, een aangekondigde
schemawijziging, etc.). `UITVOER_CONTRACT_VERSIE` gaat bij de implementatie wel omhoog
(`CLAUDE.md`), zodat een lokale cache niet stilzwijgend de oude, ongerepareerde uitvoer hergebruikt.

## 12. Wat er moet gebeuren

1. **De vijf sentinelwaarden een benoemde constante maken**, met de bronvermelding uit §3 (bestand,
   rij, woning, tijdstip) in het commentaar erbij -- niet als losse getallen in een
   vergelijkingsexpressie. Voorstel voor de plek: `tellers.py`, naast `SPRONG_DREMPEL__W`.
2. **De handtekeningdetectie bouwen**: alle vijf registers tegelijk op hun sentinelwaarde, op elke
   positie in de reeks (§4.1). Zet de vijf tellerstanden op die rij op `NaN` vóór het
   differentiëren.
3. **`markeer_nulmetingen` overnemen uit `minuut.py`** naar het kwartierpad, ONGEWIJZIGD qua
   cummax-criterium, en **na** stap 2 laten lopen (§5).
4. **Een `teller_wissel__bool` voor het kwartierpad**: vlaggen op een daling die niet in een
   nulmeting eindigt, en het ene betrokken interval (niet de stand) op `NaN`.
4bis. **Hetzelfde interval-masker voor `teller_wissel__bool` in het minuutpad** (A2, §10): op de
   `wissel`-rijen in zowel `minuut.py:464-483` (batchpad) als `minuut.py:707-721` (streamend pad)
   moet `afgeleid["delta"]`/`afgeleid["vermogen__W"]` (en de daarvan afgeleide kolommen
   `g_gebruik__m3_s_1`, `q_geleverd__W`, `p_warmtepomp__W`, `p_ketel__W`) op `NaN` voor dat ene
   interval, net als bij 4.3 in het kwartierpad -- de stand zelf (`schoon`) blijft staan. De sentinel
   (4.1) en `markeer_nulmetingen` (4.2) blijven kwartierpad-only (M1: het minuutpad heeft ze niet
   nodig).
5. **`teller_terug__bool` herdefiniëren** als OR van de vlaggen uit stap 3 en 4 (§7).
6. **`docs/variable-dictionary.md` en `docs/data-quality.md`/`rapport.py` bijwerken** volgens §7 en
   §8.
7. **Testen**: minimaal de handtekeningdetectie op de 1896 bekende rijen, het cummax-criterium op
   `g_gebruik_cum__m3` (de langste uitvalperiode uit §6), een regressietest die de volgorde uit
   §5 vastlegt (sentinel vóór cummax) zodat die niet per ongeluk omgedraaid wordt, en een test voor
   4bis die aantoont dat een `wissel`-interval in het minuutpad (beide varianten) na de fix `NaN` is
   in plaats van de onmogelijke waarde van vóór de fix.
8. **`UITVOER_CONTRACT_VERSIE` ophogen** (§11).
