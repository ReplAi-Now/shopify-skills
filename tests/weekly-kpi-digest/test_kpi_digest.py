"""Tests for weekly-kpi-digest. Expected numbers were worked out by hand from fixtures/orders.csv.

Fixture weeks (Saturday start, Asia/Riyadh, as of Monday 2026-10-26):
  this week      2026-10-17 to 2026-10-23: orders #1007-#1013 (#1012 cancelled)
  last week      2026-10-10 to 2026-10-16: #1003-#1006 (#1006 cancelled)
  4 weeks ago    2026-09-19 to 2026-09-25: #1001, #1002
#1007 is 2026-10-16 22:30 UTC = 2026-10-17 01:30 Riyadh, so it belongs to THIS week.
"""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "weekly-kpi-digest", "scripts")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)
import kpi_digest  # noqa: E402


def run(*extra):
    cmd = [sys.executable, os.path.join(SCRIPTS, "kpi_digest.py"),
           "--orders", os.path.join(FIX, "orders.csv"), "--setup", os.path.join(FIX, "setup.json")] + list(extra)
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def kpi(d, key):
    return next(k for k in d["kpis"] if k["key"] == key)


class TestWeeks(unittest.TestCase):
    def setUp(self):
        self.d = run("--as-of", "2026-10-26")

    def test_week_bounds(self):
        self.assertEqual(self.d["weeks"]["this"], {"start": "2026-10-17", "end": "2026-10-23"})
        self.assertEqual(self.d["weeks"]["last"], {"start": "2026-10-10", "end": "2026-10-16"})
        self.assertEqual(self.d["weeks"]["four_weeks_ago"], {"start": "2026-09-19", "end": "2026-09-25"})

    def test_monday_week_start(self):
        tz = kpi_digest.get_tz("Asia/Riyadh")
        w = kpi_digest.week_bounds({"week_start": "monday"}, tz, as_of="2026-10-26")
        self.assertEqual(str(w["this"]), "2026-10-19")
        w = kpi_digest.week_bounds({"week_start": "sunday"}, tz, as_of="2026-10-26")
        self.assertEqual(str(w["this"]), "2026-10-18")

    def test_timezone_boundary(self):
        tz = kpi_digest.get_tz("+03:00")
        t = kpi_digest.parse_ts("2026-10-16 22:30:00 +0000", tz)
        self.assertEqual(str(t.date()), "2026-10-17")
        self.assertEqual(t.hour, 1)


