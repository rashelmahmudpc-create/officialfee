import datetime as dt
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ofdata.model import FeeItem, FeeRecord, RecordError


def rec(**kw):
    base = dict(country="GB", country_name="United Kingdom", slug="x-fee", category="visa",
                title="T", fees=[FeeItem("Visa", 100, "GBP")],
                source_url="https://www.gov.uk/visa-fees", verified_on="2026-01-01",
                status="verified")
    base.update(kw)
    return FeeRecord(**base)


class TestModel(unittest.TestCase):
    def test_rejects_missing_source(self):
        with self.assertRaises(RecordError):
            rec(source_url="")

    def test_rejects_plain_http(self):
        with self.assertRaises(RecordError):
            rec(source_url="http://www.gov.uk/x")

    def test_rejects_no_fees(self):
        with self.assertRaises(RecordError):
            rec(fees=[])

    def test_rejects_bad_currency(self):
        with self.assertRaises(RecordError):
            FeeItem("Visa", 10, "pounds")

    def test_rejects_negative_amount(self):
        with self.assertRaises(RecordError):
            FeeItem("Visa", -1, "GBP")

    def test_published_record_needs_date(self):
        with self.assertRaises(RecordError):
            rec(verified_on="")

    def test_draft_needs_no_date(self):
        self.assertEqual(rec(status="draft", verified_on="").status, "draft")

    def test_freshness_window(self):
        r = rec(verified_on="2026-01-01")
        self.assertTrue(r.is_fresh(90, dt.date(2026, 2, 1)))
        self.assertFalse(r.is_fresh(90, dt.date(2026, 6, 1)))

    def test_stale_degrades_and_unpublishes(self):
        r = rec(verified_on="2026-01-01")
        self.assertEqual(r.effective_status(90, dt.date(2026, 6, 1)), "stale")
        self.assertFalse(r.publishable(90, dt.date(2026, 6, 1)))

    def test_draft_never_publishes(self):
        r = rec(status="draft")
        self.assertFalse(r.publishable(90, dt.date(2026, 1, 2)))

    def test_claim_patterns_must_be_valid_regex(self):
        with self.assertRaises(RecordError):
            rec(claim_patterns=["£135 (unclosed"])

    def test_claim_patterns_accepted_when_valid(self):
        self.assertEqual(len(rec(claim_patterns=[r"£135"]).claim_patterns), 1)

    def test_changed_source_forces_review_and_hides(self):
        r = rec(review_required=True)
        self.assertEqual(r.effective_status(90, dt.date(2026, 1, 2)), "review")
        self.assertFalse(r.publishable(90, dt.date(2026, 1, 2)))

    def test_official_host_detection(self):
        self.assertTrue(rec().is_official_source())
        self.assertFalse(rec(source_url="https://someblog.com/fees").is_official_source())

    def test_roundtrip_dict(self):
        r = rec()
        self.assertEqual(FeeRecord.from_dict(r.to_dict()).slug, r.slug)


if __name__ == "__main__":
    unittest.main()
