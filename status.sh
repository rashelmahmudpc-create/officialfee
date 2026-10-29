#!/usr/bin/env bash
# One-glance answer to "what is the loop doing right now?"
cd "$(dirname "$0")"

PIDFILE="state/loop.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  START=$(ps -o lstart= -p "$(cat "$PIDFILE")" 2>/dev/null)
  echo "loop: RUNNING (pid $(cat "$PIDFILE"), since$START)"
else
  echo "loop: stopped"
fi

echo
echo "dataset:"
python3 - <<'PY'
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ofdata.store import load_all
d = load_all()
by_country = Counter(r.country for r in d.values())
print(f"  {len(d)} verified records across {len(by_country)} countries")
for cc, n in by_country.most_common():
    print(f"    {cc}: {n}")
flagged = [r.slug for r in d.values() if r.review_required]
if flagged:
    print(f"  needs human review: {flagged}")
PY

echo
echo "queue:"
python3 harvest.py --report 2>/dev/null | sed 's/^/  /'

echo
echo "last cycles:"
tail -6 state/journal.log 2>/dev/null | sed 's/^/  /'