class TestKpis(unittest.TestCase):
    def setUp(self):
        self.d = run("--as-of", "2026-10-26")

    def test_this_week(self):
        d = self.d
        # Live orders 1007,1008,1009,1010,1011,1013. Subtotals 150+600+270+100+300+200 = 1620, refunds 100.
        self.assertEqual(kpi(d, "net_sales")["this"], 1520.0)
        self.assertEqual(kpi(d, "orders")["this"], 6)
        self.assertEqual(kpi(d, "aov")["this"], 270.0)
        self.assertEqual(kpi(d, "units")["this"], 11)
        self.assertEqual(kpi(d, "new_customers")["this"], 3)          # e, f, g
        self.assertEqual(kpi(d, "returning_customers")["this"], 3)    # a, c, phone of #1004
        self.assertEqual(kpi(d, "discount_share")["this"], 1.8)       # 30 / 1650
        self.assertEqual(kpi(d, "refunds")["this"], 100.0)
        self.assertEqual(kpi(d, "refund_rate")["this"], 16.7)         # 1 of 6
        self.assertEqual(kpi(d, "cod_share")["this"], 66.7)           # 4 of 6
        self.assertEqual(kpi(d, "cod_delivery_success")["this"], 50.0)  # 1 delivered, 1 refused
        self.assertEqual(kpi(d, "cancelled_orders")["this"], 1)
        self.assertEqual(d["cod_delivery"], {"cod_orders": 4, "delivered": 1, "failed": 1, "unknown": 2})

    def test_last_week(self):
        d = self.d
        # Live 1003,1004,1005: subtotals 460+100+200 = 760, refunds 200.
        self.assertEqual(kpi(d, "net_sales")["last"], 560.0)
        self.assertEqual(kpi(d, "aov")["last"], 253.33)
        self.assertEqual(kpi(d, "units")["last"], 5)
        self.assertEqual(kpi(d, "new_customers")["last"], 2)
        self.assertEqual(kpi(d, "returning_customers")["last"], 1)
        self.assertEqual(kpi(d, "discount_share")["last"], 5.0)       # 40 / 800
        self.assertEqual(kpi(d, "refund_rate")["last"], 33.3)
        self.assertEqual(kpi(d, "cod_delivery_success")["last"], 50.0)

    def test_four_weeks_ago(self):
        d = self.d
        self.assertEqual(kpi(d, "net_sales")["four_weeks_ago"], 500.0)
        self.assertEqual(kpi(d, "orders")["four_weeks_ago"], 2)
        self.assertEqual(kpi(d, "cod_delivery_success")["four_weeks_ago"], 100.0)

    def test_changes_and_flags(self):
        ns = kpi(self.d, "net_sales")
        self.assertEqual(ns["vs_last"]["change"], 171.4)              # (1520-560)/560
        self.assertEqual(ns["vs_last"]["arrow"], "↑")
        self.assertTrue(ns["vs_last"]["flag"])
        self.assertEqual(ns["vs_four_weeks_ago"]["change"], 204.0)
        aov = kpi(self.d, "aov")
        self.assertEqual(aov["vs_last"]["change"], 6.6)
        self.assertFalse(aov["vs_last"]["flag"])
        ds = kpi(self.d, "discount_share")
        self.assertEqual(ds["vs_last"], {"change": -3.2, "unit": "pp", "arrow": "↓", "flag": True, "severity": 1.067})
        cod = kpi(self.d, "cod_share")
        self.assertEqual(cod["vs_last"]["arrow"], "→")
        self.assertIsNone(kpi(self.d, "refunds")["vs_four_weeks_ago"]["change"])  # previous was 0

    def test_target(self):
        ns = kpi(self.d, "net_sales")
        self.assertEqual(ns["target"], 2000)
        self.assertEqual(ns["vs_target_pct"], -24.0)

    def test_products(self):
        top = self.d["top_products"]
        self.assertEqual([p["product"] for p in top], ["Hoodie", "Tee", "Cap", "Socks"])
        self.assertEqual(top[0]["revenue"], 900.0)
        self.assertEqual(top[0]["change_pct"], 246.2)                 # (900-260)/260
        self.assertEqual(top[1]["revenue"], 370.0)                    # 300-30 + 100
        self.assertIsNone(top[3]["change_pct"])
        self.assertEqual(self.d["bottom_products"], [])

    def test_no_analytics_means_no_conversion(self):
        keys = [k["key"] for k in self.d["kpis"]]
        self.assertNotIn("conversion_rate", keys)
        self.assertNotIn("sessions", keys)
        self.assertTrue(any("never estimated" in n for n in self.d["notes"]))
        self.assertTrue(any("still settling" in n for n in self.d["notes"]))

    def test_act_on_without_inventory(self):
        act = self.d["act_on"]
        self.assertEqual(len(act), 3)
        # COD success is still settling this week (2 of 4 unknown) and rests on 2 outcomes: not ranked.
        # COD share +16.7 pp vs 4 weeks ago rests on 2 orders then: not ranked. Target miss first, then
        # the biggest flagged good changes (returning +200%, units +120%).
        self.assertEqual([a["kpi"] for a in act], ["net_sales", "returning_customers", "units"])
        self.assertEqual(act[0]["text"], "Net sales is 24.0% off your weekly target of 2000.")


class TestInventoryAndAnalytics(unittest.TestCase):
    def test_inventory_warnings(self):
        d = run("--as-of", "2026-10-26", "--inventory", os.path.join(FIX, "inventory.csv"))
        inv = d["inventory_warnings"]
        # 28 days 2026-09-26..2026-10-23: TEE-L 2 units, 0 left; TEE-M 5 units, 1 left = 5.6 days.
        self.assertEqual([i["sku"] for i in inv], ["TEE-L", "TEE-M"])
        self.assertEqual(inv[0]["name"], "Tee - L")
        self.assertEqual(inv[1]["days_of_cover"], 5.6)
        self.assertEqual([a["kpi"] for a in d["act_on"]], ["inventory_warnings", "net_sales", "returning_customers"])

    def test_analytics(self):
        d = run("--as-of", "2026-10-26", "--analytics", os.path.join(FIX, "analytics.json"))
        s = kpi(d, "sessions")
        self.assertEqual((s["this"], s["last"], s["four_weeks_ago"]), (2000, 1000, None))
        self.assertEqual(s["vs_last"]["change"], 100.0)
        self.assertIsNone(s["vs_four_weeks_ago"])
        self.assertEqual(kpi(d, "conversion_rate")["vs_last"]["change"], 0.0)

    def test_missing_history_left_blank(self):
        d = run("--week-start", "2026-08-08")
        self.assertIsNone(kpi(d, "orders")["four_weeks_ago"])
        self.assertTrue(any("No order data" in n for n in d["notes"]))


