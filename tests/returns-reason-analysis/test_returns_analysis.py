"""Tests for returns-reason-analysis. Expected numbers were worked out by hand from fixtures/.

Window: orders placed 2026-09-01 to 2026-09-30, as of 2026-10-29 (mature until 2026-10-08).
Units sold in the window (cancelled #2005 and #2006 excluded):
  LS-M-W 6, LS-L-W 3, MD-S-R 4, MD-M-R 3, TB 3  (Linen Shirt 9, Maxi Dress 7, Tote Bag 3, total 19)
Return rows counted: R1 (2 units), R2, R3, R4, R5, R6, R8 = 8 units. R7 refused, R9 outside the
window (August order), R10 unmatched order.
Money per row (shipping default 40, exchange reship 60, restock = units x cost x unsellable share):
  R1 1000+50+20=1070  R2 0+40+60+10=110  R3 500+40+10=550  R4 800+40+300=1140
  R5 800+40+300=1140 (agent override to quality)  R6 800+40+15=855  R8 0+40+60+0=100 (no cost)
"""
import csv, json, os, re, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "operations", "returns-reason-analysis", "scripts")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)
import classify_reasons as cr  # noqa: E402
import analyze_returns as ar  # noqa: E402


def run(script, *args):
    out = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def rows(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestLexicon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = cr.load_lexicon(None)

    def cat(self, text):
        return cr.match_text(text, self.lex)[0]

    def test_english(self):
        self.assertEqual(self.cat("Too small, ordered my usual size"), "size_too_small")
        self.assertEqual(self.cat("way too big on me"), "size_too_large")
        self.assertEqual(self.cat("wrong color sent"), "wrong_item")
        self.assertEqual(self.cat("The color is nice but too small"), "size_too_small")
        self.assertEqual(self.cat("arrived damaged, box crushed"), "damaged_in_shipping")
        self.assertEqual(self.cat("changed my mind"), "changed_mind")

    def test_arabic(self):
        self.assertEqual(self.cat("المقاس واسع جدا"), "size_too_large")
        self.assertEqual(self.cat("الجاكيت واااسعة"), "size_too_large")
        self.assertEqual(self.cat("ضيق عليا"), "size_too_small")
        self.assertEqual(self.cat("اللون مختلف عن الصورة"), "not_as_pictured")
        self.assertEqual(self.cat("فيه عيب في الخياطة"), "quality_defect")
        self.assertEqual(self.cat("مقاس غلط"), "fit_other")          # longer phrase beats "غلط"
        self.assertEqual(self.cat("بعتولي غلط"), "wrong_item")
        self.assertEqual(self.cat("رفض الاستلام"), "refused_at_door")

    def test_franco(self):
        self.assertEqual(self.cat("el ma2as sghayaaar awy"), "size_too_small")
        self.assertEqual(self.cat("kbeeer 3alaya"), "size_too_large")
        self.assertEqual(self.cat("el lon mokhtalef"), "not_as_pictured")
        self.assertEqual(self.cat("mesh 3ayez"), "changed_mind")
        self.assertEqual(self.cat("et2a5ar gedan"), "late_delivery")

    def test_no_match(self):
        self.assertIsNone(self.cat("bla bla"))
        self.assertIsNone(self.cat(""))

    def test_normalise(self):
        self.assertEqual(cr.normalise("كبيرة"), cr.normalise("كبيره"))
        self.assertEqual(cr.normalise("Kbeeer!"), "kber")


class TestClassify(unittest.TestCase):
    def test_classify_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "c.csv")
            s = run("classify_reasons.py", "--returns", os.path.join(FIX, "returns_app.csv"), "--out", out)
            self.assertEqual(s["by_source"], {"lexicon": 6, "code": 2, "none": 1, "type": 1})
            self.assertEqual([u["row"] for u in s["unclassified"]], [5])
            r = rows(out)
            self.assertEqual(r[0]["category"], "size_too_small")      # "Too small" free text
            self.assertEqual(r[1]["category"], "size_too_small")      # SIZE_TOO_SMALL code
            self.assertEqual(r[1]["type"], "exchange")
            self.assertEqual(r[3]["category"], "quality_defect")      # DEFECTIVE code
            self.assertEqual(r[6]["category"], "refused_at_door")
            self.assertEqual(r[6]["type"], "refused")
            # Agent classifies the leftover, then it is applied.
            s = run("classify_reasons.py", "--returns", os.path.join(FIX, "returns_app.csv"), "--out", out,
                    "--overrides", os.path.join(FIX, "overrides.csv"))
            self.assertEqual(s["unclassified"], [])
            self.assertEqual(rows(out)[4]["category_source"], "agent")

    def test_code_text_conflict(self):
        lex = cr.load_lexicon(None)
        out, _, conflicts = cr.classify_rows([{"reason_code": "SIZE_TOO_LARGE", "note": "wrong item sent"}], lex)
        self.assertEqual(out[0]["category"], "size_too_large")
        self.assertEqual(conflicts[0]["text_category"], "wrong_item")

    def test_new_reason_handles(self):
        lex = cr.load_lexicon(None)
        out, _, _ = cr.classify_rows([{"return_reason_handle": "not-as-described"}, {"reason": "COLOR"}], lex)
        self.assertEqual([o["category"] for o in out], ["not_as_pictured", "not_as_pictured"])


