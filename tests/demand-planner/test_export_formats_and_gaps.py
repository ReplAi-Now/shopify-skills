"""Regression tests for the Oct 2026 real-export findings, on SYNTHETIC data only.

Covers: 2026 Shopify export headers (URL handle, SKU, Price, Inventory quantity, Option1 value,
Option 1 Value, Canceled at), missing unit cost shown as unknown (never 0), draft/archived products
left out by default, estimates asked once per group, negative stock (oversold), and a light dashboard.

Scenario (as of 2026-10-28, lead time 5, review 2, flat sales so the numbers are exact):
  T-S  Tee S, active, sells 1/day Oct 19-28, stock 10, no cost. A canceled order of 50 is ignored.
  T-M  Tee M, active, sells 1/day Oct 19-28, stock -3 (oversold 3), no cost.
  Z-1  Belt, active, one sale on Oct 13 (before the 10 day window), stock -2.
  D-1  Dress, DRAFT, sells, stock 5.
  C-1, C-2  Cap (type Hats), active, never sold. M-1 Mug (no type), active, never sold.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "demand-planner", "scripts")
sys.path.insert(0, SCRIPTS)
import demand_plan as dp  # noqa: E402
import store_data  # noqa: E402

NODE = shutil.which("node")

ORDERS_2026 = "Name,Created at,Canceled at,Financial Status,Lineitem quantity,Lineitem name,Lineitem SKU\n"
PRODUCTS_2026 = ("Title,URL handle,Vendor,Type,Tags,Status,SKU,Option1 name,Option1 value,Price,"
                 "Compare-at price,Cost per item,Inventory quantity\n"
                 "Tee,tee,House,Tees,,Active,T-S,Size,S,200,,,10\n"
                 ",tee,,,,,T-M,,M,200,,,-3\n"
                 "Belt,belt,House,Belts,,Active,Z-1,Title,Default Title,150,,,-2\n"
                 "Dress,dress,House,Dresses,,Draft,D-1,Title,Default Title,500,,,5\n"
                 "Cap,cap,House,Hats,,Active,C-1,Color,Red,90,,,4\n"
                 ",cap,,,,,C-2,,Blue,90,,,4\n"
                 "Mug,mug,House,,,Active,M-1,Title,Default Title,60,,,7\n")


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

    def files(self):
        lines = []
        n = 0
        for day in range(19, 29):
            for sku in ("T-S", "T-M", "D-1"):
                n += 1
                lines.append(f"#{n},2026-10-{day} 10:00:00 +0200,,paid,1,{sku},{sku}")
        lines.append("#900,2026-10-13 10:00:00 +0200,,paid,1,Belt,Z-1")
        lines.append("#901,2026-10-28 11:00:00 +0200,2026-10-28 12:00:00 +0200,voided,50,Tee - S,T-S")
        o = self.path("orders.csv", ORDERS_2026 + "\n".join(lines) + "\n")
        p = self.path("products.csv", PRODUCTS_2026)
        s = self.path("setup.json", json.dumps({"default_lead_time_days": 5, "review_period_days": 2,
                                                "history_days": 10, "min_history_days": 3}))
        return o, p, s

    def run_plan(self, *extra, setup=None):
        o, p, s = self.files()
        return dp.run(["--orders", o, "--products", p, "--setup", setup or s, "--as-of", "2026-10-28"] + list(extra))


class TestExportFormats(Base):
    def test_2026_products_export_and_canceled_at(self):
        res = self.run_plan()
        it = {i["sku"]: i for i in res["items"]}
        self.assertEqual(set(it), {"T-S", "T-M", "Z-1", "C-1", "C-2", "M-1"})
        # The canceled order of 50 (spelled "Canceled at") must not count: demand stays exactly 1/day.
        self.assertEqual(it["T-S"]["daily_demand"], 1.0)
        self.assertEqual(it["T-S"]["price"], 200)
        self.assertEqual(it["T-M"]["variant_title"], "M")
        self.assertEqual(it["T-S"]["available"], 10)
        self.assertEqual(it["C-2"]["type"], "Hats")              # carried forward from the first row

    def test_legacy_cancelled_spelling_still_read(self):
        o = self.path("o.csv", "Name,Created at,Cancelled at,Lineitem quantity,Lineitem sku\n"
                               "#1,2026-10-27,,1,A\n#2,2026-10-28,2026-10-28,9,A\n")
        orders = store_data.load_orders(o)
        self.assertEqual([x["cancelled"] for x in orders], [False, True])

    def test_inventory_export_option_with_space(self):
        inv = self.path("inv.csv", "Handle,Title,Option 1 Name,Option 1 Value,Option 2 Name,Option 2 Value,SKU,"
                                   "Location,Available (not editable),On hand (current)\n"
                                   "scarf,Scarf,Color,Red,Size,L,,Cairo,3,3\n")
        recs = store_data.load_variants(None, inv)
        self.assertIn("NAME:scarf - red / l", recs)
        self.assertEqual(recs["NAME:scarf - red / l"]["available"], 3)

    def test_missing_handle_message_names_both_spellings(self):
        p = self.path("p.csv", "Title,SKU,Price\nTee,A,10\n")
        with self.assertRaises(store_data.DataError) as cm:
            store_data.load_variants(p)
        self.assertIn("URL handle", str(cm.exception))


class TestDraftsAndEstimates(Base):
    def test_drafts_left_out_by_default(self):
        res = self.run_plan()
        self.assertNotIn("D-1", [i["sku"] for i in res["items"]])
        self.assertEqual(res["excluded_inactive_variants"], 1)
        self.assertEqual(res["unmatched_order_skus"], [])         # draft sales are not "unmatched"
        self.assertTrue(any("draft or archived" in n for n in res["data_notes"]))

    def test_include_drafts_option(self):
        s = self.path("s2.json", json.dumps({"default_lead_time_days": 5, "review_period_days": 2,
                                             "history_days": 10, "min_history_days": 3, "include_drafts": True}))
        res = self.run_plan(setup=s)
        self.assertIn("D-1", [i["sku"] for i in res["items"]])
        self.assertEqual(res["excluded_inactive_variants"], 0)

    def test_estimates_grouped_by_type_or_product(self):
        res = self.run_plan()
        self.assertEqual(sorted(res["needs_estimate"]), ["C-1", "C-2", "M-1"])
        groups = [(g["group"], g["basis"], g["variants"], g["products"], g["estimate_key"])
                  for g in res["estimate_groups"]]
        self.assertEqual(groups, [("Hats", "type", 2, 1, "TYPE:Hats"), ("Mug", "product", 1, 1, "PRODUCT:mug")])

    def test_one_group_estimate_covers_every_variant(self):
        res = self.run_plan("--estimate", "TYPE:Hats=0.5", "--estimate", "product:MUG=0.25")
        it = {i["sku"]: i for i in res["items"]}
        for sku in ("C-1", "C-2"):
            self.assertEqual(it[sku]["daily_demand"], 0.5)
            self.assertEqual(it[sku]["demand_source"], "merchant_estimate")
        self.assertEqual(it["M-1"]["daily_demand"], 0.25)
        self.assertEqual(res["needs_estimate"], [])


class TestOversold(Base):
    def test_negative_stock_is_planned_from_zero_and_owed_units_ordered(self):
        res = self.run_plan()
        it = {i["sku"]: i for i in res["items"]}
        tm = it["T-M"]
        self.assertEqual((tm["available"], tm["oversold_units"]), (0, 3))
        # d=1, sd=0: ROP 5, order-up-to 7; position 0 + 0 incoming - 3 owed = -3, so 7 + 3 = 10 units.
        self.assertEqual(tm["position"], -3)
        self.assertEqual((tm["urgency"], tm["order_qty"]), ("order_now", 10))
        self.assertEqual(tm["days_to_stockout"], 0)
        # Z-1 has no demand in the window but 2 units are owed: order those 2 now.
        z = it["Z-1"]
        self.assertEqual((z["urgency"], z["order_qty"], z["oversold_units"]), ("order_now", 2, 2))
        self.assertEqual([(x["sku"], x["units_owed"]) for x in res["oversold"]], [("T-M", 3), ("Z-1", 2)])
        self.assertTrue(any("negative stock" in n and "5 units owed" in n for n in res["data_notes"]))


class TestMissingCost(Base):
    def test_no_costs_gives_unknown_not_zero(self):
        res = self.run_plan()
        c = res["cash"]
        self.assertIsNone(c["order_now"])
        self.assertEqual((c["order_now_items"], c["order_now_items_with_cost"]), (2, 0))   # T-M, Z-1
        self.assertIsNone(c["this_week"])                                                   # T-S
        self.assertIsNone(c["capital_tied_now"])
        self.assertEqual(c["later"], 0)                       # nothing in that bucket: a true 0
        self.assertEqual(c["items_missing_cost_count"], 6)
        trade = res["service_level_tradeoff"][0]
        self.assertIsNone(trade["safety_stock_value"])
        self.assertTrue(any("No unit costs found" in n for n in res["data_notes"]))

    def test_partial_costs_are_labelled(self):
        o, p, s = self.files()
        sup = self.path("sup.csv", "sku,unit_cost\nT-M,20\n")
        res = dp.run(["--orders", o, "--products", p, "--setup", s, "--as-of", "2026-10-28", "--suppliers", sup])
        c = res["cash"]
        self.assertEqual(c["order_now"], 200)                 # T-M 10 units x 20; Z-1 has no cost
        self.assertEqual((c["order_now_items"], c["order_now_items_with_cost"]), (2, 1))
        self.assertTrue(any("5 of 6 items have no unit cost" in n for n in res["data_notes"]))


def build(plan, tmp):
    pj, out = os.path.join(tmp, "plan.json"), os.path.join(tmp, "dash.html")
    write(pj, json.dumps(plan))
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "build_dashboard.py"), "--plan", pj, "--out", out],
                   check=True, capture_output=True)
    with open(out, encoding="utf-8") as fh:
        return out, fh.read()


def run_page(page, tmp):
    js = page[page.index("<script>") + 8:page.rindex("</script>")]
    stub = ("const E={};const document={getElementById:id=>E[id]||(E[id]={value:'',checked:false,"
            "textContent:'',innerHTML:'',addEventListener(){}})};\n")
    runner = os.path.join(tmp, "run.js")
    write(runner, stub + js + "\nconsole.log(JSON.stringify({last:LAST,answer:E.answer.innerHTML,"
                                "now:E.k_now.textContent,later:E.later.textContent}));")
    out = subprocess.run([NODE, runner], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class TestDashboard(Base):
    @unittest.skipUnless(NODE, "node not installed")
    def test_unknown_cash_is_not_shown_as_zero(self):
        plan = self.run_plan()
        _, page = build(plan, self.tmp)
        got = run_page(page, self.tmp)
        self.assertIsNone(got["last"]["now"])
        self.assertEqual(got["now"], "unknown")
        self.assertIn("cash unknown", got["answer"])
        self.assertNotIn("EGP 0", got["answer"])

    def test_large_catalog_stays_light(self):
        plan = self.run_plan()
        tmpl = {i["sku"]: i for i in plan["items"]}
        items = []
        for n in range(3000):   # 3,000 "later" rows and 3,000 rows that need an estimate
            later = dict(tmpl["T-S"], key="L-%d" % n, sku="L-%d" % n, title="Long product name %d" % (n // 5),
                         available=500, flags=["a flag that should not be embedded in the page"])
            later.update(urgency="later")
            items.append(later)
            items.append(dict(tmpl["C-1"], key="E-%d" % n, sku="E-%d" % n, title="Other %d" % n))
        items += [tmpl["T-M"], tmpl["Z-1"]]
        plan["items"] = items
        out, page = build(plan, self.tmp)
        self.assertLess(len(page.encode("utf-8")), 500 * 1024)
        self.assertNotIn("a flag that should not be embedded", page)
        with open(os.path.splitext(out)[0] + "-all-items.csv", encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 1 + len(items))
        if NODE:
            got = run_page(page, self.tmp)
            self.assertEqual(got["last"]["rows"], 2)                 # only the actionable oversold rows
            self.assertIn("3000 more items to reorder later", got["later"])


if __name__ == "__main__":
    unittest.main()