class TestRender(unittest.TestCase):
    def test_all_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            dj = os.path.join(tmp, "d.json")
            run("--as-of", "2026-10-26", "--out", dj)
            r = os.path.join(SCRIPTS, "render_digest.py")
            for fmt, name in (("report", "r.md"), ("dashboard", "r.html"), ("email", "r.txt"), ("spreadsheet", "sheets")):
                subprocess.run([sys.executable, r, "--digest", dj, "--format", fmt, "--out", os.path.join(tmp, name)],
                               check=True, capture_output=True)
            md = read(os.path.join(tmp, "r.md"))
            self.assertIn("## Act on this", md)
            self.assertIn("Made with the free ReplAi skills pack", md)
            self.assertNotRegex(md, "[\\u2013\\u2014]")
            self.assertTrue(read(os.path.join(tmp, "r.txt")).startswith("Subject: "))
            self.assertIn('id="tpct"', read(os.path.join(tmp, "r.html")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "sheets", "kpis.csv")))


def run_with(tmp, orders_csv, setup, *extra):
    o, st = os.path.join(tmp, "o.csv"), os.path.join(tmp, "s.json")
    with open(o, "w", encoding="utf-8") as fh:
        fh.write(orders_csv)
    with open(st, "w", encoding="utf-8") as fh:
        json.dump(setup, fh)
    cmd = [sys.executable, os.path.join(SCRIPTS, "kpi_digest.py"), "--orders", o, "--setup", st] + list(extra)
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


QA_ORDERS = """Name,Email,Currency,Subtotal,Created at,Lineitem quantity,Lineitem name,Lineitem price,Lineitem sku,Payment Method,Tags
#1,a@x.com,EGP,500,2026-10-10 10:00:00 +0300,1,Shirt - M,500,SH-M,Cash on Delivery (COD),
#2,b@x.com,EGP,300,2026-10-11 10:00:00 +0300,1,Shirt - L,300,SH-L,Cash on Delivery (COD),
#3,c@x.com,USD,100,2026-10-12 10:00:00 +0300,0,Gift,100,GIFT,Card,
"""


class TestQaRegressions(unittest.TestCase):
    """Bugs found in adversarial QA (Oct 29 2026)."""

    def test_out_for_delivery_is_not_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = os.path.join(tmp, "c.csv")
            with open(c, "w", encoding="utf-8") as fh:
                fh.write("Business Reference,Status\n#1,Out for delivery\n#2,\u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u062a\u0633\u0644\u064a\u0645\n")
            d = run_with(tmp, QA_ORDERS, {"timezone": "Africa/Cairo"}, "--as-of", "2026-10-17", "--courier", c)
        self.assertEqual(d["cod_delivery"], {"cod_orders": 2, "delivered": 0, "failed": 1, "unknown": 1})

    def test_zero_quantity_line_does_not_crash_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = os.path.join(tmp, "inv.csv")
            with open(inv, "w", encoding="utf-8") as fh:
                fh.write("SKU,Available\nGIFT,5\nSH-L,0\n")
            d = run_with(tmp, QA_ORDERS, {"timezone": "Africa/Cairo"}, "--as-of", "2026-10-17", "--inventory", inv)
        self.assertEqual([i["sku"] for i in d["inventory_warnings"]], ["SH-L"])

    def test_city_timezone_short_weekday_string_target_and_new_out_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "replai-reports", "digest.json")
            d = run_with(tmp, QA_ORDERS, {"timezone": "Riyadh", "week_start": "Sat", "targets": {"net_sales": "1,000"}},
                         "--as-of", "2026-10-17", "--out", out)
            self.assertTrue(os.path.exists(out))
        self.assertEqual(d["weeks"]["this"]["start"], "2026-10-10")
        self.assertEqual(kpi(d, "net_sales")["vs_target_pct"], -10.0)

    def test_stale_export_and_mixed_currency_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = run_with(tmp, QA_ORDERS, {"timezone": "Africa/Cairo"}, "--as-of", "2026-10-31")
        self.assertEqual(d["history_end"], "2026-10-12")
        self.assertTrue(d["notes"][0].startswith("STALE DATA"))
        self.assertTrue(any("more than one currency (EGP, USD)" in n for n in d["notes"]))


