# Analysebevindingen

**Gegenereerd door** `dph_preprocessing.analyses`, uit de Parquet-tussenresultaten in `data/analyse/` (niet handmatig bijgehouden). Beantwoordt groep A en groep B uit `ontwerp-preprocessing.md` §8.

> **Dit is de volledige dataset** (174 woningen).

Elke analyse hieronder rekent EERST per woning, dan pas gepoold (ontwerpprincipe 7): één woning met extreme uitschieters mag een gepoolde conclusie niet vertekenen -- zie `ontwerp-intervalsemantiek.md` §5.

## A1. Warmtepompteller: uitschieters

**Vraag**: correleert `p_warmtepomp__W` (teller) met `p_warmtepomp_meting__W` (momentaan) per woning, en bij hoeveel woningen komen fysisch onmogelijke waarden (>50 kW) voor?

n=174 woningen, gemiddelde=0,875, mediaan=0,931, spreiding p10-p90=0,707..0,965, min=-0,009, max=0,994 (correlatie)
- Woningen met >=1 waarde boven de fysische grens (50 kW) in de teller: 3 van 174 (1,7 %).
- Woningen met een correlatie < 0,5 (teller vs. momentaan): 5 van 174 (2,9 %).

Tien meest afwijkende woningen (laagste correlatie):

| home_id | corr | p99 teller (W) | max teller (W) | max meting (W) | n>50kW teller |
|---|---:|---:|---:|---:|---:|
| 0XvCtU3v | -0,009 | 1812 | 12.312.980 | 226.876 | 20 |
| di1C3DT- | -0,002 | 4 | 8 | 5 | 0 |
| UkhY0kLf | 0,000 | 76 | 3.185.136 | 13.446 | 2 |
| LyD1Zpmn | 0,006 | 1428 | 9.660.204 | 1839 | 2 |
| ooQJGe15 | 0,403 | 48 | 132 | 165 | 0 |
| 9H8W2b5Q | 0,509 | 36 | 76 | 86 | 0 |
| vtBLsHpC | 0,512 | 28 | 40 | 86 | 0 |
| 1WyeUbFg | 0,528 | 28 | 44 | 84 | 0 |
| ib2L3SnU | 0,532 | 28 | 40 | 83 | 0 |
| I3v9SmRO | 0,571 | 20 | 40 | 80 | 0 |

**Conclusie**: de warmtepompteller deugt bij de grote meerderheid. De mediane correlatie tussen teller en momentane meting is 0,931; 3 van 174 (1,7 %) van de woningen heeft waarden boven de fysische grens en 5 van 174 (2,9 %) heeft een correlatie onder 0,5. Dat is te weinig om een punt voor de mail aan KITE van te maken: het gaat om losse installaties, niet om de dataset. Ze horen wel uit de populatie vóór er een COP op gebaseerd wordt (pre-registratie §4, filter 3).

## A5. Lopen de vier meetbronnen op dezelfde klok?

**Vraag**: verschilt de mediane scheefheid systematisch per bron? Dit is de aanname onder elke COP-per-bedrijfspunt-berekening ("alle vier aanwezig" == "tegelijk gemeten").

| bron | mediaan van de mediane scheefheid (s) | spreiding over woningen (mediaan, p10-p90) |
|---|---:|---|
| boiler | 2,0 | n=174 woningen, gemiddelde=2,01 s, mediaan=2 s, spreiding p10-p90=2 s..2 s, min=2 s, max=3 s |
| dsmr | 5,0 | n=174 woningen, gemiddelde=9,22 s, mediaan=5 s, spreiding p10-p90=5 s..5 s, min=2 s, max=366 s |
| heatpump | 2,0 | n=174 woningen, gemiddelde=2,1 s, mediaan=2 s, spreiding p10-p90=2 s..2 s, min=2 s, max=18 s |
| kamstrup | 2,0 | n=174 woningen, gemiddelde=2,1 s, mediaan=2 s, spreiding p10-p90=2 s..2 s, min=2 s, max=18 s |

**Conclusie**: dit zijn **niet één maar meerdere loggers**. `dsmr` meet mediaan 5,0 s na de kwartiergrens en `boiler` 2,0 s -- een verschil van 3,0 s. Bronnen met dezelfde mediaan worden vermoedelijk in één slag uitgelezen. "Alle vier aanwezig" betekent dus niet letterlijk "tegelijk gemeten", maar op een kwartier van 900 s is 0,33 % van het interval verwaarloosbaar voor een COP per bedrijfspunt.

## A6. Is uitval per bron of per woning?

**Vraag**: is een ontbrekend kwartier een dataloggerstoring (alle vier bronnen ontbreken) of een sensorprobleem (precies één bron ontbreekt)?

| home_id | alle vier ontbrekend | precies één ontbrekend |
|---|---:|---:|
| -B51sQOp | 18.209 | 6511 |
| -ORiFQC6 | 1888 | 0 |
| -uFUg8jU | 18.093 | 128 |
| 0RQyG6WX | 2166 | 2415 |
| 0XvCtU3v | 10.473 | 73 |
| 0_6TUlP4 | 8815 | 11.280 |
| 0rE1EXuT | 52.489 | 5863 |
| 0z5clxou | 16.621 | 4 |
| 141Q2Shj | 3650 | 1 |
| 1WyeUbFg | 13.940 | 6 |
| 1Y5XKgSd | 38.564 | 43.612 |
| 1uGr4CK2 | 31.556 | 0 |
| 2L97t6LT | 179 | 35 |
| 2aE7xTqC | 14.537 | 21 |
| 3QryrLjd | 14.789 | 0 |
| 3V2aOh4L | 175 | 3279 |
| 3WCT0MF1 | 2108 | 2 |
| 3c1fUm5M | 1083 | 7 |
| 3jcFOgZ5 | 41.569 | 339 |
| 3voUJ8cb | 3169 | 11.635 |
| 46no-WLf | 4487 | 1924 |
| 4OnYOkIn | 26.843 | 7010 |
| 4iyux5_5 | 8173 | 9895 |
| 5GCcwjbF | 7131 | 19.699 |
| 5NNgThim | 27.910 | 37 |
| 5QvgGmut | 26.259 | 22 |
| 5n48RmBE | 18.069 | 4071 |
| 6-gOUJps | 12.822 | 9 |
| 66lZ2dKl | 34.648 | 0 |
| 6U_ZxCz7 | 27.180 | 23 |
| 6oWZr5LM | 30.499 | 6 |
| 6pd9A10u | 13.112 | 3 |
| 6sdsV762 | 6200 | 81 |
| 7JgOwuUh | 12.142 | 1 |
| 7iTwZNm7 | 52.102 | 3 |
| 9-agjI3L | 1801 | 20 |
| 96H2Z6-Y | 31.638 | 8494 |
| 9H8W2b5Q | 14.949 | 3 |
| 9LFZHK7q | 1774 | 235 |
| 9SiQCg0b | 27.630 | 617 |
| A0JoUuz- | 7864 | 1 |
| B4oZ6JEm | 27.043 | 77 |
| BdMf5w-N | 3365 | 19 |
| CbPETsjw | 32.242 | 32.992 |
| D8ZSj9yG | 19.682 | 5 |
| Dduwcofx | 11.513 | 0 |
| Di0nyhC7 | 30.118 | 7901 |
| DlCdUGP1 | 23.040 | 13.311 |
| DsPYyuTY | 4404 | 0 |
| EyZIyLSP | 8853 | 95 |
| FFOpKdF2 | 9586 | 9497 |
| GDO9C-2s | 16.198 | 6029 |
| GMbBE51s | 31.240 | 7921 |
| GdemEVzZ | 10.418 | 16 |
| GjGxfcOD | 29.259 | 380 |
| H6PEe0lX | 9869 | 204 |
| HedOCi6L | 14.400 | 4 |
| HuOvEokt | 14.753 | 6 |
| I3v9SmRO | 30.880 | 23.283 |
| IF9c6c-H | 34.441 | 45.966 |
| J1bBIrb_ | 6186 | 5 |
| JEZzJ1_- | 14.699 | 0 |
| JqpjoDDU | 33.889 | 1 |
| Jr9PJjgK | 37.196 | 39.021 |
| JyqIksBN | 15.916 | 1 |
| KR2H1ovj | 17.369 | 0 |
| Kwb9DHh8 | 19.438 | 37 |
| Lm4kAwHz | 27.744 | 1 |
| Lo8oUUaQ | 28.405 | 318 |
| LyD1Zpmn | 46.224 | 2174 |
| LzZTAYkZ | 34.599 | 1 |
| MBelxm3z | 14.589 | 2398 |
| MNbpwIxe | 13.037 | 105 |
| MPjpuY8a | 30.652 | 48 |
| MT_lo4kd | 14.800 | 300 |
| Mz219wDb | 7879 | 343 |
| Nkw-o7MK | 14.248 | 15.669 |
| OMa7vZ0x | 34.098 | 1463 |
| OnRTARXf | 44.994 | 4559 |
| P1IrM5bq | 17.379 | 54 |
| PL238TVN | 10.394 | 0 |
| Q7c7Wak6 | 23.883 | 275 |
| Q_CTMAg9 | 38.451 | 32 |
| QtE_uvEX | 2570 | 3273 |
| QytoLUAL | 23.376 | 0 |
| RHON9wor | 8191 | 40 |
| RirVqJd3 | 28.837 | 31.121 |
| SDIPnuVt | 4137 | 2368 |
| SZphemL4 | 8210 | 177 |
| TkMyAOp1 | 23.629 | 14.135 |
| U-vtaXTk | 10.847 | 2 |
| UigJRsPF | 2772 | 173 |
| UkhY0kLf | 23.655 | 14.285 |
| VF54k5wO | 24.710 | 0 |
| W3lmQOBD | 29.231 | 646 |
| W5J0QUUq | 16.415 | 2 |
| WUAgbEiI | 13.444 | 3 |
| XmrgAM1Q | 6504 | 36 |
| Y6E5x8IP | 16.938 | 0 |
| Z5GVYH20 | 21.031 | 0 |
| Z5tUk-4t | 11.736 | 14.105 |
| ZzY3cd3h | 1548 | 29.345 |
| aGIM-uhc | 16.046 | 1 |
| aQ1RbqD6 | 10.203 | 1783 |
| b0-a0MJb | 12.345 | 4981 |
| bB9dwLYE | 6309 | 1 |
| bW_iJrKG | 10.377 | 517 |
| b_eXywsq | 16.252 | 250 |
| bep7sbGN | 13.328 | 870 |
| btF7zwOl | 2023 | 10.026 |
| cXHtdNjQ | 14.547 | 1524 |
| c_pkxwxm | 1683 | 61 |
| ccN0cg3e | 1756 | 0 |
| cfs3OE3j | 21.079 | 5816 |
| cggNkr7C | 16.944 | 25.535 |
| d7dbrO23 | 9146 | 37.753 |
| df79ygat | 1342 | 18.263 |
| di1C3DT- | 15.027 | 47.048 |
| diDdCX6N | 11.994 | 0 |
| e-V7pn_P | 9697 | 5 |
| e6Pc72sP | 26.854 | 1519 |
| e9WTomef | 12.690 | 199 |
| eS3U7RoL | 14.292 | 57 |
| eTBI5kYm | 5144 | 598 |
| ez7d4xNY | 14.310 | 0 |
| fEQuZl6P | 13.444 | 28.416 |
| frZKRmLD | 26.886 | 152 |
| g6cwpA70 | 26.288 | 1 |
| gfhTqPfk | 29.167 | 23 |
| gmtO-ZIa | 10.475 | 47.061 |
| h57Wozww | 29.451 | 3 |
| hRPmkwLs | 1018 | 0 |
| hlOONbvk | 8823 | 24 |
| ib2L3SnU | 11.653 | 13 |
| kKi5OIGx | 42.526 | 1291 |
| kaTMcjBU | 15.329 | 197 |
| l7_BBT0u | 8500 | 5773 |
| lVK0bORa | 4383 | 4455 |
| nPZwu5CK | 13.385 | 221 |
| nkMckb09 | 5617 | 53 |
| on1VMMTO | 32.721 | 1 |
| ooQJGe15 | 16.046 | 2260 |
| oqb_lZc9 | 4383 | 1 |
| pv_IsvbE | 7360 | 384 |
| qAVHYp3J | 26.881 | 1664 |
| qBr4JQ_w | 21.128 | 11.638 |
| qdC1C7Lx | 15.043 | 17.337 |
| rC_pkM3K | 5081 | 1 |
| sNLALR1w | 21.935 | 5 |
| tJM9KqTt | 16.917 | 0 |
| tZSnEgva | 9109 | 15.636 |
| tf9oJob7 | 13.045 | 581 |
| u3RHJ15y | 31.758 | 1 |
| uQLTOCT9 | 19.695 | 4 |
| uTJqSvxx | 2706 | 17 |
| uUFhBQzs | 23.872 | 3006 |
| ueGJf9d5 | 23.023 | 29.447 |
| uennkFAE | 6092 | 8010 |
| vAibnS26 | 28.468 | 8 |
| vtBLsHpC | 19.408 | 118 |
| w2fLs42F | 1622 | 1648 |
| wEqq3ifR | 9035 | 111 |
| wv6qC56z | 13.664 | 205 |
| xSDmm63y | 11.225 | 6323 |
| xURf3a0o | 134 | 1458 |
| y5TEbHnC | 4815 | 18.243 |
| yNmVF4oy | 2131 | 1212 |
| yV4lUIbS | 4525 | 4517 |
| yjpSQKFb | 16.983 | 8 |
| ywCyyxQF | 28.856 | 299 |
| yxOWx66O | 8009 | 800 |
| zK4WxULP | 44.599 | 2680 |
| zPZ3d57M | 13.884 | 15 |
| zskLB4tU | 27.462 | 10.137 |

