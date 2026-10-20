@echo off
rem De minuut-preprocessing, onbeheerd en hervatbaar (ontwerp-preprocessing-minuut.md §10).
rem
rem Bedoeld om via de Windows-taakplanner gestart te worden, niet vanuit een terminal: de
rem taakplanner koppelt het proces los van de sessie die het start, zodat het sluiten van VS Code
rem of van een chatsessie de run niet meeneemt. Een achtergrondproces uit een terminal zit in een
rem job object en gaat wel mee.
rem
rem De run is hervatbaar per locatie: een locatie waarvan het definitieve bestand al bestaat wordt
rem overgeslagen. Opnieuw starten kost dus niets wat al af is.

cd /d "%~dp0"
set PYTHONPATH=src
set PYTHONUNBUFFERED=1
rem De standaard arrow-geheugenpool geeft vrijgegeven blokken niet aan het systeem terug. Bij een
rem run die honderden batches achter elkaar alloceert en weer loslaat groeit de commit charge
rem daardoor mee met het aantal batches in plaats van met de grootste batch. Gemeten op het grootste
rem bestand (1.174.876 rijen): 1.171 MB piek met de standaardpool tegen 726 MB met deze, terwijl de
rem verzamelde data in beide gevallen 311 MB is. Het is een instelling en geen ontwerp, en hij staat
rem daarom hier en niet in de code.
set ARROW_DEFAULT_MEMORY_POOL=system
rem -u erbij: PYTHONUNBUFFERED alleen bleek de log pas bij het einde
rem van het proces vrij te geven, en een run van uren die niets laat zien is niet te volgen.
if not exist data mkdir data
echo. >> data\minuut-run.log
echo ==== start %DATE% %TIME% ==== >> data\minuut-run.log
python -u -m dph_preprocessing.minuut --deadline 06:45 -v >> data\minuut-run.log 2>&1
echo ==== einde %DATE% %TIME% (exitcode %ERRORLEVEL%) ==== >> data\minuut-run.log
