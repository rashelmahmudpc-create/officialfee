#!/usr/bin/env bash
# OfficialFee work loop.
#
# Each cycle does only mechanical work: probe candidate sources, extract
# fee-shaped rows, re-verify every published source, rebuild the site, and write
# a journal entry. It never invents a fee - rows it finds are queued for review.
#
# Usage: ./loop.sh [HOURS]      default 10 hours
#        BUDGET_MIN=5 ./loop.sh 1     shorter cycles for testing

set -uo pipefail
cd "$(dirname "$0")"

# One loop at a time: two would double the request rate against the same hosts
# and trip their rate limits, which then looks like broken sources.
#
# This is a pidfile, not flock, on purpose. Children inherit open file
# descriptors, so a slow helper that outlives the loop keeps holding an flock and
# the next run refuses to start forever. A pidfile plus a liveness check has no
# such inheritance problem.
PIDFILE="state/loop.pid"
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null \
     && grep -qa "loop.sh" "/proc/$OLD_PID/cmdline" 2>/dev/null; then
    echo "another loop is already running (pid $OLD_PID)" >&2
    exit 1
  fi
  echo "clearing stale pidfile (pid ${OLD_PID:-?} is gone)" >&2
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

HOURS="${1:-10}"
BUDGET_MIN="${BUDGET_MIN:-20}"
# Whole seconds, so a fractional hour like 0.5 works for testing.
SECONDS_TOTAL=$(python3 -c "print(int(float('${HOURS}') * 3600))")
DEADLINE=$(( $(date +%s) + SECONDS_TOTAL ))
JOURNAL="state/journal.log"
CYCLE=0

mkdir -p state
log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$JOURNAL"; }

log "=== loop start: ${HOURS}h, cycle budget ${BUDGET_MIN}m ==="

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  CYCLE=$((CYCLE + 1))
  log "--- cycle $CYCLE ---"

  # 1. Keep the queue fed from official sitemaps, then probe what is new.
  #    Discovery only reads government hosts and only appends to the queue.
  log "discover: $(python3 discover.py --limit 60 2>&1 | tail -1)"
  log "probe: $(python3 harvest.py --probe 25 2>&1 | tail -3 | tr '\n' ' ')"
  # Be polite: the probe phase just hit these hosts, and hammering them makes
  # them rate-limit, which would look like a broken source.
  sleep 5
  log "extract: $(python3 extract_tables.py --from-candidates 2>&1 | tail -1)"
  sleep 5

  # 2. Re-verify every published record against its source. A source that
  #    changed under us is flagged for review, never silently re-stamped.
  VERIFY="$(python3 verify.py --all 2>&1 | tail -1)"
  log "verify: $VERIFY"
  case "$VERIFY" in
    *"failed 0"*) : ;;
    *) log "WARNING: some sources failed verification this cycle - see above" ;;
  esac

  # 3. Rebuild the site; the gate decides what is indexable.
  log "build: $(python3 build.py 2>&1 | tail -1)"

  # 4. Run the tests - a red suite stops the loop rather than shipping a guess.
  if python3 -m unittest discover -s tests >/dev/null 2>&1; then
    log "tests: ok"
  else
    log "tests: FAILED - stopping so a human can look"
    break
  fi

  # 5. How much is left to do, honestly.
  log "queue: $(python3 harvest.py --report 2>&1 | head -1)"

  REMAIN=$(( DEADLINE - $(date +%s) ))
  [ "$REMAIN" -le 0 ] && break
  SLEEP=$(( BUDGET_MIN * 60 ))
  [ "$SLEEP" -lt 1 ] && SLEEP=1
  [ "$SLEEP" -gt "$REMAIN" ] && SLEEP=$REMAIN
  log "sleeping ${SLEEP}s (cycle $CYCLE done, $((REMAIN/60))m left)"
  sleep "$SLEEP"
done

log "=== loop end after $CYCLE cycles ==="
