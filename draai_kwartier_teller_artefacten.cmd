@echo off
rem Herverwerking van het kwartierpad na de reparatie van de drie teller-artefacten
rem (ontwerp-teller-artefacten.md, Fase C). Draait alleen de preprocessing-stap (niet de analyses),
rem want alleen measurements.parquet/quality.parquet/docs/data-quality.md moeten de reparatie
rem krijgen.
rem
rem Bedoeld om via de Windows-taakplanner gestart te worden, niet vanuit een terminal: de
rem taakplanner koppelt het proces los van de sessie die het start (zelfde reden als
rem draai_minuut.cmd/taak-minuut.xml). De vorige volledige run (07-09-2026) deed de
rem preprocessing-stap in ongeveer 23 minuten; dat is boven de vuistregel van tien minuten om
rem synchroon te draaien.
rem
rem De run is chunked en hervatbaar (CLAUDE.md): een deelbestand per blok woningen, en een
rem herstart slaat over wat al klaar is. data/processed is vooraf leeg (de vorige uitvoer staat
rem in data/processed-voor-teller-artefacten-20260922), dus dit begint gegarandeerd vanaf nul.

cd /d C:\dev\demoprojecthybride-dataset-preprocessing
set PYTHONPATH=src
set PYTHONUNBUFFERED=1
if not exist data mkdir data
echo. >> data\kwartier-teller-artefacten-run.log
echo ==== start %DATE% %TIME% ==== >> data\kwartier-teller-artefacten-run.log
python -u -m dph_preprocessing --raw-dir data\raw --out-dir data\processed --docs-dir docs -v >> data\kwartier-teller-artefacten-run.log 2>&1
echo ==== einde %DATE% %TIME% (exitcode %ERRORLEVEL%) ==== >> data\kwartier-teller-artefacten-run.log