**Conclusie**: over alle woningen samen 2.914.408 kwartier(en) waarin alle vier de bronnen ontbreken (dataloggerstoring), tegenover 843.852 kwartier(en) met precies één ontbrekende bron (sensor).

## B2. Sluit de energiebalans na het differentiëren?

**Vraag**: is `som(vermogen x delta_t)` gelijk aan `laatste stand - eerste stand`, per woning en per teller? Toetst of het differentiëren verliesvrij is.

| teller | n | gemiddelde | mediaan | p10 | p90 | min | max (relatieve afwijking) |
|---|---:|---:|---:|---:|---:|---:|---:|
| e_net__W | 169 | 24,88 % | -0,02 % | -98,76 % | 29,70 % | -1924,16 % | 8582,52 % |
| g_gebruik__W | 169 | -21,81 % | -0,05 % | -118,01 % | 0,43 % | -488,38 % | 1523,61 % |
| p_ketel__W | 174 | -0,56 % | -0,00 % | -1,41 % | 0,00 % | -23,46 % | 2,64 % |
| p_warmtepomp__W | 174 | -0,50 % | -0,00 % | -0,78 % | 0,00 % | -11,21 % | 0,00 % |
| q_geleverd__W | 171 | -0,51 % | -0,00 % | -0,68 % | 0,00 % | -10,96 % | 0,00 % |

Tien meest afwijkende (woning, teller)-combinaties:

| home_id | teller | relatieve afwijking | energie uit teller (J) | energie uit vermogen (J) |
|---|---|---:|---:|---:|
| OnRTARXf | e_net__W | 8582,52 % | 2,24e+08 | 1,94e+10 |
| 2aE7xTqC | e_net__W | -1924,16 % | -1,31e+09 | 2,38e+10 |
| -B51sQOp | g_gebruik__W | 1523,61 % | 1,21e+10 | 1,96e+11 |
| tZSnEgva | e_net__W | 1469,38 % | 9,91e+08 | 1,56e+10 |
| Nkw-o7MK | e_net__W | -1162,63 % | -3,13e+09 | 3,32e+10 |
| 96H2Z6-Y | e_net__W | 683,05 % | 4,11e+09 | 3,21e+10 |
| c_pkxwxm | e_net__W | -568,93 % | -1,44e+10 | 6,77e+10 |
| rC_pkM3K | g_gebruik__W | -488,38 % | -6,01e+09 | 2,33e+10 |
| ib2L3SnU | e_net__W | -446,10 % | -4,3e+09 | 1,49e+10 |
| HuOvEokt | e_net__W | 426,46 % | 5,19e+09 | 2,73e+10 |

**Conclusie**: de balans sluit voor de tellers die uit één bron komen en niet voor de samengestelde. Mediane absolute afwijking over alle (woning, teller)-paren: 0,01 %. Sluit goed (mediaan onder 1 %): `g_gebruik__W`, `p_ketel__W`, `p_warmtepomp__W`, `q_geleverd__W`. Wijkt af: `e_net__W`. Dat de afwijking zich concentreert bij `e_net__W` is geen toeval: dat is de enige SAMENGESTELDE teller (import min export). Bij een klein verschil tussen twee grote getallen werkt elk gat in één van beide door in de uitkomst, terwijl de andere vier rechtstreeks uit één bronreeks komen. Daar bovenop heeft de DSMR-bron per woning duidelijk minder complete kwartieren dan de andere drie (zie §1): een gat in één bron, terwijl de rij door een andere bron wel bestaat, breekt de balans van díé teller -- een kwartier dat bij ALLE bronnen ontbreekt doet dat niet. Zie de docstring van `analyse_b2_energiebalans`.

## B4. Verdeling van de gaten per grootheid

**Vraag**: hoe zijn de ontbrekende periodes per grootheid verdeeld over de zes bakken (<15 min ... >24 u)? Bepaalt de gatlimiet voor interpolatie.

Totale duur (uren) per grootheid en bak, gepoold over woningen (spreiding per woning staat in het Parquet-tussenresultaat):

| kolom | <15 min | 15-30 min | 30-90 min | 1,5-6 u | 6-24 u | >24 u |
|---|---:|---:|---:|---:|---:|---:|
| e_net__W | 0,0 | 1218,8 | 14.646,2 | 27.238,0 | 41.433,0 | 844.892,0 |
| g_gebruik__W | 0,0 | 1218,8 | 14.646,2 | 27.238,0 | 41.433,0 | 844.892,0 |
| ghi__W_m_2 | 0,0 | 1409,8 | 6403,8 | 13.552,5 | 22.216,2 | 762.232,2 |
| p_ketel__W | 0,0 | 1324,8 | 6507,8 | 13.972,5 | 23.017,2 | 713.184,8 |
| p_warmtepomp__W | 0,0 | 1329,2 | 6527,5 | 14.003,8 | 23.061,8 | 693.121,2 |
| q_geleverd__W | 0,0 | 1329,5 | 6528,2 | 14.013,5 | 23.041,8 | 693.123,5 |
| rv_binnen_meting__0 | 0,0 | 3574,5 | 12.607,8 | 25.308,5 | 39.437,5 | 793.517,0 |
| temp_aanvoer_meting__degC | 0,0 | 1459,2 | 6438,0 | 13.918,0 | 22.818,2 | 692.911,0 |
| temp_binnen_meting__degC | 0,0 | 3574,5 | 12.607,8 | 25.308,5 | 39.437,5 | 793.517,0 |
| temp_buiten__degC | 0,0 | 1411,5 | 6428,0 | 13.577,8 | 22.261,5 | 723.059,2 |
| temp_retour_meting__degC | 0,0 | 1459,2 | 6438,0 | 13.918,0 | 22.818,2 | 692.911,0 |
| u_L1_meting__V | 0,0 | 4249,2 | 13.669,5 | 27.199,8 | 39.190,2 | 837.078,8 |
| wind__m_s_1 | 0,0 | 1411,5 | 6424,0 | 13.577,8 | 22.261,5 | 723.247,2 |

**Conclusie**: de bak `<15 min` is op kwartierdata per definitie leeg -- het kortste waarneembare gat is precies 900 s -- en dat is zelf een bevinding, geen fout. Van de 387.706 gaten valt 65,3 % binnen anderhalf uur en 12,0 % boven de zes uur. De geërfde gatlimiet van NeedForHeat (90 minuten) dekt daarmee de meerderheid af en laat de lange uitval staan, wat de bedoeling is -- maar het blijft een overgenomen waarde. Welke limiet hier verdedigbaar is hoort uit een weglaattoets te komen en niet uit deze verdeling alleen: B12 in `ontwerp-preprocessing.md` §8.

## B5. Aaneengesloten bruikbare tijd per woning

**Vraag**: hoeveel van de tijd van elke woning is aaneengesloten bruikbaar (NeedForHeats `calculate_covered_time`/`calculate_streak_durations`, overgenomen op ons kwartierraster)?

n=174 woningen, gemiddelde=0,745, mediaan=0,781, spreiding p10-p90=0,525..0,958, min=0,00475, max=0,998 (aandeel gedekt)

