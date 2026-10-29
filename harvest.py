#!/usr/bin/env python3
"""Queue-driven source discovery. Deliberately does NOT extract fees.

Finding a fee page and reading a number off it are different jobs. A script can
reliably do the first (fetch, measure, hash, record) and cannot honestly do the
second without judgement. So this only ever *queues* a candidate and says what it
saw - the number itself is still read and entered by a person or an agent.

Usage:
    python3 harvest.py --probe 20
    python3 harvest.py --report
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATES = ROOT / "candidates.txt"
STATE = ROOT / "state" / "candidates.json"
UA = "OfficialFee-harvester/1.0 (+https://officialfee.example/about)"
TIMEOUT = 20

# A number only counts as a fee signal if a currency symbol sits next to it.
FEE_RE = re.compile(
    r"(?:£|€|\$|AUD|CAD|NZD|SGD|INR|Rs\.?|BDT|¥|CHF|AED|MYR|THB|IDR|PHP|₱|₺|₹)\s?\d[\d,]{1,}",
    re.I,
)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(400_000).decode("utf-8", "ignore")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return 0, ""


def fee_hits(body):
    text = re.sub(r"<(script|style).*?</\1>", " ", body, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return sorted({m.group(0).strip() for m in FEE_RE.finditer(text)})[:12]


def probe(url, state, today):
    status, body = fetch(url)
    hits = fee_hits(body) if status == 200 else []
    entry = {
        "url": url,
        "last_probe": today.isoformat(),
        "http_status": status,
        "bytes": len(body),
        "fee_like_hits": hits,
        "verdict": "candidate" if (status == 200 and len(hits) >= 3) else
                   ("reachable-no-fees" if status == 200 else "unreachable"),
    }
    state[url] = entry
    return entry


def candidates():
    if not CANDIDATES.exists():
        return []
    return [l.strip() for l in CANDIDATES.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=0, help="probe up to N never-probed URLs")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    today = dt.date.today()
    state = load_state()

    if args.probe:
        todo = [u for u in candidates() if u not in state][: args.probe]
        if not todo:
            print("queue empty - nothing new to probe")
        for url in todo:
            e = probe(url, state, today)
            print(f"  {e['verdict']:<18} {e['http_status']:<4} {len(e['fee_like_hits'])} hits  {url}")
        save_state(state)

    if args.report or not args.probe:
        counts = {}
        for e in state.values():
            counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
        total = len(candidates())
        print(f"queue: {total} urls, probed: {len(state)}, pending: {max(0, total - len(state))}")
        for k, v in sorted(counts.items()):
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