def week_orders(rows):
    """rows: (name, created_at, payment, tags, extra) -> orders CSV with Notes and Payment Method columns."""
    head = "Name,Email,Subtotal,Created at,Lineitem quantity,Lineitem name,Lineitem price,Payment Method,Tags,Notes\n"
    return head + "".join("%s,%s@x.com,100,%s,1,Tee - M,100,%s,%s,%s\n" % (n, n.strip("#"), c, pay, tags, note)
                          for n, c, pay, tags, note in rows)


class TestFixPassOct29(unittest.TestCase):
    """Fix pass decided by the lead (Oct 29 2026). Week of 2026-10-10 (Saturday start, as of 2026-10-17)."""

    def test_test_orders_excluded_everywhere(self):
        rows = [("#1", "2026-10-10 10:00:00 +0300", "Credit card", "", ""),
                ("#2", "2026-10-11 10:00:00 +0300", "Bogus Gateway", "", ""),     # Shopify test gateway
                ("#3", "2026-10-12 10:00:00 +0300", "Credit card", "Test", ""),   # tagged test
                ("#4", "2026-10-12 11:00:00 +0300", "Credit card", "", "test order please ignore"),
                ("#5", "2026-10-13 10:00:00 +0300", "Credit card", "", "contest winner"),  # not a test
                ("#6", "2026-10-03 10:00:00 +0300", "bogus", "", "")]              # test, earlier week
        with tempfile.TemporaryDirectory() as tmp:
            d = run_with(tmp, week_orders(rows), {"timezone": "Asia/Riyadh"}, "--as-of", "2026-10-17")
        self.assertEqual(kpi(d, "orders")["this"], 2)                    # #1 and #5
        self.assertEqual(kpi(d, "net_sales")["this"], 200.0)
        self.assertEqual(kpi(d, "new_customers")["this"], 2)
        self.assertTrue(any(n.startswith("4 test orders") and "3 of them in the report week" in n for n in d["notes"]))

    def test_small_base_rate_change_not_ranked_but_big_base_is(self):
        def digest(n_last, n_this):
            # All COD. Last week every order delivered; this week one refused, rest delivered.
            rows = [("#L%d" % i, "2026-10-03 10:00:00 +0300", "COD", "delivered", "") for i in range(n_last)]
            rows += [("#T%d" % i, "2026-10-11 10:00:00 +0300", "COD", "refused" if i == 0 else "delivered", "")
                     for i in range(n_this)]
            with tempfile.TemporaryDirectory() as tmp:
                return run_with(tmp, week_orders(rows), {"timezone": "Asia/Riyadh"}, "--as-of", "2026-10-17")
        small = digest(4, 4)        # 100% -> 75%, -25 pp on 4 orders
        self.assertEqual(kpi(small, "cod_delivery_success")["vs_last"]["change"], -25.0)
        self.assertEqual(kpi(small, "cod_delivery_success")["base"]["this"], 4)
        self.assertNotIn("cod_delivery_success", [a["kpi"] for a in small["act_on"]])
        big = digest(10, 10)        # 100% -> 90%, -10 pp on 10 orders: ranked first (bad, flagged)
        self.assertEqual(big["act_on"][0]["kpi"], "cod_delivery_success")

    def test_settling_cod_week_not_ranked(self):
        # 10 delivered last week; this week 6 delivered, 2 refused, 8 with no status yet (50% unknown).
        rows = [("#L%d" % i, "2026-10-03 10:00:00 +0300", "COD", "delivered", "") for i in range(10)]
        rows += [("#T%d" % i, "2026-10-11 10:00:00 +0300", "COD",
                  "delivered" if i < 6 else ("refused" if i < 8 else ""), "") for i in range(16)]
        with tempfile.TemporaryDirectory() as tmp:
            d = run_with(tmp, week_orders(rows), {"timezone": "Asia/Riyadh"}, "--as-of", "2026-10-17")
        row = kpi(d, "cod_delivery_success")
        self.assertEqual((row["this"], row["settling"]), (75.0, True))
        self.assertNotIn("cod_delivery_success", [a["kpi"] for a in d["act_on"]])

    def test_fillers_do_not_ask_for_data_already_given(self):
        k = [{"key": "orders", "label": "Orders", "kind": "count", "polarity": 1, "vs_last": None,
              "vs_four_weeks_ago": None}]
        act = kpi_digest.action_items(k, [], kpi_digest.DEFAULTS, have_analytics=True, have_delivery_data=True)
        text = " ".join(a["text"] for a in act)
        self.assertEqual(len(act), 3)
        self.assertNotIn("analytics", text)
        self.assertNotIn("courier", text)
        act = kpi_digest.action_items(k, [], kpi_digest.DEFAULTS)
        self.assertIn("analytics", act[0]["text"])
        self.assertIn("courier", act[1]["text"])
        with tempfile.TemporaryDirectory() as tmp:
            c = os.path.join(tmp, "c.csv")
            with open(c, "w", encoding="utf-8") as fh:
                fh.write("Business Reference,Status\n#1,Delivered\n")
            d = run_with(tmp, QA_ORDERS, {"timezone": "Africa/Cairo"}, "--as-of", "2026-10-17", "--courier", c,
                         "--analytics", os.path.join(FIX, "analytics.json"))
        self.assertFalse(any("courier" in a["text"] or "analytics" in a["text"] for a in d["act_on"]))



