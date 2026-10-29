"""Tests for skills/operations/cod-rto-analysis. Expected numbers worked out by hand from the fixtures.

Fixture story (orders_export.csv, 14 orders, setup.json: outbound 50, return 40, packaging 10,
COD fee on failure 0, min_orders 3, bands 500/1000, action gap 0.15):
- COD scope = 13 orders (#1009 is Shopify Payments).
- delivered 6: #1001 #1004 #1007(courier says Delivered) #1010 #1011 #1013
- failed 4: #1002 (cancelled after fulfillment), #1003 (tag RTO), #1008 (courier Returned),
  #1012 (cancelled after fulfillment)
- cancelled_before_shipping #1005, not_shipped #1006, open #1014
- losses: 100 + 100 + (55+45+5+10=115) + 100 = 415
"""
import io, json, os, sys, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "cod-rto-analysis", "scripts")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)

import rto_analysis  # noqa: E402
from regions import Regions  # noqa: E402


def run(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = rto_analysis.main(list(args))
    json.loads(buf.getvalue())  # printed output is valid JSON
    return res


def seg(res, dim, value):
    return next(s for s in res["segments"][dim] if s["value"] == value)


class TestMain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("--orders", os.path.join(FIX, "orders_export.csv"),
                    "--setup", os.path.join(FIX, "setup.json"),
                    "--courier", os.path.join(FIX, "courier_a.csv") + "::FastShip")

    def test_outcomes(self):
        self.assertEqual(self.r["orders_in_file"], 14)
        self.assertEqual(self.r["orders_in_scope"], 13)
        self.assertEqual(self.r["outcomes"], {"delivered": 6, "failed": 4, "cancelled_before_shipping": 1,
                                              "not_shipped": 1, "open": 1})

    def test_overall(self):
        o = self.r["overall"]
        self.assertEqual((o["resolved"], o["delivered"], o["failed"]), (10, 6, 4))
        self.assertEqual(o["failure_rate"], 0.4)
        self.assertEqual(o["delivery_success_rate"], 0.6)
        self.assertEqual(o["money_lost"], 415.0)
        self.assertEqual(o["avg_loss_per_failed_order"], 103.75)
        self.assertEqual(o["loss_breakdown"], {"outbound": 205.0, "return": 165.0, "cod_fee": 5.0, "packaging": 40.0})
        self.assertEqual(self.r["period"], {"from": "2026-10-05", "to": "2026-10-12", "days": 8})
        self.assertEqual(o["money_lost_per_month"], 1556.25)   # 415 x 30 / 8

    def test_regions(self):
        g = seg(self.r, "region", "Giza")
        self.assertEqual((g["resolved"], g["failed"], g["money_lost"]), (5, 3, 300.0))
        self.assertEqual(g["failure_rate"], 0.6)
        self.assertEqual(g["confidence"], "medium")
        self.assertAlmostEqual(g["ci95_low"], 0.2307, places=3)
        self.assertAlmostEqual(g["ci95_high"], 0.8824, places=3)
        c = seg(self.r, "region", "Cairo")
        self.assertEqual((c["resolved"], c["failed"], c["money_lost"]), (4, 1, 115.0))
        u = seg(self.r, "region", "Unknown (EG)")
        self.assertEqual((u["resolved"], u["ranked"], u["confidence"]), (1, False, "too few orders"))
        self.assertEqual(self.r["worst"]["region"], ["Giza"])
        self.assertEqual(self.r["unknown_regions"], [{"province": "", "city": "Nowhere Town", "country": "EG", "orders": 1}])

    def test_other_segments(self):
        self.assertEqual(seg(self.r, "value_band", "500-999 EGP")["failed"], 2)
        self.assertEqual(seg(self.r, "value_band", "1000+ EGP")["ranked"], False)
        self.assertEqual(seg(self.r, "value_band", "under 500 EGP")["failure_rate"], 0.0)
        b = seg(self.r, "product", "Product B")
        self.assertEqual((b["resolved"], b["failed"], b["money_lost"], b["failure_rate"]), (5, 4, 415.0, 0.8))
        a = seg(self.r, "product", "Product A")
        self.assertEqual((a["resolved"], a["failed"]), (6, 1))
        f = seg(self.r, "customer_history", "first order in data")
        self.assertEqual((f["resolved"], f["failed"]), (8, 4))
        self.assertEqual(seg(self.r, "customer_history", "repeat, failed before")["resolved"], 1)
        self.assertEqual(seg(self.r, "customer_history", "repeat, no earlier failure")["resolved"], 1)
        m = seg(self.r, "day_of_week", "Monday")   # Oct 5 (#1001, #1002) and Oct 12 (#1013)
        self.assertEqual((m["resolved"], m["failed"]), (3, 1))
        self.assertEqual(seg(self.r, "courier", "FastShip")["resolved"], 2)
        self.assertEqual(seg(self.r, "payment_method", "Shopify Payments")["resolved"], 1)
        self.assertEqual(seg(self.r, "payment_method", "Cash on Delivery (COD)")["resolved"], 10)

    def test_actions(self):
        acts = [(x["type"], x["target"], x["estimated_saving"], x["label"]) for x in self.r["actions"]]
        self.assertEqual(acts, [("prepay_area", "Giza", 150.0, "estimate"),
                                ("product_check", "Product B", 124.5, "estimate"),
                                ("confirm_value", "500-999 EGP", 64.5, "estimate")])
        self.assertEqual(self.r["actions"][0]["estimated_saving_per_month"], 562.5)

    def test_courier_join(self):
        self.assertEqual(self.r["courier"]["rows"], 3)
        self.assertEqual(self.r["courier"]["matched"], 2)
        self.assertEqual(self.r["courier"]["unmatched"], 1)
        self.assertEqual(self.r["failure_reasons"], [{"reason": "customer refused", "orders": 1}])
        cols = self.r["courier"]["columns"]["courier_a.csv"]
        self.assertEqual(cols["ref"], "order_reference")
        self.assertEqual(cols["return_fee"], "return_fees")


class TestCourierSwitch(unittest.TestCase):
    def test_switch(self):
        r = run("--orders", os.path.join(FIX, "switch_orders.csv"),
                "--setup", os.path.join(FIX, "switch_setup.json"),
                "--courier", os.path.join(FIX, "switch_courier_x.csv") + "::X",
                "--courier", os.path.join(FIX, "switch_courier_y.csv") + "::Y")
        self.assertEqual(r["overall"]["failed"], 2)
        self.assertEqual(r["overall"]["money_lost"], 200.0)
        self.assertEqual(len(r["actions"]), 1)
        act = r["actions"][0]
        self.assertEqual((act["type"], act["target"], act["estimated_saving"]),
                         ("switch_courier", "Cairo: X to Y", 200.0))
        self.assertEqual(act["estimated_saving_per_month"], 1000.0)   # 6-day period


class TestRegions(unittest.TestCase):
    R = Regions()

    def check(self, expected, **kw):
        self.assertEqual(self.R.resolve(**kw)[0], expected, kw)

    def test_egypt(self):
        self.check("Giza", province_name="6th of October", country="EG")
        self.check("Giza", city="Sheikh Zayed", country="EG")
        self.check("Giza", province_name="gizeh")
        self.check("Giza", province_name="الجيزة", country="EG")
        self.check("Cairo", province_name="Al-Qahira Governorate", country="Egypt")
        self.check("Cairo", city="التجمع الخامس", country="EG")
        self.check("Cairo", city="Maadi", country="EG")
        self.check("Cairo", province_code="C", country="EG")
        self.check("Dakahlia", city="Mansoura", country="EG")
        self.check("Kafr El Sheikh", province_name="Kafr El-Sheikh", country="EG")
        self.check("Alexandria", province_name="Alex", country="EG")
        self.check("Sharqia", province_name="الشرقية", country="EG")
        self.check(None, city="Nowhere Town", country="EG")

    def test_egypt_has_27(self):
        with open(os.path.join(SCRIPTS, "..", "assets", "regions.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["countries"]["EG"]["regions"]), 27)
        self.assertEqual(set(data["countries"]), {"EG", "AE", "SA", "KW", "QA", "BH", "OM"})

    def test_gcc(self):
        self.check("Eastern Province", province_name="الشرقية", country="SA")
        self.check("Makkah", city="Jeddah", country="SA")
        self.check("Dubai", province_code="DU", country="AE")
        self.check("Abu Dhabi", city="Al Ain", country="AE")
        self.check("Hawalli", city="Salmiya", country="KW")
        self.check("Qatar", city="Doha", country="QA")
        self.check("Capital", city="Manama", country="BH")
        self.check("Dhofar", city="Salalah", country="OM")


class TestDashboard(unittest.TestCase):
    def test_render(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            res, out = os.path.join(d, "r.json"), os.path.join(d, "r.html")
            with open(res, "w", encoding="utf-8") as fh:
                json.dump(run("--orders", os.path.join(FIX, "orders_export.csv"), "--setup", os.path.join(FIX, "setup.json")), fh)
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "render_dashboard.py"), res, out],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            page = open(out, encoding="utf-8").read()
        self.assertIn("Made with the free ReplAi skills pack", page)
        self.assertNotIn("__DATA__", page)
        self.assertIn('name="viewport"', page)


# ---------- regressions from the adversarial QA pass (Oct 29 2026) ----------

ORDER_HEAD = "Name,Email,Financial Status,Fulfillment Status,Total,Created at,Lineitem quantity,Lineitem name,Shipping Province Name,Shipping Country,Payment Method,Tags\n"


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


class TestRegressions(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        rows = "".join(f"#10{i},,pending,fulfilled,500,2026-10-0{i} 10:00:00 +0200,1,Hoodie - Black / M,Cairo,EG,Cash on Delivery (COD),\n"
                       for i in range(1, 6))
        self.orders = write(self.d, "orders.csv", ORDER_HEAD + rows)
        self.setup = write(self.d, "setup.json", json.dumps({"default_outbound_shipping": 50, "default_return_shipping": 40,
                                                              "packaging_cost": 10, "min_orders": 1}))

    def tearDown(self):
        self.tmp.cleanup()

    def outcomes(self, res):
        return {o: c for o, c in res["outcomes"].items()}

    def test_arabic_courier_statuses_with_default_lists(self):
        # Default setup lists only (no setup file): "not delivered" in Arabic contains "delivered" in Arabic.
        c = write(self.d, "c.csv", "رقم الطلب,حالة الشحنة,سبب\n101,لم يتم التسليم,العميل رفض\n102,مرفوض,\n"
                                   "103,تم الإرجاع للتاجر,\n104,تم التسليم,\n")
        res = run("--orders", self.orders, "--setup", self.setup, "--courier", c + "::ArCo")
        self.assertEqual(self.outcomes(res), {"failed": 3, "delivered": 1, "open": 1})
        self.assertEqual(res["courier"]["columns"]["c.csv"]["status"], "حالة_الشحنة")

    def test_two_couriers_with_repeated_courier_map(self):
        a = write(self.d, "a.csv", "Ref,Phase\n101,Delivered\n102,Returned\n")
        b = write(self.d, "b.csv", "Ref,Etat\n103,Delivered\n104,Undelivered\n")
        res = run("--orders", self.orders, "--setup", self.setup, "--courier", a + "::A", "--courier", b + "::B",
                  "--courier-map", "status=Phase", "--courier-map", "status=Etat")
        self.assertEqual(res["courier"]["matched"], 4)
        self.assertEqual(self.outcomes(res), {"delivered": 2, "failed": 2, "open": 1})

    def test_fee_text_without_number_uses_setup_default(self):
        c = write(self.d, "c.csv", "Order Number,Status,Shipping Fees,Return Fees\n101,Undelivered,60,N/A\n102,Returned,-,0\n")
        res = run("--orders", self.orders, "--setup", self.setup, "--courier", c)
        # 101: 60 + default 40 + 10 = 110. 102: default 50 + written 0 + 10 = 60.
        self.assertEqual(res["overall"]["money_lost"], 170.0)

    def test_excel_resaved_dates(self):
        from orders import load_orders
        us = write(self.d, "us.csv", ORDER_HEAD + "#1,,paid,fulfilled,5,10/13/2026 10:00,1,A,Cairo,EG,COD,\n"
                                                  "#2,,paid,fulfilled,5,10/2/2026 9:00,1,A,Cairo,EG,COD,\n")
        eu = write(self.d, "eu.csv", ORDER_HEAD + "#1,,paid,fulfilled,5,13/10/2026 10:00,1,A,Cairo,EG,COD,\n"
                                                  "#2,,paid,fulfilled,5,02/10/2026,1,A,Cairo,EG,COD,\n")
        serial = write(self.d, "serial.csv", ORDER_HEAD + "#1,,paid,fulfilled,5,46308.4166,1,A,Cairo,EG,COD,\n")
        self.assertEqual([o["date"] for o in load_orders(us)], ["2026-10-13", "2026-10-02"])
        self.assertEqual([o["date"] for o in load_orders(eu)], ["2026-10-13", "2026-10-02"])
        self.assertEqual([o["date"] for o in load_orders(serial)], ["2026-10-13"])
        res = run("--orders", us, "--setup", self.setup)
        self.assertEqual(res["period"], {"from": "2026-10-02", "to": "2026-10-13", "days": 12})

    def test_region_spellings_and_setup_aliases(self):
        R = Regions()
        self.assertEqual(R.resolve("Gizah", "", "", "EG")[0], "Giza")
        self.assertEqual(R.resolve("Bani Sweif", "", "", "EG")[0], "Beni Suef")
        o = write(self.d, "o.csv", ORDER_HEAD + "#1,,paid,fulfilled,5,2026-10-01,1,A,Haram Gedid,EG,COD,\n")
        s = write(self.d, "s.json", json.dumps({"region_aliases": {"Giza": ["haram gedid"], "Atlantis": ["x"]}}))
        res = run("--orders", o, "--setup", s)
        self.assertEqual(res["segments"]["region"][0]["value"], "Giza")
        self.assertTrue(any("Atlantis" in w for w in res["warnings"]))

    def test_actions_carry_failures_avoided_and_short_period_warns(self):
        res = run("--orders", os.path.join(FIX, "orders_export.csv"), "--setup", os.path.join(FIX, "setup.json"),
                  "--courier", os.path.join(FIX, "courier_a.csv") + "::FastShip")
        giza = next(a for a in res["actions"] if a["type"] == "prepay_area")
        self.assertEqual(giza["failures_avoided_estimate"], 1.5)   # 3 failed x 0.5
        self.assertTrue(any("only 8 days" in w for w in res["warnings"]))

    def test_negative_refund_and_discount_are_read_as_amounts(self):
        from orders import load_orders
        o = write(self.d, "o.csv", "Name,Financial Status,Fulfillment Status,Discount Amount,Refunded Amount\n#1,paid,fulfilled,-20,-150\n")
        x = load_orders(o)[0]
        self.assertEqual((x["discount"], x["refunded"]), (20.0, 150.0))


# ---------- fixes from the real-export run (Oct 2026 formats), synthetic data only ----------

NEW_HEAD = "Name,Email,Financial Status,Fulfillment Status,Total,Created at,Lineitem quantity,Lineitem name,Lineitem SKU,Shipping Province Name,Shipping City,Shipping Country,Canceled at,Payment Method,Tags\n"
COD = "Cash on Delivery (COD)"


class TestRealExportFindings(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.setup = write(self.d, "s.json", json.dumps({"default_outbound_shipping": 50, "default_return_shipping": 40,
                                                          "packaging_cost": 10, "min_orders": 1}))

    def tearDown(self):
        self.tmp.cleanup()

    def orders(self, rows, name="o.csv"):
        return write(self.d, name, NEW_HEAD + "".join(",".join(r) + "\n" for r in rows))

    def test_canceled_at_one_l_is_read(self):
        # Findings 1 and 8: "Canceled at" (2026 spelling). #1 cancelled before shipping, #2 cancelled after fulfillment.
        o = self.orders([["#1", "", "voided", "unfulfilled", "500", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "2026-10-02", COD, ""],
                         ["#2", "", "voided", "fulfilled", "500", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "2026-10-03", COD, ""],
                         ["#3", "", "paid", "fulfilled", "500", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, ""]])
        res = run("--orders", o, "--setup", self.setup)
        self.assertEqual(res["outcomes"], {"cancelled_before_shipping": 1, "failed": 1, "delivered": 1})
        self.assertEqual(res["overall"]["money_lost"], 100.0)

    def test_product_segment_groups_variants(self):
        # Finding 6: variants of one product are one segment by default; setup product_group "variant" splits them.
        o = self.orders([["#1", "", "paid", "fulfilled", "5", "2026-10-01", "1", "Hoodie - Black / M", "H1", "Cairo", "", "EG", "", COD, ""],
                         ["#2", "", "voided", "fulfilled", "5", "2026-10-01", "1", "Hoodie - Grey / L", "H2", "Cairo", "", "EG", "2026-10-02", COD, ""],
                         ["#3", "", "paid", "fulfilled", "5", "2026-10-01", "1", "T - Shirt - Red", "T1", "Cairo", "", "EG", "", COD, ""]])
        res = run("--orders", o, "--setup", self.setup)
        self.assertEqual(seg(res, "product", "Hoodie")["resolved"], 2)
        self.assertEqual(seg(res, "product", "T - Shirt")["resolved"], 1)
        v = write(self.d, "v.json", json.dumps({"min_orders": 1, "product_group": "variant"}))
        res = run("--orders", o, "--setup", v)
        self.assertEqual(len(res["segments"]["product"]), 3)
        # A products export (2026 headers) gives exact titles by SKU, also for titles containing " - ".
        prods = write(self.d, "p.csv", "Title,URL handle,SKU,Option1 name,Option1 value\nT - Shirt,t,T1,Color,Red\nHoodie,h,H1,Color,Black\n,h,H2,Color,Grey\n")
        res = run("--orders", o, "--setup", self.setup, "--products", prods)
        self.assertEqual(sorted(x["value"] for x in res["segments"]["product"]), ["Hoodie", "T - Shirt"])

    def test_courier_from_tags_without_courier_file(self):
        # Finding 7: courier named only in tags.
        o = self.orders([["#1", "", "paid", "fulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, '"printed, Sent to ShipBlu"'],
                         ["#2", "", "paid", "fulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, "bosta_synced"],
                         ["#3", "", "paid", "fulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, "aramex"],
                         ["#4", "", "paid", "fulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, "vip"]])
        res = run("--orders", o, "--setup", self.setup)
        self.assertEqual(sorted(x["value"] for x in res["segments"]["courier"]), ["Aramex", "Bosta", "ShipBlu", "Unknown"])
        own = write(self.d, "t.json", json.dumps({"min_orders": 1, "courier_tags": {"vip": "OwnFleet"}}))
        res = run("--orders", o, "--setup", own)
        self.assertEqual(sorted(x["value"] for x in res["segments"]["courier"]), ["OwnFleet", "Unknown"])

    def test_courier_cancel_on_unshipped_order_is_not_rto(self):
        # Finding 9: cancelled before pickup is not a failed delivery and costs no shipping.
        o = self.orders([["#1001", "", "pending", "unfulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, ""],
                         ["#1002", "", "pending", "fulfilled", "5", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, ""]])
        c = write(self.d, "c.csv", "Order Number,Status\n1001,Cancelled\n1002,Cancelled\n")
        res = run("--orders", o, "--setup", self.setup, "--courier", c + "::X")
        self.assertEqual(res["outcomes"], {"cancelled_before_shipping": 1, "failed": 1})
        self.assertEqual(res["overall"]["money_lost"], 100.0)   # only #1002

    def test_split_shipment_suffix_joins_base_order(self):
        # Finding 10.
        from orders import order_key
        for ref in ("#1001-2", "1001_2", "1001-F1", "#1001", "ORD-1001"):
            self.assertEqual(order_key(ref), "1001", ref)
        self.assertEqual(order_key("EG-2026-1001"), "20261001")   # a 4-digit tail is not a suffix

    def test_several_courier_rows_pick_latest_or_most_final(self):
        # Finding 11.
        from orders import CourierIndex, load_courier
        s = rto_analysis.load_setup(None)
        dated = write(self.d, "d.csv", "Order Number,Status,Last Update\n1001,Delivered,2026-10-05 09:00\n1001,Out for delivery,2026-10-03 10:00\n"
                                       "1002,Returned,05/10/2026\n1002,In transit,25/09/2026\n")
        rows, _ = load_courier(dated)
        idx = CourierIndex(rows, s)
        self.assertEqual(idx.match({"key": "1001", "tracking": []})["status"], "Delivered")
        self.assertEqual(idx.match({"key": "1002", "tracking": []})["status"], "Returned")
        undated = write(self.d, "u.csv", "Order Number,Status\n1001,Delivered\n1001,In transit\n1002,Out for delivery\n1002,Picked up\n")
        rows, _ = load_courier(undated)
        idx = CourierIndex(rows, s)
        self.assertEqual(idx.match({"key": "1001", "tracking": []})["status"], "Delivered")
        self.assertEqual(idx.match({"key": "1002", "tracking": []})["status"], "Picked up")   # equal: later row

    def test_money_lost_null_without_any_cost(self):
        # Finding 14.
        o = self.orders([["#1", "", "voided", "fulfilled", "900", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "2026-10-02", COD, ""],
                         ["#2", "", "paid", "fulfilled", "900", "2026-10-01", "1", "A", "", "Cairo", "", "EG", "", COD, ""]])
        none = write(self.d, "n.json", json.dumps({"min_orders": 1}))
        res = run("--orders", o, "--setup", none)
        self.assertIsNone(res["overall"]["money_lost"])
        self.assertIsNone(res["overall"]["avg_loss_per_failed_order"])
        self.assertIsNone(seg(res, "region", "Cairo")["money_lost"])
        self.assertTrue(any("money lost cannot be computed" in w for w in res["warnings"]))
        self.assertTrue(all(a["estimated_saving"] is None for a in res["actions"]))
        c = write(self.d, "c.csv", "Order Number,Status,Shipping Fees,Return Fees\n1,Returned,60,45\n")
        res = run("--orders", o, "--setup", none, "--courier", c)
        self.assertEqual(res["overall"]["money_lost"], 105.0)

    def test_unrecognised_province_falls_back_to_city(self):
        # Finding 18: data-sources.md now says "blank or not recognised"; this is what the code does.
        self.assertEqual(Regions().resolve("Zzz Unknownia", "", "Maadi", "EG")[:1], ("Cairo",))
        self.assertEqual(Regions().resolve("", "", "Mansoura", "EG")[2], "city")


if __name__ == "__main__":
    unittest.main()