| home_id | totale tijd (dagen) | gedekte tijd (dagen) | aandeel gedekt |
|---|---:|---:|---:|
| -B51sQOp | 569,9 | 380,4 | 66,8 % |
| -ORiFQC6 | 538,2 | 518,7 | 96,4 % |
| -uFUg8jU | 851,3 | 663,1 | 77,9 % |
| 0RQyG6WX | 446,7 | 426,8 | 95,5 % |
| 0XvCtU3v | 736,4 | 632,5 | 85,9 % |
| 0_6TUlP4 | 833,4 | 743,0 | 89,2 % |
| 0rE1EXuT | 863,6 | 316,8 | 36,7 % |
| 0z5clxou | 595,5 | 422,7 | 71,0 % |
| 141Q2Shj | 305,3 | 267,3 | 87,5 % |
| 1WyeUbFg | 700,4 | 556,1 | 79,4 % |
| 1Y5XKgSd | 870,4 | 468,8 | 53,9 % |
| 1uGr4CK2 | 865,5 | 537,0 | 62,0 % |
| 2L97t6LT | 686,3 | 684,8 | 99,8 % |
| 2aE7xTqC | 869,3 | 718,2 | 82,6 % |
| 3QryrLjd | 721,4 | 567,6 | 78,7 % |
| 3V2aOh4L | 570,4 | 568,8 | 99,7 % |
| 3WCT0MF1 | 644,5 | 622,8 | 96,6 % |
| 3c1fUm5M | 830,6 | 820,1 | 98,7 % |
| 3jcFOgZ5 | 531,1 | 102,1 | 19,2 % |
| 3voUJ8cb | 584,6 | 551,8 | 94,4 % |
| 46no-WLf | 578,4 | 531,9 | 92,0 % |
| 4OnYOkIn | 688,6 | 429,8 | 62,4 % |
| 4iyux5_5 | 688,5 | 606,7 | 88,1 % |
| 5GCcwjbF | 869,4 | 795,5 | 91,5 % |
| 5NNgThim | 847,8 | 558,9 | 65,9 % |
| 5QvgGmut | 690,5 | 423,7 | 61,4 % |
| 5n48RmBE | 592,6 | 410,1 | 69,2 % |
| 6-gOUJps | 595,5 | 465,4 | 78,2 % |
| 66lZ2dKl | 393,2 | 32,4 | 8,2 % |
| 6U_ZxCz7 | 848,5 | 566,6 | 66,8 % |
| 6oWZr5LM | 786,4 | 470,3 | 59,8 % |
| 6pd9A10u | 432,5 | 296,1 | 68,5 % |
| 6sdsV762 | 589,6 | 525,1 | 89,1 % |
| 7JgOwuUh | 350,8 | 224,4 | 64,0 % |
| 7iTwZNm7 | 868,5 | 328,1 | 37,8 % |
| 9-agjI3L | 560,5 | 542,1 | 96,7 % |
| 96H2Z6-Y | 869,5 | 546,2 | 62,8 % |
| 9H8W2b5Q | 326,1 | 170,6 | 52,3 % |
| 9LFZHK7q | 578,6 | 560,4 | 96,9 % |
| 9SiQCg0b | 869,3 | 581,6 | 66,9 % |
| A0JoUuz- | 797,7 | 716,1 | 89,8 % |
| B4oZ6JEm | 845,1 | 565,0 | 66,9 % |
| BdMf5w-N | 851,4 | 816,7 | 95,9 % |
| CbPETsjw | 837,4 | 502,0 | 59,9 % |
| D8ZSj9yG | 589,9 | 385,1 | 65,3 % |
| Dduwcofx | 612,4 | 492,7 | 80,5 % |
| Di0nyhC7 | 783,8 | 470,3 | 60,0 % |
| DlCdUGP1 | 566,2 | 325,2 | 57,4 % |
| DsPYyuTY | 578,5 | 532,8 | 92,1 % |
| EyZIyLSP | 388,2 | 296,1 | 76,3 % |
| FFOpKdF2 | 734,2 | 634,5 | 86,4 % |
| GDO9C-2s | 715,4 | 546,8 | 76,4 % |
| GMbBE51s | 872,5 | 553,0 | 63,4 % |
| GdemEVzZ | 850,1 | 742,6 | 87,4 % |
| GjGxfcOD | 708,0 | 403,2 | 57,0 % |
| H6PEe0lX | 694,4 | 591,9 | 85,2 % |
| HedOCi6L | 865,3 | 715,7 | 82,7 % |
| HuOvEokt | 638,3 | 485,0 | 76,0 % |
| I3v9SmRO | 834,6 | 515,7 | 61,8 % |
| IF9c6c-H | 840,4 | 482,5 | 57,4 % |
| J1bBIrb_ | 591,6 | 527,3 | 89,1 % |
| JEZzJ1_- | 688,0 | 535,1 | 77,8 % |
| JqpjoDDU | 598,6 | 245,6 | 41,0 % |
| Jr9PJjgK | 793,9 | 406,8 | 51,2 % |
| JyqIksBN | 718,4 | 552,7 | 76,9 % |
| KR2H1ovj | 298,6 | 117,6 | 39,4 % |
| Kwb9DHh8 | 533,0 | 334,1 | 62,7 % |
| Lm4kAwHz | 840,4 | 551,9 | 65,7 % |
| Lo8oUUaQ | 850,4 | 554,8 | 65,2 % |
| LyD1Zpmn | 868,4 | 392,2 | 45,2 % |
| LzZTAYkZ | 484,1 | 123,6 | 25,5 % |
| MBelxm3z | 522,3 | 370,5 | 70,9 % |
| MNbpwIxe | 689,6 | 554,0 | 80,3 % |
| MPjpuY8a | 872,4 | 553,2 | 63,4 % |
| MT_lo4kd | 715,6 | 561,6 | 78,5 % |
| Mz219wDb | 533,0 | 451,1 | 84,6 % |
| Nkw-o7MK | 701,3 | 553,6 | 78,9 % |
| OMa7vZ0x | 842,4 | 487,5 | 57,9 % |
| OnRTARXf | 865,6 | 407,7 | 47,1 % |
| P1IrM5bq | 715,4 | 534,5 | 74,7 % |
| PL238TVN | 275,9 | 167,9 | 60,9 % |
| Q7c7Wak6 | 700,3 | 465,1 | 66,4 % |
| Q_CTMAg9 | 716,3 | 315,8 | 44,1 % |
| QtE_uvEX | 687,6 | 661,1 | 96,2 % |
| QytoLUAL | 848,6 | 605,5 | 71,4 % |
| RHON9wor | 758,8 | 678,3 | 89,4 % |
| RirVqJd3 | 863,6 | 571,8 | 66,2 % |
| SDIPnuVt | 591,5 | 548,5 | 92,7 % |
| SZphemL4 | 868,5 | 783,4 | 90,2 % |
| TkMyAOp1 | 598,7 | 352,8 | 58,9 % |
| U-vtaXTk | 591,6 | 478,8 | 80,9 % |
| UigJRsPF | 279,2 | 250,6 | 89,8 % |
| UkhY0kLf | 850,6 | 605,3 | 71,2 % |
| VF54k5wO | 475,2 | 217,9 | 45,8 % |
| W3lmQOBD | 844,3 | 539,9 | 63,9 % |
| W5J0QUUq | 850,5 | 679,9 | 79,9 % |
| WUAgbEiI | 689,4 | 549,6 | 79,7 % |
| XmrgAM1Q | 704,9 | 657,7 | 93,3 % |
| Y6E5x8IP | 517,9 | 341,5 | 65,9 % |
| Z5GVYH20 | 717,6 | 498,7 | 69,5 % |
| Z5tUk-4t | 613,4 | 491,4 | 80,1 % |
| ZzY3cd3h | 834,5 | 819,6 | 98,2 % |
| aGIM-uhc | 596,6 | 429,7 | 72,0 % |
| aQ1RbqD6 | 844,5 | 740,9 | 87,7 % |
| b0-a0MJb | 760,7 | 637,8 | 83,8 % |
| bB9dwLYE | 844,6 | 779,2 | 92,3 % |
| bW_iJrKG | 836,6 | 729,3 | 87,2 % |
| b_eXywsq | 723,6 | 554,3 | 76,6 % |
| bep7sbGN | 717,4 | 578,7 | 80,7 % |
| btF7zwOl | 618,7 | 597,9 | 96,6 % |
| cXHtdNjQ | 706,3 | 555,0 | 78,6 % |
| c_pkxwxm | 848,6 | 831,7 | 98,0 % |
| ccN0cg3e | 585,4 | 567,2 | 96,9 % |
| cfs3OE3j | 603,0 | 384,5 | 63,8 % |
| cggNkr7C | 612,0 | 438,7 | 71,7 % |
| d7dbrO23 | 844,5 | 749,8 | 88,8 % |
| df79ygat | 682,1 | 668,4 | 98,0 % |
| di1C3DT- | 714,5 | 558,3 | 78,1 % |
| diDdCX6N | 694,4 | 569,7 | 82,0 % |
| e-V7pn_P | 848,6 | 748,5 | 88,2 % |
| e6Pc72sP | 594,1 | 314,4 | 52,9 % |
| e9WTomef | 602,4 | 470,4 | 78,1 % |
| eS3U7RoL | 724,4 | 575,8 | 79,5 % |
| eTBI5kYm | 865,3 | 812,0 | 93,8 % |
| ez7d4xNY | 869,4 | 720,7 | 82,9 % |
| fEQuZl6P | 869,5 | 729,7 | 83,9 % |
| frZKRmLD | 589,5 | 321,9 | 54,6 % |
| g6cwpA70 | 851,3 | 577,6 | 67,8 % |
| gfhTqPfk | 870,4 | 566,7 | 65,1 % |
| gmtO-ZIa | 599,4 | 490,4 | 81,8 % |
| h57Wozww | 837,5 | 531,0 | 63,4 % |
| hRPmkwLs | 610,1 | 599,7 | 98,3 % |
| hlOONbvk | 596,3 | 504,7 | 84,6 % |
| ib2L3SnU | 558,6 | 437,3 | 78,3 % |
| kKi5OIGx | 869,6 | 428,5 | 49,3 % |
| kaTMcjBU | 575,5 | 420,4 | 73,1 % |
| l7_BBT0u | 584,7 | 496,5 | 84,9 % |
| lVK0bORa | 865,6 | 820,2 | 94,8 % |
| nPZwu5CK | 591,4 | 455,9 | 77,1 % |
| nkMckb09 | 582,3 | 533,1 | 91,6 % |
| on1VMMTO | 871,3 | 530,7 | 60,9 % |
| ooQJGe15 | 714,5 | 547,6 | 76,6 % |
| oqb_lZc9 | 718,4 | 673,3 | 93,7 % |
| pv_IsvbE | 870,5 | 794,2 | 91,2 % |
| qAVHYp3J | 836,3 | 556,4 | 66,5 % |
| qBr4JQ_w | 612,4 | 392,7 | 64,1 % |
| qdC1C7Lx | 869,3 | 712,8 | 82,0 % |
| rC_pkM3K | 742,2 | 689,8 | 92,9 % |
| sNLALR1w | 723,5 | 495,2 | 68,5 % |
| tJM9KqTt | 591,3 | 415,2 | 70,2 % |
| tZSnEgva | 689,5 | 594,9 | 86,3 % |
| tf9oJob7 | 850,6 | 715,2 | 84,1 % |
| u3RHJ15y | 531,4 | 200,7 | 37,8 % |
| uQLTOCT9 | 206,2 | 1,0 | 0,5 % |
| uTJqSvxx | 592,5 | 564,4 | 95,3 % |
| uUFhBQzs | 715,6 | 466,9 | 65,3 % |
| ueGJf9d5 | 546,6 | 310,8 | 56,9 % |
| uennkFAE | 729,3 | 666,3 | 91,4 % |
| vAibnS26 | 851,4 | 555,1 | 65,2 % |
| vtBLsHpC | 697,6 | 496,3 | 71,1 % |
| w2fLs42F | 582,5 | 566,0 | 97,2 % |
| wEqq3ifR | 610,1 | 516,7 | 84,7 % |
| wv6qC56z | 753,0 | 624,9 | 83,0 % |
| xSDmm63y | 717,3 | 600,7 | 83,7 % |
| xURf3a0o | 564,5 | 563,3 | 99,8 % |
| y5TEbHnC | 729,4 | 679,6 | 93,2 % |
| yNmVF4oy | 557,5 | 535,5 | 96,0 % |
| yV4lUIbS | 568,9 | 521,9 | 91,7 % |
| yjpSQKFb | 724,6 | 548,9 | 75,8 % |
| ywCyyxQF | 868,6 | 568,1 | 65,4 % |
| yxOWx66O | 596,5 | 515,6 | 86,4 % |
| zK4WxULP | 756,9 | 292,6 | 38,7 % |
| zPZ3d57M | 721,3 | 578,3 | 80,2 % |
| zskLB4tU | 587,0 | 301,1 | 51,3 % |

Gedekte tijd (dagen) per aaneengesloten-reeks-lengte, gepoold over woningen:

- `streak__dag_tot_week__s`: 7115,7 dagen
- `streak__kwartier_tot_uur__s`: 139,3 dagen
- `streak__meer_dan_maand__s`: 63.001,6 dagen
- `streak__uur_tot_dag__s`: 2404,4 dagen
- `streak__week_tot_maand__s`: 17.316,4 dagen

