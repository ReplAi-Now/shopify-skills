"""Tests for skills/operations/dead-stock-clearance. Expected numbers were worked out by hand (see comments).

Fixture as of 2026-10-28: F fast mover; S1 slow (last sale 70 days, bought with F twice);
S2 slow (300 days of cover); D1 dead 150 days; D2 dead, margin floor binds; D3 never sold in
297 days of history (extreme); D4 dead, cost too close to price for a markdown; N1 new; Z no stock.

Run: python3 -m unittest discover -s tests/dead-stock-clearance
"""
import csv
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "dead-stock-clearance", "scripts")
FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)
import dead_stock as ds  # noqa: E402


def args(*extra):
    return ["--orders", os.path.join(FX, "orders.csv"), "--products", os.path.join(FX, "products.csv"),
            "--first-stocked", os.path.join(FX, "first_stocked.csv"), "--setup", os.path.join(FX, "setup.json"),
            "--as-of", "2026-10-28"] + list(extra)


def read_csv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestHelpers(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(ds.floor_to(179.1, 5), 175)
        self.assertEqual(ds.ceil_to(93.5, 5), 95)
        self.assertEqual(ds.ceil_to(110, 5), 110)

    def test_markdown_floor(self):
        st = dict(ds.DEFAULTS, price_rounding=5, margin_floor_pct=10, allow_below_cost=False)
        self.assertEqual(ds.markdown_price(199, 80, 10, st), (175, 90, False))
        self.assertEqual(ds.markdown_price(100, 85, 20, st), (95, 95, True))      # 80 < floor 95
        self.assertIsNone(ds.markdown_price(50, 48, 20, st)[0])                   # floor 55 >= 50
        st["allow_below_cost"] = True
        self.assertEqual(ds.markdown_price(50, 48, 20, st)[0], 40)               # below cost allowed


class TestPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = ds.run(args())
        cls.it = {i["sku"]: i for i in cls.res["items"]}

    def opt(self, sku, tactic):
        return next(o for o in self.it[sku]["options"] if o["tactic"] == tactic)

    def test_classification(self):
        cats = {k: v["category"] for k, v in self.it.items()}
        self.assertEqual(cats, {"F": "healthy", "S1": "slow", "S2": "slow", "D1": "dead", "D2": "dead",
                                "D3": "dead", "D4": "dead", "N1": "new", "Z": "no_stock"})
        self.assertTrue(self.it["D3"]["extreme"])
        self.assertFalse(self.it["D1"]["extreme"])

    def test_metrics(self):
        f = self.it["F"]
        self.assertEqual(f["units_sold_cover_window"], 8)       # cancelled order of 5 excluded
        self.assertEqual(f["days_of_cover"], 75)                # 20 / (8/30)
        self.assertEqual(f["sell_through_pct"], 31.03)          # 9 / (9 + 20)
        self.assertEqual(self.it["S1"]["days_since_last_sale"], 70)
        self.assertEqual(self.it["S1"]["sell_through_pct"], 3.23)   # 1 / 31
        self.assertEqual(self.it["S2"]["days_of_cover"], 300)       # 10 / (1/30)
        self.assertEqual(self.it["D1"]["days_since_last_sale"], 150)
        self.assertEqual(self.it["N1"]["age_days"], 13)
        self.assertEqual(self.res["history"]["days_of_history"], 297)

    def test_cash_stuck(self):
        s = self.res["summary"]
        self.assertEqual(s["cash_stuck_slow"], 3800)    # 30*100 + 10*80
        self.assertEqual(s["cash_stuck_dead"], 7510)    # 12*150 + 6*85 + 40*100 + 25*48
        self.assertEqual(s["cash_stuck_total"], 14110)  # + F 2400 + N1 400
        self.assertEqual(s["aov"], 478.29)              # 3348 / 7 orders in 90 days
        self.assertEqual(s["gift_threshold"], 625)      # 478.29 * 1.3 = 621.8 -> 625

    def test_s1_bundle_from_co_purchase(self):
        self.assertEqual(self.it["S1"]["recommended"], "bundle")
        b = self.opt("S1", "bundle")
        self.assertEqual((b["partner_sku"], b["basis"], b["co_orders"]), ("F", "co_purchase", 2))
        self.assertEqual(b["item_price_in_bundle"], 210)   # 250 * 0.85 = 212.5 -> 210
        self.assertEqual(b["bundle_price"], 510)
        self.assertEqual(b["cash_recovered"], 6300)
        self.assertEqual(b["profit_if_all_sell"], 3300)    # (210 - 100) * 30

    def test_s2_markdown_first_step(self):
        self.assertEqual(self.it["S2"]["recommended"], "markdown")
        m = self.opt("S2", "markdown")
        self.assertEqual((m["step_pct"], m["new_price"], m["floor_price"]), (10, 175, 90))
        self.assertEqual(m["cash_recovered"], 1750)
        self.assertEqual(m["profit_if_all_sell"], 950)
        self.assertEqual(m["revenue_given_up"], 240)

    def test_dead_markdowns(self):
        self.assertEqual(self.it["D1"]["recommended"], "markdown_clearance")
        m = self.opt("D1", "markdown")
        self.assertEqual((m["step_pct"], m["new_price"], m["cash_recovered"], m["profit_if_all_sell"]),
                         (20, 320, 3840, 2040))
        self.assertEqual(self.it["D2"]["recommended"], "markdown_clearance")
        m2 = self.opt("D2", "markdown")
        self.assertEqual((m2["new_price"], m2["discount_pct"], m2["floor_applied"]), (95, 5, True))
        self.assertEqual(m2["profit_if_all_sell"], 60)

    def test_extreme_liquidate_and_gift(self):
        self.assertEqual(self.it["D3"]["recommended"], "liquidate")   # 30% step held at floor 110
        liq = self.opt("D3", "liquidate")
        self.assertEqual((liq["cash_recovered"], liq["profit_if_all_sell"]), (1200, -2800))
        self.assertEqual(self.it["D4"]["recommended"], "gift")
        g = self.opt("D4", "gift")
        self.assertEqual((g["threshold"], g["cash_recovered"], g["profit_if_all_sell"]), (625, 0, -1200))
        self.assertNotIn("markdown", [o["tactic"] for o in self.it["D4"]["options"]])

    def test_plan_totals(self):
        s = self.res["summary"]
        self.assertEqual(s["plan_cash_recovered"], 13660)     # 6300+1750+3840+570+1200+0
        self.assertEqual(s["plan_profit_if_all_sell"], 2350)  # 3300+950+2040+60-2800-1200

    def test_change_list_and_rollback(self):
        got = sorted((c["sku"], c["field"], str(c["old_value"]), str(c["new_value"])) for c in self.res["changes"])
        want = sorted([
            ("S1", "tag", "", "clearance-bundle"),
            ("S2", "price", "199", "175"), ("S2", "compare_at_price", "", "199"),
            ("D1", "price", "400", "320"), ("D1", "tag", "", "clearance"), ("D1", "collection", "", "Clearance"),
            ("D2", "price", "100", "95"), ("D2", "compare_at_price", "", "100"),
            ("D2", "tag", "", "clearance"), ("D2", "collection", "", "Clearance"),
            ("D4", "tag", "", "free-gift"),
        ])
        self.assertEqual(got, want)   # D1 keeps its existing compare-at 450, D3 is sold off outside the store
        rb = sorted((r["sku"], r["field"], r["action"], str(r["restore_value"])) for r in self.res["rollback"])
        self.assertEqual(len(rb), 11)
        self.assertIn(("S2", "price", "set", "199"), rb)
        self.assertIn(("S2", "compare_at_price", "set", ""), rb)
        self.assertIn(("D1", "tag", "remove_tag", "clearance"), rb)
        self.assertIn(("D2", "collection", "remove_from_collection", "Clearance"), rb)

    def test_below_cost_not_allowed_by_default(self):
        for i in self.res["items"]:
            for o in i["options"]:
                if o["tactic"] == "markdown":
                    self.assertGreaterEqual(o["new_price"], i["unit_cost"] * 1.1 - 1e-6)


class TestCli(unittest.TestCase):
    def test_writes_three_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "dead_stock.py")] + args("--out-dir", tmp),
                                 capture_output=True, text=True, check=True)
            res = json.loads(out.stdout)
            self.assertEqual(len(read_csv(res["files"]["changes"])), 11)
            rb = read_csv(res["files"]["rollback"])
            self.assertEqual(len(rb), 11)
            self.assertEqual(list(rb[0].keys())[:7], ["handle", "product_title", "variant_title", "sku",
                                                      "variant_id", "level", "field"])
            self.assertEqual(len(read_csv(res["files"]["classification"])), 9)
            plan = os.path.join(tmp, "plan.json")
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write(out.stdout)
            html = os.path.join(tmp, "dash.html")
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "build_dashboard.py"), "--plan", plan,
                            "--out", html], check=True, capture_output=True)
            with open(html, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn('id="floor"', text)
            self.assertIn("Made with the free ReplAi skills pack", text)
            self.assertNotRegex(text, "[\u2013\u2014]")

    def test_missing_products_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "p.csv")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("Title,Variant SKU\nX,Y\n")
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "dead_stock.py"), "--orders",
                                  os.path.join(FX, "orders.csv"), "--products", bad], capture_output=True, text=True)
            self.assertEqual(out.returncode, 2)
            self.assertIn("Handle", json.loads(out.stdout)["error"])


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TestQaRegressions(unittest.TestCase):
    """Bugs found in adversarial QA (Oct 29 2026)."""

    def test_short_history_does_not_mark_down_healthy_items(self):
        # 7 days of orders, 5 units sold, 30 in stock. Real pace 5/7 a day = 42 days of cover (healthy).
        # Dividing by the 30 day window gave 180 days of cover, "slow", and a price cut in the change list.
        with tempfile.TemporaryDirectory() as tmp:
            o, p = os.path.join(tmp, "o.csv"), os.path.join(tmp, "p.csv")
            rows = ["#%d,2026-10-%02d,1,X1" % (i, 22 + i % 7) for i in range(5)]
            write(o, "Name,Created at,Lineitem quantity,Lineitem sku\n" + "\n".join(rows) + "\n#9,2026-10-22,1,Y\n")
            write(p, "Handle,Title,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\n"
                     "x,X,X1,200,80,30\n")
            res = ds.run(["--orders", o, "--products", p, "--as-of", "2026-10-28"])
            it = res["items"][0]
            self.assertEqual(it["category"], "healthy")
            self.assertEqual(round(it["days_of_cover"]), 42)
            self.assertEqual(res["changes"], [])

    def test_duplicate_sku_gets_no_store_change(self):
        # Same SKU on two products, dead for 200 days. A price row would carry one product's handle with
        # the other's price, so the SKU is flagged and left out of the change list.
        with tempfile.TemporaryDirectory() as tmp:
            o, p = os.path.join(tmp, "o.csv"), os.path.join(tmp, "p.csv")
            write(o, "Name,Created at,Lineitem quantity,Lineitem sku\n#1,2026-04-11,1,P1\n#2,2026-10-28,1,Z\n")
            write(p, "Handle,Title,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\n"
                     "linen,Linen Pants,P1,600,250,4\ncargo,Cargo Pants,P1,700,300,6\n")
            res = ds.run(["--orders", o, "--products", p])
            it = next(i for i in res["items"] if i["sku"] == "P1")
            self.assertEqual((it["category"], it["recommended"], it["price"]), ("dead", None, 600))
            self.assertEqual(res["changes"], [])
            self.assertTrue(any("P1" in n for n in res["data_notes"]))

    def test_setup_values_typed_as_text_and_rounding_default(self):
        self.assertEqual(ds.DEFAULTS["price_rounding"], 5)   # matches the setup interview default
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "s.json")
            write(sp, json.dumps({"margin_floor_pct": "10%", "markdown_steps_pct": ["10%", "20%", "30%"]}))
            res = ds.run(["--orders", os.path.join(FX, "orders.csv"), "--products", os.path.join(FX, "products.csv"),
                          "--first-stocked", os.path.join(FX, "first_stocked.csv"), "--setup", sp,
                          "--as-of", "2026-10-28"])
            self.assertEqual(res["settings"]["margin_floor_pct"], 10)


