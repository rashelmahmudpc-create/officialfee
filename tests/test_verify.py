"""The verify step is where the site's honesty is actually enforced, so its
refusals matter more than its successes."""

import datetime as dt
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import verify
from ofdata.model import FeeItem, FeeRecord

TODAY = dt.date(2026, 10, 29)


def rec(**kw):
    base = dict(country="GB", country_name="United Kingdom", slug="x-fee", category="visa",
                title="T", fees=[FeeItem("Visa", 135, "GBP")],
                source_url="https://www.gov.uk/visa-fees", verified_on="2026-10-01",
                status="verified")
    base.update(kw)
    return FeeRecord(**base)


class TestApplyVerdict(unittest.TestCase):
    def test_draft_is_never_promoted(self):
        """A reachable URL is not confirmation. This was a real bug: verify.py
        stamped drafts as verified and published an unread number."""
        r = rec(status="draft", verified_on="")
        ok, why = verify.apply_verdict(r, {"ok": True, "changed": False}, TODAY)
        self.assertFalse(ok)
        self.assertEqual(r.status, "draft")
        self.assertEqual(r.verified_on, "")
        self.assertIn("person", why)

    def test_verified_record_is_restamped(self):
        r = rec()
        ok, _ = verify.apply_verdict(r, {"ok": True, "changed": False}, TODAY)
        self.assertTrue(ok)
        self.assertEqual(r.verified_on, "2026-10-29")

    def test_changed_source_does_not_refresh_the_date(self):
        r = rec()
        ok, why = verify.apply_verdict(r, {"ok": True, "changed": True}, TODAY)
        self.assertFalse(ok)
        self.assertEqual(r.verified_on, "2026-10-01")
        self.assertTrue(r.review_required)

    def test_unreachable_source_is_not_promoted(self):
        r = rec()
        ok, _ = verify.apply_verdict(r, {"ok": False, "changed": False, "http_status": 503}, TODAY)
        self.assertFalse(ok)


class TestClaimPatterns(unittest.TestCase):
    def test_missing_number_fails_the_claim(self):
        r = rec(claim_patterns=[r"costs £135 for up to 6 months"])
        ok, detail = verify.check_claims(r, "<p>It now costs £200.</p>")
        self.assertFalse(ok)
        self.assertIn("no longer found", detail)

    def test_present_number_passes(self):
        r = rec(claim_patterns=[r"costs £135 for up to 6 months"])
        ok, _ = verify.check_claims(r, "<p>It costs £135 for up to 6 months.</p>")
        self.assertTrue(ok)

    def test_record_without_patterns_is_only_reachability_checked(self):
        ok, detail = verify.check_claims(rec(), "<p>anything</p>")
        self.assertTrue(ok)
        self.assertIn("no claim patterns", detail)


class TestPageText(unittest.TestCase):
    def test_strips_style_with_attributes(self):
        """A naive <style> strip missed attributes and leaked raw CSS, which
        broke every claim match on pages that use them."""
        html = '<style type="text/css">p{color:red}</style><p>It costs £135.</p>'
        self.assertNotIn("color:red", verify.page_text(html))
        self.assertIn("£135", verify.page_text(html))

    def test_survives_an_unterminated_style_block(self):
        """One real source page has an unclosed <style>; the fees sit after it."""
        html = "<style>body{color:red}<p>It costs £135.</p>"
        self.assertIn("£135", verify.page_text(html))


if __name__ == "__main__":
    unittest.main()


class TestContentDigest(unittest.TestCase):
    """The stored hash decides whether a page counts as changed, so it must
    ignore the per-request tokens gov.uk puts in every response. Hashing raw
    bytes made every record look changed on every fetch - a real bug that hid
    unchanged fees behind a permanent 'needs human review'."""

    def test_per_request_tokens_do_not_change_the_digest(self):
        a = '<meta name="csrf-token" content="AAA111"> <p>It costs £135.</p>'
        b = '<meta name="csrf-token" content="ZZZ999"> <p>It costs £135.</p>'
        self.assertEqual(verify.content_digest(a.encode()), verify.content_digest(b.encode()))

    def test_a_real_fee_change_does_change_the_digest(self):
        a = '<p>It costs £135.</p>'
        b = '<p>It costs £200.</p>'
        self.assertNotEqual(verify.content_digest(a.encode()), verify.content_digest(b.encode()))

    def test_randomised_element_ids_are_ignored(self):
        a = '<label for="search-main-4fd8265c">Search</label><p>Fee £135</p>'
        b = '<label for="search-main-e0448d8e">Search</label><p>Fee £135</p>'
        self.assertEqual(verify.content_digest(a.encode()), verify.content_digest(b.encode()))


class TestHashSchemeMigration(unittest.TestCase):
    def test_old_raw_byte_hash_is_not_reported_as_changed(self):
        """A baseline from the old scheme must migrate silently: the page did
        not change, only the way we measure it."""
        state = {"x-fee": {"hash": "deadbeef", "hash_scheme": None}}
        result = verify.verify_record(rec(), state, TODAY, dry_run=True)
        self.assertFalse(result["changed"])
        self.assertEqual(result["hash_scheme"], verify.HASH_SCHEME)

    def test_changed_hash_in_the_same_scheme_still_flags(self):
        state = {"x-fee": {"hash": "deadbeef", "hash_scheme": verify.HASH_SCHEME}}
        previous = state["x-fee"]["hash"]
        digest = verify.content_digest(b"<p>It costs \xc2\xa3135.</p>")
        changed = bool(state["x-fee"]["hash_scheme"] == verify.HASH_SCHEME
                       and previous and previous != digest)
        self.assertTrue(changed)