**Conclusie**: de mediane woning heeft 78,1 % van haar tijdvak gedekt (p10-p90: 52,5 % tot 95,8 %), en 89,0 % van alle gedekte tijd zit in aaneengesloten reeksen van langer dan een week. Dat laatste is het getal dat telt: losse kwartieren zijn iets anders dan een aaneengesloten stookseizoen, en alleen het tweede draagt een seizoensanalyse. Gebruikte gatlimiet: 90 minuten -- NeedForHeats default, nog een aanname en geen meting (zie B12).

## B7. De sprongdrempels tegen de werkelijke verdeling

**Vraag**: hoe verhouden `tellers.SPRONG_DREMPEL__W` (verzonnen, niet extern getoetst) zich tot de werkelijke verdeling van het intervalgemiddelde vermogen?

| teller | huidige drempel (W) | mediaan p99,99 over woningen (W) | max over woningen (W) |
|---|---:|---:|---:|
| e_net__W | 40.000 | 6494 | 387.182.656 |
| g_gebruik__W | 100.000 | 27.866 | 10.155.871.232 |
| p_ketel__W | 1000 | 56 | 354.704 |
| p_warmtepomp__W | 10.000 | 1608 | 12.312.980 |
| q_geleverd__W | 50.000 | 12.149 | 3.433.889 |

**Conclusie**: de drempels staan boven het gemeten p99,99 van de mediane woning, met een factor tussen 4 en 18. De ruimste: `p_ketel__W` staat 18x boven de mediane woning, `p_warmtepomp__W` staat 6x boven de mediane woning, `e_net__W` staat 6x boven de mediane woning. Een drempel die honderden malen boven het normale bedrijf ligt vangt alleen het absurde en laat het merely-onmogelijke door -- een warmtepomp die 15 kW meldt is onmogelijk voor deze installaties maar haalt een drempel van 20 kW niet. De drempels in `tellers.SPRONG_DREMPEL__W` zijn op 05-09-2026 op deze verdeling herzien; deze tabel laat zien of dat genoeg was.

## B8. Stookseizoenen: een eerlijke telling

**Vraag**: hoeveel stookseizoenen (okt-apr) dekt een woning ECHT, met een dekkingseis in plaats van de oude "aangeraakt"-telling (`rapport.py`)?

| home_id | >=50 % gedekt | >=80 % gedekt | >=90 % gedekt | >=95 % gedekt |
|---|---:|---:|---:|---:|
| -B51sQOp | 1 | 1 | 0 | 0 |
| -ORiFQC6 | 1 | 1 | 1 | 1 |
| -uFUg8jU | 2 | 2 | 1 | 1 |
| 0RQyG6WX | 1 | 1 | 1 | 0 |
| 0XvCtU3v | 2 | 1 | 1 | 0 |
| 0_6TUlP4 | 2 | 2 | 2 | 2 |
| 0rE1EXuT | 1 | 0 | 0 | 0 |
| 0z5clxou | 1 | 1 | 1 | 1 |
| 141Q2Shj | 1 | 0 | 0 | 0 |
| 1WyeUbFg | 2 | 1 | 1 | 1 |
| 1Y5XKgSd | 1 | 1 | 1 | 1 |
| 1uGr4CK2 | 2 | 1 | 1 | 1 |
| 2L97t6LT | 2 | 2 | 2 | 2 |
| 2aE7xTqC | 2 | 2 | 2 | 2 |
| 3QryrLjd | 2 | 2 | 1 | 1 |
| 3V2aOh4L | 2 | 2 | 1 | 1 |
| 3WCT0MF1 | 2 | 2 | 2 | 1 |
| 3c1fUm5M | 2 | 2 | 2 | 2 |
| 3jcFOgZ5 | 0 | 0 | 0 | 0 |
| 3voUJ8cb | 2 | 1 | 1 | 1 |
| 46no-WLf | 2 | 1 | 1 | 1 |
| 4OnYOkIn | 1 | 1 | 0 | 0 |
| 4iyux5_5 | 2 | 2 | 1 | 1 |
| 5GCcwjbF | 2 | 2 | 2 | 2 |
| 5NNgThim | 2 | 2 | 2 | 1 |
| 5QvgGmut | 2 | 1 | 1 | 1 |
| 5n48RmBE | 1 | 1 | 0 | 0 |
| 6-gOUJps | 1 | 1 | 1 | 0 |
| 66lZ2dKl | 0 | 0 | 0 | 0 |
| 6U_ZxCz7 | 2 | 2 | 1 | 1 |
| 6oWZr5LM | 2 | 0 | 0 | 0 |
| 6pd9A10u | 1 | 0 | 0 | 0 |
| 6sdsV762 | 2 | 1 | 1 | 1 |
| 7JgOwuUh | 1 | 1 | 1 | 0 |
| 7iTwZNm7 | 1 | 0 | 0 | 0 |
| 9-agjI3L | 2 | 1 | 1 | 1 |
| 96H2Z6-Y | 2 | 1 | 1 | 0 |
| 9H8W2b5Q | 1 | 0 | 0 | 0 |
| 9LFZHK7q | 2 | 1 | 1 | 1 |
| 9SiQCg0b | 2 | 2 | 1 | 1 |
| A0JoUuz- | 2 | 2 | 2 | 2 |
| B4oZ6JEm | 2 | 1 | 0 | 0 |
| BdMf5w-N | 2 | 2 | 2 | 2 |
| CbPETsjw | 2 | 1 | 0 | 0 |
| D8ZSj9yG | 1 | 1 | 1 | 1 |
| Dduwcofx | 1 | 1 | 1 | 1 |
| Di0nyhC7 | 2 | 1 | 0 | 0 |
| DlCdUGP1 | 1 | 1 | 0 | 0 |
| DsPYyuTY | 2 | 1 | 1 | 1 |
| EyZIyLSP | 1 | 1 | 1 | 1 |
| FFOpKdF2 | 1 | 1 | 1 | 1 |
| GDO9C-2s | 2 | 2 | 1 | 0 |
| GMbBE51s | 2 | 2 | 1 | 1 |
| GdemEVzZ | 2 | 1 | 1 | 1 |
| GjGxfcOD | 1 | 0 | 0 | 0 |
| H6PEe0lX | 1 | 1 | 1 | 1 |
| HedOCi6L | 2 | 2 | 2 | 2 |
| HuOvEokt | 2 | 1 | 0 | 0 |
| I3v9SmRO | 2 | 1 | 1 | 0 |
| IF9c6c-H | 2 | 1 | 1 | 0 |
| J1bBIrb_ | 2 | 1 | 1 | 1 |
| JEZzJ1_- | 2 | 1 | 1 | 1 |
| JqpjoDDU | 1 | 1 | 1 | 1 |
| Jr9PJjgK | 1 | 0 | 0 | 0 |
| JyqIksBN | 2 | 1 | 1 | 1 |
| KR2H1ovj | 0 | 0 | 0 | 0 |
| Kwb9DHh8 | 1 | 0 | 0 | 0 |
| Lm4kAwHz | 2 | 1 | 1 | 1 |
| Lo8oUUaQ | 2 | 1 | 1 | 1 |
| LyD1Zpmn | 2 | 0 | 0 | 0 |
| LzZTAYkZ | 0 | 0 | 0 | 0 |
| MBelxm3z | 1 | 1 | 0 | 0 |
| MNbpwIxe | 2 | 1 | 1 | 0 |
| MPjpuY8a | 2 | 1 | 1 | 1 |
| MT_lo4kd | 2 | 1 | 1 | 1 |
| Mz219wDb | 1 | 1 | 1 | 0 |
| Nkw-o7MK | 2 | 1 | 1 | 1 |
| OMa7vZ0x | 1 | 1 | 1 | 1 |
| OnRTARXf | 0 | 0 | 0 | 0 |
| P1IrM5bq | 2 | 2 | 0 | 0 |
| PL238TVN | 0 | 0 | 0 | 0 |
| Q7c7Wak6 | 2 | 0 | 0 | 0 |
| Q_CTMAg9 | 0 | 0 | 0 | 0 |
| QtE_uvEX | 2 | 2 | 2 | 2 |
| QytoLUAL | 2 | 2 | 2 | 2 |
| RHON9wor | 2 | 1 | 1 | 0 |
| RirVqJd3 | 2 | 1 | 1 | 0 |
| SDIPnuVt | 2 | 1 | 1 | 1 |
| SZphemL4 | 2 | 2 | 2 | 2 |
| TkMyAOp1 | 1 | 1 | 0 | 0 |
| U-vtaXTk | 1 | 1 | 1 | 1 |
| UigJRsPF | 1 | 1 | 0 | 0 |
| UkhY0kLf | 2 | 1 | 1 | 1 |
| VF54k5wO | 1 | 0 | 0 | 0 |
| W3lmQOBD | 2 | 1 | 1 | 0 |
| W5J0QUUq | 2 | 2 | 2 | 2 |
| WUAgbEiI | 2 | 1 | 1 | 1 |
| XmrgAM1Q | 1 | 1 | 1 | 1 |
| Y6E5x8IP | 1 | 0 | 0 | 0 |
| Z5GVYH20 | 1 | 1 | 1 | 1 |
| Z5tUk-4t | 1 | 1 | 1 | 1 |
| ZzY3cd3h | 2 | 2 | 2 | 2 |
| aGIM-uhc | 1 | 0 | 0 | 0 |
| aQ1RbqD6 | 2 | 2 | 2 | 2 |
| b0-a0MJb | 2 | 1 | 1 | 1 |
| bB9dwLYE | 2 | 2 | 2 | 2 |
| bW_iJrKG | 2 | 2 | 1 | 1 |
| b_eXywsq | 2 | 1 | 1 | 1 |
| bep7sbGN | 2 | 2 | 2 | 0 |
| btF7zwOl | 2 | 2 | 1 | 1 |
| cXHtdNjQ | 2 | 2 | 1 | 1 |
| c_pkxwxm | 2 | 2 | 2 | 2 |
| ccN0cg3e | 2 | 2 | 1 | 1 |
| cfs3OE3j | 1 | 0 | 0 | 0 |
| cggNkr7C | 2 | 0 | 0 | 0 |
| d7dbrO23 | 2 | 1 | 1 | 1 |
| df79ygat | 2 | 2 | 2 | 1 |
| di1C3DT- | 2 | 1 | 1 | 1 |
| diDdCX6N | 2 | 2 | 1 | 1 |
| e-V7pn_P | 2 | 2 | 2 | 2 |
| e6Pc72sP | 1 | 0 | 0 | 0 |
| e9WTomef | 1 | 1 | 1 | 1 |
| eS3U7RoL | 2 | 2 | 1 | 1 |
| eTBI5kYm | 2 | 2 | 2 | 2 |
| ez7d4xNY | 2 | 2 | 2 | 2 |
| fEQuZl6P | 2 | 2 | 2 | 2 |
| frZKRmLD | 1 | 1 | 1 | 0 |
| g6cwpA70 | 2 | 2 | 1 | 1 |
| gfhTqPfk | 2 | 2 | 1 | 1 |
| gmtO-ZIa | 1 | 1 | 1 | 1 |
| h57Wozww | 2 | 1 | 1 | 1 |
| hRPmkwLs | 1 | 1 | 1 | 1 |
| hlOONbvk | 2 | 1 | 1 | 1 |
| ib2L3SnU | 2 | 1 | 0 | 0 |
| kKi5OIGx | 1 | 1 | 1 | 1 |
| kaTMcjBU | 1 | 1 | 1 | 0 |
| l7_BBT0u | 1 | 1 | 1 | 1 |
| lVK0bORa | 2 | 2 | 2 | 2 |
| nPZwu5CK | 2 | 1 | 0 | 0 |
| nkMckb09 | 2 | 1 | 1 | 1 |
| on1VMMTO | 2 | 1 | 0 | 0 |
| ooQJGe15 | 2 | 1 | 1 | 1 |
| oqb_lZc9 | 2 | 2 | 2 | 2 |
| pv_IsvbE | 2 | 2 | 1 | 1 |
| qAVHYp3J | 2 | 1 | 1 | 1 |
| qBr4JQ_w | 2 | 2 | 0 | 0 |
| qdC1C7Lx | 2 | 2 | 2 | 2 |
| rC_pkM3K | 1 | 1 | 1 | 1 |
| sNLALR1w | 1 | 1 | 1 | 1 |
| tJM9KqTt | 1 | 1 | 1 | 1 |
| tZSnEgva | 2 | 2 | 2 | 1 |
| tf9oJob7 | 2 | 1 | 1 | 1 |
| u3RHJ15y | 0 | 0 | 0 | 0 |
| uQLTOCT9 | 0 | 0 | 0 | 0 |
| uTJqSvxx | 2 | 2 | 1 | 1 |
| uUFhBQzs | 2 | 0 | 0 | 0 |
| ueGJf9d5 | 1 | 0 | 0 | 0 |
| uennkFAE | 2 | 2 | 1 | 1 |
| vAibnS26 | 2 | 1 | 1 | 1 |
| vtBLsHpC | 2 | 2 | 1 | 0 |
| w2fLs42F | 2 | 2 | 1 | 1 |
| wEqq3ifR | 2 | 1 | 1 | 1 |
| wv6qC56z | 2 | 1 | 0 | 0 |
| xSDmm63y | 2 | 2 | 2 | 1 |
| xURf3a0o | 2 | 1 | 1 | 1 |
| y5TEbHnC | 2 | 2 | 2 | 2 |
| yNmVF4oy | 2 | 1 | 1 | 1 |
| yV4lUIbS | 1 | 1 | 1 | 1 |
| yjpSQKFb | 2 | 1 | 1 | 1 |
| ywCyyxQF | 2 | 2 | 1 | 1 |
| yxOWx66O | 2 | 1 | 1 | 0 |
| zK4WxULP | 2 | 0 | 0 | 0 |
| zPZ3d57M | 2 | 2 | 1 | 0 |
| zskLB4tU | 1 | 1 | 1 | 1 |

