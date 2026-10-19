# Ontwerp: preprocessing van de Demoproject Hybride-dataset

> **Status:** 05-09-2026, vastgelegd vóór de implementatie. Zusterontwerp van
> `ontwerp-preprocessing.md` in `installatiemonitor-dataset-preprocessing`; waar dat document een
> keuze al goed maakt, volgen we die en herhalen we de onderbouwing niet.

## 0. Wat dit is en niet is

Dit is een **preprocessing**: van zeven ruwe CSV's naar vijf getypeerde, herleidbare
Parquet-tabellen. Het is **geen analyse**. Er wordt hier niets geconcludeerd over
warmtepompprestaties; dat gebeurt in de afnemende repo, op de tabellen die hier uit komen.

De reden voor die scheiding is dezelfde als bij IM3: de ruwe data mag deze grens niet over. Wat
hieruit komt is klein genoeg om mee te rekenen en draagt de herkomst mee.

## 1. De brondata, zoals ze werkelijk zijn

Zeven CSV's plus een `metadata.csv` die als variabelenwoordenboek dient. **174 woningen** (geteld in
`household.csv`; de KITE-pagina zegt "circa 175" en de publieksrapportage 174),
1 januari 2022 tot 1 juni 2024, gekoppeld op `location_id`.

| bestand | omvang | inhoud |
|---|---:|---|
| `dsmr.csv` | 962 MB | slimme meter (P1): spanning, stroom en vermogen per fase, cumulatieve import/export per tarief, cumulatief gas |
| `kamstrup.csv` | 487 MB | warmtemeter: aanvoer- en retourtemperatuur, debiet, cumulatieve en momentane warmtelevering |
| `heatpump.csv` | 466 MB | elektrisch vermogen, spanning, stroom en cumulatieve energie van de warmtepomp |
| `boiler.csv` | 439 MB | idem voor de cv-ketel (elektrisch verbruik, niet het gas) |
| `room.csv` | 314 MB | binnentemperatuur en relatieve vochtigheid |
| `knmi.csv` | 218 MB | uurwaarden van het dichtstbijzijnde station, 23 velden |
| `household.csv` | klein | 17 woningkenmerken per deelnemer |

## 2. Zes bevindingen over de vorm van de data

Gecontroleerd in de data zelf, niet overgenomen uit de documentatie. Dit zijn de dingen die een
preprocessing stil verkeerd doet. §2.1 tot §2.3 stonden hier vóór de implementatie; §2.4 tot §2.6
zijn er ná de eerste bouwronde bij gekomen, en dat is precies waarvoor die ronde bedoeld was.

### 2.1 De tijdstempels liggen niet op het kwartier

De wiki van het project legt uit waarom: waar vaker dan per kwartier gemeten is, is *het eerste
meetpunt op of ná elk kwartier* genomen, **met de originele tijdstempel**. In `kamstrup.csv`:

```
-ORiFQC6,2022-02-07T11:10:50,21.75,21.78,...   <- hoort bij het kwartier van 11:00
-ORiFQC6,2022-02-07T11:15:04,21.8, 21.83,...   <- 11:15
-ORiFQC6,2022-02-07T11:30:02,21.99,21.98,...   <- 11:30; 11:45 ontbreekt
```

De afwijking loopt hier op tot bijna elf minuten. **Uitlijnen op een kwartierraster is dus een
expliciete keuze van deze preprocessing, geen gegeven.** Voorstel: het kwartier waar een meetpunt
bij hoort is `floor(tijdstip, 15min)`, en de oorspronkelijke tijdstempel blijft bewaard als
`tijdstip_meting` naast de afgeleide `tijdstip_start`. Wie wil weten hoe scheef een waarde stond,
kan dat dan zien in plaats van moeten aannemen.

### 2.2 De momentane kolommen zijn steekproeven, geen intervalgemiddelden

`p_thermal_system`, `heatpump_power`, `boiler_power` en de DSMR-vermogens zijn de waarde **op dat
ene moment**. Ze middelen tot een kwartiergemiddelde is daarom onjuist: bij een installatie die
binnen het kwartier aan- en uitschakelt is een steekproef geen gemiddelde.

Wat wél klopt: de **cumulatieve tellers** differentiëren over het interval. Dat is dezelfde route
die IM3 neemt en de reden dat het datamodel hieronder ruwe meterstanden (`measurements`) en
vermogen (`derived`) scheidt.

| grootheid | cumulatief (bruikbaar voor energie) | momentaan (alleen als steekproef) |
|---|---|---|
| netlevering | `e_consumed_low/high`, `e_delivered_low/high` | `p_consumed_L1..3`, `p_delivered_L1..3` |
| gas | `v_gas_consumed` | — |
| warmtepomp | `energy` (in `heatpump.csv`) | `power` |
| ketel | `energy` (in `boiler.csv`) | `power` |
| warmtelevering | `e_thermal_system` | `p_thermal_system` |

