#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# De volledige DPH-verwerking en -analyse, onbeheerd en hervatbaar.
#
# Beide stappen slaan hun tussenresultaten per chunk respectievelijk per analyse op en slaan bij een
# herstart over wat al klaar is. Daarom mag deze wrapper een mislukte stap gewoon opnieuw proberen:
# hij begint dan niet vooraan, maar bij het eerste stuk dat nog niet af was. Dat is de hele reden
# dat dit script bestaat -- een run van uren die op stuk 160 van de 174 sneuvelt moet geen dag
# kosten.
#
# Gebruik:  bash draai_volledig.sh
# Log:      data/run-<datum>-<tijd>.log  (en de laatste run ook als data/run-laatste.log)

set -u
cd "$(dirname "$0")" || exit 1

POGINGEN=${POGINGEN:-5}
WACHT__s=${WACHT__s:-30}

mkdir -p data
STEMPEL=$(date +%Y%m%d-%H%M%S)
LOG="data/run-${STEMPEL}.log"
ln -sf "run-${STEMPEL}.log" data/run-laatste.log 2>/dev/null || true

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

stap() {
    naam="$1"; shift
    for poging in $(seq 1 "$POGINGEN"); do
        log "== ${naam}: poging ${poging} van ${POGINGEN}"
        if "$@" >>"$LOG" 2>&1; then
            log "== ${naam}: klaar"
            return 0
        fi
        code=$?
        log "== ${naam}: MISLUKT (exitcode ${code}); over ${WACHT__s} s hervatten vanaf het laatste voltooide stuk"
        sleep "$WACHT__s"
    done
    log "== ${naam}: OPGEGEVEN na ${POGINGEN} pogingen. Zie hierboven in ${LOG} wat er misging."
    return 1
}

log "Start. Python: $(python -V 2>&1). Werkmap: $(pwd)"
log "Vrije schijfruimte: $(df -h . | tail -1 | awk '{print $4}')"

stap "preprocessing" \
    python -m dph_preprocessing \
        --raw-dir data/raw --out-dir data/processed --docs-dir docs -v \
    || exit 1

stap "analyses" \
    python -m dph_preprocessing.analyses \
        --in-dir data/processed --docs-dir docs -v \
    || exit 1

log "ALLES KLAAR."
log "Uitvoer: data/processed/*.parquet, docs/data-quality.md, docs/analyse-bevindingen.md"