- Bij een dekkingseis van 50 %: 114 van 174 (65,5 %) woningen dekt >=2 stookseizoenen.
- Bij een dekkingseis van 80 %: 55 van 174 (31,6 %) woningen dekt >=2 stookseizoenen.
- Bij een dekkingseis van 90 %: 30 van 174 (17,2 %) woningen dekt >=2 stookseizoenen.
- Bij een dekkingseis van 95 %: 24 van 174 (13,8 %) woningen dekt >=2 stookseizoenen.

**Conclusie**: de keuze van de dekkingsdrempel doet er zichtbaar toe (zie de rij hierboven per drempel); voorstel 80 % totdat er een inhoudelijke reden is voor een andere waarde.

## B9. Loopt er tapwater langs de warmtemeter?

**Vraag** (onderbouwing: ontwerp-intervalsemantiek.md §4.5): is er per woning een sterke verrijking van gasverbruik tijdens zomerse warmtelevering, wat wijst op tapwater dat langs de Kamstrup-warmtemeter loopt?

| home_id | zomerkwartieren met warmte>200W | daarvan gas>500W | basiskans gas>500W | corr(warmte,wp-elektra) | aanvoer>50°C | vlag |
|---|---:|---:|---:|---:|---:|:---:|
| -B51sQOp | 0,0 % | n.v.t. | 5,1 % | 0,020 | 0,0 % | nee |
| -ORiFQC6 | 5,5 % | 53,2 % | 3,2 % | 0,961 | 7,5 % | JA |
| -uFUg8jU | 7,3 % | 42,5 % | 22,2 % | 0,641 | 0,0 % | nee |
| 0RQyG6WX | 0,5 % | 0,0 % | 3,1 % | 0,957 | 0,0 % | nee |
| 0XvCtU3v | 0,0 % | n.v.t. | 4,8 % | n.v.t. | n.v.t. | nee |
| 0_6TUlP4 | 0,4 % | 31,7 % | 3,0 % | 0,936 | 0,0 % | JA |
| 0rE1EXuT | 2,1 % | 0,0 % | 0,8 % | 0,978 | 0,0 % | nee |
| 0z5clxou | 1,7 % | 12,0 % | 6,3 % | 0,966 | 0,0 % | nee |
| 141Q2Shj | 0,2 % | 0,0 % | 4,8 % | -0,006 | 0,0 % | nee |
| 1WyeUbFg | 1,0 % | 7,0 % | 7,2 % | 0,519 | 0,0 % | nee |
| 1Y5XKgSd | 0,2 % | n.v.t. | 0,9 % | 0,750 | 0,0 % | nee |
| 1uGr4CK2 | 0,2 % | 0,0 % | 6,0 % | 0,995 | 0,0 % | nee |
| 2L97t6LT | 7,6 % | 1,6 % | 3,4 % | 0,605 | 0,0 % | nee |
| 2aE7xTqC | 0,9 % | 5,1 % | 3,8 % | 0,265 | 0,0 % | nee |
| 3QryrLjd | 8,9 % | 4,4 % | 6,6 % | 0,831 | 0,0 % | nee |
| 3V2aOh4L | 0,1 % | 12,5 % | 2,8 % | 0,037 | 0,0 % | nee |
| 3WCT0MF1 | 0,2 % | 4,3 % | 2,7 % | 0,892 | 4,3 % | nee |
| 3c1fUm5M | 0,0 % | 0,0 % | 4,8 % | 0,736 | 0,0 % | nee |
| 3jcFOgZ5 | 15,6 % | 17,9 % | 10,0 % | 0,889 | 0,0 % | nee |
| 3voUJ8cb | 2,8 % | 8,1 % | 9,4 % | 0,847 | 7,7 % | nee |
| 46no-WLf | 0,1 % | 11,1 % | 2,0 % | 0,675 | 0,0 % | nee |
| 4OnYOkIn | 1,0 % | 11,0 % | 7,1 % | 0,894 | 0,0 % | nee |
| 4iyux5_5 | 0,0 % | n.v.t. | 3,6 % | n.v.t. | n.v.t. | nee |
| 5GCcwjbF | 0,2 % | 0,0 % | 0,8 % | 0,972 | 0,0 % | nee |
| 5NNgThim | 0,0 % | 0,0 % | 4,9 % | 0,026 | 0,0 % | nee |
| 5QvgGmut | 0,0 % | n.v.t. | 33,3 % | n.v.t. | n.v.t. | nee |
| 5n48RmBE | 0,9 % | 1,5 % | 3,6 % | 0,960 | 0,0 % | nee |
| 6-gOUJps | 1,4 % | 6,1 % | 5,7 % | 0,942 | 0,0 % | nee |
| 6U_ZxCz7 | 5,9 % | 8,9 % | 4,5 % | 0,660 | 6,4 % | nee |
| 6oWZr5LM | 11,5 % | 4,8 % | 4,6 % | 0,906 | 0,5 % | nee |
| 6pd9A10u | 0,0 % | n.v.t. | 5,5 % | -0,042 | n.v.t. | nee |
| 6sdsV762 | 1,5 % | 5,3 % | 8,2 % | 0,805 | 0,0 % | nee |
| 7JgOwuUh | 0,0 % | n.v.t. | 100,0 % | n.v.t. | n.v.t. | nee |
| 7iTwZNm7 | 0,0 % | 0,0 % | 2,6 % | 0,003 | 0,0 % | nee |
| 9-agjI3L | 0,3 % | 8,7 % | 7,9 % | 0,962 | 0,0 % | nee |
| 96H2Z6-Y | 1,3 % | 5,5 % | 5,9 % | 0,494 | 0,0 % | nee |
| 9H8W2b5Q | 0,0 % | n.v.t. | 33,3 % | n.v.t. | n.v.t. | nee |
| 9LFZHK7q | 0,2 % | 0,0 % | 1,3 % | 0,890 | 0,0 % | nee |
| 9SiQCg0b | 1,6 % | 2,2 % | 2,7 % | 0,048 | 0,0 % | nee |
| A0JoUuz- | 0,6 % | 11,9 % | 5,3 % | 0,847 | 0,0 % | nee |
| B4oZ6JEm | 1,1 % | 2,8 % | 4,0 % | 0,966 | 0,0 % | nee |
| BdMf5w-N | 0,1 % | 12,5 % | 4,5 % | 0,949 | 0,0 % | nee |
| CbPETsjw | 0,1 % | 0,0 % | 5,0 % | 0,007 | 0,0 % | nee |
| D8ZSj9yG | 2,5 % | 1,3 % | 1,7 % | 0,959 | 0,0 % | nee |
| Dduwcofx | 3,0 % | 3,8 % | 3,9 % | 0,965 | 0,0 % | nee |
| Di0nyhC7 | 0,0 % | n.v.t. | 0,2 % | n.v.t. | n.v.t. | nee |
| DlCdUGP1 | 0,0 % | n.v.t. | 3,5 % | -0,027 | n.v.t. | nee |
| DsPYyuTY | 2,7 % | 3,8 % | 1,0 % | 0,949 | 0,0 % | JA |
| EyZIyLSP | 0,4 % | 0,0 % | 2,4 % | 0,979 | 0,0 % | nee |
| FFOpKdF2 | 0,9 % | 7,2 % | 2,0 % | 0,844 | 0,0 % | JA |
| GDO9C-2s | 0,3 % | n.v.t. | 2,8 % | 0,322 | 0,0 % | nee |
| GMbBE51s | 7,2 % | 7,1 % | 6,0 % | 0,982 | 0,0 % | nee |
| GdemEVzZ | 0,3 % | 14,0 % | 8,5 % | 0,336 | 0,0 % | nee |
| GjGxfcOD | 0,5 % | 0,0 % | 0,9 % | 0,977 | 0,0 % | nee |
| H6PEe0lX | 0,1 % | 9,1 % | 6,0 % | 0,006 | 0,0 % | nee |
| HedOCi6L | 0,7 % | 3,5 % | 5,3 % | 0,925 | 0,0 % | nee |
| HuOvEokt | 0,0 % | n.v.t. | 13,0 % | n.v.t. | n.v.t. | nee |
| I3v9SmRO | 0,7 % | 8,6 % | 9,1 % | 0,314 | 0,0 % | nee |
| IF9c6c-H | 0,0 % | n.v.t. | n.v.t. | 0,029 | 0,0 % | nee |
| J1bBIrb_ | 0,3 % | 13,0 % | 6,5 % | -0,005 | 0,0 % | nee |
| JEZzJ1_- | 7,2 % | 0,8 % | 0,2 % | 0,625 | 0,0 % | JA |
| Jr9PJjgK | 1,2 % | n.v.t. | n.v.t. | 0,943 | 0,0 % | nee |
| JyqIksBN | 2,1 % | 9,6 % | 5,9 % | 0,349 | 0,0 % | nee |
| KR2H1ovj | 0,0 % | 0,0 % | 20,6 % | -0,010 | 0,0 % | nee |
| Kwb9DHh8 | 0,1 % | 11,1 % | 10,6 % | 0,220 | 0,0 % | nee |
| Lm4kAwHz | 0,0 % | 0,0 % | 4,7 % | 0,049 | 0,0 % | nee |
| Lo8oUUaQ | 5,1 % | 6,7 % | 5,8 % | 0,653 | 0,0 % | nee |
| LyD1Zpmn | 0,5 % | 9,1 % | 3,4 % | 0,000 | 0,0 % | nee |
| LzZTAYkZ | 0,3 % | 0,0 % | 2,3 % | -0,017 | 0,0 % | nee |
| MBelxm3z | 0,2 % | 9,1 % | 9,1 % | -0,006 | 0,0 % | nee |
| MNbpwIxe | 0,6 % | 7,8 % | 3,9 % | 0,428 | 0,0 % | nee |
| MPjpuY8a | 0,0 % | 0,0 % | 1,6 % | 0,049 | 0,0 % | nee |
| MT_lo4kd | 0,0 % | n.v.t. | 2,3 % | n.v.t. | n.v.t. | nee |
| Mz219wDb | 0,7 % | 10,6 % | 5,7 % | 0,887 | 24,2 % | nee |
| Nkw-o7MK | 0,0 % | n.v.t. | 3,4 % | n.v.t. | n.v.t. | nee |
| OMa7vZ0x | 1,5 % | 3,8 % | 3,0 % | 0,681 | 0,0 % | nee |
| OnRTARXf | 0,0 % | 0,0 % | 5,8 % | -0,001 | 0,0 % | nee |
| P1IrM5bq | 0,1 % | 40,0 % | 7,3 % | 0,178 | 0,0 % | nee |
| PL238TVN | 2,2 % | 100,0 % | 10,1 % | 0,054 | 52,3 % | JA |
| Q7c7Wak6 | 0,7 % | 7,1 % | 5,9 % | 0,233 | 0,0 % | nee |
| Q_CTMAg9 | 1,3 % | 17,9 % | 5,5 % | -0,016 | 0,0 % | JA |
| QtE_uvEX | 0,0 % | 0,0 % | 1,1 % | 0,020 | 0,0 % | nee |
| QytoLUAL | 0,1 % | 18,2 % | 5,5 % | 0,302 | 0,0 % | JA |
| RHON9wor | 0,1 % | 12,5 % | 6,1 % | 0,858 | 0,0 % | nee |
| RirVqJd3 | 1,4 % | 27,8 % | 4,8 % | 0,190 | 0,0 % | JA |
| SDIPnuVt | 0,2 % | 28,6 % | 4,4 % | 0,882 | 0,0 % | JA |
| SZphemL4 | 0,1 % | 0,0 % | 2,0 % | 0,384 | 0,0 % | nee |
| TkMyAOp1 | 1,1 % | n.v.t. | n.v.t. | 0,894 | 0,0 % | nee |
| U-vtaXTk | 0,4 % | 5,9 % | 3,3 % | 0,566 | 0,0 % | nee |
| UigJRsPF | 0,4 % | 0,0 % | 4,6 % | 0,944 | 0,0 % | nee |
| UkhY0kLf | 3,1 % | 9,4 % | 4,4 % | 0,272 | 0,0 % | nee |
| VF54k5wO | 0,8 % | 2,4 % | 3,5 % | 0,975 | 0,0 % | nee |
| W3lmQOBD | 0,2 % | 7,1 % | 4,7 % | 0,927 | 0,0 % | nee |
| W5J0QUUq | 0,0 % | 0,0 % | 4,4 % | 0,007 | 0,0 % | nee |
| WUAgbEiI | 0,2 % | 21,1 % | 5,4 % | 0,495 | 0,0 % | JA |
| XmrgAM1Q | 0,2 % | 15,0 % | 16,1 % | 0,939 | 0,0 % | nee |
| Y6E5x8IP | 0,0 % | n.v.t. | 2,0 % | n.v.t. | n.v.t. | nee |
| Z5GVYH20 | 0,4 % | 0,0 % | 3,3 % | 0,196 | 0,0 % | nee |
| Z5tUk-4t | 1,0 % | 1,1 % | 1,0 % | 0,874 | 0,0 % | nee |
| ZzY3cd3h | 0,7 % | 6,3 % | 5,2 % | 0,847 | 0,0 % | nee |
| aGIM-uhc | 0,2 % | 5,0 % | 1,3 % | 0,067 | 0,0 % | JA |
| aQ1RbqD6 | 0,4 % | 0,0 % | 1,9 % | 0,239 | 0,0 % | nee |
| b0-a0MJb | 1,6 % | 9,5 % | 6,9 % | 0,622 | 0,0 % | nee |
| bB9dwLYE | 2,2 % | 12,8 % | 7,5 % | 0,796 | 0,0 % | nee |
| bW_iJrKG | 3,2 % | 7,4 % | 9,4 % | 0,688 | 0,0 % | nee |
| b_eXywsq | 8,1 % | 5,9 % | 7,3 % | 0,488 | 0,0 % | nee |
| bep7sbGN | 0,0 % | n.v.t. | 3,2 % | n.v.t. | n.v.t. | nee |
| btF7zwOl | 0,7 % | 6,0 % | 3,5 % | 0,957 | 0,0 % | nee |
| cXHtdNjQ | 0,0 % | n.v.t. | 1,3 % | n.v.t. | n.v.t. | nee |
| c_pkxwxm | 0,1 % | 25,0 % | 7,5 % | 0,951 | 0,0 % | JA |
| ccN0cg3e | 0,6 % | 0,0 % | 0,0 % | 0,948 | 0,0 % | nee |
| cfs3OE3j | 3,1 % | 8,0 % | 8,2 % | 0,662 | 0,0 % | nee |
| cggNkr7C | 3,6 % | 0,0 % | 5,7 % | 0,194 | 0,0 % | nee |
| d7dbrO23 | 0,3 % | 9,5 % | 0,6 % | 0,985 | 0,0 % | JA |
| df79ygat | 0,0 % | 0,0 % | 8,2 % | 0,038 | 0,0 % | nee |
| di1C3DT- | 4,9 % | 6,4 % | 9,1 % | -0,003 | 0,0 % | nee |
| diDdCX6N | 4,1 % | 10,4 % | 3,4 % | 0,622 | 0,0 % | JA |
| e-V7pn_P | 0,0 % | 0,0 % | 2,3 % | 0,004 | 0,0 % | nee |
| e6Pc72sP | 1,6 % | 8,0 % | 3,6 % | 0,488 | 0,0 % | nee |
| e9WTomef | 2,4 % | 6,9 % | 3,6 % | 0,971 | 3,2 % | nee |
| eS3U7RoL | 6,3 % | 5,0 % | 5,6 % | 0,960 | 0,0 % | nee |
| eTBI5kYm | 0,0 % | 50,0 % | 4,8 % | 0,215 | 0,0 % | nee |
| ez7d4xNY | 0,2 % | 3,6 % | 5,2 % | 0,963 | 0,0 % | nee |
| fEQuZl6P | 0,1 % | 12,5 % | 3,5 % | 0,967 | 27,3 % | JA |
| frZKRmLD | 2,6 % | 14,5 % | 12,3 % | 0,972 | 0,0 % | nee |
| g6cwpA70 | 2,2 % | 8,7 % | 6,3 % | 0,961 | 0,0 % | nee |
| gfhTqPfk | 1,1 % | 9,1 % | 8,1 % | 0,925 | 1,0 % | nee |
| gmtO-ZIa | 0,1 % | n.v.t. | n.v.t. | 0,080 | 0,0 % | nee |
| h57Wozww | 0,0 % | 25,0 % | 0,9 % | 0,068 | 0,0 % | nee |
| hRPmkwLs | 0,0 % | 0,0 % | 4,2 % | 0,658 | 0,0 % | nee |
| hlOONbvk | 0,1 % | 0,0 % | 1,8 % | 0,124 | 0,0 % | nee |
| ib2L3SnU | 1,8 % | 3,7 % | 7,0 % | 0,557 | 0,0 % | nee |
| kKi5OIGx | 2,0 % | 14,7 % | 7,5 % | 0,982 | 0,0 % | nee |
| kaTMcjBU | 0,1 % | 0,0 % | 4,8 % | 0,013 | 0,0 % | nee |
| l7_BBT0u | 0,1 % | 14,3 % | 6,9 % | 0,909 | 0,0 % | nee |
| lVK0bORa | 0,4 % | 12,7 % | 10,4 % | 0,985 | 0,0 % | nee |
| nPZwu5CK | 0,0 % | 0,0 % | 6,5 % | 0,038 | 0,0 % | nee |
| nkMckb09 | 0,2 % | 0,0 % | 0,2 % | n.v.t. | 0,0 % | nee |
| on1VMMTO | 4,5 % | 5,7 % | 2,6 % | 0,984 | 0,0 % | nee |
| ooQJGe15 | 7,8 % | 13,6 % | 10,6 % | 0,077 | 0,0 % | nee |
| oqb_lZc9 | 0,0 % | 0,0 % | 2,7 % | 0,029 | 0,0 % | nee |
| pv_IsvbE | 4,9 % | 11,9 % | 10,5 % | 0,941 | 0,0 % | nee |
| qAVHYp3J | 1,6 % | 6,2 % | 7,1 % | 0,622 | 0,0 % | nee |
| qdC1C7Lx | 0,2 % | 59,1 % | 4,4 % | 0,181 | 0,0 % | JA |
| rC_pkM3K | 0,0 % | 0,0 % | 11,1 % | -0,001 | 0,0 % | nee |
| sNLALR1w | 4,4 % | 1,3 % | 2,7 % | 0,535 | 0,0 % | nee |
| tJM9KqTt | 0,0 % | 0,0 % | 7,2 % | -0,006 | 0,0 % | nee |
| tZSnEgva | 0,0 % | 0,0 % | 11,6 % | 0,024 | 0,0 % | nee |
| tf9oJob7 | 0,2 % | 5,4 % | 3,5 % | 0,935 | 0,0 % | nee |
| u3RHJ15y | 0,0 % | n.v.t. | 8,4 % | 0,005 | n.v.t. | nee |
| uQLTOCT9 | 0,0 % | n.v.t. | 0,0 % | n.v.t. | n.v.t. | nee |
| uTJqSvxx | 0,4 % | 15,2 % | 2,0 % | 0,961 | 0,0 % | JA |
| uUFhBQzs | 1,9 % | 2,4 % | 4,7 % | 0,918 | 0,0 % | nee |
| ueGJf9d5 | 3,7 % | n.v.t. | n.v.t. | 0,971 | 0,0 % | nee |
| uennkFAE | 0,0 % | 0,0 % | 7,4 % | 0,655 | 0,0 % | nee |
| vAibnS26 | 1,2 % | 10,4 % | 6,5 % | 0,950 | 0,0 % | nee |
| vtBLsHpC | 0,9 % | 8,9 % | 4,4 % | -0,000 | 0,0 % | nee |
| w2fLs42F | 0,0 % | 0,0 % | 3,0 % | 0,033 | 0,0 % | nee |
| wEqq3ifR | 15,9 % | 24,9 % | 24,7 % | 0,970 | 0,0 % | nee |
| wv6qC56z | 0,4 % | 1,9 % | 1,9 % | 0,937 | 0,0 % | nee |
| xSDmm63y | 0,0 % | 0,0 % | 2,3 % | 0,006 | 0,0 % | nee |
| xURf3a0o | 0,3 % | 6,9 % | 3,4 % | 0,929 | 0,0 % | nee |
| y5TEbHnC | 0,1 % | 0,0 % | 2,0 % | 0,073 | 0,0 % | nee |
| yNmVF4oy | 0,2 % | 11,8 % | 3,6 % | -0,012 | 0,0 % | JA |
| yV4lUIbS | 0,0 % | n.v.t. | 3,5 % | n.v.t. | n.v.t. | nee |
| yjpSQKFb | 0,0 % | 0,0 % | 2,4 % | 0,063 | 0,0 % | nee |
| ywCyyxQF | 3,5 % | 13,7 % | 3,9 % | 0,800 | 0,0 % | JA |
| yxOWx66O | 1,2 % | 1,9 % | 0,6 % | 0,976 | 0,0 % | JA |
| zK4WxULP | 0,0 % | n.v.t. | 3,0 % | n.v.t. | n.v.t. | nee |
| zPZ3d57M | 0,4 % | 62,2 % | 4,2 % | 0,532 | 0,0 % | JA |
| zskLB4tU | 0,4 % | n.v.t. | 10,0 % | 0,825 | 0,0 % | nee |

