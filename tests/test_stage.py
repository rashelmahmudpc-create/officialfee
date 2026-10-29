import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stage


class TestStaging(unittest.TestCase):
    def test_skips_report_pages(self):
        recs, notes = stage.stage_rows(
            "https://www.canada.ca/en/immigration-refugees-citizenship/corporate/transparency/"
            "transition-binders/minister-2019/fees.html",
            [{"label": "Citizenship", "cells": ["$114,000,000"], "amounts": ["$114,000,000"]}],
            set(), None)
        self.assertEqual(recs, [])

    def test_skips_ambiguous_amounts(self):
        recs, notes = stage.stage_rows(
            "https://www.gov.uk/x-fees",
            [{"label": "Adult passport", "cells": ["$160", "$163.50"], "amounts": []}],
            set(), None)
        self.assertEqual(recs, [])
        self.assertTrue(any("ambiguous" in n for n in notes))

    def test_skips_implausible_totals(self):
        recs, _ = stage.stage_rows(
            "https://www.gov.uk/x-fees",
            [{"label": "Passport budget", "cells": ["$114,000,000"], "amounts": []}],
            set(), None)
        self.assertEqual(recs, [])

    def test_staged_record_is_always_a_draft(self):
        recs, _ = stage.stage_rows(
            "https://www.gov.uk/x-fees",
            [{"label": "Standard Visitor visa", "cells": ["£135"], "amounts": []}],
            set(), None)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].status, "draft")
        self.assertFalse(recs[0].publishable())
        self.assertEqual(recs[0].verified_on, "")

    def test_dollar_currency_is_host_specific(self):
        self.assertEqual(stage.currency_for("$", "https://www.uscis.gov/x"), "USD")
        self.assertEqual(stage.currency_for("$", "https://www.canada.ca/x"), "CAD")
        self.assertIsNone(stage.currency_for("$", "https://unknown-host.com/x"))

    def test_unknown_host_is_skipped(self):
        recs, notes = stage.stage_rows(
            "https://some-blog.com/visa-fees",
            [{"label": "Tourist visa", "cells": ["$50"], "amounts": []}],
            set(), None)
        self.assertEqual(recs, [])

    def test_dedupes_against_existing_amounts(self):
        recs, notes = stage.stage_rows(
            "https://www.gov.uk/x-fees",
            [{"label": "Standard Visitor visa", "cells": ["£135"], "amounts": []}],
            set(), None, known_amounts={"GB": {(135.0, "GBP")}})
        self.assertEqual(recs, [])


if __name__ == "__main__":
    unittest.main()
