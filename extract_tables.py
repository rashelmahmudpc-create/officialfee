#!/usr/bin/env python3
"""Find fee-shaped rows on official pages and queue them for review.

This is deliberately a *proposal* engine, not a publisher. It cannot tell whether
"£135" on a page is the current fee, an old one, a penalty or an example, so it
never writes to data/fees/. It writes state/extracted.json, and a human or an
agent promotes rows from there. That keeps the one dishonest failure mode -
inventing a number - structurally impossible.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "extracted.json"
UA = "OfficialFee-extractor/1.0 (+https://officialfee.example/about)"
TIMEOUT = 25
MONEY = re.compile(r"(?:£|€|\$|AUD|CAD|NZD|SGD|INR|Rs\.?|¥|CHF|AED|MYR|THB|IDR|₱|₺|₹)\s?\d[\d,]*(?:\.\d+)?", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(500_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return 0, ""


def clean(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def rows(body, limit=40):
    """Pull table rows that pair a label with a currency amount."""
    out = []
    for table in re.findall(r"<table.*?</table>", body, flags=re.S):
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S):
            cells = [clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            amounts = [m.group(0).strip() for c in cells for m in MONEY.finditer(c)]
            if not amounts:
                continue
            out.append({"label": cells[0][:160], "cells": [c[:120] for c in cells[1:4]],
                        "amounts": amounts[:4]})
            if len(out) >= limit:
                return out
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--from-candidates", action="store_true")
    ap.add_argument("--budget", type=int, default=25,
                    help="max URLs to fetch this run, so a growing queue stays polite")
    ap.add_argument("--recheck-days", type=int, default=7,
                    help="skip URLs extracted this recently unless --force")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    urls = list(args.urls)
    if args.from_candidates:
        for name in ("candidates.txt", "state/discovered.txt"):
            cand = ROOT / name
            if cand.exists():
                urls += [l.strip() for l in cand.read_text().splitlines()
                         if l.strip() and not l.startswith("#")]

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    today = dt.date.today()
    found = 0

    # A queue that only grows would re-fetch every URL every cycle, which is both
    # slow and rude to the hosts. Skip what was read recently and cap the run.
    fresh_cutoff = (today - dt.timedelta(days=args.recheck_days)).isoformat()
    todo = []
    for url in urls:
        prior = state.get(url, {}).get("checked_on")
        if not args.force and prior and prior > fresh_cutoff:
            continue
        todo.append(url)
    skipped = len(urls) - len(todo)
    todo = todo[: args.budget]
    print(f"{len(todo)} to read this run ({skipped} skipped as recently read, "
          f"{max(0, len(urls) - skipped - len(todo))} left for later)")

    for url in todo:
        status, body = fetch(url)
        if status != 200:
            print(f"  skip {status} {url}")
            continue
        r = rows(body)
        state[url] = {"checked_on": today.isoformat(), "http_status": status, "rows": r}
        found += len(r)
        print(f"  {len(r):>3} rows  {url}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nqueued {found} candidate rows for review in state/extracted.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