**Conclusie**: 22 van de 171 woningen gevlagd als "tapwater loopt waarschijnlijk langs de warmtemeter". Zoals ontwerp-intervalsemantiek.md §4.5 al liet zien, verschilt dit per woning -- een globale aan/uit-knop voor tapwaterfiltering is fout.

## B10. Rekent de Kamstrup na wat hij zegt te meten?

**Vraag**: klopt `q_geleverd_meting__W` met `ρ · c_p · debiet · ΔT` (water bij 45°C: ρ=990 kg/m³, c_p=4180 J/(kg·K)), op kwartieren met een noemenswaardig debiet?

n=170 woningen, gemiddelde=0,00986, mediaan=0,00865, spreiding p10-p90=0,00403..0,0166, min=-9,14e-05, max=0,0455 (mediane relatieve afwijking)

| home_id | mediane rel. afwijking | p10 | p90 | n |
|---|---:|---:|---:|---:|
| -B51sQOp | 0,60 % | -2,41 % | 4,35 % | 16.455 |
| -ORiFQC6 | 0,98 % | -3,92 % | 4,16 % | 12.943 |
| -uFUg8jU | 1,03 % | -4,50 % | 43,27 % | 38.361 |
| 0RQyG6WX | 1,43 % | -0,99 % | 5,49 % | 20.763 |
| 0XvCtU3v | 0,97 % | -3,43 % | 6,76 % | 14.446 |
| 0_6TUlP4 | 0,48 % | -1,43 % | 5,17 % | 16.723 |
| 0rE1EXuT | 0,93 % | -1,08 % | 3,91 % | 18.416 |
| 0z5clxou | 0,88 % | -1,23 % | 4,21 % | 14.451 |
| 141Q2Shj | 4,55 % | -4,14 % | 23,40 % | 6253 |
| 1WyeUbFg | 1,02 % | -4,13 % | 5,04 % | 23.244 |
| 1Y5XKgSd | 0,28 % | -1,09 % | 2,17 % | 7499 |
| 1uGr4CK2 | 0,09 % | -2,01 % | 4,35 % | 9278 |
| 2L97t6LT | 0,85 % | -3,68 % | 12,46 % | 35.626 |
| 2aE7xTqC | 0,78 % | -0,90 % | 3,16 % | 36.305 |
| 3QryrLjd | 0,03 % | -1,34 % | 2,01 % | 35.848 |
| 3V2aOh4L | 1,53 % | -1,43 % | 7,09 % | 28.092 |
| 3WCT0MF1 | 0,57 % | -1,19 % | 3,19 % | 25.534 |
| 3c1fUm5M | 0,83 % | -2,31 % | 4,28 % | 25.231 |
| 3jcFOgZ5 | 0,27 % | -1,33 % | 2,09 % | 8423 |
| 3voUJ8cb | 0,74 % | -3,01 % | 8,72 % | 20.889 |
| 46no-WLf | 1,61 % | -2,37 % | 5,83 % | 17.231 |
| 4OnYOkIn | 0,67 % | -2,75 % | 4,47 % | 13.749 |
| 4iyux5_5 | 0,43 % | -1,39 % | 3,11 % | 18.511 |
| 5GCcwjbF | 0,78 % | -2,38 % | 4,47 % | 30.953 |
| 5NNgThim | 0,52 % | -0,98 % | 3,24 % | 30.989 |
| 5QvgGmut | 1,60 % | -1,11 % | 5,86 % | 15.578 |
| 5n48RmBE | 1,04 % | -2,14 % | 4,79 % | 14.093 |
| 6-gOUJps | 1,04 % | -1,08 % | 4,69 % | 18.064 |
| 66lZ2dKl | 0,37 % | -2,90 % | 3,98 % | 2575 |
| 6U_ZxCz7 | 0,65 % | -3,11 % | 15,82 % | 17.917 |
| 6oWZr5LM | 2,67 % | -50,75 % | 95,53 % | 28.232 |
| 6pd9A10u | 0,85 % | -1,89 % | 5,51 % | 9663 |
| 6sdsV762 | 0,66 % | -2,29 % | 4,36 % | 25.484 |
| 7JgOwuUh | 1,10 % | -1,76 % | 6,16 % | 9830 |
| 7iTwZNm7 | 1,48 % | -1,44 % | 4,56 % | 11.860 |
| 9-agjI3L | 0,16 % | -1,83 % | 3,22 % | 18.966 |
| 96H2Z6-Y | 0,76 % | -0,70 % | 2,57 % | 26.376 |
| 9H8W2b5Q | 0,59 % | -2,99 % | 4,57 % | 12.266 |
| 9LFZHK7q | 1,30 % | -1,63 % | 4,53 % | 26.848 |
| 9SiQCg0b | 1,68 % | -3,11 % | 8,69 % | 21.144 |
| A0JoUuz- | 2,01 % | -3,74 % | 11,53 % | 35.319 |
| B4oZ6JEm | 0,68 % | -2,11 % | 10,51 % | 30.140 |
| BdMf5w-N | 0,77 % | -1,41 % | 3,65 % | 35.518 |
| CbPETsjw | 1,77 % | -0,78 % | 5,44 % | 23.573 |
| D8ZSj9yG | 0,38 % | -1,48 % | 2,62 % | 14.372 |
| Dduwcofx | 0,60 % | -1,88 % | 4,14 % | 22.434 |
| Di0nyhC7 | 0,27 % | -2,58 % | 4,85 % | 11.498 |
| DlCdUGP1 | 0,78 % | -8,66 % | 10,44 % | 331 |
| DsPYyuTY | 1,13 % | -0,81 % | 3,86 % | 31.427 |
| EyZIyLSP | 0,21 % | -2,11 % | 6,46 % | 4811 |
| FFOpKdF2 | -0,01 % | -3,69 % | 6,32 % | 12.300 |
| GDO9C-2s | 1,16 % | -0,88 % | 4,38 % | 29.642 |
| GMbBE51s | 0,43 % | -1,20 % | 2,30 % | 35.104 |
| GdemEVzZ | 1,18 % | -1,47 % | 4,54 % | 19.531 |
| GjGxfcOD | 1,47 % | -1,30 % | 6,77 % | 15.488 |
| H6PEe0lX | 1,48 % | -1,47 % | 5,32 % | 17.550 |
| HedOCi6L | 1,50 % | -2,18 % | 9,59 % | 1615 |
| HuOvEokt | 1,35 % | -2,06 % | 27,30 % | 12.355 |
| I3v9SmRO | 1,26 % | -6,52 % | 5,93 % | 13.914 |
| IF9c6c-H | 1,03 % | -2,03 % | 4,40 % | 12.510 |
| J1bBIrb_ | 0,97 % | -2,06 % | 4,13 % | 14.782 |
| JEZzJ1_- | 1,42 % | -5,51 % | 10,78 % | 32.609 |
| Jr9PJjgK | 0,18 % | -1,97 % | 3,35 % | 9979 |
| JyqIksBN | 0,71 % | -0,81 % | 2,52 % | 27.359 |
| KR2H1ovj | 1,50 % | -3,32 % | 11,14 % | 88 |
| Kwb9DHh8 | 1,02 % | -5,29 % | 5,65 % | 6126 |
| Lm4kAwHz | 1,65 % | -0,72 % | 4,93 % | 26.340 |
| Lo8oUUaQ | 0,46 % | -0,86 % | 2,52 % | 34.453 |
| LyD1Zpmn | 0,49 % | -1,19 % | 3,42 % | 15.299 |
| LzZTAYkZ | 1,62 % | -1,30 % | 7,87 % | 9541 |
| MBelxm3z | 1,87 % | -2,36 % | 5,50 % | 9178 |
| MNbpwIxe | 1,27 % | -4,81 % | 11,00 % | 21.916 |
| MPjpuY8a | 1,43 % | -1,22 % | 5,58 % | 14.917 |
| MT_lo4kd | 1,17 % | -2,95 % | 6,62 % | 11.242 |
| Mz219wDb | 2,82 % | -2,05 % | 27,61 % | 14.463 |
| OMa7vZ0x | 0,41 % | -0,79 % | 2,39 % | 21.723 |
| OnRTARXf | 1,53 % | -0,85 % | 5,12 % | 14.156 |
| P1IrM5bq | 0,73 % | -2,40 % | 3,47 % | 30.524 |
| PL238TVN | 0,72 % | -2,02 % | 4,38 % | 7596 |
| Q7c7Wak6 | 1,92 % | -2,51 % | 21,44 % | 17.305 |
| Q_CTMAg9 | 0,68 % | -6,13 % | 19,01 % | 7471 |
| QtE_uvEX | 2,21 % | -0,39 % | 5,47 % | 30.384 |
| QytoLUAL | 0,41 % | -1,01 % | 6,14 % | 24.293 |
| RHON9wor | 1,25 % | -2,67 % | 5,21 % | 16.357 |
| RirVqJd3 | 0,97 % | -8,16 % | 13,15 % | 23.368 |
| SDIPnuVt | 0,28 % | -2,13 % | 3,46 % | 12.685 |
| SZphemL4 | 1,05 % | -1,11 % | 4,54 % | 30.476 |
| TkMyAOp1 | 1,33 % | -1,52 % | 4,97 % | 20.467 |
| U-vtaXTk | 0,29 % | -2,98 % | 3,69 % | 11.626 |
| UigJRsPF | 0,71 % | -2,42 % | 4,25 % | 9523 |
| UkhY0kLf | 1,00 % | -3,48 % | 6,26 % | 27.109 |
| VF54k5wO | 0,26 % | -1,46 % | 2,42 % | 8837 |
| W3lmQOBD | 0,44 % | -5,03 % | 6,84 % | 29.259 |
| W5J0QUUq | 1,75 % | -0,61 % | 4,87 % | 26.193 |
| WUAgbEiI | 0,78 % | -3,48 % | 3,88 % | 25.992 |
| XmrgAM1Q | 0,92 % | -1,97 % | 4,68 % | 17.150 |
| Y6E5x8IP | 0,54 % | -0,79 % | 2,23 % | 14.171 |
| Z5GVYH20 | 1,84 % | -2,12 % | 5,80 % | 22.564 |
| Z5tUk-4t | 0,93 % | -4,68 % | 6,30 % | 16.754 |
| ZzY3cd3h | 0,47 % | -1,85 % | 3,39 % | 28.435 |
| aGIM-uhc | 1,02 % | -1,64 % | 4,38 % | 16.420 |
| aQ1RbqD6 | 0,95 % | -1,40 % | 4,36 % | 34.016 |
| b0-a0MJb | 1,53 % | -1,24 % | 5,80 % | 28.214 |
| bB9dwLYE | 0,17 % | -13,13 % | 31,67 % | 24.339 |
| bW_iJrKG | 0,91 % | -0,63 % | 3,06 % | 36.422 |
| b_eXywsq | 0,76 % | -0,82 % | 2,54 % | 29.860 |
| bep7sbGN | 0,73 % | -9,34 % | 6,08 % | 22.078 |
| btF7zwOl | 0,68 % | -1,25 % | 4,36 % | 21.434 |
| cXHtdNjQ | 0,66 % | -0,74 % | 2,78 % | 25.803 |
| c_pkxwxm | 1,19 % | -2,91 % | 6,01 % | 15.797 |
| ccN0cg3e | 0,94 % | -1,01 % | 4,43 % | 21.654 |
| cfs3OE3j | 0,41 % | -4,13 % | 3,50 % | 20.750 |
| cggNkr7C | 0,42 % | -3,49 % | 5,15 % | 22.845 |
| d7dbrO23 | 0,68 % | -1,67 % | 3,67 % | 19.188 |
| df79ygat | 3,39 % | -0,67 % | 10,08 % | 30.445 |
| di1C3DT- | 0,60 % | -1,58 % | 2,92 % | 34.155 |
| diDdCX6N | 0,61 % | -0,80 % | 2,73 % | 34.405 |
| e-V7pn_P | 0,59 % | -3,00 % | 6,79 % | 18.584 |
| e6Pc72sP | 0,75 % | -0,54 % | 2,58 % | 15.823 |
| e9WTomef | 0,97 % | -1,64 % | 4,42 % | 17.979 |
| eS3U7RoL | 0,82 % | -0,68 % | 2,85 % | 36.736 |
| eTBI5kYm | 0,82 % | -1,82 % | 4,58 % | 24.482 |
| ez7d4xNY | 0,81 % | -1,33 % | 3,32 % | 27.023 |
| fEQuZl6P | 0,70 % | -3,02 % | 5,81 % | 13.610 |
| frZKRmLD | 0,82 % | -2,00 % | 4,62 % | 13.453 |
| g6cwpA70 | 0,70 % | -2,04 % | 3,04 % | 28.534 |
| gfhTqPfk | 1,13 % | -1,27 % | 5,12 % | 20.464 |
| gmtO-ZIa | 1,37 % | -1,50 % | 4,80 % | 20.429 |
| h57Wozww | 0,80 % | -1,02 % | 3,07 % | 24.897 |
| hRPmkwLs | 1,10 % | -1,65 % | 4,70 % | 12.226 |
| hlOONbvk | 1,06 % | -1,62 % | 5,09 % | 19.159 |
| ib2L3SnU | 0,88 % | -2,26 % | 3,82 % | 17.748 |
| kKi5OIGx | 0,50 % | -1,54 % | 2,33 % | 17.743 |
| kaTMcjBU | 0,48 % | -3,96 % | 4,03 % | 15.443 |
| l7_BBT0u | 0,57 % | -3,74 % | 6,29 % | 16.961 |
| lVK0bORa | 0,54 % | -2,09 % | 3,86 % | 15.899 |
| nPZwu5CK | 1,01 % | -3,18 % | 5,85 % | 20.622 |
| nkMckb09 | 2,64 % | -18,39 % | 96,66 % | 13.582 |
| on1VMMTO | 0,03 % | -5,22 % | 4,25 % | 28.386 |
| ooQJGe15 | 0,94 % | -1,88 % | 5,85 % | 30.279 |
| oqb_lZc9 | 2,38 % | -0,59 % | 8,08 % | 22.396 |
| pv_IsvbE | 0,75 % | -0,96 % | 10,63 % | 47.343 |
| qAVHYp3J | 1,80 % | -3,63 % | 28,80 % | 31.787 |
| qBr4JQ_w | 0,98 % | -1,63 % | 3,41 % | 31.418 |
| qdC1C7Lx | 1,80 % | -0,90 % | 5,91 % | 33.747 |
| rC_pkM3K | 0,77 % | -1,03 % | 3,61 % | 12.228 |
| sNLALR1w | 0,82 % | -0,87 % | 3,09 % | 28.188 |
| tJM9KqTt | 1,77 % | -2,87 % | 6,53 % | 7321 |
| tZSnEgva | 1,14 % | -9,21 % | 18,70 % | 19.051 |
| tf9oJob7 | 0,65 % | -3,18 % | 4,81 % | 10.799 |
| u3RHJ15y | 1,35 % | -1,35 % | 5,05 % | 782 |
| uTJqSvxx | 0,76 % | -2,15 % | 5,41 % | 24.362 |
| uUFhBQzs | 0,92 % | -3,37 % | 3,71 % | 16.760 |
| ueGJf9d5 | 0,89 % | -1,87 % | 4,02 % | 16.477 |
| uennkFAE | 1,51 % | -1,53 % | 7,33 % | 13.027 |
| vAibnS26 | 0,93 % | -0,88 % | 3,12 % | 28.068 |
| vtBLsHpC | 0,81 % | -2,95 % | 4,39 % | 21.349 |
| w2fLs42F | 0,73 % | -2,81 % | 4,57 % | 20.774 |
| wEqq3ifR | 0,43 % | -2,09 % | 7,03 % | 22.124 |
| wv6qC56z | 1,09 % | -0,76 % | 3,88 % | 20.625 |
| xSDmm63y | 0,78 % | -1,54 % | 4,02 % | 9376 |
| xURf3a0o | 0,60 % | -2,36 % | 3,03 % | 28.932 |
| y5TEbHnC | 1,19 % | -0,97 % | 4,18 % | 28.802 |
| yNmVF4oy | 0,78 % | -1,35 % | 3,46 % | 21.204 |
| yjpSQKFb | 1,26 % | -0,87 % | 5,07 % | 25.533 |
| ywCyyxQF | 0,28 % | -8,44 % | 6,94 % | 23.832 |
| yxOWx66O | 0,67 % | -2,14 % | 4,03 % | 16.355 |
| zK4WxULP | 1,15 % | -0,94 % | 4,29 % | 15.494 |
| zPZ3d57M | 1,34 % | -0,71 % | 4,88 % | 29.275 |
| zskLB4tU | 1,39 % | -13,56 % | 29,66 % | 11.371 |

