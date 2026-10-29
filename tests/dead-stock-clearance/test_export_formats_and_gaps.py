"""Regression tests for the Oct 2026 real-export findings, on SYNTHETIC data only.

Covers: 2026 Shopify export headers, negative stock clamped and flagged, missing unit cost shown as
unknown (never 0), "too early to judge" with short history, and expected cash recovered using an
assumed sell-through per tactic (so a price-unchanged clearance collection no longer looks better
than a markdown).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_dead_stock import FX, NODE, args, dashboard_totals, ds  # noqa: E402

ORDERS_2026 = "Name,Created at,Canceled at,Financial Status,Lineitem quantity,Lineitem name,Lineitem SKU\n"
PRODUCTS_2026 = ("Title,URL handle,Vendor,Type,Tags,Status,SKU,Option1 name,Option1 value,Price,"
                 "Compare-at price,Cost per item,Inventory quantity\n")


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def path(self, name, text):
        p = os.path.join(self.tmp, name)
        write(p, text)
        return p


class TestShortHistoryAndFormats(Base):
    """41 days of history (Sep 18 - Oct 28). P-1 sold 2 units, 40 days ago, 100 in stock: by the cover
    rule that is "slow", but 41 days cannot prove it. Canceled order of 30 for P-1 yesterday is ignored."""

    def files(self, products_extra=""):
        o = self.path("o.csv", ORDERS_2026 +
                      "#1,2026-09-18 10:00:00 +0200,,paid,1,Pants,P-1\n"
                      "#2,2026-09-19 10:00:00 +0200,,paid,1,Pants,P-1\n"
                      "#3,2026-10-28 10:00:00 +0200,,paid,1,Fast,F-1\n"
                      "#4,2026-10-27 10:00:00 +0200,2026-10-27 11:00:00 +0200,voided,30,Pants,P-1\n")
        p = self.path("p.csv", PRODUCTS_2026 +
                      "Pants,pants,House,Bottoms,,Active,P-1,Size,M,300,,,100\n"
                      "Fast,fast,House,Tops,,Active,F-1,Size,M,200,,80,1\n"
                      "Socks,socks,House,Tops,,Active,N-1,Size,M,50,,20,-4\n" + products_extra)
        return o, p

    def test_too_early_to_judge_instead_of_slow(self):
        o, p = self.files()
        res = ds.run(["--orders", o, "--products", p, "--as-of", "2026-10-28"])
        it = {i["sku"]: i for i in res["items"]}
        self.assertEqual(res["history"]["days_of_history"], 41)
        self.assertEqual(it["P-1"]["category"], "too_early")
        self.assertIn("only 41 days of order history", it["P-1"]["reason"])
        self.assertEqual(it["P-1"]["units_sold_cover_window"], 0)    # canceled order of 30 not counted
        self.assertIsNone(it["P-1"]["recommended"])
        self.assertTrue(any("too early to judge" in n for n in res["data_notes"]))

    def test_min_evidence_days_setting(self):
        o, p = self.files()
        s = self.path("s.json", json.dumps({"min_evidence_days": 30}))
        res = ds.run(["--orders", o, "--products", p, "--setup", s, "--as-of", "2026-10-28"])
        it = {i["sku"]: i for i in res["items"]}
        self.assertEqual(it["P-1"]["category"], "slow")              # merchant accepts 30 days of evidence

    def test_negative_stock_clamped_and_flagged(self):
        o, p = self.files("Belt,belt,House,Tops,,Active,N-2,Size,M,50,,20,-1\n")
        res = ds.run(["--orders", o, "--products", p, "--as-of", "2026-10-28"])
        it = {i["sku"]: i for i in res["items"]}
        n = it["N-1"]
        self.assertEqual((n["category"], n["stock"], n["oversold_units"]), ("no_stock", 0, 4))
        self.assertIn("oversold", n["reason"])
        cat = res["summary"]["categories"]["no_stock"]
        self.assertEqual((cat["units"], cat["oversold_units"]), (0, 5))   # was -5 before the fix
        self.assertEqual([(x["sku"], x["units_owed"]) for x in res["summary"]["oversold"]], [("N-1", 4), ("N-2", 1)])
        self.assertTrue(any("negative stock" in x for x in res["data_notes"]))

    def test_missing_cost_is_unknown(self):
        o, p = self.files()
        s = self.path("s.json", json.dumps({"min_evidence_days": 30}))
        res = ds.run(["--orders", o, "--products", p, "--setup", s, "--as-of", "2026-10-28"])
        it = {i["sku"]: i for i in res["items"]}
        self.assertIsNone(it["P-1"]["cash_stuck"])                   # 100 units, no cost: unknown
        self.assertEqual(it["N-1"]["cash_stuck"], 0)                 # nothing on the shelf: a true 0
        sm = res["summary"]
        self.assertIsNone(sm["cash_stuck_slow"])                     # never "EGP 0 is stuck"
        self.assertEqual(sm["cash_stuck_total"], 80)                 # F-1 1 x 80: partial total
        self.assertEqual((sm["cash_stuck_items"]["all"], sm["cash_stuck_items"]["all_with_cost"]), (2, 1))
        self.assertTrue(any("1 of 2 items in stock" in n for n in res["data_notes"]))


class TestExpectedCash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = ds.run(args())
        cls.it = {i["sku"]: i for i in cls.res["items"]}

    def opt(self, sku, tactic):
        return next(o for o in self.it[sku]["options"] if o["tactic"] == tactic)

    def test_clearance_collection_no_longer_beats_markdown(self):
        md, cc = self.opt("S2", "markdown"), self.opt("S2", "clearance_collection")
        self.assertGreater(cc["cash_recovered"], md["cash_recovered"])        # 1990 vs 1750 if all sell
        self.assertEqual((md["assumed_sell_through_pct"], md["expected_cash_recovered"]), (60, 1050))  # 1750 x 60%
        self.assertEqual((cc["assumed_sell_through_pct"], cc["expected_cash_recovered"]), (25, 497.5))  # 1990 x 25%
        self.assertGreater(md["expected_cash_recovered"], cc["expected_cash_recovered"])
        self.assertEqual(md["expected_units_sold"], 6)
        self.assertEqual(md["expected_profit"], 570)                            # (175 - 80) x 6

    def test_plan_expected_totals(self):
        s = self.res["summary"]
        # 6300x40% + 1750x60% + 3840x60% + 570x60% + 1200x100% + 0 = 2520+1050+2304+342+1200
        self.assertEqual(s["plan_expected_cash_recovered"], 7416)
        # 3300x.4 + 950x.6 + 2040x.6 + 60x.6 - 2800x1 - 1200x.5 = 1320+570+1224+36-2800-600
        self.assertEqual(s["plan_expected_profit"], -250)
        self.assertEqual(s["plan_cash_recovered"], 13660)                       # ceiling unchanged
        self.assertTrue(any("Expected cash recovered assumes" in n for n in self.res["data_notes"]))

    def test_assumption_is_a_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "s.json")
            with open(os.path.join(FX, "setup.json"), encoding="utf-8") as fh:
                st = json.load(fh)
            st["assumed_sell_through_markdown_pct"] = "100%"
            write(sp, json.dumps(st))
            res = ds.run([a if a != os.path.join(FX, "setup.json") else sp for a in args()])
        md = next(o for o in {i["sku"]: i for i in res["items"]}["S2"]["options"] if o["tactic"] == "markdown")
        self.assertEqual(md["expected_cash_recovered"], md["cash_recovered"])

    @unittest.skipUnless(NODE, "node not installed")
    def test_dashboard_expected_matches_script_and_is_editable(self):
        got = dashboard_totals(self.res)
        self.assertAlmostEqual(got["exp"], self.res["summary"]["plan_expected_cash_recovered"], places=2)
        self.assertAlmostEqual(got["expProfit"], self.res["summary"]["plan_expected_profit"], places=2)
        got = dashboard_totals(self.res, {"st_markdown": 100, "st_bundle": 100, "st_gift": 100,
                                          "st_clearance_collection": 100, "st_liquidate": 100})
        self.assertAlmostEqual(got["exp"], self.res["summary"]["plan_cash_recovered"], places=2)

    @unittest.skipUnless(NODE, "node not installed")
    def test_dashboard_unknown_cash_not_zero(self):
        plan = json.loads(json.dumps(self.res))
        plan["summary"]["cash_stuck_dead"] = plan["summary"]["cash_stuck_slow"] = None
        plan["summary"]["cash_stuck_items"].update(slow_with_cost=0, dead_with_cost=0)
        got = dashboard_totals(plan)
        self.assertIn("unknown until you add unit costs", got["head"])
        self.assertNotIn("EGP 0", got["head"])


if __name__ == "__main__":
    unittest.main()
