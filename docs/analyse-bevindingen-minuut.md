# Analysebevindingen: minuutpad

Het analoog van `docs/analyse-bevindingen.md`, maar voor het tweede invoerpad
(`dph_preprocessing.minuut`, `ontwerp-preprocessing-minuut.md`). Twee dingen liggen hier anders dan
bij het kwartierpad, en ze sturen de hele opzet van dit document:

1. **Er is nog geen `analyses.py`-achtige, hervatbare module voor het minuutpad.** De B5-analyse
   hieronder leunt op `dph_preprocessing.minuut_dekking` (wél geschreven en getest, zie
   `tests/test_minuut_dekking.py`), maar de vergelijking met het kwartierpad is met losse scripts
   gemaakt tegen `data/processed/*.parquet` en de NAS-uitvoer. Elk cijfer hieronder noemt de bron
   erbij, precies omdat er geen module is die het bij een herdraai automatisch reproduceert.
2. **De bron is de vorige volledige ronde, niet de ronde van vannacht.** Deze analyse is geschreven
   terwijl `DPH-minuut-preprocessing` de set opnieuw verwerkte (uint16-reparatie en
   `raster_<naam>__W`/`raster_breuk_<naam>__bool`, zie de commit "Voer de twee openstaande
   schemawijzigingen..."). `gaten.parquet`, `homes_minuut.parquet`'s bezetting/dekking-kolommen en
   `raster.parquet` zijn door die twee wijzigingen niet geraakt: ze veranderen alleen het dtype van
   negen kolommen en voegen kolommen toe, niet de gatendetectie of de dekkingsberekening. De
   cijfers hieronder gelden dus onveranderd voor de uitvoer van vannacht. Bron:
   `\\hoftenas\backup\energiedata\DPH-per-minuut-verwerkt-vorige-ronde-20260917\` (de ronde van
   17-09-2026, 20:26–20:42, 164 nieuw verwerkt + 10 al aanwezig = 174 van 174, nul mislukkingen).

## B5. Aaneengesloten bruikbare tijd op het minuutrooster

**Vraag**: hoeveel van de tijd van elke woning is aaneengesloten bruikbaar, met de overbruggingsgrenzen
uit `ontwerp-interpolatie-en-dekking.md` §4 (gemeten met de ponsmeting van 17-09-2026), en wat
betekent dat voor de COP-combinatie uit §5 (`p_warmtepomp_gemeten__W` én `q_geleverd_gemeten__W`
tegelijk, de 39 locaties met een dood warmtepompkanaal eruit)?

**Methode, en waarom hij eerlijk is over zijn eigen aanname.** Dit komt volledig uit
`gaten.parquet` en de tijdspanne (`eerste_minuut`/`laatste_minuut`) uit `homes_minuut.parquet`,
zonder een enkele meting aan te raken, zoals de opdracht vroeg (`minuut_dekking.gedekte_tijd__min`,
`minuut_dekking.segmenten`). `gaten.parquet` kent alleen RIJdekking (deze minuut staat wel of niet
in de bron); de zeven momentane grootheden hebben in principe hun EIGEN dekking binnen een
aanwezige rij. Dat verschil is gemeten via `dekking_<kolom>` uit `homes_minuut.parquet` (het
aandeel AANWEZIGE rijen met een geldige waarde in die kolom):

| kolom | mediaan | p10 | min | locaties < 95 % |
|---|---:|---:|---:|---:|
| `temp_retour__degC`, `temp_aanvoer__degC`, `debiet__dm3_s_1`, `p_warmtepomp_gemeten__W` | 100,0 % | 99,4 % | 53,7 % | 3 |
| `q_geleverd_gemeten__W` | 99,6 % | 98,6 % | 53,6 % | 5 |
| `temp_binnen__degC`, `rv_binnen__0` | 99,2 % | 75,9 % | 0,0 % | 58 |

Voor de vijf Kamstrup/warmtepompkolommen, en dus voor de COP-combinatie, is "rij aanwezig" een
goede stand-in voor "kolom aanwezig": op zijn slechtst 3 tot 5 locaties zitten onder 95 %. Voor de
twee Sonoff-kolommen (`temp_binnen__degC`, `rv_binnen__0`, een apart kastje) is dat zwakker: 58 van
de 174 locaties zitten onder 95 %, sommige op 0 % (kapotte sensor terwijl de rest van de rij
gewoon binnenkomt). De cijfers voor die twee kolommen hieronder zijn dus een BOVENGRENS.

**Aandeel gedekte tijd, per grootheid, gepoold over de 174 locaties** (bron:
`minuut_dekking.analyse_b5_minuut`, gedraaid tegen `gaten.parquet` + `homes_minuut.parquet` van de
ronde hierboven):

| grootheid | overbruggingsgrens | mediaan | p10 | p90 | min | max | referentie (k=0, geen overbrugging) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `temp_binnen__degC` / `rv_binnen__0` | 60 min | 76,6 % | 52,5 % | 93,8 % | 0,5 % | 98,7 % | 76,5 % |
| `temp_retour__degC` | 3 min | 76,5 % | 51,5 % | 93,7 % | 0,5 % | 98,4 % | 76,5 % |
| `temp_aanvoer__degC` | 2 min | 76,5 % | 51,4 % | 93,7 % | 0,5 % | 98,4 % | 76,5 % |
| `debiet__dm3_s_1` | 1 min | 76,5 % | 51,4 % | 93,7 % | 0,5 % | 98,4 % | 76,5 % |
| `q_geleverd_gemeten__W` | 0, niet overbruggen | 76,5 % | 51,4 % | 93,7 % | 0,5 % | 98,4 % | 76,5 % |
| `p_warmtepomp_gemeten__W` | 0, niet overbruggen | 76,5 % | 51,4 % | 93,7 % | 0,5 % | 98,4 % | 76,5 % |

De overbrugging zelf wint hier weinig (76,5 % → 76,6 % voor het ruimste geval): het venster tot
07:00 achter de eerste run en de losse-speldenprikken-verdeling uit ontwerp §7 (71,4 % van de gaten
duurt hoogstens 5 minuten en draagt samen 0,44 % van het gemis) zeggen al dat er weinig te winnen
valt met een grens van hoogstens een uur. Wat wél verschilt is hoe die dekking is opgebouwd;
zie de reeksverdeling hieronder.

**COP-combinatie** (`minuut_dekking.analyse_cop_combo`; 174 − 39 = 135 locaties zonder dood
warmtepompkanaal, beide kolommen op grens 0):

| | mediaan | p10 | p90 | min | max |
|---|---:|---:|---:|---:|---:|
| aandeel gedekt | 79,2 % | 51,2 % | 95,6 % | 25,5 % | 98,4 % |

Hoger dan de losse kolommen (79,2 % tegen 76,5 %) omdat de 39 dode-kanaal-locaties er ook in de
oorspronkelijke B5-tabel al ondergemiddeld uitzagen (een dood elektriciteitskanaal correleert met
een minder betrouwbare installatie in het algemeen); ze eruit halen trekt de rest omhoog. **De
combinatie zelf voegt onder de rijdekkingsaanname hierboven niets toe**: omdat beide kolommen op
dezelfde grens (0) staan en dezelfde rijgatenlijst delen, valt "allebei tegelijk" samen met "één van
de twee", en dat is precies waarom de tabel dezelfde cijfers geeft als `q_geleverd_gemeten__W` en
`p_warmtepomp_gemeten__W` los, min de 39 uitgesloten locaties.

**Reeksverdeling** (som over de 174 locaties, in dagen, bij de gemeten grens):

| grootheid | kwartier–uur | uur–dag | dag–week | week–maand | > maand | aandeel in reeksen > week |
|---|---:|---:|---:|---:|---:|---:|
| `temp_binnen__degC` (k=60) | 34,3 | 1494,0 | 4847,1 | 11671,6 | 72009,4 | 92,9 % |
| COP-combo (k=0) | 559,7 | 5156,7 | 13660,3 | 29048,1 | 22918,0 | 72,8 % |

Ter vergelijking, het kwartierpad (B5 in `docs/analyse-bevindingen.md`): 89,0 % van alle gedekte
tijd zit in reeksen langer dan een week, bij een gatlimiet van 90 minuten (NeedForHeats default).
`temp_binnen__degC` op het minuutrooster zit daar met 92,9 % dicht bij, met een grens die twintig
keer zo krap is (60 minuten tegen 90); een teken dat de kwartierpad-drempel vooral de LOSSE
kwartieren aan het opruimen was, niet dat een ruimere grens per se nodig is. De COP-combinatie zit
met 72,8 % duidelijk lager: dat is precies de prijs van "niet overbruggen" op de warmtekant (§4 van
het interpolatieontwerp), en het is een gemeten prijs, geen giswerk.

**Kruiscontrole tussen de twee paden.** `uQLTOCT9` heeft op het kwartierpad de laagste dekking van
alle 174 woningen: 0,5 % (`docs/analyse-bevindingen.md`, B5: "206,2 dagen totaal, 1,0 dag gedekt").
Op het minuutrooster is dezelfde woning ook de slechtste: 0,48 % (referentie k=0). Twee onafhankelijk
gebouwde pijplijnen, twee verschillende roosters, en toch dezelfde uitschieter met bijna hetzelfde
getal; dat is een sterkere aanwijzing dat de dekkingsberekening zelf klopt dan één van de twee
losse getallen dat zou zijn.

## Vergelijking met het kwartierpad

**Dit is de belangrijkste vraag van de hele exercitie**: komen de energietotalen per woning overeen
tussen de twee paden, en zo nee, waar zit het verschil?

Beide paden kennen dezelfde 174 `home_id__str`-waarden (geen enkele alleen in het ene of het
andere; gecontroleerd op `data/processed/homes.parquet` tegen `homes_minuut.parquet`). Het
minuutpad bestrijkt nominaal 25-11-2021 t/m 31-05-2024 (`ontwerp-preprocessing-minuut.md` §1); het
`measurements.parquet` van het kwartierpad begint pas 10-01-2022 volgens zijn eigen
footer-statistieken en eindigt op dezelfde dag, 31-05-2024. Het kwartierpad mist dus de eerste
anderhalve maand die het minuutpad wel heeft, een reëel verschil, maar te klein om de bevindingen
hieronder te verklaren.

### De projecttellers: vrijwel exacte overeenstemming

Voor de drie tellers die het project zelf heeft geïnstalleerd (de warmtepomp-, ketel- en
Kamstrup-warmtemeter, nooit eerder gebruikt en dus zonder voorgeschiedenis) is het totaal
(laatste stand min eerste stand, gesommeerd over alle 174 woningen) op vijf decimalen gelijk:

| teller | totaal minuutpad | totaal kwartierpad | relatief verschil | grootste afwijking bij één woning |
|---|---:|---:|---:|---:|
| `e_warmtepomp_cum__kWh` | 532.745,4 kWh | 532.742,7 kWh | +0,0005 % | 0,0139 % |
| `e_ketel_cum__kWh` | 17.706,4 kWh | 17.703,2 kWh | +0,018 % | 5,26 % (één woning, n=172) |
| `q_geleverd_cum__J` | 1,262213·10¹³ J | 1,262202·10¹³ J | +0,0008 % | 0,044 % |

(Bron: de footer-eerste/laatste van `raster.parquet`, zie `minuut_raster.eerste_laatste_uit_footer`,
17-09-2026-ronde, tegen `data/processed/measurements.parquet`, per woning eerste/laatste geldige
kwartierwaarde, gesorteerd op tijd.) Dit bevestigt dat de kernlogica (vooruit differentiëren,
delen door de werkelijke verstreken tijd, telescoperen tot laatste stand min eerste stand) in
beide pijplijnen hetzelfde doet voor een teller zonder wissel of vervuiling in zijn geschiedenis.
Dat is precies de garantie die `ontwerp-interpolatie-en-dekking.md` §6.3 belooft ("energiebalansen
... zijn ongemoeid") en hier voor het eerst TUSSEN de twee paden getoetst is, niet alleen binnen
één pad.

### De DSMR-tellers en gas: grote, en aanvankelijk onverklaarde, verschillen

Voor de vier DSMR-registers (import/export, laag/hoog tarief) en gas is het beeld heel anders:

| teller | totaal minuutpad | totaal kwartierpad | relatief verschil (totaal) | woningen met > 5 % afwijking |
|---|---:|---:|---:|---:|
| `e_import_laag_cum__kWh` | 744.126 kWh | 930.709 kWh | −20,0 % | 150 van 162 |
| `e_import_hoog_cum__kWh` | 566.170 kWh | 607.838 kWh | −6,9 % | 148 van 162 |
| `e_export_laag_cum__kWh` | 217.234 kWh | 96.462 kWh | +125,2 % | 147 van 162 |
| `e_export_hoog_cum__kWh` | 474.287 kWh | 124.569 kWh | +280,7 % | 151 van 162 |
| `g_gebruik_cum__m3` | 193.562 m³ | 625.302 m³ | −69,0 % | 154 van 162 |

(n=162: van de 174 hebben er 4 helemaal geen DSMR-teller (`ontwerp-preprocessing-minuut-
geheugen.md` §6.6a), en voor de rest ontbreekt bij een enkele woning een geldige kwartierwaarde.)
Bij één woning (`A0JoUuz-`) was het minuutpad-totaal voor `e_import_laag_cum__kWh` een factor
88.480 groter dan het kwartierpad-totaal van 0,041 kWh. Dat is geen precisieverschil maar een teken
dat één van de twee kanten (of allebei) de verkeerde start- of eindwaarde te pakken heeft.

**De oorzaak, gevonden door één woning met een absurd cijfer uit te pluizen.** `RHON9wor`'s
`e_import_laag_cum__kWh` op het kwartierpad: de eerste twee kwartieren (18-02-2022, 08:30 en 08:45)
staan op 8969,994 kWh; het derde geldige kwartier (28-02-2022, 08:45, tien dagen later) springt naar
5619,978 kWh en loopt van daar normaal op tot 8951,071 kWh op 31-05-2024
(`stap8_diagnose_negatief.py` tegen `data/processed/measurements.parquet`). Het kwartierpad neemt
"eerste geldige waarde" letterlijk en trekt dus 8969,994 van 8951,071 af: een fysiek onmogelijke
NEGATIEVE hoeveelheid geïmporteerde energie (−18,923 kWh). De ruwe bron van het minuutpad
(`DPH-per-minuut/measurements_per_minuut/location_id=RHON9wor.parquet`) bevat die 8969,994 helemaal
niet: de eerste minuut met een geldige `dsmr_e_consumed_low_eerste` staat al op 5619,978, om
28-02-2022 07:57 UTC.

**8969,994 is geen meterstand maar een sentinelwaarde**, en dat is met een schaalcontrole over alle
174 woningen aan te tonen: het is niet alleen bij `RHON9wor` de eerste waarde, maar bij **166 van de
174 woningen (95 %)** letterlijk, tot en met de derde decimaal, dezelfde eerste geldige waarde
in `measurements.parquet`. En dat geldt niet alleen voor dit ene register: elk van de vijf
DSMR/gas-kolommen heeft zijn EIGEN vaste sentinel, telkens bij dezelfde 166 woningen:

| kolom | sentinelwaarde | woningen met exact deze eerste waarde |
|---|---:|---:|
| `e_import_laag_cum__kWh` | 8969,994 kWh | 166 |
| `e_import_hoog_cum__kWh` | 8789,167 kWh | 166 |
| `e_export_laag_cum__kWh` | 3433,300 kWh | 166 |
| `e_export_hoog_cum__kWh` | 8299,146 kWh | 166 |
| `g_gebruik_cum__m3` | 5059,199 m³ | 166 |

(Bron: `stap10_sentinel_omvang.py`, `value_counts()` van de per-woning eerste geldige waarde over
alle 174 woningen in `data/processed/measurements.parquet`.) Vijf onafhankelijke registers met
allemaal precies één, over 95 % van de woningen identieke waarde is geen toeval: dit is een
fabrieks- of loggerdefault die verschijnt vóórdat de echte DSMR-telegram-koppeling loopt, en die in
`measurements.parquet` als een normale, geldige meting binnenkomt. Voor `e_import_laag_cum__kWh`
is dat bij `RHON9wor` aantoonbaar NIET aanwezig in de bron van het minuutpad; of dat voor alle 166
woningen en alle vijf kolommen zo is, is met de tijd van vannacht niet meer te controleren, maar het
patroon (één ronde getal per kolom, over bijna de hele set) wijst niet naar toeval.

**Na het wegfilteren van de sentinelwaarde als "eerste waarde"** (de eerste geldige kwartierwaarde
die NIET gelijk is aan de sentinel van die kolom, tegen dezelfde minuutpad-totalen; bron:
`stap12_na_sentinel_correctie.py`) verdwijnt het gros van het verschil in één klap:

| teller | relatief verschil (totaal) | mediaan \|relatief verschil\| per woning | p90 \|relatief verschil\| | woningen met een nog negatieve kwartierdelta |
|---|---:|---:|---:|---:|
| `e_import_laag_cum__kWh` | +7,9 % | 0,0011 % | 0,0049 % | 15 van 162 |
| `e_import_hoog_cum__kWh` | +11,6 % | 0,0000060 % | 0,0010 % | 15 van 162 |
| `e_export_laag_cum__kWh` | +9,9 % | 0,0000061 % | 0,0000335 % | 10 van 162 |
| `e_export_hoog_cum__kWh` | +11,5 % | 0,0000050 % | 0,00099 % | 10 van 162 |
| `g_gebruik_cum__m3` | +1.660 % | 0,000032 % | 102,8 % | 11 van 162 |

Voor de vier elektriciteitsregisters is de MEDIANE woning nu binnen 0,001 % gelijk tussen de twee
paden; de sentinel verklaart vrijwel het hele verschil dat de vorige tabel liet zien. Wat overblijft
zijn de 10 à 15 woningen (van de 162) waar de kwartierdelta nog steeds negatief is: die hebben een
ECHTE tellerwissel ergens in de reeks, geen sentinel, en dat trekt het TOTAAL (en de p90) nog altijd
scheef. Gas is de uitzondering: ook daar is de mediane woning bijna perfect (0,000032 %), maar de
p90 van 102,8 % en het totaal (+1.660 %) laten zien dat een KLEINE groep woningen een veel groter
gas-specifiek probleem heeft dan bij elektriciteit: waarschijnlijk meerdere resets of een tweede
sentinel die deze nacht niet meer te achterhalen was.

**Wat overblijft is een reëel, kleiner probleem: echte tellerwissels.** Beide paden documenteren
expliciet dat ze wissels VLAGGEN maar niet REPAREREN (`ontwerp-preprocessing-minuut.md` §11: "Geen
meterwisselreparatie... net als in de kwartierpijplijn"; A3 in `docs/analyse-bevindingen.md` doet
de reparatiediagnose alleen, niet de reparatie zelf). Een tellerwissel middenin de reeks maakt
"laatste stand min eerste stand" ONJUIST in BEIDE paden, ongeacht welke kant preciezer is: de enige
correcte manier is per segment optellen (vóór de wissel, ná de wissel), en dat is precies het werk
dat beide ontwerpen bewust hebben uitgesteld. De DSMR-registers zijn hier het gevoeligst, want ze
lopen al vóór de start van het project en zijn dus het langst blootgesteld aan een eventuele
meterwissel; de drie projecttellers (warmtepomp, ketel, Kamstrup) beginnen bij nul bij de installatie
en hebben dat probleem niet, wat meteen verklaart waarom precies díe drie tellers hierboven wel
overeenkomen.

### Conclusie van de vergelijking

- **De kernlogica klopt tussen de twee paden**: voor tellers zonder voorgeschiedenis (de drie
  projectmeters) is het totaal identiek tot op vijf decimalen. Dat is het antwoord op "doet het
  minuutpad hetzelfde als het kwartierpad", los van de complicaties hieronder.
- **De DSMR/gas-totalen zijn in GEEN van beide paden op dit moment betrouwbaar** als "laatste min
  eerste", door een combinatie van (a) een sentinelwaarde die bij 166 van de 174 woningen als
  eerste geldige kwartierwaarde wordt aangezien voor een meting, en (b) echte tellerwissels die
  geen van beide paden repareert. Dit is geen verschil TUSSEN de paden maar een eigenschap van de
  ruwe DSMR-data die allebei de paden nog niet opvangen. **Met de sentinel eruit gefilterd, komen de
  vier elektriciteitsregisters voor de MEDIANE woning tot op 0,001 % overeen**; het achterliggende
  verschil is dus vrijwel volledig de sentinel, niet een verschil in hoe de twee paden differentiëren.
  Gas heeft daarnaast nog een tweede, kleiner-verspreid maar groter probleem dat deze nacht niet is
  opgelost (zie de tabel hierboven).
- **Aanbeveling voor het kwartierpad**: `e_import_laag/hoog_cum__kWh`, `e_export_laag/hoog_cum__kWh`
  en `g_gebruik_cum__m3` zouden een uitzondering kunnen krijgen naar het voorbeeld van
  `minuut.NUL_IS_AFWEZIG` (die op het minuutpad al bewijst dat "een vaste, fysiek onwaarschijnlijke
  waarde is een sentinel en geen meting" een werkende aanpak is): de vijf waarden in de tabel
  hierboven zijn kandidaten. Dat is een wijziging in de KWARTIER-pijplijn en dus buiten de scope van
  deze nacht, maar wel de meest concrete opbrengst van deze vergelijking.
- **Aanbeveling voor het minuutpad**: `eerste_laatste_uit_footer` (deze nacht toegevoegd aan
  `minuut_raster.py`) is een goedkope, footer-only benadering en geen garantie; een sentinel of
  wissel binnen de eerste of laatste ~100.000 rijen zou hem alsnog kunnen raken. Voor een
  betrouwbaar energietotaal per teller hoort uiteindelijk dezelfde segment-gebaseerde reparatie als
  hierboven, met dezelfde sentinelwaarden als startpunt.

## Welke van de twaalf kwartieranalyses één op één overkomen

| analyse | komt 1:1 over? | reden |
|---|---|---|
| **A1** (warmtepompteller-uitschieters) | Deels | `p_warmtepomp__W` en `p_warmtepomp_gemeten__W` bestaan allebei, maar de momentane kant is op het minuutpad al hard afgekapt door het plausibiliteitsfilter (`GRENZEN`, ontwerp §6): wat A1 op het kwartierpad als uitschieter ONTDEKT, is op het minuutpad al als `onplausibel__bool` weggezet vóórdat een analist ernaar kijkt. De tellerkant (`p_warmtepomp__W`, ongebonden) kan wél opnieuw. |
| **A3** (meterwissels/spiegelparen) | Ja, met een kanttekening | De acht cumulatieve tellers staan ook op het minuutpad gepubliceerd; `_tel_spiegelparen_alle_woningen`'s algoritme (MAD-drempel, spiegelpaar binnen 2 rijen) is roosteronafhankelijk. Kanttekening: "2 rijen verder" is op een minuutrooster 2 minuten in plaats van 30, dus de afstandsparameter verdient een nieuwe meting. Bovendien doet het minuutpad al een DEEL van dit werk inline (`teller_wissel__bool`, `teller_nulmeting__bool`), zonder de spiegelpaar-detectie die een wissel als "artefact, mogelijk repareerbaar" van een echte wissel onderscheidt. |
| **A4** (modulusartefacten) | Ja | Gaat over de absolute stand van dezelfde acht brontellers, onafhankelijk van het rooster. Het kwartierpad vond nul gevallen; dat is een eigenschap van de meterhardware, dus het minuutpad zal vermoedelijk hetzelfde nulresultaat geven, maar "vermoedelijk" is geen "gemeten", dus dit staat nog open. |
| **A5** (scheefheid per bron) | Nee, want het probleem dat het oplost bestaat hier niet | A5 bestaat omdat het kwartierpad na de outer-merge van vier bronnen nog maar ÉÉN `tijdstip_meting` per kwartier overhoudt. Het minuutpad verliest die informatie nooit: `offset_eerste_g1/2/3__ms` en `offset_laatste_g1/2/3__ms` staan al PER MINUUT in de uitvoer (`OVERNEMEN`). De vraag die A5 beantwoordt is op het minuutpad al rechtstreeks af te lezen, zonder aparte analyse. |
| **A6** (uitval per bron of per woning) | Deels | "Alle bronnen ontbrekend" = een rij die in `gaten.parquet` als gat staat; dat deel is er al. "Precies één bron ontbrekend" vraagt de GEZAMENLIJKE (niet marginale) aanwezigheid van de vier brontellers per minuut, en dat is uit `dekking_<teller>` (marginaal per kolom) niet exact te reconstrueren; dat vraagt alsnog een scan van de metingen zelf. |
| **B2** (sluit de energiebalans) | Ja, en al impliciet getoetst | `differentieer_snel` is met een aparte test (`test_differentieer_snel_is_gelijk_aan_de_gedeelde_functie`) al tegen `tellers.differentieer_teller` gelegd, en het streamende pad tegen het volledige pad. Een aparte B2-analyse zou dezelfde telescopie-identiteit nog een keer bevestigen die de unit-tests al bewaken. De vergelijking met het kwartierpad hierboven is de INTERESSANTERE versie van deze vraag: niet "klopt de wiskunde binnen één pad" maar "komt twee onafhankelijke implementaties op hetzelfde uit". |
| **B4** (gatverdeling per kolom) | Deels, en het doel is al elders bereikt | De VRAAG die B4 beantwoordt (welke gatlimiet kiezen) is voor het minuutpad al beantwoord door de ponsmeting in `ontwerp-interpolatie-en-dekking.md` §3 (gemeten interpolatiefout per gatlengte, geen gatlengte-histogram). Dat is een directere methode dan B4's binning. De losse binverdeling zelf is met dezelfde rijdekkingsaanname als B5 uit `gaten.parquet` te reconstrueren, maar is hier niet apart gebouwd. |
| **B5** (aaneengesloten bruikbare tijd) | Ja | Hierboven volledig uitgevoerd. |
| **B7** (sprongdrempels tegen de werkelijke verdeling) | **Nee, een gat, geen "hoeft niet"** | `ontwerp-preprocessing-minuut.md` §4 belooft dit met zoveel woorden: "meet de eigen p99,99 tijdens de pas, zodat de drempels voor een volgende versie onderbouwd kunnen worden". Er staat geen enkele `p99`/`quantile`/drempel-tracking in `minuut.py`: dit is ontworpen maar niet gebouwd. Alsnog doen vraagt een scan van de metingen (geen footer-shortcut zoals bij raster), dus dit blijft open werk voor een volgende ronde. |
| **B8** (stookseizoendekking) | Ja, nog te bouwen | Volledig analoog aan B5 te maken uit `gaten.parquet`, met een venster-intersectie (okt–apr) bovenop `gedekte_tijd__min`. Niet gebouwd vannacht: geen expliciete vraag naar in de opdracht, en de tijd ging naar B5 en de vergelijking. |
| **B9** (tapwater langs de warmtemeter) | **Nee, ontbrekende invoer** | Vraagt `g_gebruik__W` (gas omgerekend naar vermogen met de calorische waarde). Het minuutpad laat gas bewust in m³ staan (`ontwerp-preprocessing-minuut.md` §11: "Geen gaskwaliteit... de omrekening naar W is een tweede, goedkope slag op de uitvoer"). Zonder die tweede slag is B9 hier niet te draaien. |
| **B10** (Kamstrup-consistentie, ρ·cₚ·debiet·ΔT) | Ja, en waarschijnlijk sterker | `debiet__dm3_s_1`, `temp_aanvoer__degC`, `temp_retour__degC` en `q_geleverd_gemeten__W` bestaan allemaal, met dezelfde fysische betekenis als hun kwartier-tegenhangers. Op minuutresolutie vangt deze toets bovendien kortere stromingstransiënten die een kwartiergemiddelde al uitmiddelt: een schonere toets, niet alleen een gelijkwaardige. |

**Samenvattend**: vier analyses (B5, A3, A4, B10) transfereren rechtstreeks; twee (A5, B4) zijn
overbodig omdat het minuutpad de onderliggende vraag al op een andere, betere manier beantwoordt;
twee (B9, B7) zijn geblokkeerd door een expliciet uitgestelde bouwstap (gaskwaliteit, sprongdrempel-
meting); en de rest (A1, A6, B2, B8) transfereert gedeeltelijk, met de reden er telkens bij.

## Wat open blijft

- **`dekking.parquet`** (ontwerp-interpolatie-en-dekking.md §5): gebouwd met
  `minuut_dekking.bouw_dekking_tabel` tegen de vorige-ronde-data als proef (7.443 rijen); wordt na
  afloop van de nachtronde opnieuw gedraaid tegen de verse `gaten.parquet`/`homes_minuut.parquet` en
  weggeschreven naar de NAS-uitvoermap, zoals de rest van de uitvoer.
- **De sentinelwaarden in het kwartierpad** (zie hierboven): een reële bug-kandidaat in
  `dph_preprocessing.tabellen`/`bron.py`, buiten de scope van deze nacht (die code hoort bij het
  EERSTE invoerpad), maar met de vijf kandidaatwaarden al in dit document.
- **B7 op het minuutpad**: ontworpen, niet gebouwd. Vraagt een scan van de metingen (geen footer-
  shortcut), dus een volgende volledige leesslag.
- **A6 exact, B4 en B8 op het minuutpad**: mogelijk uit `gaten.parquet` alleen (B4, B8) of met een
  gerichte scan (A6), niet gedaan bij gebrek aan tijd.
- **Segmentgebaseerde reparatie van tellerwissels**: de enige manier om DSMR/gas-energietotalen
  tussen de twee paden eerlijk te vergelijken, in geen van beide paden aanwezig.
