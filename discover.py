#!/usr/bin/env python3
"""Grow the candidate queue from official sitemaps.

Only government/authority hosts are read, and only URLs whose path looks like a
fee page. Everything found is appended to candidates.txt, which is a *queue* -
nothing is published from here. The point is to keep a night's worth of real
sources lined up for a person or an agent to read.

Usage: python3 discover.py [--limit 200]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEEDS = ROOT / "candidates.txt"
DISCOVERED = ROOT / "state" / "discovered.txt"
UA = "OfficialFee-discoverer/1.0 (+https://officialfee.example/about)"
TIMEOUT = 25

# Official hosts we have already proven reachable and worth reading.
HOSTS = [
    # Only hosts whose sitemap was confirmed to answer. A dead entry just prints
    # "no sitemap" every cycle and wastes a request.
    "https://www.gov.uk",
    "https://www.uscis.gov",
    "https://www.irishimmigration.ie",
    "https://immi.homeaffairs.gov.au",
    "https://www.mom.gov.sg",
    "https://www.mfa.gov.sg",
    "https://www.immigration.govt.nz",
    "https://www.moi.gov.ae",
]
SITEMAPS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
# A path is interesting if it talks about a fee, a visa or a passport.
# A URL is interesting only if it is BOTH in the immigration/visa domain AND about
# money. "price" alone matches things like a drug-pricing review board; "immigration"
# alone matches every news post. Requiring both is what keeps the queue usable.
TOPIC = re.compile(r"(immigration|visa|passport|citizenship|residence|migration|naturali)", re.I)
MONEY = re.compile(r"(fee|fees|charge|charges|price|pricing|cost|costs|surcharge)", re.I)
WANT = re.compile(rf"{TOPIC.pattern}|{MONEY.pattern}", re.I)
SKIP = re.compile(
    r"(\.(jpg|png|gif|svg|css|js|zip|mp4)$"
    r"|/(news|press|blog|tag|search|login|contact|media|notice|announcement)\b"
    r"|(upcoming|ceremony|announces|reminder|scheduled-maintenance|portal|maintenance|"
    r"open-call|appointments|travelling|christmas|important-notice|guidance-regarding))", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(1_500_000).decode("utf-8", "ignore")
    except Exception:
        return ""


def urls_from(xml):
    """Pull <loc> values, and follow one level of a sitemap index."""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    return locs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200, help="max new URLs to add")
    args = ap.parse_args(argv)

    known = set()
    for path in (SEEDS, DISCOVERED):
        if path.exists():
            known |= {l.strip() for l in path.read_text().splitlines() if l.strip()}

    found = []
    for host in HOSTS:
        if len(found) >= args.limit:
            break
        xml = ""
        for path in SITEMAPS:
            xml = fetch(host + path)
            if "<loc>" in xml:
                break
        if not xml:
            print(f"  no sitemap  {host}")
            continue
        locs = urls_from(xml)
        # A sitemap index points at other sitemaps; open the promising ones.
        # A sitemap index points at more sitemaps, whose own names are often
        # opaque ("sitemap_1.xml", ".../sitemap/.../1"). Those are navigation,
        # not content, so they must NOT be topic-filtered - only the pages inside
        # them should be. Filtering them here silently yielded nothing.
        children = [u for u in locs if u.endswith(".xml") or "/sitemap" in u][:4]
        for child in children:
            sub = fetch(child)
            locs += urls_from(sub)
        host_new = 0
        for url in locs:
            if len(found) >= args.limit:
                break
            if url in known or not url.startswith("https://"):
                continue
            if not (TOPIC.search(url) and MONEY.search(url)):
                continue
            if SKIP.search(url):
                continue
            known.add(url)
            found.append(url)
            host_new += 1
        print(f"  {host_new:>4} new  {host}")

    if found:
        DISCOVERED.parent.mkdir(parents=True, exist_ok=True)
        with DISCOVERED.open("a", encoding="utf-8") as fh:
            for url in found:
                fh.write(url + "\n")
    print(f"added {len(found)} new candidate URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
