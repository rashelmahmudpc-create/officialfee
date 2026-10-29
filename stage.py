#!/usr/bin/env python3
"""Turn extracted rows into *draft* records, so the loop's night is not wasted.

This is the only way the loop can add a fee, and it adds it as a draft: the page
is rendered with noindex, kept out of sitemap.xml, and carries no verified date.
A person or an agent then reads the source, confirms the number and promotes it.

So the loop can prepare work, but it can never publish a number on its own. That
split is the whole point - it makes "the site is honest" a property of the
structure rather than a promise about the script's judgement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ofdata.model import RecordError
from ofdata.store import DATA_DIR, load_all, save_country

EXTRACTED = Path(__file__).resolve().parent / "state" / "extracted.json"

# Only a label that names a visa/passport/fee product is worth staging.
LABEL_WANT = re.compile(r"(visa|passport|permit|citizen|naturali|residen|fee|surcharge|permit|licence|license)", re.I)
LABEL_SKIP = re.compile(r"(exempt|waiver of the fee|refund|penalt|fine|deposit|example|total|subtotal|balance)", re.I)

# Currency word -> ISO code, so the record can be validated.
CURRENCY = {
    "£": "GBP", "€": "EUR", "$": None, "usd": "USD", "aud": "AUD", "cad": "CAD",
    "nzd": "NZD", "sgd": "SGD", "inr": "INR", "rs": "INR", "myr": "MYR", "aed": "AED",
    "thb": "THB", "idr": "IDR", "php": "PHP", "₱": "PHP", "₹": "INR", "¥": "JPY",
    "chf": "CHF", "try": "TRY", "₺": "TRY", "bdt": "BDT", "taka": "BDT",
}
AMOUNT = re.compile(r"(£|€|\$|AUD|CAD|NZD|SGD|INR|Rs\.?|MYR|AED|THB|IDR|PHP|₱|₹|¥|CHF|TRY|₺|BDT)\s?([\d,]+(?:\.\d+)?)", re.I)

# Pages that merely mention money - budgets, annual reports, committee minutes -
# are not fee pages, and a number lifted from one would be nonsense on the site.
URL_SKIP = re.compile(
    r"(transition-binder|committee|parliament|annual-report|departmental-plan|"
    r"financial-statement|results-report|budget|consultation|news|media-room|"
    r"statistics|research|report|fee-change|fee-changes)", re.I)

# A single government fee above this is almost certainly a budget line or a
# multi-year total, not one person's fee. Better to skip a real outlier than to
# publish a number that is wrong by six orders of magnitude.
MAX_FEE = 100_000

# Which currency "$" means depends on the host, so it is stated per host rather
# than guessed. A host not listed here is skipped instead of assumed.
DOLLAR_HOSTS = {
    "uscis.gov": "USD", "canada.ca": "CAD", "homeaffairs.gov.au": "AUD",
    "immigration.govt.nz": "NZD",
}


def currency_for(symbol, url):
    if symbol == "$":
        for host, code in DOLLAR_HOSTS.items():
            if host in url:
                return code
        return None
    key = symbol.lower() if symbol.isalpha() else symbol
    return CURRENCY.get(key)


def parse_amount(text):
    m = AMOUNT.search(text)
    if not m:
        return None, None
    try:
        return float(m.group(2).replace(",", "")), m.group(1)
    except ValueError:
        return None, None


def slugify(*parts):
    raw = "-".join(parts).lower()
    raw = raw.replace("\\n", " ").replace("\n", " ")
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return re.sub(r"-{2,}", "-", raw)[:80]


def country_from_url(url):
    """Map a source host to an ISO country code. Unknown hosts are skipped."""
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    for needle, code, name in (
        ("gov.uk", "GB", "United Kingdom"),
        ("uscis.gov", "US", "United States"),
        ("irishimmigration.ie", "IE", "Ireland"),
        ("canada.ca", "CA", "Canada"),
        ("homeaffairs.gov.au", "AU", "Australia"),
        ("mom.gov.sg", "SG", "Singapore"),
        ("ica.gov.sg", "SG", "Singapore"),
        ("imi.gov.my", "MY", "Malaysia"),
        ("gdrfad.gov.ae", "AE", "United Arab Emirates"),
        ("immigration.govt.nz", "NZ", "New Zealand"),
    ):
        if needle in host:
            return code, name
    return None, None


def stage_rows(url, rows, existing_slugs, today, limit=8, known_amounts=None):
    """Build draft records from a page's extracted rows. Returns (records, notes)."""
    if URL_SKIP.search(url):
        return [], ["not a fee page (report/budget/committee)"]
    country, country_name = country_from_url(url)
    if not country:
        return [], ["host not mapped to a country"]
    out, notes = [], []
    for row in rows:
        if len(out) >= limit:
            break
        label = row.get("label", "")
        if not LABEL_WANT.search(label) or LABEL_SKIP.search(label):
            continue
        # A row with several amounts is almost always an old/new or
        # standard/express pair. Picking one would be a coin flip, so the row is
        # skipped rather than guessed - an unpublished draft costs nothing, a
        # draft carrying the wrong number costs trust.
        amounts = AMOUNT.findall(label) + AMOUNT.findall(" ".join(row.get("cells", [])))
        distinct = {a[1] for a in amounts}
        if len(distinct) != 1:
            if len(distinct) > 1:
                notes.append(f"skipped {label[:40]!r}: {len(distinct)} amounts, ambiguous")
            continue
        amount, symbol = parse_amount(label) or (None, None)
        if amount is None:
            amount, symbol = parse_amount(" ".join(row.get("cells", [])))
        if amount is None or amount <= 0:
            continue
        if amount > MAX_FEE:
            notes.append(f"skipped {label[:40]!r}: {amount:g} looks like a total, not a fee")
            continue
        currency = currency_for(symbol, url)
        if not currency:
            notes.append(f"unknown currency {symbol!r} - skipped")
            continue
        slug = slugify(country, label, currency)
        if slug in existing_slugs:
            continue
        # Do not re-stage a figure that is already in the dataset for this
        # country: a draft duplicating a verified page is just clutter.
        if known_amounts and (round(amount, 2), currency) in known_amounts.get(country, set()):
            notes.append(f"skipped {label[:40]!r}: {amount:g} {currency} already in the dataset")
            continue
        try:
            from ofdata.model import FeeItem, FeeRecord
            record = FeeRecord(
                country=country, country_name=country_name, slug=slug,
                category="visa" if "visa" in label.lower() else "fee",
                title=f"{label.strip()[:110]} ({country_name})",
                fees=[FeeItem(name=label.strip()[:110], amount=amount, currency=currency)],
                source_url=url, source_name=url.split("//", 1)[-1].split("/", 1)[0],
                status="draft", checked_by="automated",
                notes="Staged automatically from a source page. The number has NOT "
                      "been confirmed by a person, so this is a draft and is not published.",
            )
        except RecordError as exc:
            notes.append(f"skipped {label[:40]!r}: {exc}")
            continue
        existing_slugs.add(slug)
        out.append(record)
    return out, notes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-per-page", type=int, default=8)
    ap.add_argument("--max-drafts", type=int, default=60,
                    help="stop staging once the dataset holds this many drafts, so "
                         "the queue cannot grow into unreadable noise")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not EXTRACTED.exists():
        print("no extraction state yet")
        return 0
    state = json.loads(EXTRACTED.read_text(encoding="utf-8"))
    everything = load_all()
    existing = set(everything)
    today = dt.date.today().isoformat()

    known_amounts = {}
    for r in everything.values():
        for f in r.fees:
            known_amounts.setdefault(r.country, set()).add((round(f.amount, 2), f.currency))

    already_draft = sum(1 for r in everything.values() if r.status == "draft")
    if already_draft >= args.max_drafts:
        print(f"{already_draft} drafts already staged (cap {args.max_drafts}) - "
              f"promote or drop some before staging more")
        return 0

    staged, per_country = [], {}
    for url, entry in state.items():
        rows = entry.get("rows") or []
        if not rows:
            continue
        records, notes = stage_rows(url, rows, existing, today, args.limit_per_page,
                                    known_amounts)
        for r in records:
            per_country.setdefault(r.country, []).append(r)
        staged += records

    for cc, recs in per_country.items():
        merged = [r for r in everything.values() if r.country == cc] + recs
        if args.dry_run:
            print(f"  would stage {len(recs)} draft(s) for {cc}")
            continue
        save_country(cc, merged)
        print(f"  staged {len(recs)} draft(s) for {cc}")

    print(f"\nstaged {len(staged)} draft records (noindex, not in sitemap, no verified date)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