COD_RTO_SCRIPTS = os.path.join(ROOT, "skills", "operations", "cod-rto-analysis", "scripts")


def cod_orders(rows, canceled_col="Canceled at"):
    """rows: (name, created_at, financial, fulfillment, cancelled_at, payment, tags) -> a newer-style
    orders export (column spelled "Canceled at"). All synthetic."""
    head = ("Name,Email,Financial Status,Fulfillment Status,Subtotal,Created at,Lineitem quantity,"
            "Lineitem name,Lineitem price,Lineitem sku,%s,Payment Method,Tags\n" % canceled_col)
    return head + "".join("%s,%s@x.com,%s,%s,100,%s,1,Tee - M,100,TEE-M,%s,%s,%s\n"
                          % (n, n.strip("#"), fin, ful, c, ca, pay, tags)
                          for n, c, fin, ful, ca, pay, tags in rows)


WEEK = "2026-10-11 10:00:00 +0300"     # inside the report week 2026-10-10..16 (as of 2026-10-17)
CANC = "2026-10-13 09:00:00 +0300"
COD = "Cash on Delivery (COD)"
HISTORY = ("#0", "2026-09-01 10:00:00 +0300", "paid", "fulfilled", "", "Credit card", "")
# Report week: #1 and #5 delivered (paid after fulfilment), #2 refused at the door (cancelled after
# fulfilment, voided), #3 cancelled before shipping, #4 out with the courier (pending), #6 prepaid
# card order cancelled after fulfilment (failed, not COD).
SPLIT_ROWS = [("#1", WEEK, "paid", "fulfilled", "", COD, ""),
              ("#2", WEEK, "voided", "fulfilled", CANC, COD, ""),
              ("#3", WEEK, "voided", "unfulfilled", CANC, COD, ""),
              ("#4", WEEK, "pending", "fulfilled", "", COD, ""),
              ("#5", WEEK, "paid", "fulfilled", "", COD, ""),
              ("#6", WEEK, "pending", "fulfilled", CANC, "Credit card", "")]


