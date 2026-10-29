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
CANDIDATES = ROOT / "candidates.txt"
UA = "OfficialFee-discoverer/1.0 (+https://officialfee.example/about)"
TIMEOUT = 25

# Official hosts we have already proven reachable and worth reading.
HOSTS = [
    "https://www.gov.uk",
    "https://www.uscis.gov",
    "https://www.irishimmigration.ie",
    "https://immi.homeaffairs.gov.au",
    "https://www.canada.ca",
    "https://www.mom.gov.sg",
    "https://www.ica.gov.sg",
    "https://www.imi.gov.my",
    "https://www.gdrfad.gov.ae",
]
SITEMAPS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
# A path is interesting if it talks about a fee, a visa or a passport.
# Money words, not "immigration" - that alone matches every news post on a site.
WANT = re.compile(r"(fee|fees|charge|charges|price|pricing|cost|costs|surcharge)", re.I)
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
    if CANDIDATES.exists():
        known = {l.strip() for l in CANDIDATES.read_text().splitlines() if l.strip()}

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
        children = [u for u in locs if u.endswith(".xml") and WANT.search(u)][:4]
        for child in children:
            sub = fetch(child)
            locs += urls_from(sub)
        host_new = 0
        for url in locs:
            if len(found) >= args.limit:
                break
            if url in known or not url.startswith("https://"):
                continue
            if not WANT.search(url) or SKIP.search(url):
                continue
            known.add(url)
            found.append(url)
            host_new += 1
        print(f"  {host_new:>4} new  {host}")

    if found:
        with CANDIDATES.open("a", encoding="utf-8") as fh:
            for url in found:
                fh.write(url + "\n")
    print(f"added {len(found)} new candidate URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
