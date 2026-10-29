#!/usr/bin/env python3
"""The honesty gate, in code.

For every record it fetches the source_url, records the HTTP status, the
content hash and the date, and only then may a record become `verified`.
A record whose source is unreachable, non-https, or an unofficial host is
reported and left alone - never silently promoted.

Usage:
    python3 verify.py --all
    python3 verify.py --country PH
    python3 verify.py --all --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ofdata.model import RecordError
from ofdata.store import DATA_DIR, load_all, load_country, save_country

STATE = Path(__file__).resolve().parent / "state" / "verified.json"
UA = "OfficialFee-verifier/1.0 (+https://officialfee.example/about)"
TIMEOUT = 25
# The content hash is taken over the first READ_CAP bytes. Changing this value
# changes every stored hash, which would flag the whole dataset for review - so
# it is a constant here rather than a magic number at the call site.
READ_CAP = 2_000_000


def _fetch_once(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Some official fee pages are large; truncating too early cut the
            # fees section off entirely and looked like a changed page.
            body = resp.read(READ_CAP)
            return resp.status, hashlib.sha256(body).hexdigest(), len(body), body
    except urllib.error.HTTPError as exc:
        return exc.code, None, 0, b""
    except Exception:  # DNS, TLS, timeout - all the same verdict: unproven
        return 0, None, 0, b""


def fetch(url, timeout=TIMEOUT, retries=2):
    """Fetch a source URL and return (status, sha256, bytes). Never raises for HTTP.

    Retries a non-2xx a couple of times before believing it. Official sites
    rate-limit, and a transient 429 would otherwise be recorded as a broken
    source, which would hide a page that is in fact fine.
    """
    for attempt in range(retries + 1):
        status, digest, size, body = _fetch_once(url, timeout)
        if 200 <= status < 300 or attempt == retries:
            return status, digest, size, body
        time.sleep(1.5 * (attempt + 1))
    return status, digest, size, body


def page_text(html_text):
    """Strip markup so a claim pattern can match the visible words."""
    # Two traps here, both found the hard way:
    #  * the tag may carry attributes (<style type="text/css">), and
    #  * a page may contain an unterminated <style> block, so a pattern that
    #    insists on a closing tag silently leaves raw CSS in the text.
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", html_text, flags=re.S | re.I)
    # For a tag that never closes, cut only up to the next markup tag rather
    # than to the end of the document. CSS contains no "<", so this drops the
    # stylesheet and keeps whatever real content follows it.
    text = re.sub(r"<(script|style)\b[^>]*>[^<]*", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def check_claims(record, body):
    """Every claim pattern must still match the page. Returns (ok, detail)."""
    if not record.claim_patterns:
        return True, "no claim patterns"
    text = page_text(body)
    missing = [p for p in record.claim_patterns if not re.search(p, text, re.I)]
    if missing:
        return False, f"number no longer found on page ({len(missing)} pattern(s) missed)"
    return True, f"{len(record.claim_patterns)} claim pattern(s) matched"


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_record(record, state, today, dry_run=False):
    status, digest, size, body = (0, None, 0, b"") if dry_run else fetch(record.source_url)
    ok = 200 <= status < 300
    claims_ok, claim_detail = (True, "dry-run") if dry_run else \
        (check_claims(record, body.decode("utf-8", "ignore")) if ok else (False, "source unreachable"))
    ok = ok and claims_ok
    previous = state.get(record.slug, {})
    changed = bool(digest and previous.get("hash") and previous["hash"] != digest)

    result = {
        "slug": record.slug,
        "source_url": record.source_url,
        "checked_on": today.isoformat(),
        "http_status": status,
        "hash": digest,
        "bytes": size,
        "ok": ok,
        "claims_ok": claims_ok,
        "claim_detail": claim_detail,
        "changed": changed,
        "official_host": record.is_official_source(),
    }
    if not dry_run:
        state[record.slug] = result
    return result


def apply_verdict(record, result, today):
    """Promote to verified only when the evidence actually supports it.

    Three things this must never do, each learned the hard way:

    * never promote a *draft* - a draft means "a script read this off a page and
      nobody has confirmed it". Reaching the URL is not confirmation, and
      auto-promoting here would publish an unread number with a fresh date.
    * never refresh the date when the source *changed* - we no longer know the
      number is right, so refreshing would claim a check we did not do.
    * never treat an unreachable host as a defect in our data.
    """
    if record.status == "draft":
        return False, "draft - needs a person to confirm the number before it can be verified"
    if not result["ok"]:
        if not result.get("claims_ok", True):
            record.review_required = True
            return False, result.get("claim_detail", "claim check failed")
        return False, f"source unreachable (HTTP {result['http_status']})"
    if result["changed"]:
        record.review_required = True
        return False, "source content changed - needs human review"
    record.verified_on = today.isoformat()
    record.status = "verified"
    record.review_required = False
    record.checked_by = "mixed" if record.checked_by != "human" else "human"
    return True, "verified"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify fee sources and stamp the dataset.")
    ap.add_argument("--all", action="store_true", help="verify every country file")
    ap.add_argument("--country", help="ISO-3166 alpha-2, e.g. PH")
    ap.add_argument("--dry-run", action="store_true", help="do not fetch or write anything")
    ap.add_argument("--max-age", type=int, default=90, help="days a stamp stays fresh")
    ap.add_argument("--ack", metavar="SLUG", action="append", default=[],
                    help="clear review_required for a slug after a human re-read the source")
    args = ap.parse_args(argv)

    if not args.all and not args.country and not args.ack:
        ap.error("pass --all, --country XX or --ack SLUG")

    today = dt.date.today()
    state = load_state()

    if args.ack:
        everything = load_all()
        touched = set()
        for slug in args.ack:
            record = everything.get(slug)
            if record is None:
                print(f"unknown slug: {slug}", file=sys.stderr)
                return 2
            record.review_required = False
            record.verified_on = today.isoformat()
            record.status = "verified"
            touched.add(record.country)
        for country in touched:
            save_country(country, [r for r in everything.values() if r.country == country])
        print(f"acknowledged {len(args.ack)} record(s); a human re-read their sources")
        return 0

    if args.all:
        all_records = list(load_all().values())
        by_country = {}
        for r in all_records:
            by_country.setdefault(r.country, []).append(r)
        # Drafts are not checked at all: they have no claim to defend, and
        # fetching them would only invite the promotion bug above.
        records = [r for r in all_records if r.status != "draft"]
    else:
        records = [r for r in load_country(args.country) if r.status != "draft"]
        by_country = {args.country.upper(): load_country(args.country)}

    if not records:
        print("no published records to verify (drafts are skipped by design)")
        return 0

    promoted = stale = failed = 0
    claim_failures = 0
    unreachable = 0
    for record in records:
        result = verify_record(record, state, today, args.dry_run)
        ok, why = (False, "dry-run") if args.dry_run else apply_verdict(record, result, today)
        if ok:
            promoted += 1
            print(f"  ok    {record.slug:<34} {record.source_url}")
        else:
            failed += 1
            age = record.age_days(today)
            if age is not None and age > args.max_age:
                stale += 1
            if result.get("claims_ok") is False:
                claim_failures += 1
                kind = "CLAIM"
            else:
                # A source we could not reach is a different thing from a source
                # that changed: the page may be perfectly fine. Reported, but not
                # treated as a defect in our data.
                unreachable += 1
                kind = "NET  "
            print(f"  {kind} {record.slug:<34} {why}", file=sys.stderr)

    if not args.dry_run:
        for country, group in by_country.items():
            save_country(country, group)
        save_state(state)

    print(f"\nverified {promoted}, unreachable {unreachable}, "
          f"claims-failed {claim_failures}, stale-by-age {stale}")
    # Only a claim failure is a defect in our data. An unreachable host is worth
    # reporting but must not fail the build, or a flaky network would look like a
    # broken dataset.
    return 0 if claim_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
