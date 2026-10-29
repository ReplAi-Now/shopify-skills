"""Tests for skills/operations/true-profit. Expected numbers worked out by hand from the fixtures.

setup.json: gateway 3% + 2, COD fee 1% + 0, shipping 60, return 50, packaging 10,
fixed 300/month, 1 USD = 50 EGP, bestseller_top_n 2.

#2001 COD delivered: Hoodie Black 600 + Cap 2 x 200 = 1000 gross, discount 100, shipping
  charged 50 -> shares 0.6 / 0.4. Courier: shipping 70, COD fee 9.5.
  Hoodie net 600-60+30 = 570, COGS 300, ship 42, fee 5.7, pack 6.
  Cap net 400-40+20 = 380, COGS 160, ship 28, fee 3.8, pack 4.
#2002 card delivered: Hoodie Grey 650, COGS 320, ship 60, fee 3% x 650 + 2 = 21.5, pack 10.
#2003 COD cancelled after fulfillment = RTO: courier shipping 70 + return 55 + COD fee 0 + pack 10 = 135.
#2004 COD delivered, refunded 150: Cap 150 (0.6) + Socks 2 x 50 (0.4, no cost).
  Cap net 150-90 = 60, COGS 80 x (1 - 150/250) = 32, ship 36, fee 1.5, pack 6.
#2005 not shipped: ignored.
Ads: meta 6 USD = 300 EGP (Hoodie campaign 200, brand 100 shared), tiktok 120 (Caps -> Cap),
  google 70 shared (file has 2 title lines and a Total row). Shared 170 split by net revenue
  1220 / 440 / 40 of 1700 -> 122 / 44 / 4.
"""
import io, json, os, subprocess, sys, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "true-profit", "scripts")
ASSETS = os.path.join(ROOT, "skills", "operations", "true-profit", "assets")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)

import profit  # noqa: E402


def f(name):
    return os.path.join(FIX, name)


ARGS = ["--orders", f("orders_export.csv"), "--setup", f("setup.json"), "--costs", f("products_export.csv"),
        "--ads", "meta=" + f("meta.csv"), "--ads", "tiktok=" + f("tiktok.csv"), "--ads", "google=" + f("google.csv"),
        "--ad-map", f("ad_map.csv"), "--courier", f("courier.csv")]