**Conclusie**: de mediane woning wijkt 0,87 % af van wat `rho x c_p x debiet x dT` voorspelt. Geen enkele woning zit boven 10 %: de Kamstrup rekent intern consistent na wat hij zegt te meten.

## A3. Meterwissels en resets

**Vraag**: de verdeling van de deltas per brontteller, en komen de karakteristieke spiegelparen (grote sprong, direct gevolgd door dezelfde sprong terug) hier voor?

| teller | # woningen | totaal dalingen | totaal spiegelparen | totaal deltas |
|---|---:|---:|---:|---:|
| e_export_hoog_cum__kWh | 173 | 89 | 2 | 7.834.529 |
| e_export_laag_cum__kWh | 173 | 84 | 1 | 7.834.529 |
| e_import_hoog_cum__kWh | 173 | 69 | 3 | 7.834.529 |
| e_import_laag_cum__kWh | 173 | 66 | 2 | 7.834.529 |
| e_ketel_cum__kWh | 174 | 212 | 68 | 8.520.213 |
| e_warmtepomp_cum__kWh | 174 | 12 | 12 | 8.600.067 |
| g_gebruik_cum__m3 | 173 | 69 | 34 | 7.834.529 |
| q_geleverd_cum__J | 174 | 19 | 0 | 8.600.095 |