class TestAnalyze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        c = os.path.join(cls.tmp.name, "c.csv")
        run("classify_reasons.py", "--returns", os.path.join(FIX, "returns_app.csv"), "--out", c,
            "--overrides", os.path.join(FIX, "overrides.csv"))
        cls.d = run("analyze_returns.py", "--returns", c, "--orders", os.path.join(FIX, "orders.csv"),
                    "--setup", os.path.join(FIX, "setup.json"), "--products", os.path.join(FIX, "products.csv"),
                    "--as-of", "2026-10-29", "--start", "2026-09-01", "--end", "2026-09-30",
                    "--csv-dir", os.path.join(cls.tmp.name, "csv"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_totals(self):
        t = self.d["totals"]
        self.assertEqual((t["sold_units"], t["returned_units"], t["return_rate"]), (19, 8, 42.1))
        self.assertEqual((t["refund_units"], t["exchange_units"]), (6, 2))
        self.assertEqual(t["money_lost"], 4965.0)
        self.assertEqual(self.d["money_breakdown"], {"refunded": 3900.0, "return_shipping": 290.0,
                                                     "exchange_reship": 120.0, "restock_loss": 655.0, "handling": 0.0,
                                                     "return_shipments": 7})
        self.assertEqual(self.d["exchanges_vs_refunds"]["exchange_share"], 25.0)

    def test_window(self):
        self.assertEqual(self.d["window"]["mature_until"], "2026-10-08")

    def test_products(self):
        p = {x["product"]: x for x in self.d["by_product"]}
        self.assertEqual((p["Linen Shirt"]["sold_units"], p["Linen Shirt"]["returned_units"], p["Linen Shirt"]["return_rate"]), (9, 4, 44.4))
        self.assertEqual(p["Linen Shirt"]["money_lost"], 1730.0)
        self.assertEqual(p["Maxi Dress"]["return_rate"], 42.9)
        self.assertEqual(p["Maxi Dress"]["money_lost"], 3135.0)
        self.assertEqual(p["Tote Bag"]["return_rate"], 33.3)

    def test_variant_size_colour_vendor(self):
        v = {x["variant"]: x["return_rate"] for x in self.d["by_variant"]}
        self.assertEqual(v, {"LS-M-W": 50.0, "LS-L-W": 33.3, "MD-S-R": 50.0, "MD-M-R": 33.3, "TB": 33.3})
        self.assertEqual({x["size"]: x["return_rate"] for x in self.d["by_size"]}, {"S": 50.0, "M": 44.4, "L": 33.3})
        self.assertEqual({x["colour"]: x["return_rate"] for x in self.d["by_colour"]}, {"White": 44.4, "Rose": 42.9})
        self.assertEqual({x["vendor"]: x["return_rate"] for x in self.d["by_vendor"]}, {"Supplier A": 41.7, "Supplier B": 42.9})

    def test_top_fixes(self):
        f = self.d["top_fixes"]
        self.assertEqual([x["product"] for x in f], ["Maxi Dress", "Linen Shirt"])  # Tote Bag: 1 return < min 2
        self.assertEqual(f[0]["top_reason"], "quality_defect")
        self.assertEqual(f[0]["top_reason_share"], 66.7)
        self.assertTrue(f[0]["fix"].startswith("Defects: raise with the supplier"))
        self.assertEqual(f[1]["top_reason"], "size_too_small")
        self.assertTrue(f[1]["fix"].startswith("Runs small: shift the size chart one size"))
        self.assertEqual([(s["size"], s["return_rate"]) for s in f[1]["by_size"]], [("M", 50.0), ("L", 33.3)])

    def test_reasons(self):
        r = self.d["reasons"]
        self.assertEqual([(x["category"], x["units"], x["share"]) for x in r[:2]],
                         [("size_too_small", 3, 37.5), ("quality_defect", 2, 25.0)])
        self.assertEqual((r[0]["refund_units"], r[0]["exchange_units"]), (2, 1))
        self.assertEqual(r[1]["money_lost"], 2280.0)

    def test_refused_separate(self):
        self.assertEqual(self.d["refused_at_door"], {"units": 1.0, "by_product": [{"product": "Maxi Dress", "units": 1.0, "orders": 1}]})

    def test_trend(self):
        t = {x["month"]: x for x in self.d["trend"]}
        self.assertEqual((t["2026-08"]["sold_units"], t["2026-08"]["returned_units"], t["2026-08"]["return_rate"]), (2, 1, 50.0))
        self.assertEqual(t["2026-09"]["return_rate"], 42.1)
        self.assertTrue(t["2026-09"]["mature"])
        self.assertFalse(t["2026-10"]["mature"])

    def test_notes(self):
        n = " ".join(self.d["notes"])
        self.assertIn("1 return rows had no order date", n)
        self.assertIn("outside the window", n)
        self.assertIn("1 returned units with no unit cost", n)

    def test_csv_written(self):
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "csv", "top_fixes.csv")))

    def test_default_window_and_min_sample(self):
        self.assertEqual(ar.split_variant("M / Black", ar.DEFAULTS), ("M", "Black"))
        self.assertEqual(ar.split_variant("Rose / 38", ar.DEFAULTS), ("38", "Rose"))
        c = os.path.join(self.tmp.name, "c.csv")
        d = run("analyze_returns.py", "--returns", c, "--orders", os.path.join(FIX, "orders.csv"),
                "--as-of", "2026-10-29")
        covered = d["window"].pop("covered")
        self.assertEqual(d["window"], {"start": "2026-07-11", "end": "2026-10-08", "as_of": "2026-10-29", "mature_until": "2026-10-08"})
        self.assertLess(covered["days"], covered["window_days"])   # the fixture covers part of the 90 days
        self.assertEqual(d["top_fixes"], [])                 # default min_units_sold 20 is not met
        self.assertTrue(all(p["low_sample"] for p in d["by_product"]))


