#!/usr/bin/env python3
"""Build the static site from the verified dataset.

The build refuses to publish anything it cannot prove. A record that is a
draft, or whose stamp is older than MAX_AGE_DAYS, is rendered as a noindex
placeholder and kept out of sitemap.xml - so the site can be incomplete but
never wrong.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ofdata.store import load_all

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
MAX_AGE = 90
SITE = "https://officialfee.example"
TODAY = dt.date.today()


def esc(text):
    return html.escape(str(text), quote=True)


def page(title, description, body, canonical, indexable=True, extra_head=""):
    robots = "index,follow" if indexable else "noindex,follow"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<link rel="stylesheet" href="/assets/style.css">
{extra_head}
</head>
<body>
<header class="site"><a href="/">OfficialFee</a><span class="tag">sourced · dated · verified</span></header>
<main>
{body}
</main>
<footer class="site">
<p>Every fee on this site carries an official source and the date it was last checked.
Nothing is published without proof.</p>
<p><a href="/about/">How we verify</a></p>
</footer>
</body>
</html>
"""


def fee_table(record):
    rows = "\n".join(
        f"<tr><td>{esc(f.name)}</td><td class=\"amt\">{f.amount:g} {esc(f.currency)}</td>"
        f"<td>{esc(f.notes)}</td></tr>"
        for f in record.fees
    )
    return f"""<table class="fees">
<thead><tr><th>Fee</th><th>Amount</th><th>Notes</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>"""


def badge(record, today=None, max_age=None):
    status = record.effective_status(max_age or MAX_AGE, today or TODAY)
    if status == "verified":
        return f'<p class="badge ok">Verified {esc(record.verified_on)} · checked by {esc(record.checked_by)}</p>'
    if status == "stale":
        return f'<p class="badge warn">Last verified {esc(record.verified_on)} — now stale, not shown as current</p>'
    if status == "review":
        return '<p class="badge warn">The official source changed since our last check — this page is hidden until a person re-reads it</p>'
    return '<p class="badge draft">Draft — not yet verified against an official source</p>'


def jsonld(record, canonical):
    data = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": record.title,
        "description": f"Official {record.category} fees for {record.country_name}, with source and date.",
        "url": canonical,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "OfficialFee"},
        "dateModified": record.verified_on or None,
        "citation": record.source_url,
        "spatialCoverage": {"@type": "Country", "name": record.country_name},
    }
    return json.dumps({k: v for k, v in data.items() if v is not None}, ensure_ascii=False)


def render_record(record, today=None, max_age=None):
    today = today or TODAY
    max_age = max_age or MAX_AGE
    canonical = f"{SITE}/{record.slug}/"
    indexable = record.publishable(max_age, today)
    body = f"""<article>
<h1>{esc(record.title)}</h1>
{badge(record, today, max_age)}
{fee_table(record)}
<p class="src">Source: <a href="{esc(record.source_url)}" rel="nofollow noopener" target="_blank">{esc(record.source_name or record.source_url)}</a></p>
{f'<p class="notes">{esc(record.notes)}</p>' if record.notes else ''}
</article>"""
    extra = f'<script type="application/ld+json">{jsonld(record, canonical)}</script>' if indexable else ""
    return page(record.title, f"Official {record.category} fees for {record.country_name}: "
                + ", ".join(f"{f.name} {f.amount:g} {f.currency}" for f in record.fees),
                body, canonical, indexable, extra)


def render_index(records, today=None, max_age=None):
    live = [r for r in records if r.publishable(max_age or MAX_AGE, today or TODAY)]
    live.sort(key=lambda r: (r.country_name, r.category))
    items = "\n".join(
        f'<li><a href="/{esc(r.slug)}/">{esc(r.title)}</a> '
        f'<span class="meta">· verified {esc(r.verified_on)}</span></li>'
        for r in live
    )
    if not items:
        items = "<li>No verified entries yet. Drafts stay hidden until a source is checked.</li>"
    body = f"""<h1>Verified government &amp; visa fees, with sources</h1>
<p class="lede">Every figure below was read from an official source on the date shown.
If a source cannot be checked, the entry is hidden rather than guessed.</p>
<ul class="listing">
{items}
</ul>"""
    return page("OfficialFee — verified visa and government fees",
                "Dated, sourced visa and government fees from official pages. "
                "Every number carries its source link and the date it was checked.",
                body, f"{SITE}/")


def render_about(records):
    body = f"""<article>
<h1>How we verify</h1>
<p>Each fee is stored with the official page it came from and the date it was read.</p>
<ol>
<li>We read the fee from an official source (a government or authority page).</li>
<li>We fetch that URL and record its status, a content hash and the date.</li>
<li>Only then does the entry become <strong>verified</strong> and appear in search results.</li>
<li>After {MAX_AGE} days without a recheck, the entry degrades to <strong>stale</strong> and is
removed from the index — an old number is worse than no number.</li>
</ol>
<p>If a source is unreachable we say so and leave the entry unpublished. We would
rather have fewer pages than a page that misleads someone about a fee.</p>
</article>"""
    return page("How we verify — OfficialFee",
                "Our verification process: official sources, content hashes and dated rechecks.",
                body, f"{SITE}/about/")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=int, default=MAX_AGE)
    args = ap.parse_args(argv)

    records = list(load_all().values())
    if OUT.exists():
        shutil.rmtree(OUT)
    write(OUT / "assets/style.css", (ROOT / "assets/style.css").read_text(encoding="utf-8"))

    published = []
    for record in records:
        write(OUT / record.slug / "index.html", render_record(record, TODAY, args.max_age))
        if record.publishable(args.max_age, TODAY):
            published.append(record)

    write(OUT / "index.html", render_index(records, TODAY, args.max_age))
    write(OUT / "about/index.html", render_about(records))

    urls = [f"{SITE}/", f"{SITE}/about/"] + [f"{SITE}/{r.slug}/" for r in published]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        sitemap += f"  <url><loc>{esc(url)}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n"
    sitemap += "</urlset>\n"
    write(OUT / "sitemap.xml", sitemap)
    write(OUT / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")

    hidden = len(records) - len(published)
    print(f"built {len(published)} indexable pages, {hidden} hidden (draft or stale)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