def run(args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = profit.main(args)
    json.loads(buf.getvalue())
    return res


class TestProfit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run(ARGS)
        cls.p = {x["product"]: x for x in cls.r["products"]}

    def test_outcomes(self):
        self.assertEqual(self.r["order_outcomes"], {"delivered": 3, "failed": 1, "not_shipped": 1})

    def test_hoodie(self):
        h = self.p["Hoodie"]
        self.assertEqual((h["units_sold"], h["units_rto"], h["orders"]), (2, 1, 2))
        self.assertEqual(h["gross_sales"], 1250.0)
        self.assertEqual(h["discounts"], 60.0)
        self.assertEqual(h["shipping_income"], 30.0)
        self.assertEqual(h["net_revenue"], 1220.0)
        self.assertEqual(h["cogs"], 620.0)
        self.assertEqual(h["shipping_cost"], 102.0)
        self.assertEqual(h["payment_fees"], 27.2)
        self.assertEqual(h["packaging"], 16.0)
        self.assertEqual(h["rto_cost"], 135.0)
        self.assertEqual(h["ads"], 322.0)
        self.assertEqual(h["contribution_before_ads"], 319.8)
        self.assertEqual(h["contribution"], -2.2)
        self.assertEqual(h["margin"], -0.0018)
        self.assertEqual(h["break_even_roas"], 3.81)            # 1220 / 319.8
        self.assertEqual(h["break_even_platform_roas"], 5.78)   # (1250 + 600) / 319.8
        self.assertEqual(h["actual_roas"], 3.79)                # 1220 / 322

    def test_cap(self):
        c = self.p["Cap"]
        self.assertEqual(c["units_sold"], 3)
        self.assertEqual(c["refunds"], 90.0)
        self.assertEqual(c["net_revenue"], 440.0)
        self.assertEqual(c["cogs"], 192.0)
        self.assertEqual(c["shipping_cost"], 64.0)
        self.assertEqual(c["payment_fees"], 5.3)
        self.assertEqual(c["ads"], 164.0)
        self.assertEqual(c["contribution"], 4.7)
        self.assertEqual(c["break_even_roas"], 2.61)

    def test_missing_cost(self):
        s = self.p["Socks"]
        self.assertTrue(s["cost_missing"])
        self.assertIsNone(s["contribution"])
        self.assertEqual(s["net_revenue"], 40.0)
        self.assertEqual(s["ads"], 4.0)
        self.assertTrue(any("Socks" in w for w in self.r["warnings"]))

    def test_totals(self):
        t = self.r["totals"]
        self.assertEqual(t["net_revenue"], 1700.0)
        self.assertEqual(t["ads_total"], 490.0)
        self.assertEqual(t["ads_mapped"], 320.0)
        self.assertEqual(t["ads_shared_by_revenue"], 170.0)
        self.assertEqual(t["contribution_known_products"], 2.5)
        self.assertEqual(t["fixed_costs_for_period"], 60.0)    # 300 x 6 days / 30
        self.assertEqual(t["net_profit_known"], -57.5)
        self.assertEqual(t["rto_cost"], 135.0)

    def test_bestsellers_losing_money(self):
        self.assertEqual(len(self.r["bestsellers_losing_money"]), 1)
        b = self.r["bestsellers_losing_money"][0]
        self.assertEqual((b["product"], b["contribution"], b["problem"]), ("Hoodie", -2.2, "ads"))
        self.assertEqual(b["price_increase_per_unit_to_break_even"], 1.1)
        self.assertEqual(b["ad_cut_to_break_even"], 2.2)

    def test_orders(self):
        o = self.r["orders"]
        self.assertEqual((o["delivered"], o["failed_rto"], o["delivery_rate"]), (3, 1, 0.75))
        worst = {x["order"]: x["contribution"] for x in o["worst_orders"]}
        self.assertEqual(worst, {"#2003": -135.0, "#2002": 66.94, "#2001": 108.42})
        self.assertEqual(o["orders_with_missing_cost"], 1)

    def test_channels(self):
        ch = {c["channel"]: c for c in self.r["sales_channels"]}
        self.assertEqual(ch["web"]["net_revenue"], 1050.0)
        self.assertEqual(ch["web"]["contribution_known"], -26.58)   # 108.42 - 135
        self.assertEqual(ch["instagram"]["contribution_known"], 66.94)
        pl = {p["platform"]: p for p in self.r["ad_platforms"]}
        self.assertEqual(pl["meta"]["spend"], 300.0)
        self.assertEqual(pl["meta"]["currency_in_file"], ["USD"])
        self.assertEqual(pl["meta"]["platform_roas"], 4.0)          # 24 USD x 50 / 300
        self.assertEqual(pl["meta"]["true_cpa_estimate"], 200.0)    # 300 / (2 x 0.75)
        # Costed delivered orders only (#2004 has Socks without cost): #2001 950 - 460 - 89.5 = 400.5,
        # #2002 650 - 320 - 91.5 = 238.5, minus RTO #2003 135 = 504, over 2 orders.
        self.assertEqual(pl["meta"]["break_even_cpa"], 252.0)
        self.assertEqual(pl["google"]["spend"], 70.0)               # Total row skipped
        self.assertEqual(pl["tiktok"]["mapped_spend"], 120.0)
        self.assertTrue(any("1 USD = 50 EGP" in a for a in self.r["assumptions"]))

    def test_revenue_share_only(self):
        r = run([x for x in ARGS if x not in ("--ad-map", f("ad_map.csv"))])
        p = {x["product"]: x for x in r["products"]}
        # 490 split 1220 / 440 / 40 of 1700
        self.assertEqual(p["Hoodie"]["ads"], 351.65)
        self.assertEqual(p["Cap"]["ads"], 126.82)
        self.assertEqual(p["Socks"]["ads"], 11.53)

    def test_needs_fx_rate(self):
        setup = os.path.join(FIX, "setup_no_fx.json")
        with open(f("setup.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        data["fx_rates"] = {}
        with open(setup, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        try:
            proc = subprocess.run([sys.executable, os.path.join(SCRIPTS, "profit.py")] +
                                  [setup if x == f("setup.json") else x for x in ARGS],
                                  capture_output=True, text=True)
        finally:
            os.unlink(setup)
        self.assertEqual(proc.returncode, 2)
        out = json.loads(proc.stdout)
        self.assertEqual((out["error"], out["currency"]), ("need_fx_rate", "USD"))

    def test_cost_template(self):
        by_sku, by_title, _ = profit.load_costs(os.path.join(ASSETS, "product-costs-template.csv"),
                                                {"currency": "EGP", "fx_rates": {"USD": 50}})
        self.assertEqual(by_sku["bag-01"], 210.0)
        self.assertEqual(by_title["basic t-shirt"], 95.0)


class TestDashboard(unittest.TestCase):
    def test_render(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            res, out = os.path.join(d, "r.json"), os.path.join(d, "r.html")
            with open(res, "w", encoding="utf-8") as fh:
                json.dump(run(ARGS), fh)
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "render_dashboard.py"), res, out],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            page = open(out, encoding="utf-8").read()
        self.assertIn("Made with the free ReplAi skills pack", page)
        self.assertNotIn("__DATA__", page)
        self.assertIn('name="viewport"', page)


# ---------- regressions from the adversarial QA pass (Oct 29 2026) ----------

class TestRegressions(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.orders = self.write("o.csv", "Name,Financial Status,Fulfillment Status,Total,Created at,Lineitem quantity,"
                                          "Lineitem name,Lineitem price,Lineitem sku,Payment Method,Refunded Amount\n"
                                          "#1,paid,fulfilled,1000,2026-10-01,1,Hoodie - Black / M,1000,H,Visa,0\n"
                                          "#2,partially_refunded,fulfilled,1000,2026-10-02,1,Hoodie - Black / M,1000,H,Visa,-200\n"
                                          "#3,paid,fulfilled,300,2026-10-02,1,Cap,300,C,Visa,0\n")
        self.costs = self.write("c.csv", "Handle,Title,Variant SKU,Cost per item\nhoodie,Hoodie,H,400\ncap,Cap,C,0\n")
        self.setup = self.write("s.json", json.dumps({"currency": "EGP", "shipping_cost_per_order": 0,
                                                      "return_shipping_per_order": 0, "fx_rates": {"USD": 50}}))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text, enc="utf-8"):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding=enc) as fh:
            fh.write(text)
        return p

    def base(self):
        return ["--orders", self.orders, "--setup", self.setup, "--costs", self.costs]

    def test_negative_refund_reduces_revenue(self):
        r = run(self.base())
        hoodie = next(p for p in r["products"] if p["product"] == "Hoodie")
        # 1000 + (1000 - 200) = 1800; COGS 400 + 400 x (1 - 200/1000) = 720.
        self.assertEqual((hoodie["net_revenue"], hoodie["refunds"], hoodie["cogs"]), (1800.0, 200.0, 720.0))

    def test_meta_summary_row_skipped_and_total_named_campaign_kept(self):
        meta = self.write("meta.csv", "Reporting starts,Campaign name,Ad set name,Amount spent (USD)\n"
                                      "2026-10-01,,,30\n2026-10-01,Hoodie Sale,Broad,10\n2026-10-01,Total Look Bundle,Broad,20\n"
                                      "2026-10-01,Total,,30\n")
        r = run(self.base() + ["--ads", "meta=" + meta])
        self.assertEqual(r["totals"]["ads_total"], 1500.0)   # (10 + 20) x 50

    def test_utf16_ads_without_title_lines(self):
        g = self.write("g.csv", "Campaign\tCost\tCurrency code\nHoodie\t70\tEGP\nTotal: Account\t70\tEGP\n", enc="utf-16")
        r = run(self.base() + ["--ads", "google=" + g])
        self.assertEqual(r["totals"]["ads_total"], 70.0)

    def test_zero_cost_warned_and_bestsellers_listed(self):
        r = run(self.base())
        self.assertTrue(any("unit cost of 0" in w and "Cap" in w for w in r["warnings"]))
        self.assertEqual(r["bestsellers"], ["Hoodie", "Cap"])

    def test_missing_cost_warning_names_lost_ad_share(self):
        costs = self.write("c2.csv", "Handle,Title,Variant SKU,Cost per item\nhoodie,Hoodie,H,400\n")
        meta = self.write("m.csv", "Campaign name,Amount spent (EGP)\nBrand,210\n")
        r = run(["--orders", self.orders, "--setup", self.setup, "--costs", costs, "--ads", "meta=" + meta])
        # Shared 210 by net revenue 1800 / 300: Cap (no cost) takes 30.
        self.assertTrue(any("Cap" in w and "(30 EGP)" in w for w in r["warnings"]))

    def test_ad_dates_from_excel_serials(self):
        meta = self.write("m.csv", "Reporting starts,Campaign name,Amount spent (EGP)\n46296,Brand,10\n")
        r = run(self.base() + ["--ads", "meta=" + meta])
        self.assertFalse(any("Ad data runs" in w for w in r["warnings"]))   # 46296 = 2026-10-01, inside the orders


# ---------- fixes from the real-export run (Oct 2026 formats), synthetic data only ----------

HEAD = ("Name,Financial Status,Fulfillment Status,Total,Shipping,Discount Amount,Created at,Lineitem quantity,"
        "Lineitem name,Lineitem price,Lineitem SKU,Canceled at,Payment Method,Refunded Amount,Source,Tags\n")
COD = "Cash on Delivery (COD)"


def make_xlsx(path, grid):
    """Minimal XLSX (inline strings, first sheet) for tests."""
    import zipfile
    from xml.sax.saxutils import escape

    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    rows = "".join(f'<row r="{ri + 1}">' + "".join(
        f'<c r="{col(ci)}{ri + 1}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for ci, v in enumerate(r) if v != "")
        + "</row>" for ri, r in enumerate(grid))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                   f'spreadsheetml/2006/main"><sheetData>{rows}</sheetData></worksheet>')


class TestRealExportFindings(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.setup = self.write("s.json", json.dumps({"currency": "EGP", "shipping_cost_per_order": 50,
                                                      "return_shipping_per_order": 40, "packaging_cost_per_order": 0}))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def orders(self, rows):
        return self.write("o.csv", HEAD + "".join(",".join(r) + "\n" for r in rows))

    def test_canceled_at_and_2026_products_headers(self):
        # Findings 1 and 2: "Canceled at" (one L) and the 2026 products export (URL handle, SKU, Title only on row 1).
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee - Red / S", "500", "T-R-S", "", "Visa", "0", "web", ""],
                         ["#2", "voided", "unfulfilled", "500", "0", "0", "2026-10-01", "1", "Tee - Red / S", "500", "T-R-S", "2026-10-01", COD, "0", "web", ""],
                         ["#3", "voided", "fulfilled", "500", "0", "0", "2026-10-02", "1", "Tee - Blue / M", "500", "T-B-M", "2026-10-04", COD, "0", "web", ""]])
        new = self.write("p_new.csv", "Title,URL handle,Description,SKU,Option1 name,Option1 value,Price,Compare-at price,Cost per item,Inventory quantity\n"
                                      "Tee,tee,x,T-R-S,Color,Red,500,,200,3\n,tee,,T-B-M,,Blue,500,,220,1\n")
        legacy = self.write("p_old.csv", "Handle,Title,Variant SKU,Option1 Value,Variant Price,Cost per item\ntee,Tee,T-R-S,Red,500,200\ntee,,T-B-M,Blue,500,220\n")
        for costs in (new, legacy):
            r = run(["--orders", o, "--setup", self.setup, "--costs", costs])
            self.assertEqual(r["order_outcomes"], {"delivered": 1, "cancelled_before_shipping": 1, "failed": 1})
            tee = r["products"][0]
            self.assertEqual((tee["product"], tee["cogs"], tee["rto_cost"]), ("Tee", 200.0, 90.0))
            by_sku, by_title, _ = profit.load_costs(costs, {"currency": "EGP"})
            self.assertEqual((by_sku["t-b-m"], by_title["tee"]), (220.0, 210.0))

    def test_no_costs_means_profit_unknown(self):
        # Finding 3: no cost anywhere must not print a profit; a product whose only orders failed is cost missing too.
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee - Red", "500", "T1", "", COD, "0", "web", ""],
                         ["#2", "voided", "fulfilled", "300", "0", "0", "2026-10-01", "1", "Cap", "300", "C1", "2026-10-03", COD, "0", "web", ""]])
        r = run(["--orders", o, "--setup", self.setup])
        p = {x["product"]: x for x in r["products"]}
        self.assertTrue(p["Cap"]["cost_missing"])
        self.assertIsNone(p["Cap"]["contribution"])
        self.assertFalse(r["profit_known"])
        self.assertIsNone(r["totals"]["contribution_known_products"])
        self.assertIsNone(r["totals"]["margin_known"])
        self.assertEqual(r["bestsellers_losing_money"], [])
        self.assertTrue(r["warnings"][0].startswith("No product has a unit cost, so profit is unknown"))
        ch = r["sales_channels"][0]
        self.assertIsNone(ch["contribution"])
        self.assertIsNone(ch["contribution_known"])
        import subprocess
        res, out = os.path.join(self.d, "r.json"), os.path.join(self.d, "r.html")
        with open(res, "w", encoding="utf-8") as fh:
            json.dump(r, fh)
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "render_dashboard.py"), res, out], check=True, capture_output=True)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("Profit is unknown", page)
        self.assertIn("unknown: add product costs", page)

    def test_returned_units_reduce_revenue(self):
        # Finding 4: Try & Buy. #1 delivered 2 x Tee at 300, one handed back, restocked, 0 refunded.
        # #2 delivered 1 Tee 300, returned AND refunded 300: the refund already covers it (no double count).
        o = self.orders([["#1", "paid", "fulfilled", "600", "0", "0", "2026-10-01", "2", "Tee - Red", "300", "T1", "", COD, "0", "web", "ShipBlu Try & Buy"],
                         ["#2", "refunded", "fulfilled", "300", "0", "0", "2026-10-02", "1", "Tee - Red", "300", "T1", "", COD, "300", "web", ""]])
        costs = self.write("c.csv", "SKU,Title,Cost per item\nT1,Tee,100\n")
        base = ["--orders", o, "--setup", self.setup, "--costs", costs]
        r0 = run(base)
        tee0 = r0["products"][0]
        self.assertEqual((tee0["net_revenue"], tee0["units_sold"], tee0["cogs"]), (600.0, 3, 200.0))
        self.assertTrue(any("No returned-units data" in a for a in r0["assumptions"]))
        self.assertTrue(any("Try & Buy" in w for w in r0["warnings"]))
        ret = self.write("ret.csv", "order,sku,quantity,refund_amount\n#1,T1,1,0\n#2,T1,1,300\n#9,T1,1,0\n")
        r = run(base + ["--returns", ret])
        tee = r["products"][0]
        # Revenue 600 - 300 (unrefunded return) + 300 - 300 (refund) = 300; units 3 - 2 = 1;
        # COGS: #1 100 x 2 x (1 - 1/2) = 100, #2 100 x (1 - 1) = 0.
        self.assertEqual((tee["net_revenue"], tee["units_sold"], tee["units_returned"], tee["cogs"]), (300.0, 1, 2, 100.0))
        self.assertEqual(r["totals"]["returns_not_refunded"], 300.0)
        # Same answer from a connector-built "Lineitem returned quantity" column.
        o2 = self.write("o2.csv", HEAD.rstrip("\n") + ",Lineitem returned quantity\n"
                        f"#1,paid,fulfilled,600,0,0,2026-10-01,2,Tee - Red,300,T1,,{COD},0,web,,1\n")
        r2 = run(["--orders", o2, "--setup", self.setup, "--costs", costs])
        self.assertEqual(r2["products"][0]["net_revenue"], 300.0)
        self.assertTrue(any("Units sent back after delivery" in a for a in r2["assumptions"]))

    def test_price_scenario_leaves_shipping_income_alone(self):
        # Finding 5: the dashboard scales only product revenue (net revenue minus shipping charged).
        with open(os.path.join(SCRIPTS, "render_dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("const goods = p.net_revenue - (p.shipping_income || 0), dnet = goods * s.price;", src)
        self.assertNotIn("p.net_revenue * (1 + s.price)", src)

    def test_arabic_meta_headers(self):
        # Finding 12.
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee", "500", "T1", "", "Visa", "0", "web", ""]])
        meta = self.write("m.csv", "بداية التقارير,اسم الحملة,اسم مجموعة الإعلانات,المبلغ المنفق (EGP),عمليات الشراء\n"
                                   "2026-10-01,حملة تي شيرت,واسع,120,2\n2026-10-01,الإجمالي,,120,2\n")
        r = run(["--orders", o, "--setup", self.setup, "--ads", "meta=" + meta])
        self.assertEqual(r["totals"]["ads_total"], 120.0)
        self.assertEqual(r["ad_platforms"][0]["platform_purchases"], 2)

    def test_google_xlsx_title_rows_skipped(self):
        # Finding 13.
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee", "500", "T1", "", "Visa", "0", "web", ""]])
        x = os.path.join(self.d, "g.xlsx")
        make_xlsx(x, [["Campaign report"], ["October 1, 2026 to October 31, 2026"],
                      ["Campaign", "Day", "Currency code", "Cost", "Conversions"],
                      ["Search Tee", "2026-10-01", "EGP", "70", "1"], ["Total: Account", "", "EGP", "70", "1"]])
        r = run(["--orders", o, "--setup", self.setup, "--ads", "google=" + x])
        self.assertEqual(r["totals"]["ads_total"], 70.0)

    def test_break_even_cpa_uses_costed_orders_only(self):
        # Finding 15: #1 has cost (500 - 200 - 50 = 250), #2 has no cost: 250 / 1, not 250 / 2.
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee", "500", "T1", "", "Visa", "0", "web", ""],
                         ["#2", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Mug", "500", "M1", "", "Visa", "0", "web", ""]])
        costs = self.write("c.csv", "SKU,Title,Cost per item\nT1,Tee,200\n")
        meta = self.write("m.csv", "Campaign name,Amount spent (EGP),Purchases\nBrand,100,2\n")
        r = run(["--orders", o, "--setup", self.setup, "--costs", costs, "--ads", "meta=" + meta])
        self.assertEqual(r["ad_platforms"][0]["break_even_cpa"], 250.0)

    def test_cod_fee_on_cash_part_of_gift_card_orders(self):
        # Finding 16: COD 2%. With a Gift Card Amount column the fee is on 1000 - 400 = 600 -> 12.
        s = self.write("s2.json", json.dumps({"currency": "EGP", "shipping_cost_per_order": 0, "return_shipping_per_order": 0,
                                              "cod_fee_pct": 2}))
        costs = self.write("c.csv", "SKU,Title,Cost per item\nT1,Tee,100\n")
        o = self.write("g.csv", HEAD.rstrip("\n") + ",Gift Card Amount\n"
                       f"#1,paid,fulfilled,1000,0,0,2026-10-01,1,Tee,1000,T1,,gift_card + {COD},0,web,,400\n")
        r = run(["--orders", o, "--setup", s, "--costs", costs])
        self.assertEqual(r["products"][0]["payment_fees"], 12.0)
        o = self.orders([["#1", "paid", "fulfilled", "1000", "0", "0", "2026-10-01", "1", "Tee", "1000", "T1", "", "gift_card + " + COD, "0", "web", ""]])
        r = run(["--orders", o, "--setup", s, "--costs", costs])
        self.assertEqual(r["products"][0]["payment_fees"], 20.0)
        self.assertTrue(any("gift card amount is not in the file" in w for w in r["warnings"]))

    def test_shipped_pending_orders_are_open_and_left_out(self):
        # Finding 17: same rule as cod-rto-analysis.
        o = self.orders([["#1", "paid", "fulfilled", "500", "0", "0", "2026-10-01", "1", "Tee", "500", "T1", "", COD, "0", "web", ""],
                         ["#2", "pending", "fulfilled", "500", "0", "0", "2026-10-02", "1", "Tee", "500", "T1", "", COD, "0", "web", ""]])
        costs = self.write("c.csv", "SKU,Title,Cost per item\nT1,Tee,200\n")
        r = run(["--orders", o, "--setup", self.setup, "--costs", costs])
        self.assertEqual(r["order_outcomes"], {"delivered": 1, "open": 1})
        self.assertEqual(r["products"][0]["net_revenue"], 500.0)
        self.assertTrue(any(w.startswith("1 shipped orders are still open") for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main()