class TestRender(unittest.TestCase):
    def test_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, a = os.path.join(tmp, "c.csv"), os.path.join(tmp, "a.json")
            run("classify_reasons.py", "--returns", os.path.join(FIX, "returns_app.csv"), "--out", c)
            d = run("analyze_returns.py", "--returns", c, "--orders", os.path.join(FIX, "orders.csv"),
                    "--setup", os.path.join(FIX, "setup.json"), "--as-of", "2026-10-29",
                    "--start", "2026-09-01", "--end", "2026-09-30")
            with open(a, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            for fmt, name in (("report", "r.md"), ("dashboard", "r.html")):
                run("render_returns.py", "--analysis", a, "--format", fmt, "--out", os.path.join(tmp, name))
            with open(os.path.join(tmp, "r.md"), encoding="utf-8") as fh:
                md = fh.read()
            self.assertTrue(md.splitlines()[2] == "## Fix these first")
            self.assertIn("Made with the free ReplAi skills pack", md)
            self.assertNotRegex(md, "[\u2013\u2014]")
            with open(os.path.join(tmp, "r.html"), encoding="utf-8") as fh:
                self.assertIn('id="cut"', fh.read())


class TestExtract(unittest.TestCase):
    def test_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.csv")
            s = run("extract_from_orders.py", "--orders", os.path.join(FIX, "orders.csv"), "--out", out)
            self.assertEqual(s["orders"], {"refund": 4, "exchange": 1, "refused": 1, "refused_cancelled_after_fulfilment": 0,
                                           "not_identified": 4, "estimated_units": 1})
            r = rows(out)
            self.assertEqual(len(r), 7)
            self.assertEqual([x["order"] for x in r if x["product"] == "(not identified)"], ["#2001", "#2002", "#2003", "#2004"])
            refused = [x for x in r if x["type"] == "refused"]
            self.assertEqual([x["sku"] for x in refused], ["LS-M-W", "MD-M-R"])
            last = r[-1]
            self.assertEqual((last["order"], last["quantity"], last["refund_amount"], last["reason_text"]), ("#2007", "1", "500.0", "too small"))
            self.assertEqual(r[1]["reason_text"], "")        # the "exchange" tag is not a reason


QA_ORDERS = """Name,Financial Status,Created at,Cancelled at,Subtotal,Refunded Amount,Lineitem quantity,Lineitem name,Lineitem price,Lineitem sku,Lineitem discount,Vendor,Tags,Notes
#1,paid,2026-08-06 10:00:00 +0300,,5000,0,10,Tee - M / Black,500,T-M-B,0,V1,,
#2,paid,2026-08-07 10:00:00 +0300,,5000,0,10,Tee - L / Black,500,T-L-B,0,V1,,
#3,paid,2026-08-08 10:00:00 +0300,,500,0,1,Tee - S / Black,500,T-S-B,0,V1,returned to origin,
#4,partially_refunded,2026-08-09 10:00:00 +0300,,500,50,1,Tee - S / Black,500,T-S-B,0,V1,,shipping fee refund
"""


class TestQaRegressions(unittest.TestCase):
    """Bugs found in adversarial QA (Oct 29 2026)."""

    @classmethod
    def setUpClass(cls):
        cls.lex = cr.load_lexicon(None)

    def test_bigger_size_means_too_small(self):
        cat = lambda t: cr.match_text(t, self.lex)[0]  # noqa: E731
        self.assertEqual(cat("exchange for a bigger size please"), "size_too_small")
        self.assertEqual(cat("want a smaller size"), "size_too_large")
        self.assertEqual(cat("\u0639\u0627\u064a\u0632 \u0645\u0642\u0627\u0633 \u0623\u0643\u0628\u0631"), "size_too_small")  # 3ayez ma2as akbar
        self.assertEqual(cat("3ayez ma2as akbar"), "size_too_small")
        self.assertEqual(cat("\u0645\u0642\u0627\u0633\u064a \u063a\u0644\u0637"), "fit_other")  # my size is wrong
        self.assertEqual(cat("\u0648\u0635\u0644\u0646\u064a \u0645\u0642\u0627\u0633 \u063a\u0644\u0637"), "wrong_item")  # received wrong size
        self.assertNotEqual(cat("I didn't receive the right size"), "refused_at_door")

    def test_courier_type_return_to_origin_is_refused(self):
        self.assertEqual(cr.detect_type("Return to origin", "", self.lex), "refused")
        self.assertEqual(cr.detect_type("\u0645\u0631\u0641\u0648\u0636", "", self.lex), "refused")

    def test_refused_units_leave_sold_and_small_refund_is_money_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            o = os.path.join(tmp, "o.csv")
            with open(o, "w", encoding="utf-8") as fh:
                fh.write(QA_ORDERS)
            app = os.path.join(tmp, "app.csv")
            with open(app, "w", encoding="utf-8") as fh:
                fh.write("Return ID,Order,Product,Variant,Quantity,Type,Reason\nR1,#1,Tee,M / Black,3,Refund,too small\n")
            ex = os.path.join(tmp, "ex.csv")
            run("extract_from_orders.py", "--orders", o, "--out", ex)
            ex_rows = rows(ex)
            small = next(r for r in ex_rows if r["order"] == "#4")
            self.assertEqual((small["product"], small["quantity"], small["refund_amount"]), ("(not identified)", "", "50.0"))
            # Combine: app row (no SKU) + export rows.
            comb = os.path.join(tmp, "comb.csv")
            with open(comb, "w", encoding="utf-8") as fh:
                fh.write("return_id,order,product,variant,quantity,type,reason\nR1,#1,Tee,M / Black,3,refund,too small\n")
                fh.write("R2,#3,Tee,S / Black,1,refused,\n")
            cl = os.path.join(tmp, "cl.csv")
            run("classify_reasons.py", "--returns", comb, "--out", cl)
            d = run("analyze_returns.py", "--returns", cl, "--orders", o, "--as-of", "2026-10-29")
        # Sold 10 + 10 + 1 + 1 = 22, minus 1 refused unit (#3 never delivered) = 21.
        self.assertEqual(d["totals"]["sold_units"], 21.0)
        self.assertEqual(d["totals"]["returned_units"], 3.0)
        # The SKU-less app row joins the variant it sold under.
        v = next(x for x in d["by_variant"] if x["variant"] == "T-M-B")
        self.assertEqual((v["sold_units"], v["returned_units"], v["return_rate"]), (10.0, 3.0, 30.0))
        self.assertFalse(any(x["variant"] == "Tee - M / Black" for x in d["by_variant"]))
        self.assertTrue(any("taken out of units sold" in n for n in d["notes"]))

    def test_dashboard_shipping_blank_when_unknown(self):
        d = {"currency": "EGP", "window": {"start": "a", "end": "b"}, "top_fixes": [], "reasons": [],
             "totals": {"return_rate": None, "returned_units": 1}, "exchanges_vs_refunds": {"exchange_share": None},
             "refused_at_door": {"units": 0}, "by_size": [], "by_colour": [], "by_vendor": [], "trend": [], "notes": [],
             "money_breakdown": {"refunded": 10, "return_shipping": 0, "exchange_reship": 0, "restock_loss": 0,
                                 "handling": 0, "return_shipments": 1}}
        import render_returns
        self.assertIn('id="ship" type="number" inputmode="decimal" value=""', render_returns.dashboard(d))


NODE = shutil.which("node")


class TestFixPassOct29(unittest.TestCase):
    """Fix pass decided by the lead (Oct 29 2026)."""

    @classmethod
    def setUpClass(cls):
        cls.lex = cr.load_lexicon(None)

    def cat(self, text):
        return cr.match_text(text, self.lex)[0]

    def test_negated_size_keywords_do_not_count(self):
        self.assertIsNone(self.cat("not small enough"))
        self.assertIsNone(self.cat("\u0645\u0634 \u0635\u063a\u064a\u0631"))         # mesh soghayar in Arabic
        self.assertIsNone(self.cat("mesh soghayar"))
        self.assertIsNone(self.cat("isn't small at all"))
        self.assertIsNone(self.cat("\u0645\u0648 \u0636\u064a\u0642"))                # Gulf: not tight
        self.assertIsNone(self.cat("ma soghayar"))
        self.assertEqual(self.cat("not too small, too big"), "size_too_large")
        # Still matched without a negator, and other categories keep their own "not" phrases.
        self.assertEqual(self.cat("it is small"), "size_too_small")
        self.assertEqual(self.cat("does not fit"), "fit_other")
        self.assertEqual(self.cat("not as pictured"), "not_as_pictured")

    def test_tied_size_directions_are_inconsistent_sizing(self):
        self.assertEqual(ar.top_of({"size_too_small": 2, "size_too_large": 2, "quality_defect": 1}),
                         "size_inconsistent")
        self.assertEqual(ar.top_of({"size_too_small": 3, "size_too_large": 2}), "size_too_small")
        self.assertEqual(ar.top_of({"size_too_large": 2, "quality_defect": 2}), "quality_defect")  # alphabetical
        with tempfile.TemporaryDirectory() as tmp:
            c = os.path.join(tmp, "c.csv")
            with open(c, "w", encoding="utf-8") as fh:
                fh.write("row,order,order_date,product,variant,quantity,type,category,refund_amount\n"
                         "1,#1,2026-09-02,Jeans,32,1,refund,size_too_small,500\n"
                         "2,#2,2026-09-03,Jeans,32,1,refund,size_too_large,500\n"
                         "3,#3,2026-09-04,Jeans,34,1,refund,size_too_large,500\n"
                         "4,#4,2026-09-05,Jeans,34,1,refund,size_too_small,500\n")
            d = run("analyze_returns.py", "--returns", c, "--as-of", "2026-10-29",
                    "--start", "2026-09-01", "--end", "2026-09-30")
        fix = d["top_fixes"][0]
        self.assertEqual((fix["top_reason"], fix["top_reason_label"]),
                         ("size_inconsistent", "Inconsistent sizing between batches"))
        self.assertEqual(fix["top_reason_share"], 100.0)
        self.assertIn("batches", fix["fix"])

    @unittest.skipUnless(NODE, "node not installed")
    def test_dashboard_product_saving_follows_shipping_input(self):
        import render_returns
        d = {"currency": "EGP", "window": {"start": "a", "end": "b"}, "reasons": [],
             "totals": {"return_rate": None, "returned_units": 4}, "exchanges_vs_refunds": {"exchange_share": None},
             "refused_at_door": {"units": 0}, "by_size": [], "by_colour": [], "by_vendor": [], "trend": [], "notes": [],
             "money_breakdown": {"refunded": 1000, "return_shipping": 160, "exchange_reship": 0, "restock_loss": 0,
                                 "handling": 0, "return_shipments": 4},
             "top_fixes": [{"product": "Jeans", "sold_units": None, "returned_units": 3, "return_rate": None,
                            "money_lost": 870, "top_reason_label": "Size too small", "top_reason_share": 100,
                            "fix": "x", "by_size": [], "return_shipping": 120, "return_shipments": 3}]}
        page = render_returns.dashboard(d)
        m = re.search(r'data-lost="([^"]+)" data-ship="([^"]+)" data-shipments="([^"]+)"', page)
        self.assertIsNotNone(m)
        default = re.search(r'id="ship" type="number" inputmode="decimal" value="([^"]*)"', page).group(1)

        def saving(ship_value):
            stub = ("const E={data:{textContent:%s},ship:{value:%s,defaultValue:%s},cut:{value:'30'},lost:{},saved:{}};"
                    "const S={dataset:{lost:%s,ship:%s,shipments:%s}};"
                    "const document={getElementById:id=>E[id],querySelectorAll:q=>q==='input'?[]:[S]};\n"
                    % (json.dumps(json.dumps(d)), json.dumps(ship_value), json.dumps(default),
                       json.dumps(m.group(1)), json.dumps(m.group(2)), json.dumps(m.group(3))))
            with tempfile.TemporaryDirectory() as tmp:
                js = os.path.join(tmp, "r.js")
                with open(js, "w", encoding="utf-8") as fh:
                    fh.write(stub + render_returns.JS + "\nconsole.log(JSON.stringify([S.textContent,E.lost.textContent]));")
                return json.loads(subprocess.run([NODE, js], capture_output=True, text=True, check=True).stdout)

        self.assertEqual(default, "40.0")
        # Default input: the data's numbers. 870 x 30% = 261.
        self.assertEqual(saving("40.0"), ["Estimated saving: 261 EGP", "1,160 EGP"])
        # Shipping 100 per return: Jeans 870 - 120 + 100 x 3 = 1050, x 30% = 315. Store 1000 + 400 = 1400.
        self.assertEqual(saving("100"), ["Estimated saving: 315 EGP", "1,400 EGP"])



# Synthetic COD store that records failed deliveries as "cancelled after fulfilment" and keeps returns
# as Shopify return records (so no refunds and no return tags in the export). Newer "Canceled at" header.
COD_STORE = """Name,Financial Status,Fulfillment Status,Created at,Canceled at,Subtotal,Refunded Amount,Lineitem quantity,Lineitem name,Lineitem price,Lineitem sku,Vendor,Tags,Notes
#1,paid,fulfilled,2026-09-02 10:00:00 +0300,,500,0,1,Slipper - 36/37 / Red,500,SL-36-R,V1,,
#2,voided,fulfilled,2026-09-03 10:00:00 +0300,2026-09-06 10:00:00 +0300,900,0,1,Slipper - 38/39 / red,500,SL-38-R,V1,,
#2,,,,,,,1,Slipper - 36/37 / RED,400,SL-36-R,V1,,
#3,voided,unfulfilled,2026-09-04 10:00:00 +0300,2026-09-04 12:00:00 +0300,500,0,1,Slipper - 36/37 / Gold,500,SL-36-G,V1,,
#4,pending,fulfilled,2026-09-05 10:00:00 +0300,,500,0,1,Slipper - 38/39 / Gold,500,SL-38-G,V1,,
"""


class TestRealExportFindingsOct2026(unittest.TestCase):
    """Findings from a run on real Shopify exports (Oct 2026), reproduced on synthetic data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orders = os.path.join(self.tmp.name, "orders.csv")
        with open(self.orders, "w", encoding="utf-8") as fh:
            fh.write(COD_STORE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refused_at_door_from_cancelled_after_fulfilment(self):
        # Finding 9: only tags were used, so a refused parcel recorded as a cancellation was missed.
        out = os.path.join(self.tmp.name, "r.csv")
        s = run("extract_from_orders.py", "--orders", self.orders, "--out", out)
        self.assertEqual(s["orders"]["refused"], 1)                         # #2; #3 never shipped
        self.assertEqual(s["orders"]["refused_cancelled_after_fulfilment"], 1)
        r = rows(out)
        self.assertEqual([(x["order"], x["type"], x["refund_amount"]) for x in r],
                         [("#2", "refused", "0.0"), ("#2", "refused", "0.0")])   # no money moved
        self.assertIn("Shopify return records", s["no_returns_found"])
        # Classify and analyse: refused is reported on its own and never as a return.
        c = os.path.join(self.tmp.name, "c.csv")
        run("classify_reasons.py", "--returns", out, "--out", c)
        d = run("analyze_returns.py", "--returns", c, "--orders", self.orders, "--as-of", "2026-10-29",
                "--start", "2026-09-01", "--end", "2026-09-30")
        self.assertEqual(d["totals"]["returned_units"], 0)
        self.assertEqual(d["refused_at_door"]["units"], 2)
        self.assertTrue(any("only orders refused at the door" in n for n in d["notes"]))

    def test_setup_can_turn_off_cancelled_after_fulfilment(self):
        st = os.path.join(self.tmp.name, "s.json")
        with open(st, "w", encoding="utf-8") as fh:
            json.dump({"count_cancelled_after_fulfillment_as_failed": False}, fh)
        s = run("extract_from_orders.py", "--orders", self.orders, "--out", os.path.join(self.tmp.name, "r.csv"),
                "--setup", st)
        self.assertEqual((s["rows"], s["orders"]["refused"]), (0, 0))

    def test_empty_returns_file_explains_instead_of_stopping(self):
        empty = os.path.join(self.tmp.name, "empty.csv")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write("order,product,quantity,type,reason_text\n")
        res = run("classify_reasons.py", "--returns", empty, "--out", os.path.join(self.tmp.name, "c.csv"))
        self.assertEqual(res["rows"], 0)
        self.assertIn("connector", res["no_returns_found"])
        self.assertNotIn("error", res)

    def test_wrong_colour_sent_is_wrong_item(self):
        # Finding 10.
        lex = cr.load_lexicon(None)
        cat = lambda t: cr.match_text(t, lex)[0]  # noqa: E731
        self.assertEqual(cat("تم إرسال لون مختلف عن اللون المطلوب"), "wrong_item")
        self.assertEqual(cat("received red instead of gold"), "wrong_item")
        self.assertEqual(cat("Different colour sent"), "wrong_item")
        self.assertEqual(cat("different color than ordered"), "wrong_item")
        self.assertEqual(cat("وصلني الاحمر بدل الدهبي"), "wrong_item")
        self.assertEqual(cat("ده مش اللي طلبته"), "wrong_item")
        self.assertEqual(cat("el lon tany"), "wrong_item")
        self.assertEqual(cat("تم استلام اللون الأحمر بدلًا من اللون الذهبي المطلوب"), "wrong_item")
        # Still not as pictured, and "بدل" inside other words does not count.
        self.assertEqual(cat("اللون مختلف عن الصورة"), "not_as_pictured")
        self.assertEqual(cat("colour looks different from the photo"), "not_as_pictured")
        self.assertNotEqual(cat("عايزة استبدل اللون"), "wrong_item")
        self.assertEqual(cat("البدلة ضيقة"), "size_too_small")

    def test_window_reports_covered_range(self):
        # Finding 11: a 90 day window over an orders file that covers far fewer days.
        c = os.path.join(self.tmp.name, "c.csv")
        with open(c, "w", encoding="utf-8") as fh:
            fh.write("row,order,order_date,product,variant,quantity,type,category,refund_amount\n"
                     "1,#1,2026-09-02,Slipper,36/37 / Red,1,refund,size_too_small,500\n")
        d = run("analyze_returns.py", "--returns", c, "--orders", self.orders, "--as-of", "2026-10-29")
        self.assertEqual(d["window"]["covered"], {"start": "2026-09-02", "end": "2026-09-05", "days": 4, "window_days": 90})
        self.assertTrue(any("covers only 4 of the 90 days" in n for n in d["notes"]))
        import render_returns
        self.assertIn("2026-09-02 to 2026-09-05, 4 of the 90 days", render_returns.report(d).splitlines()[0])

    def test_split_variant_keeps_slash_sizes_and_merges_colour_case(self):
        # Finding 12.
        self.assertEqual(ar.split_variant("36/37 / Red", ar.DEFAULTS), ("36/37", "Red"))
        self.assertEqual(ar.split_variant("38/39 / red", ar.DEFAULTS), ("38/39", "Red"))
        self.assertEqual(ar.split_variant("36/37", ar.DEFAULTS), ("36/37", ""))
        self.assertEqual(ar.split_variant("M / navy blue", ar.DEFAULTS), ("M", "Navy Blue"))
        self.assertEqual(ar.split_variant("black / s", ar.DEFAULTS), ("S", "Black"))
        c = os.path.join(self.tmp.name, "c.csv")
        with open(c, "w", encoding="utf-8") as fh:
            fh.write("row,order,order_date,product,variant,quantity,type,category,refund_amount\n"
                     "1,#1,2026-09-02,Slipper,36/37 / Red,1,refund,size_too_small,500\n")
        d = run("analyze_returns.py", "--returns", c, "--orders", self.orders, "--as-of", "2026-10-29",
                "--start", "2026-09-01", "--end", "2026-09-30")
        self.assertEqual(sorted(x["colour"] for x in d["by_colour"]), ["Gold", "Red"])
        self.assertEqual(sorted(x["size"] for x in d["by_size"]), ["36/37", "38/39"])


if __name__ == "__main__":
    unittest.main()