De momentane kolommen gaan wél mee, maar met een naam die zegt wat ze zijn (zie
`docs/variable-dictionary.md`). Ze zijn bruikbaar voor bedrijfspuntanalyse — bij welke
aanvoertemperatuur draaide de warmtepomp — en niet voor energiebalansen.

### 2.3 De tijdstempels dragen geen tijdzone

In het bestand staat `2022-02-07T11:10:50`, zonder `Z` of offset. `metadata.csv` documenteert ze
als UTC. Die toekenning gebeurt hier **expliciet**, en een test legt vast dat er geen naïeve
tijdstempel doorheen glipt. Zie `ontwerp-intervalsemantiek.md` in de IM3-zusterrepo voor waarom dit
bij kwartierdata zwaarder weegt dan het lijkt: zomertijdovergangen vallen anders stil verkeerd.

### 2.4 Gas van m³ naar W vraagt een calorische waarde, en die staat er niet bij

`g_gebruik__W` leek een kwestie van dezelfde omrekening als IM3. Dat is het niet: van kubieke meters
naar vermogen vergt de **calorische waarde** van het geleverde gas, en die varieert per netgebied en
per uur. In de dataset staat ze niet.

Deze pijplijn haalt daarom de **werkelijke, per uur gepubliceerde** waarde op via
`mijnenergiedata.nl/calorische-gaswaarden` (EDSN en de regionale netbeheerders), net als de
IM3-zusterrepo. Lukt dat voor een uur niet, dan valt die rij terug op de **vaste waarde van
35,17 MJ/m³**, en dat staat dan per rij in `derived.gas_hhv_bron__cat` met een telling in het
kwaliteitsrapport. Zie `src/dph_preprocessing/gaskwaliteit.py` voor de API, de beperkingen en de
onderbouwing; hier alleen de vier keuzes die het ontwerp raken.

