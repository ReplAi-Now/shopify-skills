"""Tests for skills/operations/demand-planner. Expected numbers were worked out by hand (see comments).

Run: python3 -m unittest discover -s tests/demand-planner
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "demand-planner", "scripts")
FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)
import demand_plan as dp  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


CAL = os.path.join(SCRIPTS, "..", "assets", "seasonal-calendar.json")


def base_args(*extra):
    return ["--orders", os.path.join(FX, "orders.csv"),
            "--inventory", os.path.join(FX, "inventory.csv"),
            "--products", os.path.join(FX, "products.csv"),
            "--suppliers", os.path.join(FX, "suppliers.csv"),
            "--stock-history", os.path.join(FX, "stock_history.csv"),
            "--setup", os.path.join(FX, "setup.json")] + list(extra)


def by_sku(res):
    return {i["sku"]: i for i in res["items"]}


class TestHelpers(unittest.TestCase):
    def test_z_scores(self):
        self.assertEqual(round(dp.z_for(90), 4), 1.2816)
        self.assertEqual(round(dp.z_for(95), 4), 1.6449)
        self.assertEqual(round(dp.z_for(99), 4), 2.3263)

    def test_round_order(self):
        self.assertEqual(dp.round_order(6.8, 10, 6), 12)   # 7 -> MOQ 10 -> 2 cases of 6
        self.assertEqual(dp.round_order(0, 10, 6), 0)
        self.assertEqual(dp.round_order(2.4, 0, 1), 3)
        self.assertEqual(dp.round_order(13, 0, 12), 24)

    def test_weighted_demand(self):
        # ages 3,2,1,0 with half life 1: weights .125,.25,.5,1 (sum 1.875)
        d, s = dp.weighted_demand([(3, 2), (2, 4), (1, 2), (0, 4)], 1)
        self.assertAlmostEqual(d, 6.25 / 1.875, places=9)          # 3.3333
        self.assertAlmostEqual(s, (1.666666667 / 1.875) ** 0.5, places=6)  # 0.9428

    def test_seasonal_uplift_from_last_year(self):
        cal = json.loads(read(CAL))
        totals = {}
        day = dt.date(2025, 10, 24)
        while day <= dt.date(2025, 12, 1):
            totals[day] = 2 if day < dt.date(2025, 11, 21) else 5   # baseline 2/day, window 5/day
            day += dt.timedelta(days=1)
        evs, needs = dp.compute_events(totals, dt.date(2025, 10, 1), dt.date(2026, 11, 10), 30, cal, [], 28, "auto")
        self.assertEqual(needs, [])
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["event"], "white_friday")
        self.assertAlmostEqual(evs[0]["factor"], 2.5, places=9)    # (55/11) / (56/28)
        # d=2, LT 10 + R 4 = 14 days from Nov 16; overlap with Nov 20-30 = 10 days
        d_eff, extra = dp.horizon_demand(2.0, 10, 4, dt.date(2026, 11, 15), evs)
        self.assertAlmostEqual(extra, 15.0, places=9)              # (2.5 - 1) * 10
        self.assertAlmostEqual(d_eff, 2 * 29 / 14.0, places=9)     # 4.142857

    def test_seasonal_uplift_needs_history(self):
        cal = json.loads(read(CAL))
        evs, needs = dp.compute_events({}, dt.date(2026, 1, 1), dt.date(2026, 11, 10), 30, cal, [], 28, "auto")
        self.assertEqual(evs, [])
        self.assertEqual([n["event"] for n in needs], ["white_friday"])

    def test_calendar_covers_2024_2028(self):
        cal = json.loads(read(CAL))
        for y in range(2024, 2029):
            names = {e["event"] for e in cal["events"] if e["year"] == y}
            self.assertEqual(names, {"ramadan", "eid_al_fitr", "eid_al_adha", "white_friday"})


class TestPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = dp.run(base_args())
        cls.items = by_sku(cls.res)

    def test_basics(self):
        self.assertEqual(self.res["as_of"], "2026-10-28")
        self.assertEqual(self.res["settings"]["z"], 1.6449)
        self.assertTrue(self.res["stockout_aware"])
        self.assertEqual(self.res["seasonality"]["events"], [])
        self.assertEqual(self.res["unmatched_order_skus"], [])

    def test_sku_a_recency_weighted_moq_case(self):
        a = self.items["SKU-A"]
        # d = 6.25/1.875; var = 1.6667/1.875; SS = 1.64485*sqrt(5*0.8889) = 3.4677
        self.assertEqual(a["daily_demand"], 3.333)
        self.assertEqual(a["daily_demand_sd"], 0.943)
        self.assertEqual(a["safety_stock"], 3.47)
        self.assertEqual(a["reorder_point"], 20.13)      # 16.6667 + 3.4677
        self.assertEqual(a["order_up_to"], 26.8)         # + 3.3333 * 2
        self.assertEqual(a["position"], 20)              # 15 + 5 available over two locations
        self.assertEqual(a["urgency"], "order_now")
        self.assertEqual(a["order_qty"], 12)             # 6.80 -> 7 -> MOQ 10 -> 2 cases of 6
        self.assertEqual(a["cash_needed"], 600)
        self.assertEqual(a["capital_tied"], 1100)        # on hand 22 * 50
        self.assertEqual(a["stockout_date"], "2026-11-03")  # 20 / 3.3333 = 6 days
        self.assertFalse(a["at_risk"])

    def test_sku_b_vendor_lead_time_variability(self):
        b = self.items["SKU-B"]
        # d = 1, sd = 0, LT 10 sd 2 from vendor row: SS = 1.64485 * sqrt(1 * 4) = 3.2897
        self.assertEqual(b["daily_demand"], 1.0)
        self.assertEqual(b["lead_time_days"], 10)
        self.assertEqual(b["safety_stock"], 3.29)
        self.assertEqual(b["reorder_point"], 13.29)
        self.assertEqual(b["order_up_to"], 15.29)
        self.assertEqual(b["urgency"], "later")
        self.assertEqual(b["reorder_date"], "2026-11-13")   # (30 - 13.29) / 1 = 16.7 days
        self.assertEqual(b["order_qty"], 2)                 # S - ROP = d * R
        self.assertEqual(b["stockout_date"], "2026-11-27")

    def test_sku_c_stockout_days_excluded(self):
        c = self.items["SKU-C"]
        self.assertEqual(c["stockout_days_excluded"], 2)    # Oct 27 and 28: stock 0, no sales
        self.assertEqual(c["days_used"], 2)
        self.assertEqual(c["daily_demand"], 3.0)            # not 1.33 as plain zeros would give
        self.assertEqual(c["safety_stock"], 0)
        self.assertEqual(c["reorder_point"], 15)
        self.assertEqual(c["order_qty"], 11)                # S 21 - position (0 + 10 incoming)
        self.assertEqual(c["cash_needed"], 330)
        self.assertTrue(c["at_risk"])
        self.assertEqual(c["risk_reason"], "out of stock now")
        self.assertEqual(c["lost_sales_estimate"], 1200)    # 5 days * 3/day * 80

    def test_sku_d_new_product_own_sales(self):
        # First sale Oct 27 (2 days ago) and the export starts Sep 30, so it is provably new.
        # Own rate 2 units / 2 days = 1.0/day, below the Shirts average 2.1667 (the cap, not a floor).
        d = self.items["SKU-D"]
        self.assertEqual(d["status"], "new")
        self.assertEqual(d["demand_source"], "new_own_sales")
        self.assertEqual(d["daily_demand"], 1.0)
        self.assertTrue(d["flags"][0].startswith("new product, estimate"))
        self.assertEqual(d["safety_stock"], 3.68)           # 1.64485 * sqrt(5 * 1^2)
        self.assertEqual(d["reorder_point"], 8.68)          # 5 + 3.678
        self.assertEqual(d["order_qty"], 6)                 # 10.68 - 5 = 5.68 -> 6
        self.assertEqual(d["cash_needed"], 150)
        self.assertEqual(d["stockout_date"], "2026-11-02")  # 5 / 1 = 5 days
        self.assertFalse(d["at_risk"])                      # 5 days of stock, lead time 5
        self.assertEqual(self.res["new_products"], ["SKU-D"])

    def test_sku_e_no_sales_needs_estimate(self):
        e = self.items["SKU-E"]
        self.assertEqual(e["urgency"], "needs_estimate")
        self.assertEqual(self.res["needs_estimate"], ["SKU-E"])

    def test_sort_and_lists(self):
        self.assertEqual([i["sku"] for i in self.res["items"]], ["SKU-A", "SKU-C", "SKU-D", "SKU-B", "SKU-E"])
        self.assertEqual([r["sku"] for r in self.res["reorder_list"]], ["SKU-A", "SKU-C", "SKU-D"])
        self.assertEqual(sorted(r["sku"] for r in self.res["at_risk"]), ["SKU-C"])

    def test_cash_summary(self):
        cash = self.res["cash"]
        self.assertEqual(cash["order_now"], 1080)          # 600 + 330 + 150
        self.assertEqual(cash["this_week"], 0)
        self.assertEqual(cash["later"], 80)
        self.assertEqual(cash["capital_tied_now"], 2585)   # 1100 + 1200 + 0 + 125 + 160
        trade = {t["service_level_pct"]: t for t in self.res["service_level_tradeoff"]}
        self.assertEqual(trade[95]["safety_stock_value"], 396.92)  # 173.38 + 131.59 + 0 + 91.95
        self.assertLess(trade[90]["safety_stock_value"], trade[99]["safety_stock_value"])


class TestOverrides(unittest.TestCase):
    def test_merchant_event_uplift(self):
        res = dp.run(base_args("--event", "Sale,2026-10-30,2026-10-31,50"))
        it = by_sku(res)
        # B: 12 day horizon Oct 29 - Nov 9 overlaps 2 event days: d_eff = (12 + 0.5*2)/12 = 1.0833
        self.assertEqual(it["SKU-B"]["horizon_daily_demand"], 1.083)
        self.assertEqual(it["SKU-B"]["safety_stock"], 3.56)   # 1.64485 * 2 * 1.0833
        self.assertEqual(it["SKU-B"]["reorder_point"], 14.4)  # 10.833 + 3.564
        # A: 7 day horizon, 2 event days: 3.3333 * 8/7
        self.assertEqual(it["SKU-A"]["horizon_daily_demand"], 3.81)
        self.assertEqual(res["seasonality"]["events"][0]["source"], "merchant")

    def test_merchant_estimate(self):
        it = by_sku(dp.run(base_args("--estimate", "SKU-E=0.5")))["SKU-E"]
        self.assertEqual(it["demand_source"], "merchant_estimate")
        self.assertEqual(it["safety_stock"], 1.84)     # 1.64485 * sqrt(5 * 0.25)
        self.assertEqual(it["reorder_point"], 4.34)
        self.assertEqual(it["urgency"], "later")       # (8 - 4.34)/0.5 = 7.3 days

    def test_cli_json_and_csv_and_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "plan.csv")
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "demand_plan.py")] +
                                 base_args("--csv-out", csv_path), capture_output=True, text=True, check=True)
            res = json.loads(out.stdout)
            self.assertEqual(res["cash"]["order_now"], 1080)
            self.assertTrue(read(csv_path).startswith("sku,title"))
            plan = os.path.join(tmp, "plan.json")
            write(plan, out.stdout)
            html = os.path.join(tmp, "dash.html")
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "build_dashboard.py"), "--plan", plan,
                            "--out", html], check=True, capture_output=True)
            text = read(html)
            self.assertIn('id="sl"', text)
            self.assertIn('id="lt"', text)
            self.assertIn("Made with the free ReplAi skills pack", text)
            self.assertNotRegex(text, "[\u2013\u2014]")

    def test_missing_column_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "orders.csv")
            write(bad, "Name,Lineitem sku\n#1,X\n")
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "demand_plan.py"), "--orders", bad,
                                  "--products", os.path.join(FX, "products.csv")], capture_output=True, text=True)
            self.assertEqual(out.returncode, 2)
            self.assertIn("Created at", json.loads(out.stdout)["error"])


class TestQaRegressions(unittest.TestCase):
    """Bugs found in adversarial QA (Oct 29 2026)."""

    def test_service_level_99_9_accepted(self):
        # 99.9 / 100 is 0.9990000000000001 in floating point; it used to be rejected.
        self.assertEqual(round(dp.z_for(99.9), 4), 3.0902)
        self.assertEqual(dp.z_for(50), 0.0)
        with self.assertRaises(dp.DataError):
            dp.z_for(99.95)

    def test_setup_values_typed_as_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "s.json")
            write(sp, json.dumps({"service_level_pct": "95%", "default_lead_time_days": "10 days"}))
            st = dp.load_setup(sp)
            self.assertEqual((st["service_level_pct"], st["default_lead_time_days"]), (95, 10))

    def test_us_dates_from_excel_do_not_crash(self):
        # Excel on a US locale rewrites Created at as MM/DD/YYYY; 10/28/2026 used to raise ValueError.
        with tempfile.TemporaryDirectory() as tmp:
            o = os.path.join(tmp, "o.csv")
            write(o, "Name,Created at,Lineitem quantity,Lineitem sku\n#1,10/28/2026 14:05,1,A\n"
                     "#2,10/03/2026 09:00,1,A\n")
            got = [x["date"] for x in dp.load_orders(o)]
            self.assertEqual(got, [dt.date(2026, 10, 28), dt.date(2026, 10, 3)])   # 10/03 is Oct 3, not Mar 10
            write(o, "Name,Created at,Lineitem quantity,Lineitem sku\n#1,28/10/2026,1,A\n#2,03/10/2026,1,A\n")
            self.assertEqual([x["date"] for x in dp.load_orders(o)], [dt.date(2026, 10, 28), dt.date(2026, 10, 3)])

    def test_estimate_for_variant_without_sku(self):
        # needs_estimate lists "NAME:<name>" keys; feeding one back used to be ignored (upper-cased).
        with tempfile.TemporaryDirectory() as tmp:
            o, p = os.path.join(tmp, "o.csv"), os.path.join(tmp, "p.csv")
            write(o, "Name,Created at,Lineitem quantity,Lineitem name,Lineitem sku\n#1,2026-10-28,1,Mug,M1\n")
            write(p, "Handle,Title,Option1 Value,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\n"
                     "tee,Basic Tee,Black,,100,40,0\nmug,Mug,Default Title,M1,50,20,5\n")
            res = dp.run(["--orders", o, "--products", p, "--estimate", "NAME:Basic Tee - Black=2"])
            self.assertNotIn("NAME:basic tee - black", res["needs_estimate"])
            it = {i["key"]: i for i in res["items"]}["NAME:basic tee - black"]
            self.assertEqual((it["daily_demand"], it["demand_source"]), (2, "merchant_estimate"))

    def test_duplicate_sku_across_products_is_flagged_not_mixed(self):
        # Two products share SKU P1. The first product's cost is kept (not silently replaced by the
        # second's), stock is added up (4 + 6), and the plan says so.
        with tempfile.TemporaryDirectory() as tmp:
            o, p = os.path.join(tmp, "o.csv"), os.path.join(tmp, "p.csv")
            write(o, "Name,Created at,Lineitem quantity,Lineitem sku\n#1,2026-10-28,1,P1\n")
            write(p, "Handle,Title,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\n"
                     "linen,Linen Pants,P1,600,250,4\ncargo,Cargo Pants,P1,700,300,6\n")
            res = dp.run(["--orders", o, "--products", p])
            it = res["items"][0]
            self.assertEqual((it["title"], it["unit_cost"], it["available"]), ("Linen Pants", 250, 10))
            self.assertTrue(any("cargo" in f for f in it["flags"]))
            self.assertTrue(any("P1" in n for n in res["data_notes"]))


def orders_csv(lines, header="Name,Created at,Lineitem quantity,Lineitem sku"):
    return header + "\n" + "\n".join(lines) + "\n"


class TestFixPassOct29(unittest.TestCase):
    """Fix pass decided by the lead (Oct 29 2026). Expected numbers worked out by hand."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name, text):
        p = os.path.join(self.tmp.name, name)
        write(p, text)
        return p

    def long_history(self, extra_lines):
        # OLD (Tees) sells 1 unit a day for 400 days up to 2026-10-28: established, d = 1.0.
        end = dt.date(2026, 10, 28)
        lines = ["#O%d,%s,1,OLD" % (i, (end - dt.timedelta(days=i)).isoformat()) for i in range(400)]
        return self.path("o.csv", orders_csv(lines + extra_lines))

    def products(self, rows):
        return self.path("p.csv", "Handle,Title,Type,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\n"
                         + "\n".join(rows) + "\n")

    def test_new_product_uses_own_rate_not_category_average(self):
        # Repro: sold once 10 days ago, 0 stock. Used to get the category average and order 39 units.
        o = self.long_history(["#N1,2026-10-19,1,NEW"])
        p = self.products(["old,Old Tee,Tees,OLD,100,40,500", "new,New Tee,Tees,NEW,100,40,0"])
        it = by_sku(dp.run(["--orders", o, "--products", p]))["NEW"]
        self.assertEqual(it["status"], "new")
        self.assertEqual(it["daily_demand"], 0.1)               # 1 unit / 10 days
        self.assertEqual(it["demand_source"], "new_own_sales")
        # LT 14, R 7, z 1.64485: SS = 1.64485*sqrt(14*0.01) = 0.6155; S = 1.4 + 0.6155 + 0.7 = 2.72 -> 3
        self.assertEqual(it["order_qty"], 3)
        self.assertIn("new product, estimate", it["flags"][0])

    def test_category_average_is_a_cap_not_a_floor(self):
        # 30 units in the 5 days since launch = 6/day, capped at the Tees average 1.0/day.
        o = self.long_history(["#N1,2026-10-24,30,HOT"])
        p = self.products(["old,Old Tee,Tees,OLD,100,40,500", "hot,Hot Tee,Tees,HOT,100,40,0"])
        it = by_sku(dp.run(["--orders", o, "--products", p]))["HOT"]
        self.assertEqual((it["daily_demand"], it["demand_source"]), (1.0, "new_own_sales_capped"))
        self.assertIn("capped", it["flags"][0])

    def test_short_export_does_not_make_old_sellers_new_and_is_low_confidence(self):
        # 20 days of export, history shorter than min_history_days (28). SLOW sold on the first and the
        # 15th day: it may be a year old, so it is planned from the 20 days, not marked new or needs estimate.
        o = self.path("o.csv", orders_csv(["#1,2026-10-09,1,SLOW", "#2,2026-10-23,1,SLOW", "#3,2026-10-28,2,FAST"]))
        p = self.products(["slow,Slow Bag,Bags,SLOW,100,40,10", "fast,Fast Bag,Bags,FAST,100,40,10"])
        res = dp.run(["--orders", o, "--products", p])
        it = by_sku(res)
        self.assertTrue(res["low_confidence"])
        self.assertTrue(any(n.startswith("LOW CONFIDENCE") for n in res["data_notes"]))
        self.assertEqual(res["needs_estimate"], [])
        self.assertEqual(it["SLOW"]["status"], "ok")
        self.assertEqual(it["SLOW"]["days_used"], 20)
        self.assertTrue(any("low confidence" in f for f in it["SLOW"]["flags"]))
        self.assertEqual(it["FAST"]["status"], "ok")             # first sale today, but nothing proves it is new

    def test_event_in_progress_is_not_applied_twice(self):
        cal = json.loads(read(CAL))
        # Today Nov 22 2026 is inside White Friday (Nov 20-30): the calendar event is in progress.
        evs, needs = dp.compute_events({}, dt.date(2026, 1, 1), dt.date(2026, 11, 22), 14, cal, [], 28, "auto")
        self.assertEqual(needs, [])                               # no uplift asked for an event already running
        self.assertTrue(evs[0]["in_progress"])
        d_eff, extra = dp.horizon_demand(3.0, 7, 7, dt.date(2026, 11, 22), evs)
        self.assertEqual((d_eff, extra), (3.0, 0))
        # A merchant event that started yesterday is not applied either.
        res = dp.run(base_args("--event", "Flash sale,2026-10-27,2026-11-05,80"))
        b = by_sku(res)["SKU-B"]
        self.assertEqual(b["horizon_daily_demand"], b["daily_demand"])
        self.assertTrue(res["seasonality"]["events"][0]["in_progress"])

    def test_eid_factor_uses_non_event_baseline(self):
        cal = json.loads(read(CAL))
        totals, day = {}, dt.date(2025, 1, 1)
        while day <= dt.date(2025, 4, 30):
            ramadan = dt.date(2025, 3, 1) <= day <= dt.date(2025, 3, 19)
            eid = dt.date(2025, 3, 20) <= day <= dt.date(2025, 4, 1)
            totals[day] = 5 if ramadan else (4 if eid else 2)
            day += dt.timedelta(days=1)
        # Today Mar 1 2026 is inside Ramadan 2026; Eid al Fitr 2026 (Mar 10-22) is in the 30 day horizon.
        evs, needs = dp.compute_events(totals, dt.date(2025, 1, 1), dt.date(2026, 3, 1), 30, cal, [], 28, "auto")
        by = {e["event"]: e for e in evs}
        self.assertTrue(by["ramadan"]["in_progress"])
        # Baseline = Feb 1-28 2025 (Ramadan days skipped): 4/day vs 2/day = 2.0 (it was 0.99 against Ramadan weeks)
        self.assertAlmostEqual(by["eid_al_fitr"]["factor"], 2.0, places=9)
        self.assertEqual(by["eid_al_fitr"]["detail"]["baseline_start"], "2025-02-01")
        # d 2, LT 23 + R 7: Ramadan days Mar 2-9 not uplifted again, Eid 13 days at x2: 2 * (30 + 13) / 30
        d_eff, _ = dp.horizon_demand(2.0, 23, 7, dt.date(2026, 3, 1), evs)
        self.assertAlmostEqual(d_eff, 2 * 43 / 30.0, places=9)

    def test_refunded_orders_excluded_and_partial_refunds_netted(self):
        hdr = "Name,Created at,Financial Status,Lineitem quantity,Lineitem sku,Lineitem refunded quantity"
        o = self.path("o.csv", orders_csv(["#1,2026-10-27,paid,2,A,0", "#2,2026-10-28,refunded,5,A,5",
                                           "#3,2026-10-28,partially_refunded,3,A,1",
                                           "#4,2026-10-28,partially refunded,1,A,1"], hdr))
        orders = dp.load_orders(o)
        live = [x for x in orders if dp.counts_as_sale(x)]
        self.assertEqual([x["name"] for x in live], ["#1", "#3", "#4"])
        self.assertEqual([sum(ln["qty"] for ln in x["lines"]) for x in live], [2, 2, 0])  # 3-1, 1-1 dropped
        # Without a refunded quantity column, partially refunded lines are kept whole and noted.
        o2 = self.path("o2.csv", orders_csv(["#1,2026-10-27,paid,2,A", "#2,2026-10-28,refunded,5,A",
                                             "#3,2026-10-28,partially_refunded,3,A"],
                                            "Name,Created at,Financial Status,Lineitem quantity,Lineitem sku"))
        p = self.products(["a,Bag,Bags,A,100,40,10"])
        res = dp.run(["--orders", o2, "--products", p, "--setup", os.path.join(FX, "setup.json")])
        self.assertTrue(any("1 fully refunded" in n for n in res["data_notes"]))
        self.assertTrue(any("1 partially refunded" in n for n in res["data_notes"]))

    def test_moq_covering_more_than_180_days_is_flagged(self):
        o = self.long_history([])
        p = self.products(["old,Old Tee,Tees,OLD,100,40,0"])
        sup = self.path("s.csv", "sku,lead_time_days,moq\nOLD,14,500\n")
        res = dp.run(["--orders", o, "--products", p, "--suppliers", sup])
        it = by_sku(res)["OLD"]
        self.assertEqual(it["order_qty"], 500)                   # need ~21, MOQ forces 500 = 500 days
        self.assertEqual(res["moq_warnings"], [{"sku": "OLD", "order_qty": 500, "days_of_demand": 500}])
        self.assertTrue(any("MOQ or case pack" in f for f in it["flags"]))
        sup2 = self.path("s2.csv", "sku,lead_time_days,moq\nOLD,14,100\n")
        self.assertEqual(dp.run(["--orders", o, "--products", p, "--suppliers", sup2])["moq_warnings"], [])

    def test_stock_history_month_first_dates(self):
        h = self.path("h.csv", "date,sku,stock\n10/03/2026,SKU-C,5\n10/27/2026,SKU-C,0\n")
        self.assertEqual(sorted(dp.load_stock_history(h)["SKU-C"]), [dt.date(2026, 10, 3), dt.date(2026, 10, 27)])
        h = self.path("h2.csv", "date,sku,stock\n03/10/2026,SKU-C,5\n27/10/2026,SKU-C,0\n")
        self.assertEqual(sorted(dp.load_stock_history(h)["SKU-C"]), [dt.date(2026, 10, 3), dt.date(2026, 10, 27)])


if __name__ == "__main__":
    unittest.main()
