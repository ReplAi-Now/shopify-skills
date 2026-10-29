import csv, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "skills", "store", "shopify-catalog-upload", "scripts", "sheet.py")


def run(*args):
    return json.loads(subprocess.check_output([sys.executable, SCRIPT, *args]))


class Sheet(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        d = os.path.join(self.root, "linen-dress")
        os.makedirs(d)
        for f in ["black-back.png", "black-front.png", "black-beige-front.png", "light-grey-front.png",
                  "light-grey-back.png", "IMG_9.png", ".hidden.png"]:
            open(os.path.join(d, f), "wb").write(b"x")

    def test_scan_order_and_colours(self):
        p = run("scan", self.root)["products"][0]
        self.assertEqual(p["colours"], ["black", "black-beige", "light-grey"])
        self.assertEqual(p["colour_titles"], ["Black", "Black/Beige", "Light Grey"])
        self.assertEqual([x["file"] for x in p["photos"]][:5],
                         ["black-front.png", "black-back.png", "black-beige-front.png",
                          "light-grey-front.png", "light-grey-back.png"])
        self.assertEqual(p["unnamed"], ["IMG_9.png"])

    def test_import_csv(self):
        data = os.path.join(self.root, "data.csv")
        with open(data, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["subfolder", "colour", "sizes", "price", "compare_at_price", "stock_per_size", "cost_per_item", "notes"])
            w.writerow(["linen-dress", "black", "S, M, L", "1450", "", "5", "600", ""])
            w.writerow(["linen-dress", "light-grey", "S-M", "1450", "1800", "", "", ""])
        plan = os.path.join(self.root, "plan.json")
        json.dump({"products": [{"subfolder": "linen-dress", "title": "Linen Midi Dress", "body_html": "<p>x</p>",
                                 "type": "Dresses", "tags": "dress", "vendor": "Shop", "sku_base": "ABC-101"}],
                   "taxable": False, "continue_selling": True,
                   "image_urls": {"linen-dress/black-front.png": "https://x/bf.png",
                                  "linen-dress/light-grey-front.png": "https://x/gf.png"}}, open(plan, "w"))
        out = os.path.join(self.root, "import.csv")
        res = run("import-csv", self.root, data, plan, out)
        self.assertEqual(res["problems"], [])
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["Variant SKU"] for r in rows], ["ABC-101-1", "ABC-101-2", "ABC-101-3", "ABC-101-4", "ABC-101-5"])
        self.assertEqual([r["Option2 Value"] for r in rows], ["S", "M", "L", "S", "M"])
        self.assertEqual(rows[0]["Title"], "Linen Midi Dress")
        self.assertEqual(rows[1]["Title"], "")
        self.assertEqual(rows[0]["Variant Inventory Qty"], "5")
        self.assertEqual(rows[3]["Variant Inventory Qty"], "0")
        self.assertEqual(rows[3]["Option1 Value"], "Light Grey")
        self.assertEqual(rows[3]["Variant Image"], "https://x/gf.png")
        self.assertEqual(rows[0]["Variant Taxable"], "FALSE")
        self.assertEqual(rows[0]["Variant Inventory Policy"], "continue")
        self.assertEqual(rows[0]["Image Src"], "https://x/bf.png")
        self.assertEqual(rows[1]["Image Src"], "https://x/gf.png")

    def test_import_csv_sizes_stock_handles(self):
        for sub in ["pyjamas", "abaya", "linen-2"]:
            os.makedirs(os.path.join(self.root, sub))
        open(os.path.join(self.root, "linen-2", "olive-green-front.png"), "wb").write(b"x")
        data = os.path.join(self.root, "data.csv")
        with open(data, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["subfolder", "colour", "sizes", "price", "compare_at_price", "stock_per_size", "cost_per_item", "notes"])
            w.writerow(["pyjamas", "navy", "2-3Y, 4-5Y", "450", "", "3,5", "", ""])
            w.writerow(["abaya", "black", "38-40", "1,450 EGP", "", "S:2 M:4", "", ""])
            w.writerow(["linen-dress", "Light Grey", "S M L", "900", "", "S:1, M:2, L:3", "", ""])
            w.writerow(["linen-2", "olive-green", "One size", "900", "", "", "", ""])
        plan = os.path.join(self.root, "plan.json")
        json.dump({"products": [
            {"subfolder": "pyjamas", "title": "\u0628\u064a\u062c\u0627\u0645\u0629", "sku_base": "A-1"},
            {"subfolder": "abaya", "title": "\u0639\u0628\u0627\u064a\u0629", "sku_base": "A-2"},
            {"subfolder": "linen-dress", "title": "Linen Dress", "sku_base": "A-3"},
            {"subfolder": "linen-2", "title": "Linen Dress", "sku_base": "A-4"}],
            "image_urls": {"linen-dress/light-grey-front.png": "https://x/gf.png"}}, open(plan, "w"))
        out = os.path.join(self.root, "import.csv")
        res = run("import-csv", self.root, data, plan, out)
        self.assertEqual(res["problems"], ["abaya Black: no stock for size 38-40; stock left at 0"])
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        by = [(r["Handle"], r["Option1 Value"], r["Option2 Value"], r["Variant Inventory Qty"], r["Variant Price"]) for r in rows]
        self.assertEqual(by[:3], [("pyjamas", "Navy", "2-3Y", "3", "450"), ("pyjamas", "Navy", "4-5Y", "5", "450"),
                                  ("abaya", "Black", "38-40", "0", "1450")])
        self.assertEqual(by[3:6], [("linen-dress", "Light Grey", "S", "1", "900"),
                                   ("linen-dress", "Light Grey", "M", "2", "900"),
                                   ("linen-dress", "Light Grey", "L", "3", "900")])
        self.assertEqual(by[6], ("linen-dress-2", "Olive Green", "One Size", "0", "900"))
        self.assertEqual(rows[3]["Variant Image"], "https://x/gf.png")   # sheet says "Light Grey", file light-grey

    def test_three_quarter_view_parsed(self):
        open(os.path.join(self.root, "linen-dress", "black-three-quarter.png"), "wb").write(b"x")
        p = run("scan", self.root)["products"][0]
        self.assertEqual(p["unnamed"], ["IMG_9.png"])


if __name__ == "__main__":
    unittest.main()
