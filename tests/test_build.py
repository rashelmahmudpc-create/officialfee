import datetime as dt
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build
from ofdata.model import FeeItem, FeeRecord

TODAY = dt.date(2026, 6, 1)


def rec(**kw):
    base = dict(country="GB", country_name="United Kingdom", slug="t-fee", category="visa",
                title="T", fees=[FeeItem("Visa", 100, "GBP")],
                source_url="https://www.gov.uk/visa-fees", verified_on="2026-01-01",
                status="verified")
    base.update(kw)
    return FeeRecord(**base)


class TestBuildGate(unittest.TestCase):
    def test_fresh_verified_is_indexable(self):
        r = rec(verified_on="2026-05-01")
        html = build.render_record(r, TODAY)
        self.assertIn('content="index,follow"', html)
        self.assertIn("application/ld+json", html)
        self.assertIn("£" if False else "GBP", html)

    def test_draft_page_is_noindex_and_has_no_jsonld(self):
        r = rec(status="draft")
        html = build.render_record(r, TODAY)
        self.assertIn("noindex,follow", html)
        self.assertNotIn("application/ld+json", html)

    def test_stale_page_is_noindex(self):
        r = rec(verified_on="2020-01-01")
        html = build.render_record(r, TODAY)
        self.assertIn("noindex,follow", html)

    def test_index_lists_only_publishable(self):
        good = rec(slug="good-fee", verified_on="2026-05-01")
        bad = rec(slug="bad-fee", verified_on="2020-01-01")
        html = build.render_index([good, bad], TODAY)
        self.assertIn("good-fee", html)
        self.assertNotIn("bad-fee", html)

    def test_changed_source_page_is_noindex(self):
        r = rec(review_required=True)
        html = build.render_record(r, TODAY)
        self.assertIn("noindex,follow", html)
        self.assertIn("hidden until a person re-reads", html)
        self.assertNotIn("application/ld+json", html)

    def test_source_link_is_present(self):
        html = build.render_record(rec())
        self.assertIn("https://www.gov.uk/visa-fees", html)


if __name__ == "__main__":
    unittest.main()
