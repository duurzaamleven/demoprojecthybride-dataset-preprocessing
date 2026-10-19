# Ontwerp: overbrugbare gaten en aaneengesloten dekking

**Status 17-09-2026: de ponsmeting is gedaan, het advies staat, de implementatie nog niet.**

Dit document beantwoordt twee vragen die bij het minuutpad open bleven. Mag de preprocessing gaten
overbruggen, en zo ja tot welke lengte per kolom? En hoe meten we aaneengesloten bruikbare tijd op een
manier die iets zegt over de vraag die iemand wil beantwoorden?

De aanleiding is de werkwijze van NeedForHeat in het REDUCEDHEATCARB-project: daar wordt eerst
geïnterpoleerd met een grens per grootheid, en pas daarna de dekking gemeten. Bij ons gebeurt geen van
beide.

## 1. Wat NeedForHeat doet, en wat daarvan deugt

Uit `nfh-diagnosis/data/preprocessor.py`, drie stappen in deze volgorde.

**Interpoleren met een grens per grootheid.** `interpolate_time(default_limit__min=90,
property_limits={...}, interpolate__min=5)`: per kolom upsamplen naar de grootste gemene deler van het
bronsinterval, dan `.interpolate(method='time', limit=n)`, dan resamplen naar het doelrooster. Voor
tekst- en categoriekolommen geen interpolatie maar `.ffill(limit=n)`.

**Daarna pas dekking meten.** `calculate_covered_time(df, max_interval=90*60)` neemt per kolom de
tijdstippen met een waarde, berekent de verschillen, en telt alleen de verschillen tot 90 minuten op.

**En dat per onderzoeksvraag.** `mandatory_props` maakt een kolom `all_mandatory_props` die alleen
gevuld is waar álle vereiste grootheden tegelijk gevuld zijn. In RHC waren dat er twee: de
binnentemperatuur en de cumulatieve gasmeter.

De gekozen grenzen laten een duidelijke regel zien:

| klasse | grens | voorbeelden uit RHC |
|---|---|---|
| snel wisselende toestellstatus | 5 min | brandertoestand, tapwaterdebiet, aanvoer- en retourtemperatuur, ventilatortoerental |
| bewust nooit overbruggen | 0 | `temp_flow_ch__degC`, `temp_ret_ch__degC` |
| weer | 4 uur | buitentemperatuur, instraling, wind, luchtdruk, luchtvochtigheid |
| instellingen en quasi-constanten | 2 dagen | maximale aanvoertemperatuur, maximaal ketelvermogen, calorische gaswaarde |
| maandelijkse meterstanden | 32 dagen | `e_use_monthly_*_cum__kWh`, `g_use_monthly_cum__m3` |

**De regel is: de grens volgt de tijdschaal waarop de grootheid zelf verandert, niet de
bemonsteringsfrequentie.** Drie dingen daaruit zijn hier onverkort bruikbaar: de grens per kolom, het
onderscheid tussen interpoleren en vasthouden, en de dekking per combinatie van kolommen.

## 2. Wat wij anders moeten doen

**De tellers krijgen géén interpolatiegrens.** `differentieer_snel` deelt al door de *werkelijke*
verstreken tijd, dus een gat wordt overbrugd als één langer interval met het echte gemiddelde
vermogen. Dat is exact in energie en eerlijk over de tijdresolutie. Interpoleren zou daar een
tijdverdeling verzinnen die niet gemeten is; dat is een verslechtering en geen verbetering. De acht
cumulatieve tellers en hun afgeleiden vallen dus buiten dit ontwerp.

**En het resultaat gaat niet in de primaire uitvoer.** Zodra geïnterpoleerde waarden in `metingen/`
staan, erft elke gebruiker onze overbruggingskeuzes en kan hij ze niet ongedaan maken, want een
ingevulde waarde is niet te onderscheiden van een gemeten waarde. Dat is dezelfde onomkeerbaarheid
waarom §6 buiten-bereikwaarden op `NaN` zet in plaats van ze af te kappen, en het botst met de
werkafspraak dat deze repo geen analyse is.

Dat kan ook niet anders hoeven, want **alles om het downstream wél te doen staat er al in**: elke
minuut heeft `delta_t__s`, `gat_na__bool` en `uitval_na__bool`, en `gaten.parquet` geeft per gat
begin, eind, duur en soort. De informatie is er; alleen de keuze hoeft niet vooraf vast te liggen.

Wat er **wel** bij hoort is de dekkings- en reeksanalyse mét die grenzen, als kwaliteitsartefact naast
de data. Niet de geïnterpoleerde reeksen, wel het antwoord op "hoeveel aaneengesloten bruikbare tijd
houdt deze locatie over als je gaten tot k minuten overbrugt".

## 3. De ponsmeting

In plaats van de grens per kolom te beredeneren, is hij gemeten. Neem intacte stukken, pons er een gat
van k minuten in, interpoleer lineair tussen de twee buren die overblijven, en vergelijk met wat er
werkelijk stond.