Tien (woning, teller)-combinaties met de meeste spiegelparen:

| home_id | teller | n_spiegelparen | n_dalingen | p99 delta | max delta |
|---|---|---:|---:|---:|---:|
| lVK0bORa | e_ketel_cum__kWh | 39 | 124 | 0,009 | 29,6 |
| HedOCi6L | e_ketel_cum__kWh | 28 | 28 | 0,01 | 88,7 |
| 0XvCtU3v | e_warmtepomp_cum__kWh | 10 | 10 | 0,484 | 3,08e+03 |
| bep7sbGN | g_gebruik_cum__m3 | 5 | 5 | 0,443 | 1,74e+04 |
| QytoLUAL | g_gebruik_cum__m3 | 4 | 4 | 0,247 | 2,56e+05 |
| h57Wozww | g_gebruik_cum__m3 | 3 | 3 | 0,225 | 1,84e+04 |
| 0z5clxou | g_gebruik_cum__m3 | 2 | 2 | 0,351 | 2,51e+03 |
| eTBI5kYm | g_gebruik_cum__m3 | 2 | 2 | 0,135 | 5,79e+03 |
| yNmVF4oy | g_gebruik_cum__m3 | 2 | 2 | 0,303 | 1,46e+04 |
| 3QryrLjd | g_gebruik_cum__m3 | 1 | 1 | 0,327 | 1,2e+04 |

**Conclusie**: 122 spiegelpaar/-paren gevonden over alle woningen en tellers samen. Anders dan bij IM3 publiceert DPH de cumulatieve standen zelf, dus meterwissels zijn hier in principe herstelbaar in plaats van alleen zichtbaar.

## A4. Slaat er ergens een teller om? (modulus-artefacten)

**Vraag**: komt het patroon voor dat de IM3-zusterrepo vond -- een register dat van 9999,9 naar 0 gaat -- en zo ja, bij welke teller? De zoekmethode is daar overgenomen; de conclusie nadrukkelijk niet, want die berust erop dat IM3 alleen verschilreeksen publiceert. Deze dataset geeft de cumulatieve standen, dus bij elke daling is de stand ervóór en erna bekend en is een omslag exact herkenbaar in plaats van een vermoeden.

| teller | # woningen | dalingen | omslag-kandidaten | daling naar nul | overig | grootste daling |
|---|---:|---:|---:|---:|---:|---:|
| e_export_hoog_cum__kWh | 86 | 89 | 0 | 29 | 60 | 2,231e+04 |
| e_export_laag_cum__kWh | 81 | 84 | 0 | 31 | 53 | 9865 |
| e_import_hoog_cum__kWh | 68 | 69 | 0 | 7 | 62 | 5,41e+04 |
| e_import_laag_cum__kWh | 64 | 66 | 0 | 6 | 60 | 4,269e+04 |
| e_ketel_cum__kWh | 4 | 212 | 0 | 212 | 0 | 88,68 |
| e_warmtepomp_cum__kWh | 3 | 12 | 0 | 12 | 0 | 3078 |
| g_gebruik_cum__m3 | 52 | 69 | 0 | 37 | 32 | 2,558e+05 |
| q_geleverd_cum__J | 3 | 19 | 0 | 0 | 19 | 1,7e+07 |

**Conclusie**: GEEN omslag-kandidaten, op 620 dalingen. Het verschijnsel uit IM3 komt in deze dataset niet voor. Wat er wél is: 334 van 620 (53,9 %) van de dalingen gaat naar (vrijwel) nul terwijl de stand ervóór nergens in de buurt van een macht van tien lag. Dat is een teller die uitvalt en nul gaat melden, niet een die omslaat, en A3 laat zien dat hij daarna meestal gewoon terugkomt op zijn oude stand (spiegelparen). Een modulo-correctie zou hier dus niets repareren en wel echte uitval wegpoetsen.

