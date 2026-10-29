# OfficialFee

Verified, dated visa / passport / government fee data. Every published number
carries the official page it came from, the date it was read, and — where the
source is HTML — a pattern that proves the number is still on that page.

## Why

Existing fee sites are undated, ad-choked and unsourced. OfficialFee refuses to
render a number it has not verified, so a page is either true or absent — never a
guess.

## Layout

| Path | Role |
|---|---|
| `ofdata/model.py` | `FeeRecord` — the only shape a fee may take |
| `ofdata/store.py` | load / save / validate the JSON dataset |
| `data/fees/*.json` | one file per country |
| `verify.py` | fetches each source, checks the number is still there, stamps the date |
| `build.py` | static site, sitemap, JSON-LD |
| `harvest.py` | probes queued URLs and records what it saw |
| `extract_tables.py` | pulls fee-shaped table rows into a review queue |
| `stage.py` | turns extracted rows into **draft** records |
| `discover.py` | grows the queue from official sitemaps |
| `loop.sh` | the work loop: discover → probe → extract → stage → verify → build → test |
| `status.sh` | one-glance status |
| `tests/` | `python3 -m unittest discover -s tests` |

## The honesty gate

`build.py` publishes a page only when **all** of these hold:

1. at least one `source_url`,
2. `verified_on` within `MAX_AGE_DAYS` (90),
3. `status == "verified"`, and
4. `review_required` is false.

Anything else renders as a `noindex` page that is left out of `sitemap.xml`. A
stale page degrades to `noindex` rather than showing an old fee as if it were
current.

## Three ways a number can be wrong, and what stops each

| Failure | Guard |
|---|---|
| The source page moved or died | `verify.py` records the HTTP status; a non-2xx flags the record |
| The page changed and now says something else | content hash changes → `review_required`, date **not** refreshed, page hidden |
| The page is fine but the number was transcribed wrongly | `claim_patterns` — a regex that must still match the page |

That third one is the important one: a record can be perfectly reachable and still
be wrong. `claim_patterns` is how a record proves its own number, and
`tests/test_build.py` covers the failure modes.

## Drafts

`stage.py` is the only way the loop can add a fee, and it always adds a draft:
`noindex`, no verified date, absent from the sitemap. Promotion is a human act —
read the source, confirm the number, then either set `status: "verified"` with a
date or delete the draft.

Ambiguity is skipped rather than guessed: a row showing two amounts (old/new,
standard/express) is dropped, as is anything over `MAX_FEE` (a budget line, not a
fee).

## Running it

```bash
python3 verify.py --all          # re-check every source
python3 verify.py --ack <slug>   # clear review_required after re-reading a source
python3 build.py                 # rebuild dist/
./loop.sh 10                     # work for 10 hours
./status.sh                      # what is happening now
```