**Netwerk in de verwerking is geen breuk met principe 4.** Dat principe ("netwerkvrij bij het
lezen") gaat over de afnemer van de tabellen, niet over de pijplijn: de uitvoer is een
parquet-bestand dat zonder netwerk te lezen is. Een eerdere versie van dit ontwerp las het ruimer en
hield de ingest er daarom buiten. Dat was de enige reden dat hier een vaste aanname stond, en die
reden houdt geen stand: de zusterrepo downloadt in zijn eigen verwerking zowel KNMI-data als de
gaskwaliteit en voldoet nog steeds aan principe 4.

**Geen netgebied per woning, dus een landelijk gemiddelde.** `household.csv` heeft geen
netbeheerder, postcode of regio, en `knmi.csv` geeft alleen het dichtstbijzijnde weerstation. Een
weerstation is geen netgebied; dat een op het ander afbeelden zou een gok zijn die in de uitvoer
niet van een meting te onderscheiden is. Wordt er ooit een netgebied per woning bekend, dan kan
dezelfde API met een `gridArea`-parameter preciezer.

**Hoogcalorische netgebieden doen niet mee, want Nederlandse woningen krijgen geen H-gas.** Een
kleinverbruikersaansluiting krijgt altijd gas van Groningen-kwaliteit; hoogcalorisch gas dat voor
huishoudens bestemd is wordt eerst met stikstof teruggemengd naar G-gas. Een huishoudelijke gasmeter
rekent dus nooit af tegen 41 MJ/m³, en een netgebied dat die waarde publiceert levert niet aan
woningen. In een gemiddelde dat op een woningmeting wordt toegepast horen ze niet thuis.

Ze zijn meteen herkenbaar, en dat is over het hele meetvenster stabiel: in alle 21.167 opgehaalde
uurwaarden (29 gasmaanden, januari 2022 t/m mei 2024) deden 161 tot 170 gebieden mee en vielen er
**elk uur precies 7** af tussen 41 en 43 MJ/m³, met niets tussen 37 en 41. De drempel
(`gaskwaliteit.G_GAS_BOVENGRENS__MJ_M3`) ligt in dat lege gat en is dus niet kritisch gekozen; het
aantal uitgesloten gebieden komt per uur mee in de opgehaalde tabel, zodat het opvalt als die
verdeling ooit verandert. De IM3-zusterrepo middelt nog wél over alle gebieden en komt daardoor
0,2 MJ/m³ (~0,6%) te hoog uit; zie `docs/lessen-uit-im3.md`.

**Onze `g_gebruik__W` wijkt hierdoor af van het meegeleverde analysepakket**, dat met een vaste
9,77 kWh/m³ (= 35,17 MJ/m³) rekent. Gemeten over de volledige run (174 woningen, 8.637.833
derived-rijen, waarvan 1.550.358 kwartieren met gasverbruik, 1.430.956 m³ in totaal): de toegepaste
waarde lag tussen 35,438 en 35,991 MJ/m³, ongewogen over rijen **1,57%** boven de vaste waarde en
naar afgezet volume gewogen **1,72%**.

Dat de volumegewogen afwijking de grootste is, is geen ruis maar een seizoenseffect: er wordt gas
gestookt in de maanden waarin het gas ook rijker is, dus wie met de vaste waarde rekent onderschat
het gasvermogen net iets méér dan een gemiddelde over alle uren suggereert. Punt 6 van
`docs/data-quality.md` rekent de ongewogen variant per run zelf uit; het volumegewogen getal hierboven
komt uit `derived` en is met `actual_gas_std_hhv__J_m_3` na te rekenen. Dat die kolom in de uitvoer
staat is precies hiervoor: wie onze cijfers naast die van de projectuitvoerder legt, kan het verschil
exact terugrekenen in plaats van het te moeten raden.

### 2.5 De data is opgeslagen per meetbron, niet per woning

Dit is een structureel verschil met IM3 dat de eerste versie van dit ontwerp over het hoofd zag.
IM3 levert **één bestand per woning**; DPH levert **één bestand per meetbron met alle woningen door
elkaar**, en niet geblokt op woning — dezelfde woning duikt verderop in het bestand opnieuw op.

Gevolg: "streamend filteren op vijf woningen" is geen goedkope steekproef. Elk bronbestand moet
volledig worden doorlopen, ook voor één woning. Gemeten bij de proefrun: `dsmr.csv` 7,9 miljoen
rijen, `kamstrup.csv` en `heatpump.csv` elk 8,6 miljoen — voor vijf woningen bleef daar telkens
ongeveer een kwart miljoen rijen van over.

Dat raakt twee dingen. De **verwachting over doorlooptijd**: een proefrun op vijf woningen kost
bijna evenveel leeswerk als de volledige set, dus "even snel iets uitproberen" bestaat hier niet.
En de **volgorde van werken**: het loont om één keer per bron te herindexeren naar woning
(`data/interim/`) in plaats van bij elke run opnieuw te filteren. Dat is nog niet gebouwd.

### 2.6 Drie kleinere afwijkingen tussen documentatie en data

Gevonden bij de implementatie, alle drie in `docs/variable-dictionary.md` verwerkt:

- **`heatpump.csv` en `boiler.csv` hebben kale kolomnamen**: `power`, `voltage`, `current`,
  `energy` — niet `heatpump_power` en `boiler_power` zoals `metadata.csv` doet vermoeden. De twee
  bestanden zijn alleen uit elkaar te houden via de bestandsnaam.
- **`household.csv` gebruikt `participant_id`** als sleutel waar alle andere bestanden
  `location_id` gebruiken.
- **`household.csv` bevat een kolom die nergens gedocumenteerd is**: `wrong_elec_measurement`
  (0/1/2), die aangeeft of de elektriciteitsmeting van díé woning deugt. Dat is geen detail: het
  raakt elke uitspraak op `e_net__W`. Opgenomen, met de kanttekening dat de betekenis van de drie
  waarden niet uit de dataset zelf blijkt en bij de bron nagevraagd moet worden.

En één praktisch ding: **`metadata.csv` is geen geldige UTF-8** (er staat een Windows-1252-teken in
"ampère"). Wie het bestand strikt als UTF-8 leest, crasht op de eerste regel.

## 3. Ontwerpprincipes

Overgenomen van de IM3-zusterrepo, met één toevoeging:

1. **Ruwe data verlaat deze repo niet.** `data/` is in zijn geheel gitignored.
2. **Geen stille correcties.** Wat afwijkt wordt gevlagd in `quality`, niet weggepoetst.
3. **Herleidbaar.** Elke afgeleide waarde is terug te voeren op een ruwe kolom via
   `docs/variable-dictionary.md`.
4. **Netwerkvrij bij het lezen.** Wie de tabellen afneemt hoeft niets te downloaden. Dit gaat over
   de afnemer, niet over de pijplijn: die haalt de werkelijke calorische gaswaarde wél op (§2.4).
5. **Gegenereerde rapportage.** `docs/data-quality.md` wordt geschreven door de pijplijn, niet met
   de hand bijgehouden.
6. *(nieuw)* **Kolomnamen volgen de Installatiemonitor waar de grootheid dezelfde is.** Een analyse
   die op IM3 draait, moet met minimale wijziging op DPH draaien. Waar DPH iets meet dat IM3 niet
   heeft, kiezen we een naam die in hetzelfde patroon past.
7. *(nieuw, 05-09-2026)* **Elke statistiek eerst per woning, dan pas gepoold.** Dit is geen
   homogene steekproef maar een verzameling van ~174 aparte installaties met aparte meetsets. Eén
   woning met uitschieters vier ordes van grootte boven het signaal trekt een gepoolde correlatie
   naar nul, en dan lijkt een dataset kapot die het niet is. Dat is hier één keer misgegaan en de
   correctie staat in `ontwerp-intervalsemantiek.md` §5; het principe is de les die overblijft.

## 4. Datamodel: vijf tabellen, dezelfde als IM3

| tabel | sleutel | inhoud |
|---|---|---|
| `homes` | `home_id__str` | één rij per woning: de 17 kenmerken uit `household.csv` |
| `measurements` | `home_id__str`, `tijdstip_start` | ruwe meterstanden per kwartier (cumulatief) |
| `weer` | `weerstation_nr`, `tijdstip_start` | uurwaarden KNMI, dezelfde drie grootheden als IM3 |
| `quality` | `home_id__str`, `tijdstip_start` | een `__bool`-kolom per controle |
| `derived` | `home_id__str`, `tijdstip_start` | gemiddeld vermogen per kwartier + gekoppeld weer |

De volledige kolomvertaling staat in [`docs/variable-dictionary.md`](docs/variable-dictionary.md).

## 5. Controles die in `quality` landen

Minimaal, en elk met een eigen `__bool`:

- **`ontbrekend__bool`** — geen meetpunt in dit kwartier. De leeswijzer zegt expliciet dat een
  ontbrekend kwartier *geen meting* betekent en niet nul.
- **`scheef__bool`** — het meetpunt lag meer dan een drempel (voorstel: 5 minuten) na de
  kwartiergrens. Volgt uit §2.1.
- **`teller_terug__bool`** — een cumulatieve teller die daalt. Meteruitval of -vervanging.
- **`teller_sprong__bool`** — een sprong die fysisch onmogelijk is binnen één kwartier.
- **`bron_incompleet__bool`** — niet alle vier de meetbronnen (dsmr, kamstrup, heatpump, boiler)
  hebben een waarde in dit kwartier. Dit is de vlag die bepaalt of een COP-berekening zinvol is.

### 5.1 Zes keuzes die het ontwerp openliet, en hoe ze nu ingevuld zijn

Bij het bouwen bleek dit ontwerp op zes punten te zwijgen. Ze zijn ingevuld, maar het zijn
**aannames en geen metingen**, en ze horen daarom hier te staan in plaats van alleen in de code.

| keuze | ingevuld als | hoe hard |
|---|---|---|
| wanneer is een tellersprong "fysisch onmogelijk" | een vermogensdrempel per teller: net 40 kW, gas ~100 kW-equivalent, warmtepomp 20 kW, ketel 10 kW, warmtelevering 50 kW | **zwak** — verzonnen, niet extern getoetst |
| scheefheid bij vier bronnen die elk hun eigen afwijking hebben | `scheef__bool` is een OR over de vier bronnen | keuze, geen noodzaak |
| twee meetpunten in hetzelfde kwartier | de laatste binnen het kwartier wint | zou niet mogen voorkomen volgens `metadata.csv` |
| de laatste tellerstand van een woning | vermogen en delta zijn NaN, en de vlaggen daar NA in plaats van False (na de correctie in ontwerp-intervalsemantiek.md §2 is dit de LAATSTE rij, niet de eerste: het vermogen op rij Q hoort bij het interval NA Q) | verdedigbaar |
| welke rijen bestaan in `measurements`/`derived` | de unie van de vier tellerbronnen; `room` en weer worden er alleen op gejoind, dus een kwartier met alleen een kamermeting krijgt geen rij | keuze met gevolgen |
| welke `tijdstip_meting` geldt als bronnen verschillen | vaste prioriteit dsmr > kamstrup > heatpump > boiler | willekeurig maar stabiel |

De eerste is de zwakste en verdient een eigen toets: kijk in de verdeling van de deltas waar de
werkelijke uitschieters liggen in plaats van een grens te kiezen die plausibel klinkt.

Die laatste is de belangrijkste openstaande onbekende: **hoe vaak zijn de vier bronnen tegelijk
beschikbaar?** Zonder die overlap is een COP per bedrijfspunt niet te berekenen. De eerste run moet
dat getal opleveren voordat er inhoudelijke vragen worden gesteld.

## 6. Wat hier bewust niet gebeurt

- **Geen tapwaterscheiding.** De projectuitvoerder heeft daar een notebook voor
  (`4_seperate_domestic_hot_water.ipynb`). Dat is een *analysekeuze* met aannames, en die hoort niet
  in een preprocessing. Wij lezen hun methode, nemen hun uitkomst niet over, en maken een eigen
  keuze zichtbaar in de analyserepo.
- **Geen SCOP-berekening.** Zelfde reden.
- **Geen eigen weer-ingest.** Anders dan bij IM3, waar het meegeleverde weer tegen een eigen
  KNMI-download is gelegd, nemen we hier het meegeleverde `knmi.csv` over. Reden: het is een
  uurreeks van het dichtstbijzijnde station, en de vraag "klopt dat station" is hier minder scherp
  dan bij IM3 omdat er geen interpolatie in zit. Als een analyse er tegenaan loopt, is dit de eerste
  plek om alsnog te controleren.
- **Geen filtering op woningen.** Wie er in of uit moet, is een keuze per onderzoeksvraag en hoort
  in de pre-registratie van die vraag.

## 7. Wat de eerste run moet opleveren

Vóór er een inhoudelijke vraag gesteld wordt:

1. Aantal woningen, en per woning het aantal complete kwartieren per meetbron.
2. De overlap: in hoeveel kwartieren zijn alle vier de bronnen beschikbaar (§5).
3. De verdeling van de scheefheid uit §2.1 — is die drempel van vijf minuten realistisch?
4. Hoe vaak tellers teruglopen of springen.
5. Het tijdvak per woning, en hoeveel woningen daadwerkelijk twee stookseizoenen dekken. Een
   "seizoensjaar" is voorlopig juli t/m juni; ook dat liet dit ontwerp open.

Dat is `docs/data-quality.md`, gegenereerd.

## 8. Analyseprogramma: wat we uitzoeken, en wat daarvan terug naar KITE gaat

§7 beschrijft wat de eerste run moet opleveren. Dit is de stap daarna: de analyses die de dataset
zelf onderzoeken in plaats van hem alleen om te zetten. De opzet volgt die van de IM3-zusterrepo,
waar dezelfde soort analyses uitmondden in een mail aan KITE met zes punten die om een correctie of
nieuwe export vroegen en vier die alleen om verduidelijking in de documentatie vroegen.

Dat onderscheid is de kern van de indeling hieronder. **Groep A** vindt dingen die alleen aan de
bronkant op te lossen zijn; die horen in een mail. **Groep B** controleert onze eigen verwerking;
die blijft binnenshuis. Beide moeten gedraaid zijn voordat er een inhoudelijke vraag gesteld wordt.

Waar hieronder een getal staat, is dat gemeten op de proefrun van vijf woningen en moet het op de
volledige set herberekend worden vóór het in een mail belandt.

### 8.1 Groep A: bevindingen over de brondata

**A1. Woningen met extreme uitschieters in de warmtepompteller.** Op de proefrun heeft één van de
vijf woningen (`0XvCtU3v`) tellerwaarden tot 12,3 MW en een momentane reeks tot 227 kW; de andere
vier zijn in orde (`ontwerp-intervalsemantiek.md` §5). Uit te zoeken op de volledige set: bij hoeveel
woningen komt dit voor, is het een handvol losse uitschieters of een structureel patroon, en valt
het samen met `wrong_elec_measurement` (A2). Pas als het meer dan een enkele woning betreft, is het
een punt voor de mail; anders is het gewoon werk voor `teller_sprong__bool`.

**A2. `wrong_elec_measurement` — al beantwoord, maar de kolom ontbreekt in onze output.** Deze vraag
stond hier als open punt en is dat niet: de betekenis staat in `notebooks/README.md` van het
meegeleverde analysepakket. `0` = de elektriciteitsmeting van de warmtepomp is bruikbaar; `1` =
onbruikbaar (die woningen verbruiken nooit meer dan ~100 W en zijn daaraan te herkennen); `2` = tijdens
het project gerepareerd, waarbij notebook 5 aangeeft vanaf wanneer de meting geldig is. De
projectuitvoerder noemt dit zelf "het grootste probleem in de dataset". Woningen met een ongeldige
elektrameting blijven bruikbaar voor gasbesparing.

Twee gevolgen. Ten eerste is er niets te vragen aan KITE, alleen te melden dat de kolom niet in
`metadata.csv` staat terwijl hij wezenlijk is (zie A7). Ten tweede, en belangrijker: **de kolom
staat wél in `docs/variable-dictionary.md` maar niet in `homes.parquet`** — de pijplijn laat hem
vallen. Dat moet gerepareerd worden vóór er iets op `p_warmtepomp__W` gebaseerd wordt, samen met de
"vanaf wanneer geldig"-datum voor de `2`-woningen uit hun notebook 5.

**A3. Meterwissels en resets.** IM3 kon dit niet zelf repareren omdat daar alleen de al-verschilde
reeks gepubliceerd is. **Hier wél**, want DPH publiceert de cumulatieve standen. Dat is een
noemenswaardig voordeel van deze dataset en hoort in de mail als compliment, niet alleen als
bevinding. Uit te zoeken: de verdeling van de deltas per teller, waar de werkelijke uitschieters
liggen, en of de karakteristieke spiegelparen (grote sprong, direct gevolgd door dezelfde sprong
terug) hier voorkomen.

**A4. De uurlabeling van `knmi.csv`.** Zie `ontwerp-intervalsemantiek.md` §3: de zonnetest wijst er
sterk op dat de KNMI-uurreeks eind-gelabeld is en als begin-gelabeld is overgenomen. Eerst
onafhankelijk verifiëren met de KNMI-ingest van de IM3-zusterrepo; die vond bij IM3 precies dit,
plus een verwisseld station. Pas daarna aan KITE voorleggen, met de meting erbij.

**A5. Lopen de vier meetbronnen op dezelfde klok?** De scheefheid is nu één verdeling over alle
bronnen (mediaan 2 s, p95 8 s, max 899 s). Uitsplitsen per bron laat zien of dsmr, kamstrup,
heatpump en boiler onafhankelijke loggers zijn of één. Dat is nodig om te weten of "alle vier
aanwezig in hetzelfde kwartier" ook betekent "tegelijk gemeten" — de aanname onder elke COP per
bedrijfspunt.

**A6. Is uitval per bron of per woning?** Een kwartier waarin alle vier de bronnen ontbreken is iets
anders dan een kwartier waarin alleen de warmtepomp ontbreekt: het eerste is een dataloggerstoring,
het tweede een sensor. Het onderscheid bepaalt of een gat overbrugbaar is en of het iets over de
installatie zegt.

**A7. Documentatiepunten, alleen ter verduidelijking.** Drie dingen zijn bij de implementatie al
gevonden en kosten geen verder onderzoek, alleen een zin in de mail:

- `heatpump.csv` en `boiler.csv` hebben kale kolomnamen (`power`, `energy`, …), niet
  `heatpump_power`/`boiler_power` zoals `metadata.csv` suggereert. De twee bestanden zijn alleen aan
  de bestandsnaam te onderscheiden.
- De sleutelkolom heet `location_id` in de meetbestanden en `participant_id` in `household.csv`.
- `metadata.csv` is geen geldige UTF-8.

### 8.2 Groep B: controles op onze eigen verwerking

**B1. Intervallabeling per grootheid.** De trapeziumtoets uit `ontwerp-intervalsemantiek.md` §2,
maar dan als vaste test in plaats van als eenmalige meting: leg vast dat het gedifferentieerde
vermogen op rij *Q* het interval `[Q, Q+1)` beschrijft. Dit is de controle die de fout gevonden
heeft en hij hoort te blijven staan.

**B2. Sluit de energiebalans na het differentiëren?** Per woning en per teller: de som van
`vermogen × delta_t` over alle kwartieren moet gelijk zijn aan de laatste tellerstand min de eerste,
op afrondfouten na. Dat toetst in één getal of de differentiatie verliesvrij is en of ontbrekende
kwartieren correct in de deler terechtkomen. IM3 doet het equivalent hiervan als `q`-som tegen
dagwaarde.

**B3. `teller_terug__bool` is bijna volledig vals-positief — al vastgesteld.** Het rapport meldt
15,8 %. Uitgesplitst per teller daalt geen enkele bronreeks vaker dan 0,0 % (2 tot 10 gevallen op
~245.000). De 39.622 vlaggen komen vrijwel allemaal van de *samengestelde* teller
`e_net = import − export`, en die mág dalen: dat is teruglevering. Gemeten: **alle 39.612 dalingen
van die samengestelde teller vallen samen met een stijging van de exportteller in hetzelfde
kwartier**; teruglevering komt voor bij 4 van de 5 woningen in de proefrun.

De vlag meet dus zonneschijn, niet meteruitval, met ongeveer 2200 vals-positieven op één terechte.
Correctie: `teller_terug__bool` per bronteller bepalen en pas daarna OR-en, en `e_net` er niet in
meenemen. Overweeg een aparte `teruglevering__bool`, want dat gegeven is op zichzelf bruikbaar.

**B4. De verdeling van de gaten per grootheid.** Nodig om de gatlimiet voor de interpolatie te
kiezen (`ontwerp-intervalsemantiek.md` §4.4) in plaats van NeedForHeats 90 minuten blind over te
nemen.

**B5. Aaneengesloten bruikbare tijd per woning.** NeedForHeat heeft hier twee functies voor die het
overnemen waard zijn: `calculate_covered_time` (totale gedekte tijd, waarbij gaten boven een limiet
niet meetellen) en `calculate_streak_durations` (de gedekte tijd verdeeld over bakken van
aaneengesloten reeksen: kwartier, uur, dag, week, maand). Het verschil met een simpele telling van
kwartieren is wezenlijk: 40.000 kwartieren verspreid over losse uren is iets anders dan 40.000
aaneengesloten kwartieren, en alleen het tweede is bruikbaar voor een seizoensanalyse.

**B6. Hoeveel gooit elke stap weg?** NeedForHeat houdt dat bij met een decorator (`track_metadata`)
die per filterstap vastlegt hoeveel waarden, woningen en grootheden er vóór en ná over waren. Hier
is dat nu onzichtbaar. Zonder die boekhouding is "we hebben 250.866 rijen" een getal zonder noemer.

**B7. De sprongdrempels tegen de werkelijke verdeling.** §5.1 noemt ze zelf de zwakste aanname
("verzonnen, niet extern getoetst"). Met de deltaverdeling uit A3 zijn ze te vervangen door een
grens die uit de data volgt.

**B9. Loopt er tapwater langs de warmtemeter, en bij welke woningen?** Uitgewerkt in
`ontwerp-intervalsemantiek.md` §4.5: het antwoord verschilt per woning en bepaalt of aanvoer- en
retourtemperatuur voorbewerkt moeten worden zoals REDUCEDHEATCARB dat doet. Het zomercriterium
(warmtelevering buiten het stookseizoen, en of die met gas of met warmtepompelektriciteit samenvalt)
levert een vlag per woning in `homes`.

**B10. Rekent de Kamstrup na wat hij zegt te meten?** De meter levert warmtevermogen, debiet én
beide temperaturen, dus `q = ρ · c_p · V̇ · ΔT` is een interne consistentiecheck. Waar die niet
sluit, wijst dat op een sensorfout of op een debiet buiten het meetbereik. NeedForHeat kon deze
controle niet doen omdat daar het debiet juist uit de warmte werd afgeleid.

**B11. Welk aandeel van de geleverde energie komt uit kwartieren met een te klein ΔΘ?** De
warmtemeter (Kamstrup MULTICAL 403) is gespecificeerd vanaf ΔΘ = 3 K; 35,5 % van de leverende
kwartieren op de proefrun zit daaronder. Maar die kwartieren leveren per definitie weinig warmte,
dus hun gewicht in een seizoenstotaal is kleiner dan hun aantal. Bereken het energiegewogen aandeel
per woning: onder 2 K, 2–3 K en boven 3 K. Is dat een paar procent, dan is het een voetnoot; is het
een kwart, dan is het een beperking op elke SCOP-uitspraak, en dan hoort die beperking in de
pre-registratie te staan en niet in een voetnoot achteraf. Onderbouwing in
`ontwerp-intervalsemantiek.md` §4.7.

**B12. Wat is de gatlimiet voor interpolatie, gemeten in plaats van geërfd?** Een weglaattoets:
verwijder uit kwartieren waar de meting wél aanwezig is kunstmatig aaneengesloten reeksen van lengte
k (1, 2, 4, 8, 16, 32 kwartieren), interpoleer over het gat, en vergelijk met de bekende waarden.
De limiet is de grootste k waarbij de fout onder een vooraf benoemde tolerantie blijft — gekoppeld
aan de sensornauwkeurigheid of aan de breedte van de analysebakken, niet aan een rond getal. Per
grootheid, per seizoen, en met de spreiding over woningen erbij: is de limiet bij de ene woning 30
minuten en bij de andere 6 uur, dan is één landelijke limiet de verkeerde vorm. Vervangt de
overgenomen 90 minuten van NeedForHeat. Onderbouwing in `ontwerp-intervalsemantiek.md` §4.9.

**B8. De telling "stookseizoenen gedekt" klopt niet.** `docs/data-quality.md` §5 meldt dat alle vijf
de woningen ≥2 stookseizoenen dekken, maar de telling telt seizoensjaren die *aangeraakt* worden,
niet gedekt. Een woning met data van juni 2022 tot januari 2024 raakt drie seizoensjaren aan en
heeft er nul volledig. Herdefiniëren met een dekkingseis, en dan pas rapporteren.

### 8.3 Wat hier bewust níét bij hoort

Alles wat een onderzoeksvraag beantwoordt in plaats van de data beschrijft. COP per bedrijfspunt,
tapwaterscheiding, SCOP: dat zijn analyses met keuzes, en die horen in de afnemende repo met een
pre-registratie, niet hier. De grens is dezelfde als in §6.

### 8.4 Volgorde en verhouding tot de melding aan KITE

De meldplicht uit `GEBRUIKSVOORWAARDEN.md` staat los van dit programma en kan meteen: die gaat over
de beoogde toepassing, niet over bevindingen. Neem in diezelfde mail de aanvraag voor het
Grafana-dashboard mee, met de expliciete vraag of de data op het fijnste meetinterval ook *als data*
beschikbaar is (export, API of databasetoegang) en niet alleen als dashboard. Een dashboard is een
kijkvorm; daar valt geen COP-decompositie op te rekenen.

Die aanvraag heeft inmiddels **drie** onderbouwingen, en dat is de moeite waard om in de mail te
noemen. De eindrapportage (bijlage 8) vermeldt dat alle sensoren **elke 10 seconden** naar het
platform sturen; de CSV-export is dus met ongeveer een factor 90 uitgedund. Op 10 seconden zijn
mogelijk: het scheiden van ontdooiverlies en pendelgedrag (Kladbloknotitie 35), de
tapwaterfiltering van aanvoer- en retourtemperatuur volgens REDUCEDHEATCARB
(`ontwerp-intervalsemantiek.md` §4.5), en een echte intervalgemiddelde in plaats van een
trapeziumbenadering. Geen daarvan kan op kwartierdata.

De inhoudelijke mail met de bevindingen uit groep A volgt later en pas als groep A en B op de
**volledige** dataset gedraaid zijn. De IM3-mail is daar het model voor: per punt wat er precies
gemeten is, zodat het na te rekenen valt, en expliciet de kanttekening dat een deel ervan een
bewuste keuze kan zijn die wij niet kennen.

## 9. Voorstel: de CSV→Parquet-omzetting apart zetten en bewaren

**Status:** voorstel, 05-09-2026. Bewust nog niet uitgevoerd; zie "wanneer" onderaan.

### Het probleem: de hervatting is nu een halve hervatting

`chunking.py` maakt een run hervatbaar door voltooide chunks over te slaan. Dat werkt voor de dure
verwerking per chunk, maar niet voor de stap ervóór. Uit de log van de eerste volledige run:

```
dsmr.csv: 7866691 rij(en) gelezen (streamend), 301652 verdeeld over de te (her)bouwen chunk(s)
```

**Volledig gelezen, gedeeltelijk verdeeld.** De `interim/`-split wordt alleen opgebouwd voor de
chunks die nog moeten, maar het bronbestand wordt daarvoor toch helemaal doorgelopen — het is niet
op woning gesorteerd, dus dat kan niet anders. Gemeten op de eerste run: `dsmr.csv` 295 s,
`kamstrup.csv` 116 s; over zes domeinbestanden samen ordegrootte **12 à 15 minuten**.

Die kosten worden bij elke herstart opnieuw betaald, ongeacht hoeveel er al klaar was. Met een
wrapper die tot vijf keer opnieuw probeert, is dat in het slechtste geval ruim een uur puur CSV
parsen. Een run die op chunk 7 van de 7 sneuvelt, betaalt evenveel als een run die meteen omvalt.

### Het voorstel

De omzetting van CSV naar Parquet als **eigen, bewaarde stap** vóór de verwerking:

```
data/raw/dph-dataset.zip
  -> data/brondata/<domein>.parquet      (nieuw: eenmalig, bewaard)
     -> data/processed/parts/...          (de bestaande chunkverwerking)
        -> data/processed/*.parquet
```

Bij een herstart is er dan **geen enkele CSV-pas** meer nodig: de chunks die nog moeten, worden
rechtstreeks uit de bewaarde Parquet gelezen. Parquet lezen is ordes sneller dan CSV parsen, dus die
12 à 15 minuten worden seconden.

### Het tweede argument, dat zwaarder weegt dan de tijdwinst

De cachegrens ligt nu op de verkeerde plek. `interim/` is opgesplitst **per chunk**, dus hij hoort
bij het chunkplan. Verander je `--chunk-grootte` of de woningselectie, dan is de hele split ongeldig
— en dat is precies de staleness die op 05-09-2026 tot een stille fout leidde (zie
`chunking.plan_vingerafdruk`).

Een kale CSV→Parquet-omzetting hangt **alleen van het bronbestand af**. Die overleeft een andere
chunkgrootte, een andere woningselectie, én een codewijziging in de verwerkingslaag. De cache wordt
dan ongeldig om precies één reden — de bron is veranderd — en dat is triviaal te controleren met de
sha256 van de zip.

Dat is ook waarom de invalidatie hier meteen goed moet: leg bij de omzetting een manifest vast met
de sha256 van `dph-dataset.zip`, het aantal rijen per domeinbestand en de kolomnamen. Wijkt er iets
af, dan opnieuw omzetten in plaats van hergebruiken. De les van vanochtend is dat een cache die
ongemerkt het verkeerde antwoord teruggeeft erger is dan geen cache.

### Waarom het huidige ontwerp hier langs redeneert

De module-docstring van `chunking.py` weegt dit expliciet af en concludeert dat interim bewaren niets
oplevert, omdat een domeinbestand niet op woning gesorteerd is en "alleen de ontbrekende chunks
aanvullen" alsnog een volledige pas vergt.

Dat klopt — voor een *gedeeltelijke* split. Bij een *complete* omzetting hoeft er niets aangevuld te
worden: je leest gewoon de Parquet van de chunks die je nodig hebt. De redenering is juist, de
aanname eronder ("we bewaren een halve split") is de verkeerde.

### Wat het kost

Schijfruimte. 2,9 GB CSV wordt als Parquet met snappy naar schatting 0,5 à 1,5 GB, bovenop de
bestaande uitvoer. Bij 40 GB vrij is dat geen bezwaar, maar het moet wel in `.gitignore` (`data/`
staat er al helemaal in, dus dat is geregeld).

Verder verdwijnt `interim/` niet: de verdeling over chunks blijft nodig. Hij wordt alleen goedkoop,
want hij leest dan Parquet in plaats van CSV.

### Wanneer

**Niet tijdens een lopende run.** `draai_volledig.sh` herstart een gesneuvelde stap, en die pikt dan
de gewijzigde code op — je krijgt een uitvoer die deels langs de oude en deels langs de nieuwe route
is gemaakt. Bij een dataset waar net een stille-fout-incident mee is geweest, is dat het laatste wat
je wilt.

Dus: na de eerste volledige run, en dan met een gelijkwaardigheidstest — dezelfde woningen via de
oude en de nieuwe route, en `pandas.testing.assert_frame_equal` erop. Dezelfde aanpak die de
IM3-zusterrepo voor zijn migratie gebruikte.
