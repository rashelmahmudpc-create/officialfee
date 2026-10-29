# OfficialFee

Verified, dated visa / passport / government fee data — every number carries a
source link and the date it was last checked. Built so a page can never publish
a fee it cannot prove.

## Why

Existing fee sites are undated, ad-choked and unsourced. OfficialFee refuses to
render a number it has not verified against an official source, so the page is
either true or absent — never a guess.

## Layout

| Path | Role |
|---|---|
| `ofdata/model.py` | `FeeRecord` — the only shape a fee may take |
| `ofdata/store.py` | load / save / validate the JSON dataset |
| `data/fees/*.json` | one file per country |
| `build.py` | static site + sitemap + JSON-LD |
| `verify.py` | fetches each `source_url`, records date + hash, promotes `draft` → `verified` |
| `tests/` | `python3 -m unittest discover -s tests` |

## Honesty gate

`build.py` will not emit a page for a record unless:

1. it has at least one `source_url`, **and**
2. `verified_on` is within `MAX_AGE_DAYS` (90), **and**
3. `status == "verified"`.

Anything else becomes a `draft` page carrying `noindex` and is left out of
`sitemap.xml`. A stale page degrades to `noindex` rather than showing an old fee
as if it were current.