Uitgevoerd 17-09-2026, in twee passen. De eerste pas op vijf locaties had twee beperkingen die het
verloop over *k* vertroebelden; de tweede pas heeft ze niet en is de maatgevende meting. Wat hieronder
staat is de tweede pas: **twaalf locaties** uit het 35e tot 95e percentiel naar bestandsgrootte,
10,2 miljoen bruikbare posities, waarvan er 36.000 per kolom getrokken zijn met seed 42.

**Dezelfde posities voor elke k.** Een positie telt alleen mee als het venster voor het *grootste* gat
volledig gevuld is, dus elke *k* bemonstert exact dezelfde plekken. Daarmee is het verloop over *k*
een effect en geen steekproefruis. In de eerste pas was dat niet zo, en daar was de fout bij *k*=2
soms kleiner dan bij *k*=1; die omkering is nu weg en alle curves lopen monotoon op. De prijs van deze
keuze hoort erbij: alleen posities binnen stukken van minstens 62 gevulde minuten doen mee, dus de
uitkomst geldt voor goed gedekte stukken. Dat is precies het regime waarin je zou willen overbruggen,
maar het is geen uitspraak over slecht gedekte locaties.

**De mediaan is onbruikbaar en dat is zelf een bevinding.** Voor `q_geleverd_gemeten__W` en
`debiet__dm3_s_1` is de mediane fout bij élke gatlengte 0,000. Die grootheden staan het grootste deel
van de tijd stil, en dan is lineair overbruggen exact. Zodra het toestel draait is het mis. Voor
schakelende grootheden is de p95 dus de maat, niet de mediaan.

**p95 van de absolute interpolatiefout, per gatlengte in minuten:**

| kolom | eenheid | IQR | k=1 | k=2 | k=5 | k=10 | k=15 | k=30 | k=60 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `rv_binnen__0` | fractie | 0,119 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,01 |
| `temp_binnen__degC` | °C | 2,94 | 0,05 | 0,05 | 0,05 | 0,05 | 0,06 | 0,08 | 0,11 |
| `debiet__dm3_s_1` | dm³/s | 0,146 | 0,01 | 0,02 | 0,04 | 0,06 | 0,07 | 0,09 | 0,13 |
| `temp_retour__degC` | °C | 6,40 | 0,20 | 0,33 | 0,71 | 1,18 | 1,55 | 2,54 | 3,91 |
| `temp_aanvoer__degC` | °C | 8,35 | 0,52 | 0,80 | 1,47 | 2,32 | 2,80 | 4,08 | 5,91 |
| `p_warmtepomp_gemeten__W` | W | 144 | 40 | 68 | 135 | 235 | 289 | 420 | 542 |
| `q_geleverd_gemeten__W` | W | 1365 | 271 | 500 | 958 | 1464 | 1774 | 2425 | 2985 |

Absolute fouten zijn per kolom niet vergelijkbaar, dus dezelfde tabel **als percentage van de eigen
spreiding** van de kolom. Dat maakt de keuze van een grens een keuze van één drempel:

| kolom | k=1 | k=2 | k=3 | k=5 | k=10 | k=15 | k=30 | k=60 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `temp_binnen__degC` | 1,7 % | 1,7 % | 1,7 % | 1,7 % | 1,9 % | 2,1 % | 2,7 % | 3,7 % |
| `rv_binnen__0` | 0,6 % | 0,8 % | 0,8 % | 1,1 % | 1,6 % | 2,1 % | 3,3 % | 5,6 % |
| `temp_retour__degC` | 3,1 % | 5,1 % | 7,1 % | 11,0 % | 18,5 % | 24,2 % | 39,8 % | 61,1 % |
| `temp_aanvoer__degC` | 6,2 % | 9,6 % | 12,6 % | 17,7 % | 27,8 % | 33,5 % | 48,9 % | 70,8 % |
| `debiet__dm3_s_1` | 6,6 % | 14,3 % | 20,7 % | 29,4 % | 39,6 % | 46,7 % | 64,9 % | 87,6 % |
| `q_geleverd_gemeten__W` | 19,8 % | 36,6 % | 50,4 % | 70,2 % | 107,3 % | 130,0 % | 177,7 % | 218,8 % |
| `p_warmtepomp_gemeten__W` | 28,0 % | 47,2 % | 65,4 % | 94,4 % | 164,0 % | 201,4 % | 292,4 % | 377,6 % |

De spreiding tussen kolommen is bijna twee ordes: bij een gat van één minuut kost het binnenklimaat
1,7 % van zijn eigen spreiding en het warmtepompvermogen 28 %.

## 4. De grenzen

De grens ligt waar de interpolatiefout te groot wordt ten opzichte van wat de grootheid zelf doet. Met
de tabel in procenten is dat één drempel in plaats van zeven oordelen. Bij **10 % van de eigen
spreiding**:

| kolom | grens | p95 daar | en bij één stap ruimer |
|---|---:|---:|---:|
| `temp_binnen__degC` | **60 min** | 3,7 % | ruimer is verdedigbaar |
| `rv_binnen__0` | **60 min** | 5,6 % | ruimer is verdedigbaar |
| `temp_retour__degC` | **3 min** | 7,1 % | 11,0 % bij 5 min |
| `temp_aanvoer__degC` | **2 min** | 9,6 % | 12,6 % bij 3 min |
| `debiet__dm3_s_1` | **1 min** | 6,6 % | 14,3 % bij 2 min |
| `q_geleverd_gemeten__W` | **0, niet overbruggen** | 19,8 % bij 1 min | |
| `p_warmtepomp_gemeten__W` | **0, niet overbruggen** | 28,0 % bij 1 min | |
| de acht tellers en hun afgeleiden | **n.v.t.** | | zie §2 |

De drempel van 10 % is een keuze en hoort als zodanig zichtbaar te blijven. Bij 5 % gaan
`temp_retour__degC` naar 1 minuut en `temp_aanvoer__degC` en `debiet__dm3_s_1` naar nul; bij 20 %
gaan ze naar respectievelijk 10, 5 en 2 minuten en mag `q_geleverd_gemeten__W` één minuut. De volgorde
van de kolommen verandert daarbij niet, en dat is het belangrijkste: welke drempel je ook kiest, het
ruimteklimaat verdraagt een uur en de warmtekant verdraagt niets.

**Twee kolommen op nul**, en dat is geen voorzichtigheid maar een meting: bij `p_warmtepomp_gemeten__W`
is de fout na één minuut 40 W, en dat is ruim meer dan de kwantiseringsstap van 14,6 W die de
tellerafgeleide tegenhanger sowieso al heeft (§6.6a van het geheugenontwerp). Overbruggen voegt daar
meer onzekerheid toe dan de data zelf heeft. Dat is dezelfde keuze die RHC voor `temp_flow_ch__degC`
maakte.

⚠️ **De eerste pas was op vier van de zeven kolommen te optimistisch.** Die gaf `temp_retour__degC`
10 minuten (nu 3), `temp_aanvoer__degC` 5 (nu 2), `p_warmtepomp_gemeten__W` 2 (nu 0) en
`debiet__dm3_s_1` 5 (nu 1). Oorzaak was de steekproefopzet, niet de data. Dat is het argument om zo'n
grens te meten en niet te beredeneren, en om de meetopzet zelf te controleren voordat je er een getal
uit overneemt.

**Drie dingen die de meting niet beslist.** Interpoleren of vasthouden is een eigenschap van de
grootheid en niet van de fout; de vlaggen en `warmtemeter_bereik__cat` horen vastgehouden te worden,
niet geïnterpoleerd. De analysevraag mag de grens verder verlagen: een ontdooicyclus duurt acht
minuten, dus daar is elke overbrugging boven een paar minuten fataal. En de grens hoort daarom een
**parameter** te zijn met een gemeten default, geen constante.

## 5. Dekking meten, en waarvoor

Na het overbruggen komt de reeksanalyse, en die beantwoordt een andere vraag dan dekking. Twee
locaties met allebei 95 % dekking verschillen wezenlijk als de ene één blok van drie weken mist en de
andere elke twintig minuten één minuut. Voor een jaartotaal maakt dat niets uit; voor een
ontdooicyclus van acht minuten, een warmtepomppakket van een half uur of een opwarmcurve van enkele
uren wel.

Onze eigen gatentabel laat zien waarom dit loont: van de 153.767 gaten is **71,4 % korter dan vijf
minuten**, en die dragen samen **0,4 %** van alle ontbrekende tijd. Heel veel speldenprikken die
nauwelijks data kosten maar overal reeksen doorknippen.

Voorstel voor het artefact, naast de bestaande uitvoer:

- `dekking.parquet`: per locatie per kolom per drempel *k* de aaneengesloten bruikbare tijd, met de
  drempels uit §4 plus 0 als referentie zonder overbrugging;
- daarin ook de **combinaties** die onderzoeksvragen nodig hebben, in de geest van
  `mandatory_props`. Voor een COP-analyse is dat `p_warmtepomp_gemeten__W` en `q_geleverd_gemeten__W`
  tegelijk, plus de eis dat de locatie geen dood warmtepompkanaal heeft (39 van de 174, §2 van
  `kwaliteit.md`);
- een paragraaf in `kwaliteit.md` met de verdeling over de locaties.

Dekking per losse kolom blijft misleidend. Wat telt is de doorsnede van wat een vraag nodig heeft.

## 6. Wat er moet gebeuren

1. ✅ **Gedaan**: de ponsmeting is overgedaan met dezelfde posities voor alle *k* en een willekeurige
   trekking over de hele reeks, op twaalf locaties. De grenzen in §4 staan daarmee vast.
2. **De grenzen vastleggen als parameter**, met de gemeten waarde als default en de herkomst erbij.
3. **`dekking.parquet` bouwen** volgens §5, inclusief de combinaties.
4. **`kwaliteit.md` uitbreiden** met de dekkingsverdeling.
5. **Niets van dit alles in `metingen/`**, om de reden in §2.

Punt 1 is een halve dag en bepaalt de rest; punt 3 en 4 zijn goedkoop omdat ze volledig uit
`gaten.parquet` kunnen, zonder de metingen aan te raken.
