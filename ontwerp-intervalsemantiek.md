# Ontwerp: intervalsemantiek en temporele interpolatie

**Status:** ontwerp, nog niet geïmplementeerd. Opgesteld 05-09-2026.

**Aanleiding.** De opdrachtgever heeft één regel gesteld die de hele output raakt: *elke waarde die
bij een `tijdstip_start` staat, heeft dezelfde betekenis — het gemiddelde over dat interval — tenzij
dat echt niet kan, en dan moet het goed gedocumenteerd zijn.*

Dat is dezelfde keuze die de IM3-zusterrepo maakte (`ontwerp-intervalsemantiek.md` daar), en om
dezelfde reden: een kolomnaam die niet zegt waar in het interval de waarde hoort, is een stille fout
die pas maanden later in een conclusie opduikt.

Deze repo voldoet op **drie plekken** niet aan die regel. Alle drie zijn hieronder gemeten op de
proefrun van vijf woningen, niet beredeneerd. Twee ervan zijn echte fouten in de uitvoer; de derde
is een ontwerpkeuze die anders moet.

---

## 1. De regel, expliciet

| begrip | betekenis |
|---|---|
| `tijdstip_start` | het **begin** van het interval, tz-aware `Europe/Amsterdam` (intern UTC) |
| intervalduur | 900 s, vast (anders dan IM3, dat vier intervaltypen kent) |
| de waarde erbij | het **tijdgewogen gemiddelde** over `[tijdstip_start, tijdstip_start + 900 s)` |

`tijdstip_start` als begin-labeling is niet vrij gekozen: het is de default van pandas `resample`,
de conventie van ENTSO-E/IEC 62325, en wat de afnemende repo impliciet
aanneemt. Zie de onderbouwing in de IM3-zusterrepo; die hoeft hier niet herhaald te worden.

Er zijn drie soorten waarden die géén intervalgemiddelde kunnen zijn. Voor elk daarvan geldt: het
staat in de kolomnaam, en het staat in `docs/variable-dictionary.md`. Zie §6.

---

## 2. Bevinding A: de tellervermogens staan een kwartier te laat

`tellers.differentieer_teller()` gebruikt `groupby(...).diff()`, dus een **achterwaarts** verschil.
De waarde op rij *Q* is `teller(Q) − teller(Q−1)`, gedeeld door de werkelijke tijd ertussen. Die
waarde beschrijft dus het interval `[Q−1, Q)` — maar staat in een kolom die `tijdstip_start` heet en
dus `[Q, Q+1)` belooft. Alle vijf de vermogens in `derived` staan één kwartier te laat.

### Hoe dit gemeten is

Een correlatie tussen tellervermogen en de momentane steekproef op dezelfde rij onderscheidt de twee
hypothesen niet: de steekproef ligt op de kwartier**grens** en correleert daardoor ongeveer even
goed met het kwartier ervoor als erna (gemeten: 0,799 tegen 0,792 voor `q_geleverd`). Dat is precies
wat je verwacht en het zegt niets.

Wel onderscheidend is de trapeziumbenadering. Het gemiddelde over een interval is bij benadering het
gemiddelde van de twee randsteekproeven. Correleer het tellervermogen op rij *Q* dus met
`(meting(Q−1) + meting(Q))/2` — de hypothese "eind-gelabeld" — en met `(meting(Q) + meting(Q+1))/2`
— de hypothese "begin-gelabeld":

**Per woning**, niet gepoold: pooling over woningen laat één kapotte teller de hele uitkomst
bepalen (§5). Na het wegknippen van fysisch onmogelijke waarden (|P| > 50 kW):

| woning | `q_geleverd__W` | | `p_ketel__W` | | `p_warmtepomp__W` | |
|---|---:|---:|---:|---:|---:|---:|
| | eind | begin | eind | begin | eind | begin |
| `-B51sQOp` | **0,919** | 0,791 | **0,803** | 0,652 | **0,969** | 0,939 |
| `-ORiFQC6` | **0,881** | 0,605 | **0,750** | 0,642 | **0,916** | 0,691 |
| `-uFUg8jU` | **0,932** | 0,882 | **0,537** | 0,330 | **0,974** | 0,942 |
| `0RQyG6WX` | **0,962** | 0,952 | **0,910** | 0,903 | **0,967** | 0,955 |
| `0XvCtU3v` | **−0,076** | −0,105 | **0,853** | 0,744 | **0,275** | 0,243 |

**Vijftien van de vijftien vergelijkingen wijzen dezelfde kant op.** Bij `0RQyG6WX` is het verschil
klein (0,962 tegen 0,952) omdat die woning traag en gelijkmatig draait, waardoor de twee
randgemiddelden weinig verschillen; de richting is er niet anders om.

### De correctie

Voorwaarts verschillen in plaats van achterwaarts: per woning `diff().shift(-1)`, of gelijkwaardig
`teller(Q+1) − teller(Q)`. De laatste rij van elke woning wordt dan NaN in plaats van de eerste, wat
correct is: van het laatste kwartier is het eindpunt niet gemeten.

`delta_t__s` schuift mee. De redenering uit de module-docstring — dat een ontbrekend kwartier de
werkelijke deler moet opleveren en niet 900 s — blijft ongewijzigd geldig; alleen het anker
verschuift.

### Eén restfout die blijft, en waarom die klein is

De tellerstand wordt niet exact op de kwartiergrens afgelezen maar mediaan 2 s erna (p95 8 s, zie
`docs/data-quality.md` §3). Het interval waarover we delen is dus niet precies `[Q, Q+1)` maar
`[Q+2s, Q+1+2s)`. Die verschuiving is al zichtbaar in `scheefheid__s` en wordt niet weggerekend: dat
zou een correctie zijn op iets dat we niet weten. Bij een mediaan van 2 s op 900 s is het 0,2 % van
het interval.

---

## 3. Bevinding B: het weer staat een uur te laat

De weerkoppeling neemt de KNMI-uurwaarde van het uur waarin het kwartier valt. Maar de KNMI-uurreeks
is **eind-gelabeld**: `HH=1` is bij het KNMI het uur van 00:00 tot 01:00. Wordt dat tijdstip als
`tijdstip_start` overgenomen, dan krijgt elke meting het weer van het uur ervóór.

### Hoe dit gemeten is

