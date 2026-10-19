# Lessen uit de IM3-preprocessing — wat hier nog te doen is

De zusterpijplijn voor de Installatiemonitor is over de volledige dataset gedraaid: 537.470.922
rijen, 6.283 woningen, in één run van ruim vijftien uur. Dat leverde een aantal dingen op om hier
tegen aan te houden. Dit document is geschreven als werkopdracht, niet als verslag: wat erin staat is
wat er nog te doen is.

**Wat al is overgenomen:** de chunking met hervatbaarheid, de plan-vingerafdruk en
`UITVOER_CONTRACT_VERSIE`; de ingest van de werkelijke calorische gaswaarde
(`src/dph_preprocessing/gaskwaliteit.py`, onderbouwing in `ontwerp-preprocessing.md` §2.4); het
tellen van terugvallen in het kwaliteitsrapport (punt 6 en 7 daarvan); en de zoekmethode voor
modulus-artefacten, nu als analyse A4. Daar hoeft niets meer aan te gebeuren.

Wat overblijft is één ding, en dat is te doen in de zusterrepo, niet hier.

---

## Terug naar de zusterrepo: H-gas hoort niet in het landelijk gemiddelde

**Nederlandse woningen krijgen geen H-gas.** Een kleinverbruikersaansluiting krijgt altijd gas van
Groningen-kwaliteit; hoogcalorisch gas dat voor huishoudens bestemd is wordt eerst met stikstof
teruggemengd naar G-gas. Een huishoudelijke gasmeter rekent dus nooit af tegen 41 MJ/m³, en een
netgebied dat die waarde publiceert levert niet aan woningen.

De zusterrepo neemt voor de calorische gaswaarde niettemin het **ongewogen gemiddelde over alle
netgebieden** die `mijnenergiedata.nl` per uur teruggeeft, inclusief de netgebieden die rond 41 tot
43 MJ/m³ publiceren. Die horen daar niet in. IM3 meet woningen, dus dat gemiddelde staat daar op de
verkeerde verzameling gebieden en komt stelselmatig 0,2 MJ/m³ (~0,6%) te hoog uit, altijd dezelfde
kant op.

Ze zijn eenvoudig te herkennen. Over alle 21.167 uurwaarden die deze repo ophaalde (29 gasmaanden,
januari 2022 t/m mei 2024) deden 161 tot 170 gebieden mee en vielen er **elk uur precies 7** af
tussen 41 en 43 MJ/m³, met **niets tussen 37 en 41**. De drempel ligt in dat lege gat, dus hij is
niet kritisch gekozen.

Deze repo sluit ze uit (`gaskwaliteit.G_GAS_BOVENGRENS__MJ_M3`, met het aantal uitgesloten gebieden
per uur in de opgehaalde tabel). Zolang de zusterrepo dat niet doet, verschilt `g_gebruik__W` tussen
de twee 0,6% om een reden die niets met de datasets te maken heeft — precies het soort verschil dat
een latere vergelijking tussen de twee onbetrouwbaar maakt.

**Te doen daar:** dezelfde filtering, met de telling van uitgesloten gebieden erbij zodat het opvalt
als de verdeling ooit verandert. Er hoeft niets afgewogen te worden: er is geen dataset van
Nederlandse woningmetingen waarvoor die netgebieden wél meetellen.

---

## Wat dit niet is

Geen verzoek om de zusterrepo na te bouwen. De twee datasets verschillen wezenlijk — de ene
publiceert cumulatieve standen en de andere niet, de ene heeft warmtemeters en de andere niet — en
dat verschil is juist de reden dat ze naast elkaar worden gebruikt. Neem de **werkwijze** over waar
die past, en schrijf op waar hij niet past en waarom.

Twee plekken waar dat laatste is gebeurd, zodat niemand ze opnieuw hoeft uit te zoeken:

- **De modulus-artefacten uit IM3 komen hier niet voor.** Daar waren 410 fysisch onmogelijke waarden
  allemaal dezelfde sprong van 10.000 kWh: een register dat van 9999,9 naar 0 gaat, achteraf niet
  meer te herstellen omdat IM3 alleen de al-verschilde reeks publiceert. Hier is de zoekmethode
  overgenomen als analyse A4, en die kan het rechtstreeks toetsen omdat deze dataset de cumulatieve
  standen wél geeft: bij elke daling is de stand ervóór en erna bekend. Over 620 dalingen: **nul**
  omslag-kandidaten. Wat er wél is, is een teller die uitvalt en nul gaat melden (54% van de
  dalingen) en daarna meestal gewoon terugkomt op zijn oude stand — zie A3's spiegelparen. Een
  modulo-correctie zou hier niets repareren en wel echte uitval wegpoetsen.
- **De weerkoppeling vult niets in.** Punt 7 van het kwaliteitsrapport telt hoe vaak een kwartier
  geen weerwaarde heeft. Dat is geen terugval op een aanname zoals bij de gaswaarde, maar het is
  even onzichtbaar: wie op het weer joint en lege waarden laat vallen, verliest rijen zonder te
  weten hoeveel.