NODE = shutil.which("node")


def dashboard_totals(plan, inputs=None):
    """Build the dashboard from a plan, run its script in node with a stub DOM, apply the input
    overrides (id -> value), re-render and return the LAST totals the page computed."""
    with tempfile.TemporaryDirectory() as tmp:
        pj, html = os.path.join(tmp, "plan.json"), os.path.join(tmp, "d.html")
        write(pj, json.dumps(plan))
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "build_dashboard.py"), "--plan", pj, "--out", html],
                       check=True, capture_output=True)
        with open(html, encoding="utf-8") as fh:
            page = fh.read()
        js = page[page.index("<script>") + 8:page.rindex("</script>")]
        stub = ("const E={};const document={getElementById:id=>E[id]||(E[id]={value:'',checked:false,"
                "textContent:'',innerHTML:'',addEventListener(){}})};\n")
        after = "\nconst IN=%s;for(const k in IN){if(typeof IN[k]==='boolean')$(k).checked=IN[k];else $(k).value=IN[k]}" \
                "render();console.log(JSON.stringify(LAST));" % json.dumps(inputs or {})
        runner = os.path.join(tmp, "run.js")
        write(runner, stub + js + after)
        out = subprocess.run([NODE, runner], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)


class TestFixPassOct29(unittest.TestCase):
    """Fix pass decided by the lead (Oct 29 2026)."""

    def test_refunded_orders_are_not_sales(self):
        # X1 last sold 10 days ago, then a fully refunded order yesterday. The refund must not make it
        # look freshly sold: last sale stays 10 days ago.
        with tempfile.TemporaryDirectory() as tmp:
            o, p = os.path.join(tmp, "o.csv"), os.path.join(tmp, "p.csv")
            write(o, "Name,Created at,Financial Status,Lineitem quantity,Lineitem sku\n"
                     "#1,2026-10-18,paid,1,X1\n#2,2026-10-27,refunded,3,X1\n#3,2026-10-28,paid,1,Y\n")
            write(p, "Handle,Title,Variant SKU,Variant Price,Cost per item,Variant Inventory Qty\nx,X,X1,200,80,30\n")
            res = ds.run(["--orders", o, "--products", p, "--as-of", "2026-10-28"])
            it = next(i for i in res["items"] if i["sku"] == "X1")
            self.assertEqual((it["last_sale"], it["units_sold_cover_window"]), ("2026-10-18", 1))
            self.assertTrue(any("1 fully refunded" in n for n in res["data_notes"]))

    def test_store_data_identical_to_demand_planner(self):
        other = os.path.join(ROOT, "skills", "operations", "demand-planner", "scripts", "store_data.py")
        self.assertTrue(filecmp.cmp(os.path.join(SCRIPTS, "store_data.py"), other, shallow=False))

    def test_first_stocked_month_first_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "f.csv")
            write(f, "sku,first_stocked\nA,10/03/2026\nB,10/27/2026\n")
            self.assertEqual(ds.load_first_stocked(f)["A"].isoformat(), "2026-10-03")   # Oct 3, not Mar 10
            write(f, "sku,first_stocked\nA,03/10/2026\nB,27/10/2026\n")
            self.assertEqual(ds.load_first_stocked(f)["A"].isoformat(), "2026-10-03")

    @unittest.skipUnless(NODE, "node not installed")
    def test_dashboard_matches_script_for_default_inputs(self):
        plan = ds.run(args())
        got = dashboard_totals(plan)
        self.assertAlmostEqual(got["rec"], plan["summary"]["plan_cash_recovered"], places=2)
        self.assertAlmostEqual(got["profit"], plan["summary"]["plan_profit_if_all_sell"], places=2)
        self.assertEqual({x["sku"]: x["tactic"] for x in got["items"]},
                         {i["sku"]: i["recommended"] for i in plan["items"] if i["category"] in ("slow", "dead")})

    @unittest.skipUnless(NODE, "node not installed")
    def test_dashboard_rechooses_tactics_like_the_script(self):
        # Changed inputs in the browser must give what the script gives with the same settings.
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "s.json")
            with open(os.path.join(FX, "setup.json"), encoding="utf-8") as fh:
                st = json.load(fh)
            st.update(allow_below_cost=True, markdown_steps_pct=[15, 40, 50], margin_floor_pct=0,
                      liquidation_recovery_pct=10)
            write(sp, json.dumps(st))
            changed = ds.run(["--orders", os.path.join(FX, "orders.csv"), "--products", os.path.join(FX, "products.csv"),
                              "--first-stocked", os.path.join(FX, "first_stocked.csv"), "--setup", sp,
                              "--as-of", "2026-10-28"])
        got = dashboard_totals(ds.run(args()), {"below": True, "slowstep": 15, "deadstep": 40, "xstep": 50,
                                                "floor": 0, "liq": 10})
        want = {i["sku"]: i["recommended"] for i in changed["items"] if i["category"] in ("slow", "dead")}
        self.assertEqual({x["sku"]: x["tactic"] for x in got["items"]}, want)
        self.assertEqual(want["D4"], "markdown_clearance")       # was gift/liquidate when below cost was not allowed
        self.assertAlmostEqual(got["rec"], changed["summary"]["plan_cash_recovered"], places=2)
        self.assertAlmostEqual(got["profit"], changed["summary"]["plan_profit_if_all_sell"], places=2)
        # The very old dead item (D3) follows its own input, not the fixed top step.
        d3 = next(x for x in got["items"] if x["sku"] == "D3")
        self.assertEqual(d3["new_price"], 75)                    # 150 * (1 - 0.50)


if __name__ == "__main__":
    unittest.main()