De zon is hier de scherpste toetssteen, want die kent geen thermische naijling. Gemiddelde
`ghi__kWh_m_2` per UTC-uur over de junimaanden in `weer.parquet`:

```
04:00  0.009   08:00  0.425   12:00  0.704  <-- maximum
05:00  0.070   09:00  0.540   13:00  0.677
06:00  0.175   10:00  0.627   14:00  0.625
07:00  0.295   11:00  0.678   16:00  0.440
```

Het maximum ligt op label 12, en het profiel is symmetrisch rond 12,0–12,5. De ware zonnemiddag in
Nederland ligt eind juni rond 11:40 UTC (13:40 lokaal). Onder begin-labeling zou de bak `[11, 12)`
dus het maximum moeten hebben. Het staat één uur later. Onder eind-labeling ís label 12 het interval
`[11, 12)`, en dan klopt het precies.

De eerste bak boven nul bevestigt het: label 04 terwijl de zon eind juni om 03:20 UTC opkomt.

### Waarom dit ertoe doet

Het raakt `temp_buiten__degC`, `wind__m_s_1` en `ghi`. De typische fout op de buitentemperatuur is
de verandering per uur: **mediaan 0,50 K, p90 1,60 K, p99 3,10 K, max 8,40 K**. In de
ochtendopwarming (05–09 UTC) is de mediane uurverandering 0,80 K.

Elke uitspraak van de vorm "COP als functie van de buitentemperatuur" — de kernvraag van dit
project — wordt hierdoor stelselmatig scheefgetrokken, en niet willekeurig: de fout heeft dezelfde
dagcyclus als het signaal.

### De correctie, en wat die omgooit

De omzetting zelf is één regel: het KNMI-uurstempel min 3600 s. Maar §6 van
`ontwerp-preprocessing.md` besloot expliciet **geen eigen weer-ingest** te doen, met als argument
dat de vraag "klopt dat station" hier minder scherp is dan bij IM3. Die redenering blijft staan voor
de *stationskeuze*, maar niet voor de *labeling*: dat is precies een aanname over de bron die we nu
tegen de bron zelf moeten toetsen, en dat kan alleen met een onafhankelijke KNMI-download.

IM3 heeft die ingest al (`im3_preprocessing.weer`) en vond er precies dit mee: een uurverschuiving
die, eenmaal gecorrigeerd, 24 van de 27 stations op exact nul verschil bracht — plus een verwisseld
station. Voorstel: **die code hergebruiken, niet herschrijven**, en de vergelijking als eenmalige
controle draaien in plaats van als vaste stap in de pijplijn.

### Bewezen op 05-09-2026

De controle is gedraaid. Met `dutch_weather.knmi.fetch_hourly_dutch_weather_data` (de route die de
IM3-zusterrepo gebruikt) is juni 2023 onafhankelijk opgehaald en per station naast `weer.parquet`
gelegd, bij drie verschuivingen. Mediane absolute afwijking op `temp_buiten__degC`:

| verschuiving van onze reeks | mediane afwijking |
|---|---:|
| geen | 0,6 – 0,9 K |
| één uur later | 1,0 – 1,6 K |
| **één uur eerder** | **3,8·10⁻⁷ K** |

Die laatste waarde is de afrondgrens van float32: **exact nul, op alle 23 vergelijkbare stations**.
De reeks staat dus precies één uur te laat, en dat is geen gevolgtrekking meer maar een meting.

Twee bijvangsten. **Twee van de 25 stations (242 en 340) komen niet voor in de actuele
KNMI-uurgegevens**, dezelfde situatie die IM3 bij 210 en 340 vond; voor die twee is geen
onafhankelijke controle mogelijk en dat moet bij elke uitspraak over die woningen vermeld worden. En
**station 240 (Schiphol) klopt hier wél**: bij IM3 bleek de meegeleverde reeks voor dat station de
gegevens van De Bilt te bevatten, hier komt het exact uit tegen Schiphol zelf. Dat probleem is dus
IM3-specifiek en herhaalt zich niet in DPH — het scheelt een punt in de mail aan KITE.

### Nog een keuze die hierbij hoort

Als beide kanten begin-gelabeld zijn, krijgen alle vier de kwartieren in een uur dezelfde
weerwaarde: een trapfunctie. Dat is niet wat de regel uit §1 vraagt — het gemiddelde over een
kwartier is niet het gemiddelde over het hele uur. Het weer is een langzaam signaal en hoort dus
onder de interpolatie van §4 te vallen. Dat is dezelfde openstaande vraag die de IM3-zusterrepo
bewust niet beslecht heeft; hier wordt hij wél beslecht, omdat de regel van de opdrachtgever hem
beslecht.

---

## 4. Bevinding C: de `_meting`-kolommen zijn steekproeven op de kwartiergrens

`ontwerp-preprocessing.md` §2.2 stelt terecht vast dat de momentane kolommen geen
intervalgemiddelden zijn, en lost dat op met een naamconventie: `_meting` in de naam. Dat is
eerlijk, maar het laat een rij achter waarin sommige kolommen het interval beschrijven en andere één
moment aan de rand ervan. Dat is precies wat de regel uit §1 wil voorkomen.

Voor een deel van die kolommen ís een intervalgemiddelde wél te maken. Daarvoor is de methode van
NeedForHeat de aangewezen route.

### 4.1 Hoe NeedForHeat het doet

