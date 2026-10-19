# Datacatalogus: Demoproject Hybride-dataset (voorbewerkte uitvoer)

Dit document beschrijft de UITVOER van deze repo: de getypeerde Parquet-tabellen die
`dph_preprocessing` maakt van de meetdata van het **Demonstratieproject Hybride Warmtepompen**. Het
is bedoeld om in een datacatalogus te zetten naast (een verwijzing naar) de dataset zelf. De opbouw
volgt het
[energietransitie-dataset-template](https://github.com/energietransitie/energy-transition-dataset-template).

**Deze repo is niet de data-eigenaar en de ruwe data staat hier niet in.** Eigenaar is de Smart
Energy Foundation; licentie, meldplicht en herkomst staan in
[`GEBRUIKSVOORWAARDEN.md`](../GEBRUIKSVOORWAARDEN.md). Dit document beschrijft alleen wat de
pijplijn ervan maakt.

Er zijn **twee invoerpaden** met elk een eigen uitvoermap:

- het **kwartierpad** (`python -m dph_preprocessing`, `pipeline.py`) leest de zeven openbare CSV's en
  schrijft vijf contracttabellen plus `scheefheid.parquet` op een kwartierrooster;
- het **minuutpad** (`python -m dph_preprocessing.minuut`, `minuut.py`) leest een per-minuut-extractie
  uit de ruwe meettabel achter het KITE-dashboard en houdt het minuutrooster vast
  ([`ontwerp-preprocessing-minuut.md`](../ontwerp-preprocessing-minuut.md) §1, §2).

Alle kolomnamen volgen de conventie
[`physiquant__unit`](https://github.com/energietransitie/physiquant__unit): de eenheid staat na de
dubbele underscore, `_cum` markeert een meterstand op een moment, `__0` een dimensieloze fractie en
`__str`/`__cat`/`__bool` een niet-fysisch type ([`docs/variable-dictionary.md`](variable-dictionary.md),
inleiding en "measurements").

**Waar de getallen vandaan komen.** Typen, rijaantallen en tijdvakken zijn afgelezen uit de
Parquet-footers (schema, rijaantal en kolomstatistieken, zonder de data zelf in te lezen) van twee
volledige runs:

- kwartierpad: de run van 22-09-2026, uitvoercontract `2026-09-22-teller-artefacten`
  (`chunking.UITVOER_CONTRACT_VERSIE`), met het door die run geschreven
  [`data-quality.md`](data-quality.md);
- minuutpad: de run van 24-09-2026 (21:46 tot 23:31, 174 van 174 locaties, exitcode 0), uitvoercontract
  `2026-09-24-lokale-tijd` (`minuut.MINUUT_CONTRACT_VERSIE`, staat in `contract.json` in de
  uitvoermap), met het door die run geschreven `kwaliteit.md`.

Beweringen over het project zelf komen uit de projectrapporten, met titel en pagina; beweringen over
de verwerking uit de ontwerpdocumenten en de code van deze repo. Zie §11 voor de volledige
bronnenlijst.

## 1. Wat deze set is

Meetdata van woningen waarin een hybride warmtepomp is geplaatst. Het doel van het project was "*om
in 200, qua bouwjaar en type uiteenlopende, woningen het effect van de plaatsing van een hybride te
bepalen*" (Eindrapportage, p. 6), met twee onderzoeksvragen: de daling van het gasgebruik en het
gevolg voor de energierekening (Eindrapportage, p. 6). Uitgevoerd door de Smart Energy Foundation
"*die optrad namens de zes fabrikanten die deel uitmaken van de Vereniging voor Duurzame Warmte*"
(Eindrapportage, p. 6); dataverwerking en data-analyse door Inversable BV (`GEBRUIKSVOORWAARDEN.md`).

Anders dan bij de Installatiemonitor zit er per woning een aparte meting van de
warmtepompelektriciteit én van de geleverde warmte ([`README.md`](../README.md), "Wat dit is").

- **Woningen:** 174. Van de 185 aanmelders kregen er 174 een functionerende meetset
  (Eindrapportage, p. 15); `household.csv` telt er ook 174 (`ontwerp-preprocessing.md` §1). Beide
  paden hebben 174 woningen: `homes.parquet` en `homes_minuut.parquet` hebben elk 174 rijen, en de
  minuutrun verwerkte 174 locatiebestanden (`kwaliteit.md`).
- **Meetperiode van de openbare set:** 1 januari 2022 tot 1 juni 2024 (`GEBRUIKSVOORWAARDEN.md`);
  "*de eerste woningen [waren] pas begin 2022 online*" (Eindrapportage, p. 14). In de kwartieruitvoer
  loopt `tijdstip_start` van 2022-01-10 10:00 tot en met 2024-05-31 23:45 lokale tijd (footer van
  `measurements.parquet`).
- **Minuutdata:** van 2021-11-25 12:04 tot en met 2024-05-31 23:59 lokale tijd (footer van
  `homes_minuut.parquet`, kolommen `eerste_minuut` en `laatste_minuut`), samen 128.883.543 minuten
  (`kwaliteit.md`; `ontwerp-preprocessing-minuut.md` §1).
- **Data-eigenaar, licentie en meldplicht:** zie `GEBRUIKSVOORWAARDEN.md`. Kort: alleen open
  verwerking, toepassing en rekenmethoden openbaar delen onder eenzelfde licentie, en gebruik,
  rekenmethoden en conclusies melden via KITE of `data@demoprojecthybride.nl`.
- **Hoe je de brondata zelf verkrijgt:** de kwartier-CSV's staan op een open URL; data fijner dan een
  kwartier is alleen via KITE aan te vragen (`GEBRUIKSVOORWAARDEN.md`, "Hoe je de dataset zelf
  verkrijgt").

## 2. Werving, in- en uitsluitcriteria

**Werving.** "*Deelnemers konden zich via de opengestelde website aanmelden en zijn via het
installateursnetwerk van de fabrikanten geworven*" (Eindrapportage, p. 6). Aanmelden vroeg een
online formulier, twee energiejaarrekeningen en een goedkeuring door de RVO (Eindrapportage, p. 6 en
p. 15). Uit die jaarrekeningen komen `gas_voor_*` en `elektra_voor_*` in `homes`
(`docs/variable-dictionary.md`, "homes"; Eindrapportage, p. 28).

**Wie meedeed.** "*Veruit de meeste deelnemers waren eigenaar van de woning. De woningen zijn niet
bouwkundig aangepast en zonder tussenkomst van een EPA adviseur is de hybride door bewoner en/of
installateur geselecteerd*" (Eindrapportage, p. 6-7). Het gemiddelde bouwjaar is 1974 en het
gasgebruik vóór plaatsing lag rond 1900 m³; vrijstaande en halfvrijstaande woningen zijn
oververtegenwoordigd en "*Appartementen zitten niet in de projectpopulatie*" (Eindrapportage, p. 11).
Bijlage 7 van hetzelfde rapport noemt toch één woning met huistype appartement (Eindrapportage,
p. 93). De toestellen hadden een vermogen van 5 tot 7 kW (Eindrapportage, p. 32); bij de meeste
woningen is de cv-ketel blijven hangen (Eindrapportage, p. 40).

**Waarom geen 200.** "*Er zijn een aantal meetsets verloren gegaan of beschadigd waardoor er bij het
installeren van de laatsten een tekort ontstond en het aantal van 200 deelnemers niet kon worden
volgemaakt*" (Eindrapportage, p. 15).

**In- en uitsluitcriteria.** Niet vastgesteld. De rapporten noemen geen eisen aan energielabel,
isolatie, bouwjaar of gasverbruik en geen representativiteitstoets tegen de woningvoorraad; de
uitspraak over over- en ondervertegenwoordiging is kwalitatief (Eindrapportage, p. 11). In de eigen
analyses van het project zijn 13 deelnemers verwijderd "*waarvan overduidelijk of bekend was dat de
gegevens niet klopten*" (Eindrapportage, p. 40); **deze preprocessing verwijdert geen woningen**
(`ontwerp-preprocessing.md` §6). Wie erin of eruit moet, is een keuze per onderzoeksvraag.

## 3. Meetopstelling

Per woning een meetset met (Eindrapportage, p. 13 en bijlage 8, p. 94):

| meting | apparaat | bronbestand kwartierpad | meetgroep minuutpad |
|---|---|---|---|
| gas, elektriciteit en teruglevering van de woning | P1-poort van de slimme meter | `dsmr.csv` | 2 |
| totale warmtestroom naar het afgiftesysteem: vermogen, debiet, aanvoer- en retourtemperatuur | Kamstrup Multical 403, MID klasse B | `kamstrup.csv` | 1 |
| elektrisch verbruik van de warmtepomp | aparte kWh-meter SDM120M, MID klasse B | `heatpump.csv` | 1 |
| elektrisch verbruik van de cv-ketel (niet het gas) | aparte kWh-meter SDM120M, MID klasse B | `boiler.csv` | 1 |
| temperatuur en luchtvochtigheid in de woonkamer | Sonoff WiFi-meter | `room.csv` | 3 |
| weer | KNMI, uurwaarden van het dichtstbijzijnde station | `knmi.csv` | geen |

Bronnen voor de meetgroepen: `ontwerp-extractie.md` §1. De nauwkeurigheid van de Sonoff-sensor "*is
niet erg hoog*" (Eindrapportage, p. 94), en of die zorgvuldig geplaatst en gekalibreerd is, zal "*in
de praktijk van het project vast niet altijd gebeurd zijn*" (Eindrapportage, p. 98). Over kalibratie
van de andere meters zegt het rapport niets naast de MID-klasse.

**Meetfrequentie.** De meetsets stuurden hun gegevens elke 10 seconden naar een cloudplatform van
Inversable, met visualisatie in Grafana (Eindrapportage, p. 13 en p. 94). In de ruwe meettabel
achter dat dashboard is het mediane aantal metingen per minuut 12 voor meetgroep 1 (5 s), 6 voor
meetgroep 2 (10 s) en 2 voor meetgroep 3 (30 s) (`ontwerp-extractie.md` §2). De openbare CSV's zijn
daar een uitgedunde afgeleide van, met één meetpunt per kwartier (`ontwerp-extractie.md`, inleiding;
`GEBRUIKSVOORWAARDEN.md`).

**Waar de warmtemeter zit.** Volgens het rapport meet hij de totale warmte naar het afgiftesysteem,
dus achter warmtepomp én ketel (Eindrapportage, p. 13). De minuutpas toetst dat per locatie
(`warmtemeter_bereik__cat`, §7.2): 142 locaties `systeem`, 16 `warmtepomp`, 16 `onbeslist`
(`kwaliteit.md`, §1). Poolen over die groepen mengt twee meetopstellingen.

**Pseudonimisering.** De meetdata staan "*onder anonieme, random gegenereerde, identifiers*", en
woninggegevens zoals bouwjaar en vloeroppervlak zijn in categorieën ingedeeld "*om ook herleiding van
de woning middels matching onmogelijk te maken*" (Eindrapportage, p. 14). Zie ook §9.

## 4. Tijdconventies

**Uitvoer in lokale tijd.** Beide paden schrijven elke tijdkolom tz-aware in `Europe/Amsterdam`
(`timestamps.TZ_UITVOER`); intern rekenen ze in UTC, en de omzetting is een `tz_convert` vlak vóór het
wegschrijven, dus het instant verandert niet (`timestamps.naar_lokale_tijdzone`,
`timestamps.naar_lokale_tijdzone_arrow`; [`README.md`](../README.md), "Tijd"). Alle woningen staan in
Europees Nederland: ze hangen aan 25 KNMI-stations in het bereik 215 tot en met 391, zonder station
in Caribisch Nederland (`timestamps.py`, bij `TZ_UITVOER`). De reden voor lokale tijd: gedrag hangt aan
de klok, en groeperen op UTC-uur smeert hetzelfde gedrag uit zodra de zomertijd wisselt
(`timestamps.naar_lokale_tijdzone`, docstring). Ook `gaten.jsonl` en `kenmerken.jsonl` van het
minuutpad schrijven hun tijdstempels in lokale tijd (`minuut._voeg_regels_toe`).

**Rekenen op het instant, niet op de wandklok.** Bij de oktoberwissel komt het lokale uur 02:00-02:59
twee keer voor; de offset (+02:00 of +01:00) onderscheidt ze. Een gat over die wissel kan lokaal een
`eind` hebben dat op de klok vóór zijn `begin` ligt (`tests/test_minuut_tijdzone.py`). Reken met
`.dt.tz_convert("UTC")` als je verschillen wilt; dat geeft exact de bronwaarde terug
(`docs/variable-dictionary.md`, "Sleutels en tijd"). Nederlandse offsets zijn hele uren, dus een
kwartier- of minuutgrens in UTC is dat ook lokaal (`timestamps.naar_lokale_tijdzone`).

**Zomertijd in de brondata.** Gecontroleerd op 24-09-2026 rond alle vijf wissels van maart 2022 tot
en met maart 2024: het aantal minuten per UTC-uur is vlak, en bij de oktoberwissels staan beide lokale
uren 02:00-02:59 er volledig in. De loggers registreerden dus in UTC en er valt geen uur weg
([`README.md`](../README.md), "Tijd").

### 4.1 Kwartierpad

- De ruwe `timestamp` draagt geen tijdzone; `metadata.csv` documenteert hem als UTC, en de pijplijn
  kent UTC expliciet toe (`ontwerp-preprocessing.md` §2.3; `timestamps.naar_utc`).
- **De tijdstempels liggen niet op het kwartier.** Waar vaker gemeten is, is het eerste meetpunt op of
  ná het kwartier genomen, met de originele tijd (`ontwerp-preprocessing.md` §2.1). `tijdstip_start`
  is daarom afgeleid: `floor(tijdstip, 15 min)`; het origineel staat in `tijdstip_meting`
  (`timestamps.resolve_timestamps`). Over de volledige run ligt de mediaan van die afwijking op 4 s,
  p95 op 9 s en het maximum op 899 s (`data-quality.md` §3).
- **Intervalregel:** de waarde bij `tijdstip_start` hoort bij `[tijdstip_start, tijdstip_start +
  900 s)` ([`ontwerp-intervalsemantiek.md`](../ontwerp-intervalsemantiek.md) §1).
- **Drie soorten waarden zijn geen intervalgemiddelde** (`ontwerp-intervalsemantiek.md` §1, §6):
  een meterstand (`_cum`) is de stand op `tijdstip_meting`, niet een gemiddelde
  (`docs/variable-dictionary.md`, "measurements"); een `_meting`-kolom is een steekproef op het
  meetmoment (`ontwerp-preprocessing.md` §2.2); het weer is een uurwaarde die op elk kwartier van dat
  uur staat (`tabellen.build_derived`).
- **Vermogens zijn vooruit gedifferentieerd:** het vermogen op rij Q is `teller(Q+1) - teller(Q)`
  gedeeld door de werkelijke tijd tot die volgende aflezing, dus de laatste rij van elke woning is
  NaN (`tellers.py`, moduledocstring; `ontwerp-intervalsemantiek.md` §2).
- **Het KNMI-uur is een uur teruggeschoven:** de bron is eind-gelabeld (`HH=1` is 00:00-01:00), en is
  verschoven zodat `tijdstip_start` ook hier het begin is (`ontwerp-intervalsemantiek.md` §3;
  `tabellen.build_weer`).

### 4.2 Minuutpad

- De extractie groepeert al per minuut, dus `tijdstip_start` ligt exact op de minuutgrens en er is
  geen scheefheid (`ontwerp-preprocessing-minuut.md` §2; `ontwerp-extractie.md` §6).
- De momentane kolommen zijn hier **wel** intervalgemiddelden: het gemiddelde van de metingen in die
  minuut, bij vaste bemonstering gelijk aan het tijdgewogen gemiddelde. Daarom geen `_meting` in de
  naam (`ontwerp-preprocessing-minuut.md` §3). Waar een tellerkolom dezelfde grootheid geeft, krijgt de
  momentane kolom `_gemeten` (`p_warmtepomp_gemeten__W` naast `p_warmtepomp__W`).
- Tellers worden vooruit gedifferentieerd op de stand aan het begin van elke minuut (`_eerste`), tot
  de volgende aanwezige minuut (`ontwerp-preprocessing-minuut.md` §4; `minuut.differentieer_snel`).
- Alleen aanwezige minuten staan in `metingen`; de gaten staan apart in `gaten.parquet`
  (`ontwerp-preprocessing-minuut.md` §7).

## 5. Uitvoertabellen van het kwartierpad

Alle tabellen staan in de uitvoermap van `pipeline.run` (standaard `data/processed/`), één bestand per
tabel, samengevoegd uit deelbestanden per blok van 25 woningen (`pipeline.py`, moduledocstring;
`data/processed/parts/plan.json`: 7 blokken, 174 woningen). Rijaantallen uit de footers:

| bestand | rijen | woningen | sleutel |
|---|---:|---:|---|
| `homes.parquet` | 174 | 174 | `home_id__str` |
| `measurements.parquet` | 8.637.833 | 174 | `home_id__str`, `tijdstip_start` |
| `derived.parquet` | 8.637.833 | 174 | `home_id__str`, `tijdstip_start` |
| `quality.parquet` | 11.552.241 | 174 | `home_id__str`, `tijdstip_start` |
| `weer.parquet` | 432.104 | 25 stations | `weerstation_nr`, `tijdstip_start` |
| `scheefheid.parquet` | 696 | 174 (x 4 bronnen) | `home_id__str`, `bron` |

Het aantal woningen per tabel komt uit `data-quality.md` (inleiding en §1, 174 woningen met elk een
rij) en `scheefheid.parquet` (174 x 4 = 696, `tabellen.bouw_scheefheid_samenvatting`); de footers geven
geen distinct-telling. Het aantal stations uit `timestamps.py`.

**Welke rijen er zijn.** `measurements` en `derived` hebben een rij voor elk kwartier waarin minstens
één van de vier tellerbronnen (dsmr, kamstrup, heatpump, boiler) iets meet; `room.csv` en het weer worden
er alleen op gekoppeld, dus een kwartier met alleen een kamermeting krijgt geen rij. `quality` heeft
daarnaast een rij voor elk kwartier binnen het tijdvak van de woning, ook zonder meting
(`tabellen.py`, moduledocstring; `ontwerp-preprocessing.md` §5.1). Het verschil, 2.914.408 rijen, zijn
de kwartieren met `ontbrekend__bool`.

### 5.1 `homes.parquet`

Eén rij per woning, uit `household.csv` (`tabellen.build_homes`; `docs/variable-dictionary.md`,
"homes").

| kolom | type | eenheid | beschrijving | bronkolom |
|---|---|---|---|---|
| `home_id__str` | string | | gepseudonimiseerde woningsleutel | `participant_id` |
| `woningtype__cat` | categorie | | woningtype | `house_type` |
| `bouwjaar_klasse__cat` | categorie | | klasse van 20 jaar | `construction_year` |
| `oppervlak_klasse__cat` | categorie | | klasse van 50 m² | `surface` |
| `energielabel__cat` | categorie | | energielabel, niet overal ingevuld | `energylabel` |
| `bewoners__cat` | categorie | | `'1'` of `'2+'` | `number_of_inhabitants` |
| `eigendom__cat` | categorie | | particulier of woningcorporatie | `ownership` |
| `gas_voor_2__m3`, `gas_voor_1__m3` | float32 | m³ | jaargasverbruik ongeveer twee en één jaar vóór installatie | `gas_before_2`, `gas_before_1` |
| `elektra_voor_2__kWh`, `elektra_voor_1__kWh` | float32 | kWh | idem, elektriciteit | `electricity_before_2`, `electricity_before_1` |
| `heeft_vloerverwarming__bool` | bool | | lage-temperatuurvloerverwarming | `has_low_heat_floor_heating` |
| `heeft_radiatoren__bool` | bool | | radiatoren | `has_high_heat_radiator_heating` |
| `heeft_gasfornuis__bool` | bool | | koken op gas (False is inductie) | `has_gas_furnace` |
| `heeft_dubbelglas__bool` | bool | | ten minste dubbel glas | `has_double_paned_glass` |
| `heeft_dakisolatie__bool`, `heeft_muurisolatie__bool`, `heeft_vloerisolatie__bool` | bool | | isolatie aanwezig | `has_roofinsulation`, `has_wallinsulation`, `has_floorinsulation` |
| `elektrameting_verdacht__cat` | categorie | | `'0'` warmtepompmeting bruikbaar, `'1'` onbruikbaar, `'2'` tijdens het project gerepareerd | `wrong_elec_measurement` |

`wrong_elec_measurement` staat niet in `metadata.csv`; de betekenis komt uit `notebooks/README.md` van
het analysepakket (`tabellen.build_homes`). Het rapport noemt 40 woningen waar het elektriciteitsgebruik
van de hybride "*door een aansluitfout, niet goed gemeten*" is (Eindrapportage, p. 29).

### 5.2 `measurements.parquet`

Cumulatieve meterstanden (`tabellen.build_measurements_en_quality`; `docs/variable-dictionary.md`,
"measurements"). De stand hoort bij `tijdstip_meting`; `tijdstip_start` is alleen de roostersleutel.

| kolom | type | eenheid | beschrijving | bronkolom |
|---|---|---|---|---|
| `home_id__str` | string | | woningsleutel | `location_id` |
| `tijdstip_start` | timestamp(us, Europe/Amsterdam) | | begin van het kwartier | `timestamp`, afgeleid |
| `tijdstip_meting` | timestamp(us, Europe/Amsterdam) | | originele tijd; bij meer bronnen de eerste in de volgorde dsmr, kamstrup, heatpump, boiler | `timestamp` |
| `e_import_laag_cum__kWh`, `e_import_hoog_cum__kWh` | float64 | kWh | afgenomen elektriciteit, laag- en normaaltarief | `dsmr.e_consumed_low`, `_high` |
| `e_export_laag_cum__kWh`, `e_export_hoog_cum__kWh` | float64 | kWh | teruggeleverde elektriciteit | `dsmr.e_delivered_low`, `_high` |
| `g_gebruik_cum__m3` | float64 | m³ | gas | `dsmr.v_gas_consumed` |
| `e_warmtepomp_cum__kWh` | float64 | kWh | elektriciteit van de warmtepomp | `heatpump.energy` |
| `e_ketel_cum__kWh` | float64 | kWh | elektriciteit van de cv-ketel | `boiler.energy` |
| `q_geleverd_cum__J` | float32 | J | geleverde warmte | `kamstrup.e_thermal_system` (GJ x 10⁹) |

Gemaskeerd op NaN, met een vlag in `quality` (§7.1): de vijf DSMR-standen van een
initialisatietelegram, en elke nulmeting van een van de acht tellers (`tabellen.build_measurements_en_quality`;
[`ontwerp-teller-artefacten.md`](../ontwerp-teller-artefacten.md) §4.1, §4.2, §7).

### 5.3 `derived.parquet`

Gemiddeld vermogen per kwartier, de momentane steekproeven, en gekoppeld weer (`tabellen.build_derived`;
`docs/variable-dictionary.md`, "derived").

| kolom | type | eenheid | beschrijving | herkomst |
|---|---|---|---|---|
| `g_gebruik__W` | float32 | W | gasvermogen | `g_gebruik_cum__m3` x `actual_gas_std_hhv__J_m_3`, gedifferentieerd |
| `p_warmtepomp__W` | float32 | W | elektrisch vermogen warmtepomp | `e_warmtepomp_cum__kWh`, gedifferentieerd |
| `p_ketel__W` | float32 | W | elektrisch vermogen cv-ketel, niet het gas | `e_ketel_cum__kWh`, gedifferentieerd |
| `q_geleverd__W` | float32 | W | geleverd warmtevermogen | `q_geleverd_cum__J`, gedifferentieerd |
| `e_net__W` | float32 | W | netto elektriciteit, (import laag + hoog) min (export laag + hoog); mag negatief | vier DSMR-tellers, gedifferentieerd |
| `actual_gas_std_hhv__J_m_3` | float32 | J/m³ | toegepaste calorische bovenwaarde; nooit leeg | `mijnenergiedata.nl`, of 35,17 MJ/m³ |
| `gas_hhv_bron__cat` | categorie | | `mijnenergiedata_actueel` of `vast_gemiddelde_fallback` | `gaskwaliteit.py` |
| `u_L1_meting__V` .. `u_L3_meting__V` | float32 | V | spanning per fase, steekproef | `dsmr.u_L1..L3` |
| `i_L1_meting__A` .. `i_L3_meting__A` | float32 | A | stroom per fase, steekproef | `dsmr.i_L1..L3` |
| `p_import_L1_meting__W` .. `L3` | float32 | W | afgenomen vermogen per fase, steekproef | `dsmr.p_consumed_L1..L3` (kW x 1000) |
| `p_export_L1_meting__W` .. `L3` | float32 | W | teruggeleverd vermogen per fase, steekproef | `dsmr.p_delivered_L1..L3` (kW x 1000) |
| `temp_aanvoer_meting__degC`, `temp_retour_meting__degC` | float32 | °C | aanvoer- en retourtemperatuur, steekproef | `kamstrup.t_supply`, `t_return` |
| `debiet_meting__dm3_s_1` | float32 | dm³/s | debiet, steekproef | `kamstrup.f_system` (L/h / 3600) |
| `q_geleverd_meting__W` | float32 | W | warmtevermogen, steekproef | `kamstrup.p_thermal_system` (kW x 1000) |
| `p_warmtepomp_meting__W`, `p_ketel_meting__W` | float32 | W | elektrisch vermogen, steekproef | `heatpump.power`, `boiler.power` |
| `temp_binnen_meting__degC` | float32 | °C | woonkamertemperatuur, steekproef | `room.temperature` |
| `rv_binnen_meting__0` | float32 | fractie | relatieve luchtvochtigheid, steekproef | `room.humidity` / 100 |
| `temp_buiten__degC`, `wind__m_s_1`, `ghi__W_m_2` | float32 | °C, m/s, W/m² | weer van het KNMI-uur waarin `tijdstip_start` valt, eigen station van de woning | `weer` |

Plus `home_id__str` en `tijdstip_start` als in `measurements`. **Interval van de vermogens:** van deze
aflezing tot de volgende van dezelfde woning, gedeeld door de werkelijke duur, die bij een ontbrekend
kwartier langer is dan 900 s (`tellers.differentieer_teller`). NaN op de laatste rij van een woning, op
een interval met een gemaskeerde stand, en op het ene interval van een tellerwissel
(`tellers.verwerk_bronteller`). **Gas:** landelijk uurgemiddelde over de netgebieden met G-gas, zonder
de zeven hoogcalorische gebieden; in de volledige run kwam elke rij uit de opgehaalde reeks en viel
geen enkele terug op de vaste waarde (`ontwerp-preprocessing.md` §2.4; `data-quality.md` §6). Het
analysepakket van de projectuitvoerder rekent met een vaste 9,77 kWh/m³ (Eindrapportage, p. 28); onze
toegepaste waarde ligt gemiddeld 1,57 % hoger (`data-quality.md` §6).

### 5.4 `weer.parquet`

KNMI-uurwaarden, per station ontdubbeld (`tabellen.build_weer`; `docs/variable-dictionary.md`, "weer").
`tijdstip_start` loopt van 2022-02-01 01:00 tot en met 2024-05-31 22:00 lokale tijd (footer).

| kolom | type | eenheid | beschrijving | bronkolom |
|---|---|---|---|---|
| `weerstation_nr` | int32 | | KNMI-stationsnummer | `knmi.station_code` |
| `tijdstip_start` | timestamp(us, Europe/Amsterdam) | | begin van het uur, een uur teruggeschoven | `knmi.timestamp` |
| `temp_buiten__degC` | float32 | °C | buitentemperatuur | `T` (0,1 °C / 10) |
| `wind__m_s_1` | float32 | m/s | uurgemiddelde windsnelheid | `FH` (0,1 m/s / 10) |
| `ghi__W_m_2` | float32 | W/m² | gemiddelde globale instraling over het uur | `Q` (J/cm² per uur x 10⁴ / 3600) |

De overige twintig KNMI-velden gaan niet mee (`docs/variable-dictionary.md`, "weer"). `household.csv`
heeft geen station; dat van een woning is het station dat het vaakst bij haar `knmi.csv`-rijen staat
(`tabellen.home_station_mapping`). Bij 1,8 % van de `derived`-rijen ontbreekt de buitentemperatuur en
bij 3,6 % de instraling (`data-quality.md` §7).

### 5.5 `quality.parquet`

Eén `__bool` per controle, op het volledige kwartierrooster per woning van het eerste tot het laatste
waargenomen kwartier (`quality.bouw_tijdas`). De regels staan in §7.1.

| kolom | type |
|---|---|
| `home_id__str` | string |
| `tijdstip_start` | timestamp(us, Europe/Amsterdam) |
| `ontbrekend__bool`, `scheef__bool`, `teller_initialisatie__bool`, `teller_nulmeting__bool`, `teller_wissel__bool`, `teller_terug__bool`, `teruglevering__bool`, `teller_sprong__bool`, `bron_incompleet__bool` | bool, met lege waarden |

### 5.6 `scheefheid.parquet`

Per woning en tellerbron de verdeling van `tijdstip_meting - tijdstip_start`: `mediaan__s` (float32),
`p95__s` (float64), `max__s` (float32), `n` (int64). Geen contracttabel: hij wordt meegeschreven omdat de
gegevens toch in geheugen staan, en een ontbrekend deelbestand laat een hervatting niet opnieuw
beginnen (`tabellen.bouw_scheefheid_samenvatting`; `pipeline._verwerk_en_schrijf_chunk`).

### 5.7 Overige bestanden in de uitvoermap

- `gaskwaliteit/<jjjj-mm>.parquet`: de opgehaalde calorische waarden per gasmaand, bewaard zodat een
  herhaalde run reproduceerbaar blijft (`pipeline.GASKWALITEIT_CACHE_MAP`).
- `parts/`: de deelbestanden per blok en `plan.json` voor het hervatten (`chunking.py`).
- `datapackage.json`: de machineleesbare beschrijving van deze map (§10).
- Het kwaliteitsrapport staat niet in de uitvoermap maar in [`docs/data-quality.md`](data-quality.md).

## 6. Uitvoertabellen van het minuutpad

Alle bestanden staan in de uitvoermap van `minuut.run` (`--doel`) (`ontwerp-preprocessing-minuut.md`
§9). Rijaantallen uit de footers van de run van 24-09-2026:

| bestand | rijen | locaties | sleutel |
|---|---:|---:|---|
| `metingen/location_id=<id>.parquet` | 128.883.543 in 174 bestanden | 174 | `home_id__str`, `tijdstip_start` |
| `homes_minuut.parquet` | 174 | 174 | `home_id__str` |
| `gaten.parquet` | 153.767 | | `home_id__str`, `begin` |
| `dekking.parquet` | 6.225 | 174 | `home_id__str`, `kolom__str`, `drempel__min` |

Alle 174 metingenbestanden hebben hetzelfde schema (footers). Daarnaast in de map: `kwaliteit.md`,
`contract.json`, `kenmerken.jsonl` en `gaten.jsonl` (dezelfde gegevens als `homes_minuut` en `gaten`,
regel voor regel weggeschreven zodat een harde afbreking ze niet kost; `minuut.run`), en
`datapackage.json` (§10).

**`dekking.parquet` is na de run opnieuw gemaakt.** De versie uit de run van 24-09-2026 was
geschreven vóór de code drempel 0 maar één keer opnam, en had daardoor per kolom en locatie twee rijen
met `drempel__min` 0 (7.443 rijen). Op 26-09-2026 is hij opnieuw geschreven met
`minuut._schrijf_dekking` uit `gaten.parquet` en `homes_minuut.parquet`: 6.225 rijen, zonder
dubbelingen (`minuut_dekking.STANDAARD_DREMPELS__min`; `tests/test_minuut_dekking.py`).

### 6.1 `metingen/location_id=<id>.parquet`

Eén bestand per locatie, één rij per aanwezige minuut (`minuut.verwerk_locatie_streamend`;
`ontwerp-preprocessing-minuut.md` §3 tot en met §9).

| kolom | type | eenheid | beschrijving | bronkolom in de extractie |
|---|---|---|---|---|
| `home_id__str` | string | | woningsleutel | bestandsnaam |
| `tijdstip_start` | timestamp(ms, Europe/Amsterdam) | | begin van de minuut | `tijdstip_start` |
| `temp_aanvoer__degC`, `temp_retour__degC` | float32 | °C | aanvoer- en retourtemperatuur, minuutgemiddelde | `kamstrup_t_supply`, `kamstrup_t_return` |
| `q_geleverd_gemeten__W` (+ `_min__W`, `_max__W`) | float32 | W | warmtevermogen, gemiddelde (minimum, maximum) in de minuut | `kamstrup_p_thermal_system` (kW x 1000, + `_min`, `_max`) |
| `debiet__dm3_s_1` | float32 | dm³/s | debiet | `kamstrup_f_system` (L/h / 3600) |
| `p_warmtepomp_gemeten__W` (+ `_min__W`, `_max__W`) | float32 | W | elektrisch vermogen warmtepomp | `heatpump_power` (+ `_min`, `_max`) |
| `u_warmtepomp__V`, `i_warmtepomp__A` | float32 | V, A | spanning en stroom warmtepomp | `heatpump_voltage`, `heatpump_current` |
| `p_ketel_gemeten__W` (+ `_min__W`, `_max__W`) | float32 | W | elektrisch vermogen cv-ketel | `boiler_power` (+ `_min`, `_max`) |
| `u_ketel__V`, `i_ketel__A` | float32 | V, A | spanning en stroom cv-ketel | `boiler_voltage`, `boiler_current` |
| `u_L1__V` .. `u_L3__V`, `i_L1__A` .. `i_L3__A` | float32 | V, A | spanning en stroom per fase | `dsmr_u_L1..L3`, `dsmr_i_L1..L3` |
| `p_import_L1__W` .. `L3`, `p_export_L1__W` .. `L3` | float32 | W | afgenomen en teruggeleverd vermogen per fase | `dsmr_p_consumed_L1..L3`, `dsmr_p_delivered_L1..L3` (kW x 1000) |
| `temp_binnen__degC`, `rv_binnen__0` | float32 | °C, fractie | woonkamer | `sonoff_temperature`, `sonoff_humidity` / 100 |
| `e_import_laag_cum__kWh` .. `e_export_hoog_cum__kWh` | float32 | kWh | vier DSMR-standen aan het begin van de minuut | `dsmr_e_consumed_low/high_eerste`, `dsmr_e_delivered_low/high_eerste` |
| `g_gebruik_cum__m3` | float32 | m³ | gasstand | `dsmr_v_gas_consumed_eerste` |
| `g_gebruik__m3_s_1` | float32 | m³/s | gasdebiet uit de stand, **niet** omgerekend naar W | afgeleid |
| `e_warmtepomp_cum__kWh`, `p_warmtepomp__W` | float32 | kWh, W | stand en afgeleid vermogen warmtepomp | `heatpump_energy_eerste` |
| `e_ketel_cum__kWh`, `p_ketel__W` | float32 | kWh, W | stand en afgeleid vermogen cv-ketel | `boiler_energy_eerste` |
| `q_geleverd_cum__J`, `q_geleverd__W` | float32 | J, W | warmtestand en afgeleid vermogen | `kamstrup_e_thermal_system_eerste` (GJ x 10⁹) |
| `e_net_cum__kWh`, `e_net__W` | float32 | kWh, W | samengestelde stand (import min export) en afgeleid vermogen | afgeleid |
| `delta_t__s` | float32 | s | tijd tot de volgende aanwezige minuut; NaN op de laatste rij | afgeleid |
| `n_g1`, `n_g2`, `n_g3` | uint16 | | aantal ruwe metingen per meetgroep in deze minuut | ongewijzigd |
| `offset_eerste_g1__ms` .. `offset_laatste_g3__ms` | uint16 | ms | tijd na de minuutgrens van de eerste en laatste meting per groep | ongewijzigd |
| zeven vlaggen | bool | | zie §7.2 | afgeleid |

De naamgeving en omrekening staan in `minuut.MOMENTAAN` en `minuut.TELLERS`; de `_laatste`-standen en
`location_id` gaan niet mee (`minuut._nodige_kolommen`; `ontwerp-preprocessing-minuut.md` §4). Het
aantal metingen per groep is het dekkingsgewicht van het gemiddelde (`ontwerp-preprocessing-minuut.md`
§3, R7). Geen gaskwaliteit, geen weer en geen COP in dit pad (`ontwerp-preprocessing-minuut.md` §11).

### 6.2 `homes_minuut.parquet`

Eén rij per locatie met kenmerken uit dezelfde leespas (`minuut._Streamend.afronden`;
`ontwerp-preprocessing-minuut.md` §8).

| kolom | type | beschrijving |
|---|---|---|
| `n_minuten`, `eerste_minuut`, `laatste_minuut` | int64, timestamp(ms, Europe/Amsterdam) | aantal aanwezige minuten, eerste en laatste |
| `bezetting__0` | float64 | `n_minuten` gedeeld door het aantal minuten van eerste tot en met laatste |
| `grootste_gat__min`, `n_gaten`, `n_uitval` | int64 | langste gat, aantal gaten, aantal gaten van meer dan 1440 minuten |
| `warmtepompkanaal_dood__bool` | bool | `p_warmtepomp_gemeten__W` komt nooit boven 200 W |
| `p_warmtepomp_max__W` | float64 | hoogste `p_warmtepomp_gemeten__W` |
| `n_onplausibel`, `n_teller_terug`, `n_teller_nulmeting`, `n_teller_wissel` | int64 | aantal minuten met die vlag |
| `bereik_n`, `bereik_fractie`, `bereik_controle`, `bereik_referentie`, `warmtemeter_bereik__cat` | int64, float64, string | de warmtemeterproef, zie hieronder |
| `raster_<teller>__W`, `raster_breuk_<teller>__bool` | float64, bool | per teller: de vermogensstap die het float32-raster van de stand oplegt, en of dat raster binnen de periode verdubbelt |
| `dekking_<kolom>` | float64 | per momentane kolom en per teller: aandeel van de aanwezige minuten waarin die kolom gevuld is |

**Warmtemeterproef** (`minuut.bepaal_warmtemeter_bereik`; `ontwerp-preprocessing-minuut.md` §8): neem de
minuten in reeksen van minstens 10 aaneengesloten minuten waarin de warmtepomp onder 200 W zit en de
ketel boven 20 W. `bereik_fractie` is het aandeel daarvan waarin de warmtemeter meer levert dan 2 % van
het locatiemaximum; boven 0,15 is het `systeem`, onder 0,01 `warmtepomp`, anders `onbeslist`, en ook
`onbeslist` zonder proefminuten. `bereik_controle` (warmtepomp en ketel uit) hoort bijna 0 te zijn en
`bereik_referentie` (warmtepomp aan) hoog; die twee verraden een onzinnige uitkomst.

**Het float32-raster** (`minuut._raster_kenmerken`, `minuut_raster.beoordeel_teller`): de bron slaat
standen op als float32, en bij de standen die de meters na 2,5 jaar bereiken is dat raster bij een
aantal tellers grover dan de metertik, wat een trap in het afgeleide minuutvermogen geeft
([`ontwerp-preprocessing-minuut-geheugen.md`](../ontwerp-preprocessing-minuut-geheugen.md) §5.3, §6).

### 6.3 `gaten.parquet`

Eén rij per gat in het minuutrooster: `begin` (eerste ontbrekende minuut), `eind` (eerste aanwezige
minuut erna), `duur__min` (aantal ontbrekende minuten, int64) en `soort`: `uitval` als `duur__min`
groter is dan 1440, anders `hapering` (`minuut.bouw_gaten`; `ontwerp-preprocessing-minuut.md` §7).
71,4 % van de gaten duurt hoogstens 5 minuten en is samen 0,4 % van het gemis; de 659 gaten van meer
dan een dag zijn samen 92,7 % (`kwaliteit.md` §5). De volledige tijdas is uit deze tabel en
`homes_minuut` te reconstrueren (`ontwerp-preprocessing-minuut.md` §7).

### 6.4 `dekking.parquet`

Per locatie, kolom en overbruggingsgrens `k` de aaneengesloten bruikbare tijd, uitsluitend uit
`gaten.parquet` en `homes_minuut.parquet` (`minuut_dekking.bouw_dekking_tabel`;
[`ontwerp-interpolatie-en-dekking.md`](../ontwerp-interpolatie-en-dekking.md) §5).

| kolom | type | beschrijving |
|---|---|---|
| `kolom__str` | string | een van de zeven kolommen hieronder, of `cop_combo__p_warmtepomp_en_q_geleverd` |
| `drempel__min` | float64 | `k`: 0, 1, 2, 3 of 60 |
| `totale_tijd__min` | float64 | minuten van `eerste_minuut` tot en met `laatste_minuut` |
| `gedekte_tijd__min` | float64 | `totale_tijd__min` min de duur van alle gaten langer dan `k` |
| `aandeel_gedekt` | float64 | `gedekte_tijd__min / totale_tijd__min` |

De gemeten overbruggingsgrenzen (`minuut_dekking.OVERBRUGGINGSGRENS__min`;
`ontwerp-interpolatie-en-dekking.md` §4): `temp_binnen__degC` en `rv_binnen__0` 60 min,
`temp_retour__degC` 3, `temp_aanvoer__degC` 2, `debiet__dm3_s_1` 1, `q_geleverd_gemeten__W` en
`p_warmtepomp_gemeten__W` 0. Elke kolom staat er bij alle vijf drempels in, zodat een analyse zelf kan
kiezen. De COP-combinatie staat er alleen bij drempel 0, en zonder de locaties met
`warmtepompkanaal_dood__bool` (`minuut_dekking.analyse_cop_combo`). **Aanname:** `gaten.parquet` kent
alleen rijdekking; binnen een aanwezige minuut kan een kolom nog leeg zijn. Voor `temp_binnen__degC` en
`rv_binnen__0` is dit daarom een bovengrens (`minuut_dekking.py`, moduledocstring).

## 7. Kwaliteit

Beide paden **vlaggen en poetsen niet weg**: een afwijking krijgt een vlag, en een waarde gaat alleen
op NaN waar hij aantoonbaar geen meting is (`ontwerp-preprocessing.md` §3, principe 2;
`ontwerp-preprocessing-minuut.md` §6). Niets wordt geïmputeerd.

### 7.1 Vlaggen in `quality.parquet` (kwartierpad)

"De acht brontellers" zijn `e_import_laag/hoog_cum__kWh`, `e_export_laag/hoog_cum__kWh`,
`g_gebruik_cum__m3`, `e_warmtepomp_cum__kWh`, `e_ketel_cum__kWh` en `q_geleverd_cum__J`; de samengestelde
`e_net` hoort er niet bij, want die daalt legitiem bij teruglevering (`quality.py`, moduledocstring;
`ontwerp-preprocessing.md` §8, B3). "De volgende rij" is de volgende rij van dezelfde woning in
`measurements`, op tijd gesorteerd. Regels uit `tabellen.build_measurements_en_quality`, `quality.py` en
`tellers.py`; aantallen uit `data-quality.md` §2 tot en met §4.

| vlag | gaat aan als | ingreep | volledige run |
|---|---|---|---|
| `ontbrekend__bool` | geen van de vier tellerbronnen heeft een meting in dit kwartier, binnen het tijdvak van de woning | rij staat alleen in `quality`; de andere vlaggen zijn daar leeg | 2.914.408 rijen (verschil van de rijaantallen) |
| `scheef__bool` | bij minstens één tellerbron ligt de meting meer dan 300 s na de kwartiergrens (`timestamps.SCHEEF_DREMPEL`) | geen | 75.815 (0,9 %) |
| `teller_initialisatie__bool` | de vijf DSMR-registers staan tegelijk exact op 8969,994, 8789,167, 3433,300 en 8299,146 kWh en 5059,199 m³ (`tellers.INITIALISATIETELEGRAM_SENTINEL`) | die vijf standen op NaN, vóór alle andere tellerbewerkingen | 1.896 rijen, 167 woningen |
| `teller_nulmeting__bool` | een van de acht brontellers leest exact 0,0 terwijl hij bij deze woning eerder boven 1 stond (lopend maximum zonder deze rij, `tellers.TELLER_ONTWAAKT_BOVEN`) | die stand op NaN vóór het differentiëren, dus beide aangrenzende intervallen NaN | 33.397 rijen, 41 woningen |
| `teller_wissel__bool` | een van de acht brontellers daalt naar de volgende rij, na maskering van sentinel en nulmeting | vermogen van dat ene interval op NaN; de stand blijft | 30 rijen, 10 woningen |
| `teller_terug__bool` | `teller_nulmeting__bool` of `teller_wissel__bool` | geen eigen ingreep | 33.427 (0,4 %) |
| `teruglevering__bool` | `e_export_laag_cum__kWh` of `e_export_hoog_cum__kWh` stijgt naar de volgende rij | geen | 2.120.481 (24,5 %) |
| `teller_sprong__bool` | de absolute waarde van een intervalvermogen ligt boven zijn drempel: `e_net__W` 40 kW, `g_gebruik__W` 100 kW, `p_warmtepomp__W` 10 kW, `p_ketel__W` 1 kW, `q_geleverd__W` 50 kW (`tellers.SPRONG_DREMPEL__W`) | geen | 6.907 (0,1 %) |
| `bron_incompleet__bool` | niet alle vier de tellerbronnen hebben een meting in dit kwartier | geen | 883.241; alle vier aanwezig in 7.754.592 van 8.637.833 (89,8 %) |

**Lege waarden.** Op een `ontbrekend`-rij zijn alle andere vlaggen leeg. Op een meetrij is een
OR-vlag alleen leeg als geen van zijn onderdelen iets te beoordelen had: `scheef__bool` als geen bron
een meting had (kan op een meetrij niet), `teruglevering__bool` als geen van beide exporttellers een
interval heeft, `teller_sprong__bool` als alle vijf vermogens NaN zijn, zoals op de laatste rij van een
woning (`quality.or_vlaggen`, `tellers.teller_gestegen_masker`, `tellers.teller_sprong_masker`).
`teller_nulmeting__bool`, `teller_wissel__bool`, `teller_terug__bool`, `teller_initialisatie__bool` en
`bron_incompleet__bool` zijn op een meetrij nooit leeg.

**Volgorde doet ertoe.** Eerst de sentinel op NaN, dan pas het lopende maximum voor de nulmeting:
omgekeerd telt 3433,300 mee in het maximum en stijgt het aantal nulmetingen op
`e_export_laag_cum__kWh` van 361 naar 542.507 (`ontwerp-teller-artefacten.md` §5).

**De sprongdrempels** zijn gekozen op de gemeten verdeling van het intervalvermogen (analyse B7,
mediane p99,99 per teller) met een fysische onderbouwing per teller (`tellers.SPRONG_DREMPEL__W`,
commentaar).

### 7.2 Vlaggen in `metingen` (minuutpad)

Regels uit `minuut._Streamend.blok` (en het gelijkwaardige `minuut.verwerk_locatie`, rij voor rij
getoetst in `tests/test_minuut_streamend.py`). Alle zeven zijn gewone booleans, nooit leeg; op de
laatste rij van een locatie zijn `teller_terug__bool`, `teller_wissel__bool`, `teruglevering__bool`,
`gat_na__bool` en `uitval_na__bool` False, want daar is geen volgende minuut. Aantallen uit `kwaliteit.md` §4.

| vlag | gaat aan als | ingreep | volledige run |
|---|---|---|---|
| `teller_nulmeting__bool` | een van de acht brontellers leest exact 0,0 terwijl hij bij deze locatie eerder boven 1 stond (`tellers.markeer_nulmetingen`, hetzelfde criterium als het kwartierpad) | stand op NaN vóór het differentiëren | 496.394 minuten, 65 locaties |
| `teller_terug__bool` | een van de acht brontellers daalt naar de volgende minuut, na maskering van de nulmetingen | geen eigen ingreep | 46 minuten, 17 locaties |
| `teller_wissel__bool` | als `teller_terug__bool`, en de volgende stand is geen nulmeting | vermogen van dat interval op NaN; de stand blijft | 46 minuten, 17 locaties |
| `teruglevering__bool` | een van de twee exporttellers stijgt naar de volgende minuut | geen | niet geteld |
| `onplausibel__bool` | een momentane kolom ligt buiten zijn grens (tabel hieronder) | die waarde op NaN, niet afgekapt | 998.412 minuten, 170 locaties |
| `gat_na__bool` | `delta_t__s` > 60: na deze minuut ontbreekt er minstens één | geen | niet geteld |
| `uitval_na__bool` | `delta_t__s` > 86.400 s: na deze minuut volgt een gat van meer dan 24 uur | geen | niet geteld |

**`teller_terug__bool` betekent in de twee paden niet hetzelfde.** In het kwartierpad is het de OR van
nulmeting en wissel. In het minuutpad is het een daling van de opgeschoonde stand; omdat een nulmeting
dan al NaN is, valt een daling naar een nulmeting er niet onder, en in de praktijk is de vlag gelijk
aan `teller_wissel__bool` (46 tegen 46 in `kwaliteit.md`). Wie beide paden naast elkaar legt, gebruikt
`teller_nulmeting__bool` en `teller_wissel__bool`.

**Plausibiliteitsgrenzen** (`minuut.GRENZEN`; `ontwerp-preprocessing-minuut.md` §6):

| kolom | ondergrens | bovengrens |
|---|---:|---:|
| `p_warmtepomp_gemeten__W` (en `_min`, `_max`) | -100 W | 15.000 W |
| `p_ketel_gemeten__W` (en `_min`, `_max`) | -100 W | 5.000 W |
| `q_geleverd_gemeten__W` (en `_min`, `_max`) | -2.000 W | 60.000 W |
| `temp_aanvoer__degC`, `temp_retour__degC` | -10 °C | 100 °C |
| `temp_binnen__degC` | -10 °C | 60 °C |
| `rv_binnen__0` | 0 | 1 |
| `u_L1__V`, `u_L2__V`, `u_L3__V`, `u_warmtepomp__V`, `u_ketel__V` | 150 V | 300 V |
| `debiet__dm3_s_1` | -1 dm³/s | 10 dm³/s |

Een exacte 0,0 op `u_L1__V`, `u_L2__V` of `u_L3__V` gaat op NaN maar zet de vlag **niet**: meters die
geen spanning rapporteren melden daar een harde nul, en zonder die uitzondering markeerde de vlag
vooral welke meter geen spanning levert (`minuut.NUL_IS_AFWEZIG`). Licht negatieve waarden op de
warmtekolommen blijven staan: dat is een nulpuntseffect, geen defect (`ontwerp-preprocessing-minuut.md`
§6). De sprongdrempels van het kwartierpad gelden hier niet, want een minuutgemiddelde middelt minder
uit (`ontwerp-preprocessing-minuut.md` §4).

### 7.3 Dekking

- **Kwartierpad:** 89,8 % van de kwartieren met een meting heeft alle vier de tellerbronnen; per woning
  het aantal complete kwartieren per bron staat in `data-quality.md` §1, het tijdvak per woning in §5.
- **Minuutpad:** mediane bezetting over de locaties 76,5 %, laagste 0,5 %; per kolom de mediane dekking
  in `kwaliteit.md` §3. `u_L2__V` en `u_L3__V` zijn bij 101 locaties helemaal leeg en `u_L1__V` bij 76,
  omdat daar de nul-sentinel staat (`kwaliteit.md` §3; `minuut.NUL_IS_AFWEZIG`). Dekking hoort per
  kolom en per combinatie die een vraag nodig heeft, niet per meetgroep (`ontwerp-interpolatie-en-dekking.md` §5).
- **Dode warmtepompkanalen:** 39 van de 174 locaties halen over de hele periode geen 200 W op
  `heatpump_power` terwijl de warmtemeter wel levert; sluit ze uit van elke COP- of opdeelanalyse
  (`kwaliteit.md` §2). Het projectrapport noemt 40 woningen met een aansluitfout op die meting
  (Eindrapportage, p. 29).

## 8. Hoe te laden

De kwartiertabellen zijn gewone Parquet-bestanden. `derived` en `measurements` zijn elk ruim 200 MB;
lees alleen de kolommen die je nodig hebt:

```python
import pandas as pd

homes = pd.read_parquet("data/processed/homes.parquet")
derived = pd.read_parquet(
    "data/processed/derived.parquet",
    columns=["home_id__str", "tijdstip_start", "p_warmtepomp__W", "q_geleverd__W"],
)
quality = pd.read_parquet("data/processed/quality.parquet")
cop_bruikbaar = derived.merge(quality, on=["home_id__str", "tijdstip_start"])
cop_bruikbaar = cop_bruikbaar[~cop_bruikbaar["bron_incompleet__bool"].fillna(True)]
```

De minuutdata per locatie, of alle locaties met een filter:

```python
import pyarrow.dataset as ds

een = pd.read_parquet("<uitvoermap>/metingen/location_id=W5J0QUUq.parquet")
alle = ds.dataset("<uitvoermap>/metingen", format="parquet")
tabel = alle.to_table(
    columns=["home_id__str", "tijdstip_start", "p_warmtepomp_gemeten__W", "q_geleverd_gemeten__W"],
    filter=ds.field("home_id__str") == "W5J0QUUq",
)
```

Tijdkolommen komen binnen als `datetime64[..., Europe/Amsterdam]`; `.dt.tz_convert("UTC")` geeft het
bron-instant (§4). Een lege vlag in `quality` is `pd.NA`: vergelijk expliciet in plaats van op
waarheid te filteren.

`datapackage.json` (§10) beschrijft alle tabellen machineleesbaar, met kolomtypen, beschrijvingen en
primaire sleutels.

**Uitvoercontractversies:** kwartierpad `2026-09-22-teller-artefacten`
(`chunking.UITVOER_CONTRACT_VERSIE`, zit in de vingerafdruk van `parts/plan.json`), minuutpad
`2026-09-24-lokale-tijd` (`minuut.MINUUT_CONTRACT_VERSIE`, in `contract.json`). Die gaan omhoog zodra
de vorm of betekenis van de uitvoer verandert; het minuutpad weigert te hervatten in een map met een
ander contract (`minuut.controleer_contract`).

## 9. Bekende beperkingen, privacy en open vragen

**Privacy.** De woningsleutels zijn willekeurige pseudoniemen en de woningkenmerken zijn in klassen
gepubliceerd (Eindrapportage, p. 14). Deze uitvoer bevat dezelfde gegevens per woning als de bron:
`homes` (jaarverbruik, kenmerken), `weer.weerstation_nr` via de koppeling in `derived`, en de standen in
`measurements` en `metingen`. Publiceer daarom geen tabellen per woning; zie `GEBRUIKSVOORWAARDEN.md`
voor wat wel gedeeld mag worden.

**Meetopstelling en brondata.**

- De warmtemeter meet niet overal wat het rapport zegt: 16 locaties gedragen zich als meting op alleen
  de warmtepomp en 16 zijn onbeslist (§3, §6.2).
- 39 dode warmtepompkanalen in de minuutdata, 40 woningen met een aansluitfout volgens het rapport
  (§7.3); `elektrameting_verdacht__cat` geeft het oordeel van de projectuitvoerder per woning.
- De Sonoff-kamersensor is niet erg nauwkeurig en niet overal zorgvuldig geplaatst (§3).
- De momentane kolommen van het kwartierpad zijn steekproeven: niet middelen tot energie
  (`ontwerp-preprocessing.md` §2.2). Het temperatuurverschil tussen aanvoer en retour is klein, en dat
  beperkt elke COP (`ontwerp-intervalsemantiek.md` §4.7).
- De tellerstanden in de minuutbron zijn float32; bij hoge standen is het raster grover dan de meter
  (§6.2; `ontwerp-preprocessing-minuut-geheugen.md` §6.5 voor de risicolijst).
- De minuutdata begint op 25-11-2021, ruim een maand vóór de openbare kwartierset (§1).

**Keuzes van deze preprocessing.**

- `scheef__bool` rust op een drempel van 5 minuten die een voorstel uit het ontwerp is, niet extern
  bevestigd (`timestamps.SCHEEF_DREMPEL`, commentaar).
- Een kwartier met alleen een kamermeting krijgt geen rij in `measurements`/`derived`
  (`ontwerp-preprocessing.md` §5.1).
- Gas wordt omgerekend met een landelijk gemiddelde, want er is geen netgebied per woning
  (`ontwerp-preprocessing.md` §2.4). Het minuutpad rekent gas helemaal niet om naar W
  (`ontwerp-preprocessing-minuut.md` §11).
- Meterwissels worden gevlagd, niet gerepareerd (`ontwerp-preprocessing-minuut.md` §11;
  `docs/variable-dictionary.md`, "quality").
- `teller_terug__bool` verschilt tussen de paden (§7.2).
- `uitval_na__bool` gaat aan vanaf 1440 ontbrekende minuten na de rij (`delta_t__s` > 86.400 s), terwijl
  `gaten.soort` pas `uitval` zegt bij meer dan 1440 ontbrekende minuten. Een gat van precies 1440 minuten
  is dus `uitval_na__bool` maar `hapering` (`minuut._Streamend.blok`, `minuut.bouw_gaten`).

**Open.**

- `datapackage.json` staat pas in de uitvoermappen na de eerstvolgende run van elk pad; tot die tijd
  schrijft `python -m dph_preprocessing.datapackage --onderdeel kwartier --pad data/processed/datapackage.json`
  hem zonder iets te herberekenen.
- De primaire sleutels in het datapackage volgen uit de code, niet uit een telling op de volledige
  uitvoer (§10).

## 10. Datapackage (machineleesbare beschrijving)

`datapackage.json` beschrijft de uitvoer volgens de
[Frictionless Data Package-standaard](https://datapackage.org/): per tabel een Table Schema met
kolomnamen, typen, beschrijvingen en primaire sleutel, plus licentie en herkomst. Het wordt **uit de
code gegenereerd** (`dph_preprocessing.datapackage`), uit de referentieschema's in
`dph_preprocessing.uitvoerschema`, niet met de hand bijgehouden. Er zijn drie kopieën:

- het kwartierpad schrijft aan het eind van `pipeline.run` een `datapackage.json` met zijn zes tabellen
  in zijn uitvoermap;
- het minuutpad schrijft aan het eind van `minuut.run` een `datapackage.json` met zijn vier tabellen in
  zijn uitvoermap, met het aantal metingenbestanden in de titel;
- de kopie in de repo-root beschrijft beide samen; per resource zegt `uitvoerpad` bij welke map hij
  hoort. Regenereren: `python -m dph_preprocessing.datapackage`.

De licentie verwijst naar `GEBRUIKSVOORWAARDEN.md`: de data is niet vrij herverspreidbaar. Het pad van
`metingen` is een patroon (`metingen/location_id=*.parquet`), geen lijst, want een lijst betekent in
Data Package "plak aan elkaar", en dat is voor Parquet geen geldig bestand. `primaryKey` staat bij elke
tabel, met in `primaryKeyOnderbouwing` waarom de code hem uniek maakt; bij `dekking` geldt dat pas na
een nieuwe run (§6).

`tests/test_datapackage.py` borgt dat het niet uit de pas loopt: elk veld van een referentieschema staat
in het datapackage en omgekeerd; beide pijplijnen schrijven op een synthetische bron precies die
schema's en hun eigen `datapackage.json`; de kopie in de repo-root is gelijk aan wat de code bouwt; en
alle drie de varianten zijn structureel geldig volgens `frictionless` (overgeslagen als dat pakket niet
geïnstalleerd is; het zit in de `dev`-extra).

## 11. Bronnen

**Projectrapporten**

- Cool, P. (2024, augustus). *Eindrapportage Demonstratieproject Hybride Warmtepompen*.
  Demonstratieproject Hybride warmtepompen in de gebouwde omgeving, ref. 2021-53403. Stichting Smart
  Energy Foundation, namens de Vereniging voor Duurzame Warmte; resultaten geverifieerd door de
  Universiteit Twente. © Vereniging Duurzame Warmte, 2025. In deze catalogus: "Eindrapportage", met
  paginanummer (voettekst "N / 113"). De Engelse vertaling draagt op de omslag 3 juni 2025.
- Cool, P. (2024, september). *Twee winters met tweehonderd hybrides. Conclusies van een cruciaal
  demonstratieproject voor de warmtetransitie*. Vereniging voor Duurzame Warmte. Een samenvatting van
  de eindrapportage zonder eigen meetgegevens; voor deze catalogus niet nodig gebleken als aparte bron.
- KITE (Kennis- en Dataplatform Individuele Technieken), RVO. Projectpagina *Demo Project Hybride*,
  community op <https://kennisdelen.rvo.nl/>. Letterlijke citaten over licentie en meldplicht in
  `GEBRUIKSVOORWAARDEN.md`.
- `readme en licentie.txt` en `metadata.csv` in `demoprojecthybride-dataset.zip`; `notebooks/README.md` in
  het analysepakket van de projectuitvoerder (`GEBRUIKSVOORWAARDEN.md`; `docs/variable-dictionary.md`).

**Documenten in deze repo**

- [`GEBRUIKSVOORWAARDEN.md`](../GEBRUIKSVOORWAARDEN.md): licentie, meldplicht, verkrijgen van de data.
- [`README.md`](../README.md): overzicht, tijdconventie en de zomertijdcontrole van 24-09-2026.
- [`ontwerp-preprocessing.md`](../ontwerp-preprocessing.md): kwartierpad, bevindingen over de brondata,
  ontwerpprincipes, gaskwaliteit.
- [`ontwerp-intervalsemantiek.md`](../ontwerp-intervalsemantiek.md): intervalregel, vooruit
  differentiëren, KNMI-verschuiving, steekproefkolommen.
- [`ontwerp-teller-artefacten.md`](../ontwerp-teller-artefacten.md): initialisatietelegram, nulmeting,
  tellerwissel.
- [`ontwerp-extractie.md`](../ontwerp-extractie.md): de per-minuut-extractie en haar schema.
- [`ontwerp-preprocessing-minuut.md`](../ontwerp-preprocessing-minuut.md): het minuutpad.
- [`ontwerp-preprocessing-minuut-geheugen.md`](../ontwerp-preprocessing-minuut-geheugen.md): streamend
  verwerken en het float32-raster.
- [`ontwerp-interpolatie-en-dekking.md`](../ontwerp-interpolatie-en-dekking.md): overbruggingsgrenzen en
  `dekking.parquet`.
- [`docs/variable-dictionary.md`](variable-dictionary.md): ruw naar gestandaardiseerd, kolom voor kolom.
- [`docs/data-quality.md`](data-quality.md): kwaliteitsrapport van de kwartierrun, door de pijplijn
  geschreven.
- `kwaliteit.md` in de uitvoermap van de minuutrun van 24-09-2026, door die run geschreven (niet in
  git, net als de rest van de uitvoer).

**Code** (`src/dph_preprocessing/`): `pipeline.py`, `tabellen.py`, `quality.py`, `tellers.py`,
`timestamps.py`, `gaskwaliteit.py`, `chunking.py`, `minuut.py`, `minuut_dekking.py`, `minuut_raster.py`,
`uitvoerschema.py`, `datapackage.py`. Waar hierboven een functie of constante genoemd wordt, staat de
regel daar.
