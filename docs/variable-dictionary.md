# Variabelenwoordenboek: ruw → gestandaardiseerd

Van de kolomnamen van de Smart Energy Foundation naar de
[`physiquant__unit`](https://github.com/energietransitie/physiquant__unit)-conventie, zoals ook de
afnemende repo die gebruikt. **Waar de grootheid dezelfde is als in de Installatiemonitor 3.0, is de
naam ook dezelfde** — dat is het hele punt: een analyse die op IM3 draait moet met minimale
wijziging op DPH draaien.

Notatie: `naam__eenheid`, met `__0` voor dimensieloos, `__str`/`__cat`/`__bool` voor niet-fysische
typen. Bron van de ruwe namen en eenheden: `metadata.csv` in de dataset.

## Sleutels en tijd

| ruw | onze naam | type | opmerking |
|---|---|---|---|
| `location_id` | `home_id__str` | str | zelfde naam als IM3. **Let op:** in `household.csv` heet deze kolom `participant_id` — de dataset is daar niet consistent |
| `timestamp` | `tijdstip_start` | datetime, tz-aware `Europe/Amsterdam` | **afgeleid**: `floor(tijdstip, 15min)`, zie ontwerp §2.1 |
| `timestamp` | `tijdstip_meting` | datetime, tz-aware `Europe/Amsterdam` | de originele tijdstempel, bewaard om de scheefheid zichtbaar te houden |

De ruwe tijdstempels zijn UTC (ontwerp §2.3) en de pijplijn rekent intern in UTC; pas bij het
wegschrijven gaat elke tijdkolom naar `Europe/Amsterdam`. Dat verandert het moment niet, alleen de
weergave: `.dt.tz_convert("UTC")` geeft exact de ruwe waarde terug. Het minuutpad doet hetzelfde.
| `station_code` | `weerstation_nr` | str | zelfde naam als IM3 |

## `homes` — uit `household.csv`

| ruw | onze naam | opmerking |
|---|---|---|
| `house_type` | `woningtype__cat` | |
| `construction_year` | `bouwjaar_klasse__cat` | klassen van 20 jaar, niet het jaar zelf |
| `surface` | `oppervlak_klasse__cat` | klassen van 50 m² |
| `energylabel` | `energielabel__cat` | |
| `number_of_inhabitants` | `bewoners__cat` | `'1'` of `'2+'`, dus geen getal |
| `ownership` | `eigendom__cat` | particulier of woningcorporatie |
| `gas_before_2` | `gas_voor_2__m3` | jaarverbruik ~2 jaar vóór installatie |
| `gas_before_1` | `gas_voor_1__m3` | jaarverbruik ~1 jaar vóór installatie |
| `electricity_before_2` | `elektra_voor_2__kWh` | |
| `electricity_before_1` | `elektra_voor_1__kWh` | |
| `has_low_heat_floor_heating` | `heeft_vloerverwarming__bool` | |
| `has_high_heat_radiator_heating` | `heeft_radiatoren__bool` | |
| `has_gas_furnace` | `heeft_gasfornuis__bool` | 1 = gas, 0 = inductie |
| `has_double_paned_glass` | `heeft_dubbelglas__bool` | ten minste dubbel |
| `has_roofinsulation` | `heeft_dakisolatie__bool` | |
| `has_wallinsulation` | `heeft_muurisolatie__bool` | |
| `has_floorinsulation` | `heeft_vloerisolatie__bool` | |
| `wrong_elec_measurement` | `elektrameting_verdacht__cat` | **staat niet in `metadata.csv`**, wel in de data en wél beschreven in `notebooks/README.md` van het analysepakket: `0` = de elektriciteitsmeting van de wármtepomp is bruikbaar, `1` = onbruikbaar (die woningen verbruiken nooit meer dan ~100 W), `2` = tijdens het project gerepareerd — hun notebook 5 geeft vanaf wanneer. De projectuitvoerder noemt dit zelf het grootste probleem in de dataset. **Let op: deze kolom ontbreekt nu in `homes.parquet`**; zie ontwerp §8, A2 |

> **De kolomnamen in `heatpump.csv` en `boiler.csv` zijn kaal.** Ze heten daar `power`, `voltage`,
> `current` en `energy` — niet `heatpump_power` en `boiler_power` zoals `metadata.csv` (en de eerste
> versie van dit document) suggereren. De twee bestanden zijn dus alleen uit elkaar te houden via de
> **bestandsnaam**. Geverifieerd bij de implementatie op 05-09-2026.

## `measurements` — cumulatieve meterstanden

Alleen tellers. Hieruit wordt `derived` berekend; zie ontwerp §2.2 voor waarom de momentane
kolommen daar níét voor gebruikt worden.

`_cum` vóór de eenheid markeert dat de kolom een **toestand op een moment** is, geen
intervalwaarde: een meterstand, niet een gemiddelde over een kwartier. Het bijbehorende tijdstip
is `tijdstip_meting`, niet `tijdstip_start` — die laatste is hier uitsluitend de roostersleutel.
Zie `ontwerp-intervalsemantiek.md` §6.

| ruw | bestand | ruwe eenheid | onze naam |
|---|---|---|---|
| `e_consumed_low` | dsmr | kWh | `e_import_laag_cum__kWh` |
| `e_consumed_high` | dsmr | kWh | `e_import_hoog_cum__kWh` |
| `e_delivered_low` | dsmr | kWh | `e_export_laag_cum__kWh` |
| `e_delivered_high` | dsmr | kWh | `e_export_hoog_cum__kWh` |
| `v_gas_consumed` | dsmr | m³ | `g_gebruik_cum__m3` — zelfde naam als IM3 |
| `energy` | heatpump | kWh | `e_warmtepomp_cum__kWh` |
| `energy` | boiler | kWh | `e_ketel_cum__kWh` |
| `e_thermal_system` | kamstrup | GJ | `q_geleverd_cum__J` — ×10⁹ |

## `derived` — gemiddeld vermogen per kwartier

De tabel om energiebalansen op te baseren. Vermogens zijn **intervalgemiddelden**, berekend uit het
verschil van de tellers gedeeld door de werkelijke intervalduur — net als IM3's `e_net__W`.

| herkomst | onze naam | omrekening |
|---|---|---|
| `e_consumed_*` − `e_delivered_*` | `e_net__W` | zelfde definitie als IM3 |
| `v_gas_consumed` | `g_gebruik__W` | **niet zomaar "zelfde als IM3"**: van m³ naar W vergt een calorische waarde, en die staat niet in de dataset. Wij gebruiken de werkelijke, per uur gepubliceerde waarde (`actual_gas_std_hhv__J_m_3` hieronder), met een vaste terugvalwaarde van 35,17 MJ/m³. Zie ontwerp §2.4 |
| `heatpump_energy` | `p_warmtepomp__W` | |
| `boiler_energy` | `p_ketel__W` | elektrisch verbruik van de ketel, **niet** het gas |
| `e_thermal_system` | `q_geleverd__W` | |

Plus twee kolommen die niet uit een ruwe kolom komen maar uit de gaskwaliteit-ingest
(`gaskwaliteit.py`), zodat de omrekening van gas na te rekenen is:

| onze naam | type | wat het is |
|---|---|---|
| `actual_gas_std_hhv__J_m_3` | `float32` | de calorische waarde die op deze rij is toegepast: landelijk gemiddelde per uur over de netgebieden met Groningen-kwaliteit gas (`mijnenergiedata.nl`, EDSN en de netbeheerders). Zelfde naam als in IM3. Nooit leeg |
| `gas_hhv_bron__cat` | `category` | `"mijnenergiedata_actueel"` of `"vast_gemiddelde_fallback"` (35,17 MJ/m³). Het kwaliteitsrapport telt per run hoe vaak elk voorkwam, want een terugval ziet er in de uitvoer hetzelfde uit als een geslaagde ophaal |

## `derived` — momentane steekproeven

Wél meegenomen, met een naam die zegt wat het is: `_meting` markeert een steekproef op één moment,
geen intervalgemiddelde. Bruikbaar voor bedrijfspuntanalyse, niet voor energie.

| ruw | bestand | ruwe eenheid | onze naam |
|---|---|---|---|
| `t_supply` | kamstrup | °C | `temp_aanvoer_meting__degC` — zie `ontwerp-intervalsemantiek.md` §4.5 over tapwaterinterferentie |
| `t_return` | kamstrup | °C | `temp_retour_meting__degC` — idem |
| `f_system` | kamstrup | L/h | `debiet_meting__dm3_s_1` — ÷3600 |
| `p_thermal_system` | kamstrup | kW | `q_geleverd_meting__W` — ×1000 |
| `power` | heatpump | W | `p_warmtepomp_meting__W` |
| `power` | boiler | W | `p_ketel_meting__W` |
| `temperature` | room | °C | `temp_binnen_meting__degC` — spiegelt IM3's `temp_buiten__degC` |
| `humidity` | room | % | `rv_binnen_meting__0` — ÷100 |
| `p_consumed_L1..L3` | dsmr | kW | `p_import_L1..L3_meting__W` — ×1000 |
| `p_delivered_L1..L3` | dsmr | kW | `p_export_L1..L3_meting__W` — ×1000 |
| `u_L1..L3` | dsmr | V | `u_L1..L3_meting__V` |
| `i_L1..L3` | dsmr | A | `i_L1..L3_meting__A` |

## `weer` — uit `knmi.csv`

Dezelfde drie grootheden als IM3's `weer`, met dezelfde namen. De overige twintig KNMI-velden gaan
niet mee: wat niet in het model gaat, hoort niet in het contract. Ze blijven in de ruwe CSV.

| ruw | ruwe eenheid | onze naam | omrekening |
|---|---|---|---|
| `T` | 0,1 °C | `temp_buiten__degC` | ÷10 |

> **De KNMI-uurreeks is eind-gelabeld** (`HH=1` is het uur 00:00–01:00). Wij trekken er één uur af
> zodat `tijdstip_start` ook hier het begin van het interval is. Bewezen tegen een onafhankelijke
> KNMI-ophaal; zie `ontwerp-intervalsemantiek.md` §3.

| `FH` | 0,1 m/s | `wind__m_s_1` | ÷10 |
| `Q` | J/cm² per uur | `ghi__W_m_2` | ×2,7778 (10⁴ J/m² gedeeld door 3600 s); een gemiddelde instraling, dus een flow |

## `quality` — één `__bool` per controle

`ontbrekend__bool`, `scheef__bool`, `teller_initialisatie__bool`, `teller_nulmeting__bool`,
`teller_wissel__bool`, `teller_terug__bool`, `teruglevering__bool`, `teller_sprong__bool`,
`bron_incompleet__bool`. Zie ontwerp §5 en `ontwerp-teller-artefacten.md` §4/§7 voor de laatste vier.

**Drie afzonderlijke teller-artefacten** (`ontwerp-teller-artefacten.md`), elk met een eigen ingreep:

- `teller_initialisatie__bool`: het DSMR-initialisatietelegram van vóór de P1-koppeling, herkend op
  de handtekening van vijf sentinelwaarden TEGELIJK (`tellers.INITIALISATIETELEGRAM_SENTINEL`;
  herkomst: eerste rij van `dsmr.csv`, woning `-ORiFQC6`, 2022-02-07T11:10:58). De vijf tellerstanden
  op die rij gaan op `NaN` vóór het differentiëren, op elke positie in de reeks.
- `teller_nulmeting__bool`: uitval met herstel -- de stand valt terug naar 0 en komt later terug op
  (ongeveer) zijn oude spoor. Criterium: de teller heeft eerder al boven 1 gestaan (lopend maximum).
  BEIDE aangrenzende intervallen gaan op `NaN`, niet alleen de overgangsrij: elke rij in een
  langdurige 0-periode is een even ongeldige aflezing als de eerste.
- `teller_wissel__bool`: een echte breuk -- de stand valt terug naar iets anders dan 0 (of naar 0 bij
  een teller die nooit boven 1 kwam), typisch een vervangen meter. Alleen het ENE betrokken interval
  (niet de stand) gaat op `NaN`; er is bewust GEEN segmentgebaseerde reparatie (`ontwerp-preprocessing-
  minuut.md` §11, `docs/analyse-bevindingen.md` A4).

`teller_terug__bool` is de optelling (OR) van `teller_nulmeting__bool` en `teller_wissel__bool`, over
de acht echte bronttellers (`e_import_laag/hoog_cum__kWh`, `e_export_laag/hoog_cum__kWh`,
`g_gebruik_cum__m3`, `e_warmtepomp_cum__kWh`, `e_ketel_cum__kWh`, `q_geleverd_cum__J`), niet over de
samengestelde `e_net`: die mag legitiem dalen bij teruglevering van zonnestroom (ontwerp §8, B3).
`teruglevering__bool` (een exportteller stijgt dit kwartier) maakt dat gegeven apart bruikbaar in
plaats van het te laten verdwijnen in `teller_terug__bool`.

Alle drie de nieuwe/gewijzigde vlaggen bestaan sinds `UITVOER_CONTRACT_VERSIE
"2026-09-22-teller-artefacten"` ook in het kwartierpad. In het minuutpad bestonden
`teller_nulmeting__bool`/`teller_terug__bool`/`teller_wissel__bool` al identiek (M1:
`teller_initialisatie__bool` is niet nodig, de sentinel komt daar niet voor); het minuutpad maskeert
sindsdien ook het ene `teller_wissel__bool`-interval, wat het eerder wel vlagde maar niet maskeerde.