`Preprocessor.interpolate_time()` in
[`needforheat-diagnosis-software`](https://github.com/energietransitie/needforheat-diagnosis-software)
(Apache 2.0) doet per woning, per bron en per kolom drie stappen:

1. **Opwaarts bemonsteren** naar een fijn raster: `gcd(modaal interval, doelinterval, gatlimiet)`,
   minimaal 1 minuut. Op dat raster staat elke oorspronkelijke meting nog op zijn eigen plek.
2. **Interpoleren met een gatlimiet**: `.interpolate(method="time", limit=n)`. Tijdgewogen lineair,
   maar alleen over gaten korter dan de limiet (default 90 minuten, per grootheid instelbaar).
   Langere uitval blijft NaN — er wordt niets overbrugd wat niet gemeten is.
3. **Neerwaarts bemonsteren met `.mean()`** naar het doelinterval.

Stap 3 is waar het om gaat. Het gemiddelde over het fijne raster ís het intervalgemiddelde van het
stuksgewijs lineaire signaal. Dat is geen benadering die je erbij verzint: het is de definitie van
"gemiddelde over het interval", gegeven de aanname dat het signaal tussen twee metingen lineair
loopt.

Voor categorische en booleaanse kolommen gebruikt NeedForHeat `.first()` + `ffill(limit)` +
`.first()` in plaats van een gemiddelde — een gemiddelde van een categorie bestaat niet. Die
uitzondering nemen we over.

### 4.2 Wat dat hier concreet betekent

Gemeten op de proefrun: het modale interval tussen twee metingen is **900 s** (26,8 % exact 900 s,
mediaan 901 s — de rest is jitter). De export is dus native kwartier, niet fijner.

Met doelinterval 15 minuten zou `gcd(900, 900, 5400) = 900 s` opleveren, en dan is stap 3 een no-op.
Het opwaartse raster moet dus **expliciet op 1 minuut** worden gezet in plaats van uit de gcd te
volgen. Dan geldt voor twee opeenvolgende randmetingen:

> gemiddelde over `[Q, Q+1)` = (meting(Q) + meting(Q+1)) / 2

precies de trapeziumregel die in §2 als toetssteen diende. Dat is meteen de goedkope implementatie:
voor het geval "één meting per kwartier" is het middelen van twee randwaarden, en pas bij
ontbrekende kwartieren is het echte raster nodig. Beide moeten hetzelfde opleveren; dat is een test
waard.

### 4.3 Welke kolommen wel, en welke uitdrukkelijk niet

De scheidslijn is niet "momentaan of niet" maar **hoe snel de grootheid beweegt ten opzichte van een
kwartier**. Lineair interpoleren tussen twee randwaarden is goed voor een traag signaal en fout voor
een signaal dat binnen het kwartier aan- en uitschakelt.

**Wel interpoleren — trage grootheden.** Hier is de trapeziumbenadering verdedigbaar en levert een
echt intervalgemiddelde op:

| kolom nu | wordt | waarom traag |
|---|---|---|
| `temp_binnen_meting__degC` | `temp_binnen__degC` | thermische massa van een woning; een kamer verandert geen graden in een kwartier |
| `rv_binnen_meting__0` | `rv_binnen__0` | idem |
| `temp_aanvoer_meting__degC` | `temp_aanvoer__degC` | **alleen onder voorwaarden**, zie §4.5 |
| `temp_retour_meting__degC` | `temp_retour__degC` | idem |
| `u_L1..L3_meting__V` | `u_L1..L3__V` | netspanning beweegt binnen enkele procenten |
| `temp_buiten__degC`, `wind__m_s_1`, `ghi` | zelfde naam | uurreeks naar kwartier, §3 |

De nieuwe namen zijn geen cosmetica: `temp_binnen__degC` is precies de naam die IM3 gebruikt, en het
wegvallen van `_meting` is het signaal dat de betekenis veranderd is. Een kolom die zijn naam houdt
terwijl zijn betekenis verandert, is de gevaarlijkste variant.

**Aanvoer- en retourtemperatuur zijn een geval apart.** Die zijn traag zolang de installatie
draait, maar springen bij het aan- en afslaan, en ze kunnen bovendien besmet zijn met
warmtapwaterbereiding. REDUCEDHEATCARB heeft daar een aparte voorbewerking voor ontwikkeld en die
verdient een eigen paragraaf: zie **§4.5**. De korte versie: interpoleren mag hier alleen onder twee
voorwaarden, en of de eerste voorwaarde geldt verschilt per woning.

**Niet interpoleren — snelle grootheden.** Hier is lineair interpoleren aantoonbaar fout, én
onnodig, want de teller geeft het echte intervalgemiddelde al:

| kolom | blijft | waarom |
|---|---|---|
| `p_warmtepomp_meting__W` | steekproef | schakelt binnen het kwartier; `p_warmtepomp__W` uit de teller is het echte gemiddelde |
| `p_ketel_meting__W` | steekproef | idem, tegenover `p_ketel__W` |
| `q_geleverd_meting__W` | steekproef | idem, tegenover `q_geleverd__W` |
| `p_import/export_L1..L3_meting__W`, `i_L1..L3_meting__A` | steekproef | huishoudelijke belasting is de snelste reeks in de set |
| `debiet_meting__dm3_s_1` | steekproef | volgt de pomp, dus binair van karakter |

Deze houden `_meting` in de naam. Ze blijven waardevol voor bedrijfspuntanalyse — bij welke
aanvoertemperatuur en welk deellastpunt draaide de warmtepomp — en dat is precies waarvoor ze
bedoeld zijn.

Dit is de "tenzij het echt niet kan, en dan goed documenteren" uit de opdracht, met per kolom de
reden erbij in plaats van als algemene disclaimer.

### 4.4 Wat de gatlimiet moet zijn

NeedForHeat kiest 90 minuten als default en laat 'm per grootheid overrulen. Voor DPH is dat een
keuze die met de data genomen moet worden en niet ervóór: de verdeling van de gaten per grootheid
staat nog niet in `docs/data-quality.md`. Dat is analyse B4 in het programma
(`ontwerp-preprocessing.md` §8). Tot die er is, 90 minuten overnemen en het als aanname markeren,
net als bij de sprongdrempels.

Per kwartier komt er één kolom bij die vastlegt hoeveel van het interval werkelijk gemeten is —
voorstel `dekking__0`, tussen 0 en 1. Zonder die kolom is een geïnterpoleerde waarde niet van een
gemeten waarde te onderscheiden, en dat is precies het soort stille verlies dat deze repo wil
vermijden.

### 4.5 Aanvoer- en retourtemperatuur: wat REDUCEDHEATCARB hierover geleerd heeft

NeedForHeat heeft sinds het REDUCEDHEATCARB-project een **extra voorbewerking** voor precies deze
twee grootheden. De reden is dat warmtapwaterbereiding de gemeten aanvoer- en retourtemperatuur
vervuilt, en dat het van de **plaats van de sensor** afhangt of dat gebeurt. Dat is geen detail: het
bepaalt of die voorbewerking hier überhaupt nodig is.

#### Wat RHC doet, en waarom

In RHC komen `T_flow` en `T_ret` uit de **ketel zelf** (Remeha, via de ketelbus). Die sensoren zitten
vóór de omschakelklep tussen cv en tapwater, dus elke tapbeurt loopt er langs. Deliverable D3.4
(slide 17–21) laat zien wat dat aanricht en geeft de oplossing als pseudocode:

> Selecteer reeksen zonder interferentie van tapwaterbereiding:
> - een reeks begint als de ketelstatus 'brandt voor cv' aangeeft;
> - een reeks mag napompen en zelfs pompstops bevatten;
> - een reeks eindigt zodra er bewijs is van tapwaterbereiding:
>   - ketelstatus 'brandt voor tapwater', **of**
>   - pompsnelheid op 100 % terwijl de ketel niet voor cv brandt, **of**
>   - een snelle stijging van aanvoer- of retourtemperatuur (> 5 K/min).
> - Verwijder reeksen korter dan D minuten (D = 10).
> - Verwijder de eerste F en de laatste L minuten van elke reeks (F = 4, L = 0).
> - Interpoleer gaten kleiner dan G minuten lineair (G = 5).

Twee dingen daarin zijn slimmer dan ze op het eerste gezicht lijken. Ten eerste stopt de
besmetting **niet** wanneer de kraan dichtgaat: het warme water blijft in de wisselaar en de leidingen
staan, dus de reeks blijft ongeldig tot de ketel aantoonbaar weer voor cv brandt. Ten tweede zijn er
drie onafhankelijke detectoren, omdat geen van de drie alleen genoeg is — D3.4 slide 18 laat
expliciet gevallen zien waarin alleen de temperatuursprong het begin verraadt, en een geval waarin
alleen de pompsnelheid dat doet.

De implementatie staat in `Preprocessor.add_filtered_flow_ret_ch_temperatures` en
`add_clipped_flow_return_temps` in `needforheat-diagnosis-software` (Apache 2.0). De defaults in de
code (D = 5, F = 2, L = 2) wijken af van de gepubliceerde waarden; die van D3.4 zijn hier aangehouden.

Uit D1.2 hoort daar nog een drempel bij: bij het afleiden van het debiet uit warmte en ΔT bleek
`ΔT < 12 K` de uitkomst onbruikbaar te maken, omdat een klein temperatuurverschil in de noemer
staat. Dat speelt hier niet — de Kamstrup meet het debiet zelf — maar het is wel de reden voor de
consistentiecheck hieronder.

#### Zit die besmetting hier ook? Grotendeels niet, en het verschilt per woning

De DPH-meetset is anders. Aanvoer en retour komen uit een **Kamstrup Multical 403**, met de
temperatuursensoren op de aan- en afvoerleiding van het warmteafgiftecircuit (eindrapportage,
bijlage 8). Het rapport noemt het "de warmteafgifte van de hybride ketel" en "de hoeveelheid warmte
die de woning binnenkwam" — dat suggereert ná de tapwaterafsplitsing, maar het staat er niet
expliciet.

Het is te toetsen. Als tapwater langs de warmtemeter loopt, moet dat in de **zomer** zichtbaar zijn:
dan is er geen ruimteverwarming, en elke warmtelevering die overblijft is tapwater. Gemeten op
juni–augustus van de proefrun:

| woning | zomerkwartieren met warmte > 200 W | daarvan met gas > 500 W | basiskans gas > 500 W | corr(warmte, wp-elektra) | aanvoer > 50 °C |
|---|---:|---:|---:|---:|---:|
| `-B51sQOp` | 0,0 % | — | 3,7 % | — | — |
| `-ORiFQC6` | 5,5 % | **53,2 %** | 3,2 % | 0,961 | 12,4 % |
| `-uFUg8jU` | 7,3 % | 42,2 % | 22,0 % | 0,641 | 0,0 % |
| `0RQyG6WX` | 0,5 % | 0,0 % | 2,8 % | 0,961 | 0,0 % |
| `0XvCtU3v` | 0,0 % | — | 4,8 % | — | — |

Over alle vijf samen: in de zomer draait het gas in 9,0 % van de kwartieren (mediaan 2,0 kW als het
draait) — dat is de tapwater- en kookbasislast. De warmtemeter ziet in slechts 3,0 % van de
kwartieren iets, en dát signaal correleert met warmtepompelektriciteit (0,88) en nauwelijks met gas
(0,20). **Het overgrote deel van het zomerse gasverbruik gaat dus langs de warmtemeter heen.**

Maar niet overal. Bij `-ORiFQC6` valt 53 % van de warmtelevering samen met gasverbruik, tegen een
basiskans van 3,2 % — een verrijking van zeventien keer — en 12 % van die kwartieren heeft een
aanvoertemperatuur boven 50 °C. Daar gebeurt iets dat op tapwater lijkt, of de ketel voedt daar in
de zomer het cv-circuit. Bij `-uFUg8jU` is de verrijking veel zwakker (42 % tegen een basiskans van
22 %) en de correlatie met de warmtepomp blijft hoog.

**Conclusie: het hangt van de installatie af, precies zoals RHC vond.** Een globale aan/uit-knop voor
tapwaterfiltering is hier dus fout. Wat nodig is, is een **diagnose per woning** met dit
zomercriterium, met een vlag in `homes` als uitkomst. Die diagnose is zelf een analyse en staat als
B9 in `ontwerp-preprocessing.md` §8.

#### En dan het echte probleem: op kwartierdata is die filtering niet uit te voeren

Alle parameters van RHC liggen **onder** het kwartier: een detectiedrempel van 5 K/**min**, reeksen
van minimaal 10 minuten, de eerste 4 minuten eraf, gaten tot 5 minuten interpoleren. Op een raster
van 15 minuten is geen van die vier berekenbaar. Een tapbeurt van zeven minuten is in kwartierdata
één punt, en dat punt verraadt zichzelf niet.

Dat kan hier ook niet met een truc worden opgelost: de vier detectoren van RHC leunen op
ketelstatussen (`brandt voor cv`, `brandt voor tapwater`) en pompsnelheid, en die staan geen van
alle in de DPH-export. Wat er wél is — een temperatuursprong — is precies de detector die resolutie
nodig heeft.

**De data bestaat wel.** De eindrapportage (bijlage 8) vermeldt dat alle sensoren **elke 10
seconden** naar het platform sturen. De CSV-export is dus met een factor 90 uitgedund. Dit is
daarmee de tweede, onafhankelijke reden voor de aanvraag bij KITE om data op het fijnste
meetinterval — naast het scheiden van ontdooiverlies en pendelen. Bij 10 seconden is de RHC-methode
één op één toepasbaar, drempels en al.

#### Wat dit betekent voor het voorstel in §4.3

Het voorstel daar — aanvoer en retour wél interpoleren, mits de installatie het hele kwartier
draaide — moet strenger. Op kwartierdata geldt:

1. **Interpoleer alleen als de woning volgens de diagnose hierboven geen tapwater door de
   warmtemeter heeft.** Bij de andere woningen blijven `temp_aanvoer_meting__degC` en
   `temp_retour_meting__degC` steekproeven, met de reden erbij.
2. **En ook dan alleen over kwartieren waar warmte geleverd werd in zowel `[Q−1, Q)` als
   `[Q, Q+1)`.** Anders interpoleer je over een aanslag- of afslagmoment heen.
3. Neem RHC's clipping **niet** over. Zij is op minuutresolutie gedefinieerd en heeft op kwartierdata
   geen betekenis; hem toch toepassen met "vertaalde" parameters zou de methode een precisie
   toedichten die de data niet heeft.

#### Eén controle die RHC niet kon doen, en wij wel

De Kamstrup levert warmtevermogen, debiet én beide temperaturen. Daarmee is
`q = ρ · c_p · V̇ · ΔT` een **interne consistentiecheck** op de meter zelf: rekent de meter na wat
hij zegt te meten? RHC moest het debiet juist uit de warmte afleiden en had die luxe niet — vandaar
hun ΔT > 12 K-drempel. Waar de check niet sluit, is dat een aanwijzing voor een sensorfout of voor
een debiet dat buiten het meetbereik van de meter valt. Dat is analyse B10.
### 4.6 Als het systeem uit staat, is de aanvoertemperatuur geen aanvoertemperatuur

Dit staat in geen van de REDUCEDHEATCARB-stukken en is hier gemeten. Het raakt tweederde van alle
rijen, en het maakt het voorstel uit §4.3 op één punt strenger.

Gemeten op de proefrun, gesplitst op of de warmtemeter noemenswaardige warmte registreert:

| | systeem aan (`q_geleverd__W` > 200) | systeem uit |
|---|---:|---:|
| aantal kwartieren | 86.135 (34 %) | 164.164 (**66 %**) |
| `temp_aanvoer_meting__degC`, mediaan | 32,7 °C | 25,0 °C |
| ΔT aanvoer − retour, mediaan | 3,75 K | **0,05 K** |
| `debiet_meting__dm3_s_1` exact 0 | 2,4 % | **71,7 %** |
| \|aanvoer − binnentemperatuur\|, mediaan | 14,29 K | 2,90 K |

Een ΔT van 0,05 K betekent dat beide voelers hetzelfde lezen. Dat is precies wat je verwacht van
**stilstaand water**: geen doorstroming, dus geen temperatuurverschil over de meter. De 71,7 % met
debiet exact nul bevestigt het langs een tweede weg.

De waarde die er dan staat is de temperatuur van een leiding die naar de omgeving toe afkoelt: hij
ligt mediaan 2,9 K van de binnentemperatuur af, maar volgt die niet (correlatie 0,115) — er zit nog
restwarmte van de vorige draaibeurt in. Het is dus geen kamertemperatuur en al helemaal geen
aanvoertemperatuur van de installatie; het is een grootheid zonder betekenis voor het
verwarmingssysteem.

Dit is dezelfde reden waarom NeedForHeat in `add_filtered_flow_ret_ch_temperatures` expliciet
`pompsnelheid == 0` uitsluit. Wij hebben geen pompsnelheid, maar we hebben het debiet, en dat doet
hetzelfde werk.

**Gevolg voor §4.3 en §4.5.** Interpoleren over een aan/uit-grens heen middelt een echte
aanvoertemperatuur met een stilstaande leiding, en levert een getal op dat nooit bestaan heeft. De
voorwaarde uit §4.5 — alleen interpoleren binnen kwartieren waar warmte geleverd werd in zowel
`[Q−1, Q)` als `[Q, Q+1)` — is daarmee niet alleen netjes maar noodzakelijk. En er hoort een derde
voorwaarde bij: **buiten die kwartieren horen `temp_aanvoer` en `temp_retour` NaN te zijn en niet de
gemeten waarde**, want die waarde zegt iets over een leiding en niet over de installatie. Dat is
principe 2 (geen stille correcties) toegepast in de andere richting: liever ontbrekend dan
misleidend gevuld.

### 4.7 Het temperatuurverschil is klein, en dat beperkt elke COP

Als er wél warmte geleverd wordt, is ΔT over de warmtemeter:

| p05 | p25 | p50 | p75 | p95 |
|---:|---:|---:|---:|---:|
| 0,09 K | 2,34 K | **3,75 K** | 5,46 K | 7,83 K |

**35,5 % van de leverende kwartieren zit onder 3 K, 21,7 % onder 2 K.** Per woning verschilt dat
sterk: van 9,4 % onder 3 K (`-B51sQOp`) tot 48,3 % (`-uFUg8jU`).

Een warmtemeter rekent `q = ρ · c_p · V̇ · ΔT`. Bij een klein ΔT staat een klein, met ruis behept
getal in die vermenigvuldiging, en de relatieve fout op `q` groeit navenant. `q` is de teller van
elke COP in dit project. Een aanzienlijk deel van de warmtemeting wordt hier dus gedaan in het
gebied waar een warmtemeter het minst nauwkeurig is.

**Het datablad geeft die grens, en hij ligt precies op de verkeerde plek.** Uit het Kamstrup-datablad
van de MULTICAL® 403 (58101436_N1_EN, p. 5–6):

> Differential range ∆Θ: **3 K…178 K**

Beneden 3 K werkt de meter dus **buiten zijn gespecificeerde meetbereik**. En 35,5 % van de
leverende kwartieren zit daaronder.

Ook binnen het bereik loopt de fout snel op, want ΔΘ staat in de noemer van beide foutformules. Het
datablad zet de EN 1434-1-eis (MPE) naast Kamstrups eigen typische waarde:

| | MPE volgens EN 1434-1 | typisch, MULTICAL 403 |
|---|---|---|
| rekenwerk | `Ec = ±(0,5 + ΔΘ_min/ΔΘ) %` | `Ec = ±(0,15 + 2/ΔΘ) %` |
| voelerpaar | `Et = ±(0,5 + 3·ΔΘ_min/ΔΘ) %` | `Et = ±(0,4 + 4/ΔΘ) %` |

Ingevuld met ΔΘ_min = 3 K. De fout van de debietmeter komt hier **nog bovenop** en zit niet in deze
tabel:

| ΔΘ | `Ec` + `Et` volgens MPE | idem, typisch |
|---:|---:|---:|
| 30 K (het referentiepunt van het datablad) | ±1,40 % | ±0,75 % |
| 10 K | ±2,20 % | ±1,15 % |
| 3,75 K (onze mediaan) | ±4,20 % | ±2,15 % |
| 3 K (ondergrens van het bereik) | ±5,00 % | ±2,55 % |
| 2 K (21,7 % van de kwartieren) | buiten bereik (±7,00 % doorgerekend) | (±3,55 %) |

De formules zijn `Ec + Et = ±(1,0 + 12/ΔΘ) %` volgens de MPE en `±(0,55 + 6/ΔΘ) %` typisch; de
waarden voor 2 K staan tussen haakjes omdat doorrekenen buiten het gespecificeerde bereik strikt
genomen niets zegt — de fabrikant garandeert daar niets.

Bij de mediaan van deze dataset is de toegestane fout op de warmtemeting dus precies drie keer zo
groot als op het punt waar de meter gespecificeerd is, en bij ruim een vijfde van de kwartieren geldt
er helemaal geen specificatie meer.

**Wat dat wel en niet betekent.** Niet dat de COP's onbruikbaar zijn: kwartieren met een kleine ΔΘ
leveren per definitie ook weinig warmte, dus hun gewicht in een seizoenstotaal is kleiner dan hun
aandeel in de kwartieren. Hoe véél kleiner is de vraag die telt, en die is met de volledige run te
beantwoorden: **welk aandeel van de geleverde energie komt uit kwartieren onder 3 K?** Is dat een
paar procent, dan is dit een voetnoot; is het een kwart, dan is het een beperking op elke
SCOP-uitspraak. Dat is analyse B11 in `ontwerp-preprocessing.md` §8.

Onafhankelijk daarvan hoort er een `dT_te_klein__bool` in `quality` — de grens van 3 K is nu een
gedocumenteerd feit en geen aanname, en dat is precies het soort drempel dat wél in de code mag.

Dit is ook de spiegel van D1.2. Daar bleek `ΔT > 12 K` nodig om het debiet uit de warmte af te
leiden; hier zit **100 %** van de kwartieren onder 12 K. Dat het hier tóch werkt komt doordat de
Kamstrup het debiet zelf meet — maar het laat zien hoe smal de marge is waarin deze installaties
draaien.

### 4.8 De stooklijn uit het veld

Mediane aanvoertemperatuur per bak buitentemperatuur, alleen over kwartieren met warmtelevering:

| buiten (°C) | −15…−5 | −5…0 | 0…5 | 5…10 | 10…15 | 15…25 |
|---|---:|---:|---:|---:|---:|---:|
| aanvoer (°C) | 38,4 | 36,7 | 34,9 | 32,2 | 30,5 | 28,6 |
| n | 708 | 6.575 | 19.797 | 33.597 | 15.914 | 3.572 |

Zelfs bij strenge vorst blijft de mediaan onder 40 °C. Dat bevestigt wat de eindrapportage zelf
schrijft over watertemperaturen die "veel lager zijn dan gewoonlijk wordt aangenomen".

Dit is geen preprocessing-bevinding maar het hoort hier genoteerd, want het is het soort veldbewijs
waarvoor deze dataset is opgehaald: de afnemende repo zet in zijn ankers een
vaste 55 °C tegenover "laagst haalbaar", en dit is een gemeten derde antwoord. De tabel hierboven
gaat over vijf woningen; herhalen op de volledige set voordat er iets op gebaseerd wordt.

### 4.9 Kan de interpolatie beter dan NeedForHeat het doet?

De vraag is gesteld vanuit de gedachte dat NeedForHeat met vaste intervallen werkte en DPH niet, en
dat er voor ongelijk bemonsterde reeksen betere methoden bestaan. Dat klopt in het algemeen, maar
voor deze dataset moet de vraag eerst scherper: **hoe ongelijk is deze reeks eigenlijk?**

#### DPH is niet ongelijk bemonsterd, maar regelmatig met jitter

Uit de scheefheidsmeting over de volledige set (8,64 M kwartieren): het meetpunt ligt vrijwel
uniform verdeeld over de eerste **tien seconden** na de kwartiergrens (95,8 % binnen [0, 10) s,
gemiddeld 4,31 s), met een klif bij 10 s. Dat is de handtekening van één trekking uit een
10-secondenraster.

De afstand tussen twee opeenvolgende metingen is dus **900 s ± 10 s**, oftewel een variatie van
1,1 % — plus veelvouden van 900 s waar een kwartier ontbreekt. Dat is geen ongelijk bemonsterde
reeks in de eigenlijke zin (zoals gebeurtenisgestuurde telemetrie), maar een regelmatig rooster met
kleine jitter en uitval.

**En de jitter raakt juist niet wat we interpoleren.** De fout die je maakt door de jitter te negeren
is van de orde `(dv/dt) · δ`. Voor een binnentemperatuur die met 0,5 K/min verandert — al snel —
geeft 10 s ongeveer 0,08 K. Verwaarloosbaar. Voor vermogens is het níét verwaarloosbaar, maar die
interpoleren we bewust niet (§4.3): daar geeft de teller het exacte intervalgemiddelde al.

De aanleiding voor een betere methode is hier dus niet de jitter. Maar er is wél een betere methode,
om een andere reden.

#### De methode kan exacter én goedkoper: het tijdgewogen integraal

NeedForHeats drietrap — opwaarts bemonsteren, interpoleren, neerwaarts middelen — is een *omweg*.
Wat je eigenlijk wilt is het gemiddelde van de stuksgewijs lineaire interpolant over het interval, en
dat is gewoon uit te rekenen:

```
gemiddelde over [a, b] = (1/(b−a)) · Σ_i  (v_i + v_{i+1})/2 · (t_{i+1} − t_i)
```

met de randsegmenten afgeknipt op `a` en `b`. Dat is de **tijdgewogen gemiddelde**, standaard in
proceshistorians (OSIsoft PI, InfluxDB `integral()`, TimescaleDB `time_weight()`).

Drie voordelen boven de drietrap:

1. **Exact in plaats van benaderd.** Middelen over een 1-minuutraster is een kwantisatie van dat
   integraal: elk monster telt mee alsof het op een minuutgrens ligt, met een fout tot 30 s in de
   weging. Het integraal heeft die fout niet.
2. **Ongelijke afstanden zijn gratis.** Er is geen raster dat op de meetpunten moet passen; de
   werkelijke `t_i` staan gewoon in de formule. De jitter, en ook een echt ongelijkmatige bron,
   worden vanzelf goed behandeld.
3. **Vijftien keer minder geheugen.** Geen opwaartse bemonstering, dus geen tijdelijke reeks van
   15 × 8,6 M rijen. Dat is bij deze omvang geen detail.

De gatlimiet past er natuurlijk in: een segment `(t_i, t_{i+1})` dat langer is dan de limiet levert
`NaN` aan elk kwartier dat het raakt, in plaats van een overbrugging.

**Waarom NeedForHeat het toch zo doet, en waarom dat daar redelijk is.** In hun opzet komen
verschillende grootheden met verschillende bemonsteringsfrequenties uit verschillende bronnen, en
die moeten op één gemeenschappelijk rooster landen voordat er iets mee gebeurt. Het opwaartse
raster is dan het rooster, en het middelen is een bijproduct. Bij ons komt alles al op hetzelfde
kwartierrooster binnen, dus we hebben dat gemeenschappelijke raster niet nodig en betalen alleen de
kosten ervan.

#### De gatlimiet hoort gemeten te worden, niet geërfd

NeedForHeat kiest 90 minuten als default, per grootheid overrulebaar. Wij hebben die waarde in §4.4
voorlopig overgenomen en als aanname gemarkeerd. Dat kan beter, en het is de kern van de vraag: **de
limiet hoort af te hangen van hoe veranderlijk de grootheid werkelijk is.**

De directe manier is een **weglaattoets** op de data die we hebben:

1. Neem kwartieren waar de meting wél aanwezig is.
2. Verwijder er kunstmatig aaneengesloten reeksen van lengte *k* uit (k = 1, 2, 4, 8, 16, 32, …
   kwartieren).
3. Interpoleer over het gat en vergelijk met de bekende werkelijke waarden.
4. Rapporteer de fout als functie van *k*, per grootheid en per woning.

De gatlimiet is dan de grootste *k* waarbij de fout onder een **vooraf benoemde tolerantie** blijft.
Die tolerantie moet aan iets betekenisvols hangen, niet aan een rond getal:

- aan de **nauwkeurigheid van de sensor zelf** — voor de aanvoer- en retourtemperatuur is dat de
  voelerspecificatie van de MULTICAL 403; een interpolatiefout ver onder de meetfout is per definitie
  onschadelijk;
- of aan de **breedte van de analysebakken**. De pre-registratie bint de aanvoertemperatuur in
  stappen van 5 K. Een interpolatiefout van 0,5 K verplaatst vrijwel nooit een waarneming naar een
  andere bak en is dan irrelevant, hoe onnauwkeurig hij op zichzelf ook oogt.

Dat levert een limiet op die uit de data volgt en die per grootheid verschilt — wat ook te verwachten
is: een binnentemperatuur is uren voorspelbaar, een aanvoertemperatuur is dat alleen zolang de
installatie in dezelfde toestand blijft.

Twee dingen om bij die toets te bewaken. De limiet mag **niet op winterdata bepaald en op zomerdata
toegepast** worden, want de veranderlijkheid verschilt per seizoen; rapporteer per seizoen. En hij
moet **stabiel zijn over woningen** — is de limiet bij de ene woning 30 minuten en bij de andere 6
uur, dan zegt dat meer over die installaties dan over de grootheid, en dan is één landelijke limiet
de verkeerde vorm.

Dit staat als analyse **B12** in `ontwerp-preprocessing.md` §8.

#### Twee grootheden horen hier helemaal niet bij

**Cumulatieve tellers hebben geen interpolatie nodig, en het zou slechter zijn.** Wij differentiëren
over de *werkelijke* verstreken tijd tussen twee aflezingen. Ontbreken er kwartieren, dan wordt de
deler navenant groter en is het resultaat het gemiddelde vermogen over die hele periode. Dat is niet
alleen goed genoeg maar **behoudt de energie exact**: de som over het gat is per constructie gelijk
aan het werkelijke verschil van de meterstanden. Een geïnterpoleerd vermogen heeft die eigenschap
niet. Wat we verliezen is de *verdeling* binnen het gat, en die kennen we ook niet.

**Het weer is een ander probleem, en wordt nu waarschijnlijk fout behandeld.** De KNMI-uurwaarden
zijn zelf al **gemiddelden over een uur**, geen monsters op een tijdstip. Zo'n reeks lineair
interpoleren alsof het monsters zijn, geeft een reeks waarvan het uurgemiddelde niet meer gelijk is
aan de opgegeven uurwaarde — je verschuift energie tussen uren. Wat hier hoort is
**gemiddelde-behoudende interpolatie**: een interpolant construeren waarvan het gemiddelde over elk
bronuur exact de gegeven uurwaarde is. Dat is een bekende techniek uit de klimatologie en het is een
andere vergelijking dan de trapeziumregel.

Zolang die er niet is, is de trapfunctie (elk kwartier krijgt de uurwaarde) **eerlijker dan lineair
interpoleren**: hij is zichtbaar grof, maar hij behoudt het uurgemiddelde wel. Dat is een reden om
§3 hier niet overhaast te "verbeteren".
---

## 5. Losse bevinding: één woning met een kapotte warmtepompteller, en de valkuil eromheen

Bij de eerste meting van §2 leek `p_warmtepomp__W` op geen enkele verschuiving te correleren met
`p_warmtepomp_meting__W` (−0,004 tot 0,074), terwijl ketel en kamstrup 0,78 en 0,86 haalden. Dat
zag eruit als een structureel probleem met `heatpump.csv`.

**Dat was gemeten over alle woningen tegelijk, en dat is de fout.** Per woning:

| woning | corr(teller, momentaan) | p99 teller | max teller | max momentaan |
|---|---:|---:|---:|---:|
| `-B51sQOp` | 0,930 | 189 W | 2.412 W | 2.454 W |
| `-ORiFQC6` | 0,781 | 1.405 W | 2.012 W | 2.105 W |
| `-uFUg8jU` | 0,938 | 2.176 W | 2.240 W | 2.396 W |
| `0RQyG6WX` | 0,931 | 1.204 W | 1.960 W | 1.343 W |
| `0XvCtU3v` | **−0,002** | 1.812 W | **12.312.980 W** | **226.876 W** |

Vier van de vijf woningen zijn in orde. Eén woning heeft uitschieters van 12,3 MW, en die ene woning
sleepte de gepoolde correlatie naar nul — bij een uitschieter die vier ordes van grootte boven het
signaal ligt, is dat precies wat er gebeurt.

Twee dingen om vast te houden:

1. **De bevinding zelf is nu kleiner en scherper.** Niet "de warmtepompteller deugt niet", maar
   "één woning heeft losse, extreme uitschieters in de tellerreeks". Dat is werk voor
   `teller_sprong__bool` en niet voor een mail aan KITE.
2. **Elke statistiek in dit project moet per woning voordat hij gepoold wordt.** Deze dataset is
   een verzameling van 174 aparte installaties met aparte meetsets, geen homogene steekproef. Wat
   hier gebeurde met één woning op vijf, kan met vijf woningen op 174 net zo goed gebeuren en dan
   valt het niet op. Dat is een principe, geen incident, en het hoort in §3 van
   `ontwerp-preprocessing.md`.

De momentane reeks van diezelfde woning haalt ±227 kW en is dus ook onbetrouwbaar; het is aan de
installatie te wijten en niet aan de teller alleen.

**En er is een derde afwijking bij diezelfde woning, die de andere twee verklaarbaar maakt.** De
mediane ΔT over de warmtemeter is daar **−3,31 K** op kwartieren waarin de meter warmtelevering
rapporteert: de retour is warmer dan de aanvoer. Dat is fysisch onmogelijk voor een woning die warmte
afgeeft. Mediane ΔT per woning, alleen als er warmte geleverd wordt:

| woning | mediane ΔT | p95 | aandeel < 3 K |
|---|---:|---:|---:|
| `-B51sQOp` | 4,18 K | 7,67 K | 9,4 % |
| `-ORiFQC6` | 6,24 K | 9,08 K | 24,3 % |
| `-uFUg8jU` | 3,06 K | 6,06 K | 48,3 % |
| `0RQyG6WX` | 3,25 K | 7,80 K | 44,8 % |
| `0XvCtU3v` | **−3,31 K** | 6,49 K | 86,3 % |

Verwisselde voelers of een verkeerd om gemonteerde meter verklaren alle drie de anomalieën bij deze
woning in één keer. Eén verklaring voor drie losse waarnemingen is aanzienlijk waarschijnlijker dan
drie toevalligheden, maar het blijft een hypothese tot de volledige set laat zien of het patroon
vaker voorkomt (analyse A1 en B10 in `ontwerp-preprocessing.md` §8).

---

## 6. Wat expliciet uitzondering blijft

Drie soorten waarden kunnen per definitie geen intervalgemiddelde zijn. Ze blijven, met de reden in
de naam en in `docs/variable-dictionary.md`:

1. **Meterstanden in `measurements`** (`e_import_laag_cum__kWh`, `g_gebruik_cum__m3`, …). Een tellerstand is
   een **toestand op een moment**, geen intervalwaarde. Het bijbehorende tijdstip is
   `tijdstip_meting` en niet `tijdstip_start`; die laatste is daar uitsluitend de roostersleutel.
   Dat staat nu nergens en moet in de variabelenwoordenboek-tekst.
2. **De `_meting`-kolommen uit §4.3**, met per kolom de reden.
3. **`homes`-kenmerken**, die helemaal geen tijdas hebben.

Wat géén uitzondering is, en nu wel zo behandeld wordt: `ghi__kWh_m_2` draagt een verkeerde eenheid.
De waarde is een gemiddelde instraling, dus een flow, en hoort `ghi__W_m_2` te heten — dezelfde
correctie die de IM3-zusterrepo al gemaakt heeft. Meenemen in dezelfde migratie.

---

## 7. Volgorde

**Stand 05-09-2026, 22:40: 1 tot en met 3 zijn gedaan en gecommit; 4 staat nog open.** Wat er
bovendien bij kwam, buiten deze lijst om: de uitvoer staat nu in tz-aware `Europe/Amsterdam` in
plaats van UTC (gelijk aan de IM3-zusterrepo), `__flag` is `__bool` geworden en de acht cumulatieve
meterstanden dragen nu `_cum` — dat laatste tweetal volgt de aangescherpte
`physiquant__unit`-conventie, en `_cum` zet in de kolomnaam wat §6 hieronder in proza zegt.

De drie bevindingen zijn onafhankelijk te repareren en verschillen sterk in kosten. Voorstel:

1. **§2, de tellerlabeling.** Eén regel in `tellers.py`, plus een test die vastlegt dat
   `tijdstip_start + 900 s` het eindpunt van het gedifferentieerde interval is. Goedkoop en het
   raakt elke energiebalans.
2. **§6, `ghi__W_m_2` en de tekst over meterstanden.** Cosmetisch maar het hoort in dezelfde PR,
   want het gaat over dezelfde belofte.
3. **§3, het weer.** Eerst de IM3-ingest hergebruiken om de labeling te bewijzen, dan pas
   corrigeren. Niet corrigeren op grond van de zonnetest alleen.
4. **§4, de interpolatie.** Het meeste werk en de meeste keuzes. Pas beginnen als 1–3 gedraaid zijn,
   anders interpoleer je op verkeerd gelabelde data.

Alle vier vragen een nieuwe volledige run. Anders dan bij IM3 (7 uur) is dat hier geen bezwaar: de
proefrun over vijf woningen kost minuten, en de volledige set is ~35× groter, niet 1000×. Een
migratiescript zoals IM3 dat nodig had, is hier dus overbodig — opnieuw draaien is goedkoper dan de
migratie schrijven.