class TestRealExportFindingsOct2026(unittest.TestCase):
    """Findings from a run on real Shopify exports (Oct 2026), reproduced on synthetic data."""

    def digest(self, rows, setup=None, *extra, canceled_col="Canceled at", history=True):
        # history: one old order so the data starts before the report week (else it is left blank).
        rows = ([HISTORY] if history else []) + rows
        with tempfile.TemporaryDirectory() as tmp:
            return run_with(tmp, cod_orders(rows, canceled_col), setup or {"timezone": "Asia/Riyadh"},
                            "--as-of", "2026-10-17", *extra)

    def test_canceled_at_with_one_l_is_read(self):
        # Finding 1: a cancelled order that is not voided was counted as a live order.
        rows = [("#1", WEEK, "paid", "fulfilled", "", COD, ""),
                ("#2", WEEK, "pending", "fulfilled", CANC, COD, "")]
        for col in ("Canceled at", "Cancelled at"):
            d = self.digest(rows, canceled_col=col)
            self.assertEqual(kpi(d, "orders")["this"], 1, col)
            self.assertEqual(kpi(d, "net_sales")["this"], 100.0, col)

    def test_cancelled_split_from_failed_deliveries(self):
        # Finding 2: refused parcels (cancelled after fulfilment) are not "cancelled orders".
        d = self.digest(SPLIT_ROWS)
        self.assertEqual(kpi(d, "orders")["this"], 3)                    # #1, #4, #5
        self.assertEqual(kpi(d, "cancelled_orders")["this"], 1)          # #3
        self.assertEqual(kpi(d, "cancelled_orders")["label"], "Cancelled before shipping")
        self.assertEqual(kpi(d, "failed_deliveries")["this"], 2)         # #2 (COD) and #6 (card)

    def test_cod_success_from_statuses_without_tags_or_courier(self):
        # Finding 3: COD success was n/a with "no final status" although paid / cancelled-after-fulfilment
        # orders say exactly what happened. 2 delivered, 1 failed, 1 open; #3 never shipped, left out.
        d = self.digest(SPLIT_ROWS)
        self.assertEqual(d["cod_delivery"], {"cod_orders": 4, "delivered": 2, "failed": 1, "unknown": 1})
        self.assertEqual(kpi(d, "cod_delivery_success")["this"], 66.7)
        self.assertFalse(kpi(d, "cod_delivery_success").get("settling"))
        self.assertFalse(any("needs a final status" in n for n in d["notes"]))

    def test_settling_still_applies_to_open_parcels(self):
        rows = [("#1", WEEK, "paid", "fulfilled", "", COD, ""),
                ("#2", WEEK, "voided", "fulfilled", CANC, COD, "")]
        rows += [("#P%d" % i, WEEK, "pending", "fulfilled", "", COD, "") for i in range(3)]
        d = self.digest(rows)
        self.assertTrue(kpi(d, "cod_delivery_success")["settling"])   # 3 of 5 still in transit
        self.assertTrue(any("3 of 5 COD orders" in n for n in d["notes"]))

    def test_setup_can_turn_off_cancelled_after_fulfilment_as_failed(self):
        d = self.digest(SPLIT_ROWS, {"timezone": "Asia/Riyadh", "count_cancelled_after_fulfillment_as_failed": False})
        self.assertEqual(kpi(d, "failed_deliveries")["this"], 0)
        self.assertEqual(kpi(d, "cancelled_orders")["this"], 3)          # #2, #3, #6

    def test_same_outcomes_as_cod_rto_analysis(self):
        # The two skills must agree on delivered / failed for the same orders file.
        d = self.digest(SPLIT_ROWS + [("#7", WEEK, "pending", "fulfilled", "", COD, "RTO")])
        with tempfile.TemporaryDirectory() as tmp:
            o = os.path.join(tmp, "o.csv")
            with open(o, "w", encoding="utf-8") as fh:
                fh.write(cod_orders([HISTORY] + SPLIT_ROWS + [("#7", WEEK, "pending", "fulfilled", "", COD, "RTO")]))
            code = ("import sys,json; sys.path.insert(0, sys.argv[1]); import orders as m;"
                    "s=json.load(open(sys.argv[3], encoding='utf-8'));"
                    "print(json.dumps([m.classify(x, s) for x in m.load_orders(sys.argv[2]) if m.is_cod(x, s['cod_payment_keywords'])]))")
            out = subprocess.run([sys.executable, "-c", code, COD_RTO_SCRIPTS, o,
                                  os.path.join(ROOT, "skills", "operations", "cod-rto-analysis", "assets", "setup.example.json")],
                                 capture_output=True, text=True, check=True).stdout
        rto = json.loads(out)
        self.assertEqual((d["cod_delivery"]["delivered"], d["cod_delivery"]["failed"]),
                         (rto.count("delivered"), rto.count("failed")))
        self.assertEqual(d["cod_delivery"]["failed"], 2)                 # #2 cancelled after fulfilment, #7 tagged

    def test_inventory_export_option_headers_with_space(self):
        # Finding 4: "Option 1 Value" (inventory export) was not read, so the size was dropped.
        rows = [HISTORY] + [("#%d" % i, WEEK, "paid", "fulfilled", "", COD, "") for i in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            inv = os.path.join(tmp, "inv.csv")
            with open(inv, "w", encoding="utf-8") as fh:
                fh.write("Handle,Title,Option 1 Name,Option 1 Value,Option 2 Name,Option 2 Value,SKU,Available (not editable)\n"
                         "tee,Tee,Size,M,Color,Red,TEE-M,0\n")
            d = run_with(tmp, cod_orders(rows), {"timezone": "Asia/Riyadh"}, "--as-of", "2026-10-17", "--inventory", inv)
        self.assertEqual(d["inventory_warnings"][0]["name"], "Tee - M / Red")

    def test_zero_vs_zero_is_no_change_not_new(self):
        # Finding 5.
        c = kpi_digest.compare(0, 0, "money", kpi_digest.DEFAULTS)
        self.assertEqual(c["change"], 0.0)
        sys.path.insert(0, SCRIPTS)
        import render_digest
        self.assertEqual(render_digest.change(c), "no change")
        self.assertEqual(render_digest.change(kpi_digest.compare(5, 0, "count", kpi_digest.DEFAULTS)), "new")

    def test_returned_units_from_connector_and_zero_refund_note(self):
        # Finding 6: Try & Buy stores restock returns without refunds; exports show 0 refunds.
        d = self.digest(SPLIT_ROWS)
        self.assertNotIn("returned_units", [k["key"] for k in d["kpis"]])
        self.assertTrue(any(n.startswith("Refunds are 0 in every week") for n in d["notes"]))
        csv_text = cod_orders([HISTORY] + SPLIT_ROWS).splitlines()
        csv_text[0] += ",Returned Units"
        csv_text = [csv_text[0]] + [r + (",2" if r.startswith("#1,") else ",") for r in csv_text[1:]]
        with tempfile.TemporaryDirectory() as tmp:
            d = run_with(tmp, "\n".join(csv_text) + "\n", {"timezone": "Asia/Riyadh"}, "--as-of", "2026-10-17")
        self.assertEqual(kpi(d, "returned_units")["this"], 2)
        self.assertFalse(any(n.startswith("Refunds are 0") for n in d["notes"]))

    def test_partial_first_day_flagged(self):
        # Finding 7: the export starts 16:30 on the first day of last week; orders usually start ~01:00.
        rows = [("#A", "2026-10-03 16:30:00 +0300", "paid", "fulfilled", "", COD, "")]
        for day in range(4, 17):
            rows.append(("#D%d" % day, "2026-10-%02d 01:00:00 +0300" % day, "paid", "fulfilled", "", COD, ""))
        rows += [("#X%d" % i, "2026-10-12 12:00:00 +0300", "paid", "fulfilled", "", COD, "") for i in range(10)]
        d = self.digest(rows, history=False)
        self.assertEqual(d["partial_weeks"], ["last"])
        self.assertTrue(kpi(d, "orders")["vs_last"]["partial"])
        self.assertTrue(any(n.startswith("PARTIAL WEEK") for n in d["notes"]))
        self.assertNotIn("orders", [a["kpi"] for a in d["act_on"]])     # +100% vs a cut week is not real
        sys.path.insert(0, SCRIPTS)
        import render_digest
        self.assertTrue(render_digest.change(kpi(d, "orders")["vs_last"]).endswith("(partial)"))
        # A store whose first order of every day is at 10:00 is not flagged for a 10:00 start.
        d = self.digest([("#L%d" % i, "2026-10-0%d 10:00:00 +0300" % (3 + i % 5), "paid", "fulfilled", "", COD, "")
                         for i in range(10)] + [("#T", WEEK, "paid", "fulfilled", "", COD, "")], history=False)
        self.assertEqual(d["partial_weeks"], [])

    def test_fell_uses_absolute_value(self):
        # Finding 8: "fell -34.5%".
        rows = [("#L%d" % i, "2026-10-04 10:00:00 +0300", "paid", "fulfilled", "", COD, "") for i in range(4)]
        rows.append(("#E", "2026-10-03 00:30:00 +0300", "paid", "fulfilled", "", COD, ""))   # last week fully covered
        rows += [("#T%d" % i, WEEK, "paid", "fulfilled", "", COD, "") for i in range(2)]
        d = self.digest(rows)
        texts = [a["text"] for a in d["act_on"]]
        self.assertIn("Orders fell 60.0% vs last week. Look at traffic and conversion first, then at stock-outs on best sellers.", texts)
        self.assertFalse(any("-" in t.split(" vs ")[0] for t in texts if " fell " in t))


if __name__ == "__main__":
    unittest.main()
