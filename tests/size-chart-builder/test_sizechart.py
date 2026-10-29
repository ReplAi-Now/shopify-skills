"""Tests for skills/store/size-chart-builder/scripts/sizechart.py. Expected values worked out by hand."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "store", "size-chart-builder", "scripts"))
import sizechart as sc  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ASSETS = os.path.join(ROOT, "skills", "store", "size-chart-builder", "assets")


def run(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        sc.main(list(args))
    return json.loads(buf.getvalue())


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Rounding(unittest.TestCase):
    def test_round_half(self):
        self.assertEqual(sc.round_half(35.25), 35.5)
        self.assertEqual(sc.round_half(35.24), 35.0)
        self.assertEqual(sc.round_half(0.75), 1.0)
        self.assertEqual(sc.round_half(36.22), 36.0)


class Validate(unittest.TestCase):
    def test_bad_chart(self):
        r = run("validate", os.path.join(FX, "bad_chart.csv"))
        # 1 error: waist 76 -> 74 (S to M). 3 warnings: L missing, XXL waist blank,
        # chest step 12 vs typical 4 (limit max(1, 0.5*4)=2). 2 info: sleeve unchanged S-M and XL-XXL.
        self.assertEqual(r["counts"], {"error": 1, "warning": 3, "info": 2})
        types = sorted((i["type"], i.get("column", "")) for i in r["issues"])
        self.assertEqual(types, [("blank_value", "waist_cm"), ("decreasing", "waist_cm"),
                                 ("no_change", "sleeve_cm"), ("no_change", "sleeve_cm"),
                                 ("size_gap", ""), ("uneven_step", "chest_cm")])
        gap = next(i for i in r["issues"] if i["type"] == "size_gap")
        self.assertEqual(gap["missing"], ["L"])
        step = next(i for i in r["issues"] if i["type"] == "uneven_step")
        self.assertEqual((step["between"], step["step"], step["typical_step"]), (["XL", "XXL"], 12, 4))
        self.assertFalse(r["ok"])

    def test_numeric_gap(self):
        r = run("validate", os.path.join(FX, "numeric_gap.csv"))
        gaps = [i for i in r["issues"] if i["type"] == "size_gap"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["missing"], ["40"])
        self.assertEqual(r["counts"]["error"], 0)

    def test_base_tables_clean(self):
        for f in sorted(os.listdir(ASSETS)):
            if f.startswith("base-typical-"):
                r = run("validate", os.path.join(ASSETS, f))
                self.assertEqual(r["counts"]["error"] + r["counts"]["warning"], 0, f)

    def test_order_error(self):
        issues = sc.check_labels(["M", "S"])
        self.assertEqual(issues[0]["type"], "size_order")
        self.assertEqual(sc.check_labels(["S", "S"])[0]["type"], "duplicate_size")


class Convert(unittest.TestCase):
    def test_cm_to_in(self):
        r = run("convert", os.path.join(FX, "bad_chart.csv"), "--to", "in")
        # 92/2.54=36.22 -> 36; 96/2.54=37.80 -> 38; 100/2.54=39.37 -> 39.5; 112/2.54=44.09 -> 44
        self.assertEqual([x["chest_in"] for x in r["rows"]], ["36", "38", "39.5", "44"])
        self.assertEqual(r["rows"][3]["waist_in"], "")  # blank stays blank

    def test_in_to_cm(self):
        out = os.path.join(tempfile.mkdtemp(), "cm.csv")
        r = run("convert", os.path.join(FX, "inches.csv"), "--to", "cm", "--out", out)
        # 36*2.54=91.44 -> 91.5; 38.5*2.54=97.79 -> 98
        self.assertEqual([x["chest_cm"] for x in r["rows"]], ["91.5", "98"])
        self.assertTrue(read(out).startswith("size,chest_cm"))


class Body(unittest.TestCase):
    def test_tops_regular(self):
        r = run("body", os.path.join(FX, "flat_tops.csv"), "--category", "tops", "--fit", "regular")
        s, m = r["rows"]
        # flat 50 -> garment 100; regular chest ease 8-12 -> body 88-92
        self.assertEqual((s["garment_chest_cm"], s["body_chest_min_cm"], s["body_chest_max_cm"]), ("100", "88", "92"))
        self.assertEqual((m["garment_chest_cm"], m["body_chest_min_cm"], m["body_chest_max_cm"]), ("106", "94", "98"))
        self.assertEqual(s["garment_length_cm"], "70")  # lengths are not doubled

    def test_bottoms_fitted(self):
        r = run("body", os.path.join(FX, "flat_bottoms.csv"), "--category", "bottoms", "--fit", "fitted")
        row = r["rows"][0]
        # waist flat 38 -> 76, fitted waist ease 0-2 -> 74-76; hip flat 50 -> 100, ease 2-4 -> 96-98
        self.assertEqual((row["body_waist_min_cm"], row["body_waist_max_cm"]), ("74", "76"))
        self.assertEqual((row["body_hip_min_cm"], row["body_hip_max_cm"]), ("96", "98"))
        self.assertEqual(row["garment_inseam_cm"], "78")

    def test_full_circumference(self):
        r = run("body", os.path.join(FX, "flat_tops.csv"), "--category", "tops", "--fit", "fitted", "--measured", "full")
        # garment 50 (not doubled), fitted 4-6 -> 44-46
        self.assertEqual(r["rows"][0]["body_chest_min_cm"], "44")


class Render(unittest.TestCase):
    def test_both_languages(self):
        out = os.path.join(tempfile.mkdtemp(), "s.html")
        r = run("render", os.path.join(FX, "good_chart.csv"), "--out", out, "--lang", "both",
                "--fit-note", "runs-small", "--arabic-digits", "eastern")
        h = read(out)
        self.assertIn('dir="rtl" lang="ar"', h)
        self.assertIn('dir="ltr" lang="en"', h)
        self.assertIn("overflow-x:auto", h)          # scroll inside the table wrapper only
        self.assertIn("position:sticky;right:0", h)  # RTL sticks the size column on the right
        self.assertIn("position:sticky;left:0", h)
        self.assertIn("جدول المقاسات", h)
        self.assertIn("الصدر (سم)", h)
        self.assertIn("٨٦", h)                       # eastern digits in the Arabic table
        self.assertIn("runs small", h)
        self.assertIn("<details", h)                 # inches table behind a no-JS toggle
        self.assertNotIn("<script", h)
        self.assertEqual(r["languages"], ["en", "ar"])
        self.assertTrue(any("mystery" in w for w in r["warnings"]))
        self.assertEqual(r["table"]["columns"], ["Size", "Bust (cm)", "Waist (cm)", "Length (cm)", "Mystery (cm)"])

    def test_inches_only_converts(self):
        out = os.path.join(tempfile.mkdtemp(), "s.html")
        run("render", os.path.join(FX, "good_chart.csv"), "--out", out, "--units", "in")
        h = read(out)
        # 86/2.54=33.86 -> 34; 90/2.54=35.43 -> 35.5
        self.assertIn(">34<", h)
        self.assertIn(">35.5<", h)
        self.assertIn("Bust (in)", h)
        self.assertNotIn("<details", h)

    def test_escapes_html(self):
        out = os.path.join(tempfile.mkdtemp(), "s.html")
        run("render", os.path.join(FX, "good_chart.csv"), "--out", out, "--title", "<b>x</b>")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", read(out))


def tmp_csv(text):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class QARegressions(unittest.TestCase):
    """Defects found in adversarial QA, Oct 29 2026."""

    def test_garment_render_doubles_flat_widths(self):
        # Flat chest 40 must show as 80 around (the note says "laid flat and doubled"); length stays 66.
        p = tmp_csv("size,chest_cm,length_cm\nS,40,66\nM,42,68\n")
        out = p + ".html"
        r = run("render", p, "--out", out, "--basis", "garment", "--units", "cm")
        html_s = read(out)
        self.assertTrue(r["widths_doubled"])
        self.assertIn(">80</td>", html_s)
        self.assertIn(">66</td>", html_s)
        self.assertNotIn(">40</td>", html_s)
        run("render", p, "--out", out, "--basis", "garment", "--units", "cm", "--measured", "full")
        full = read(out)
        self.assertIn(">40</td>", full)
        self.assertIn("all the way around", full)
        run("render", p, "--out", out, "--basis", "body", "--units", "cm")
        self.assertIn(">40</td>", read(out))

    def test_light_cells_set_dark_text(self):
        # Dark Shopify themes set white text; header and size cells have light backgrounds.
        p = tmp_csv("size,chest_cm\nS,90\nM,94\n")
        run("render", p, "--out", p + ".html")
        s = read(p + ".html")
        self.assertEqual(s.count("background:#f4f4f4;color:#111"), s.count("background:#f4f4f4"))
        self.assertEqual(s.count("background:#fafafa;color:#111"), s.count("background:#fafafa"))

    def test_body_blank_first_row_keeps_columns(self):
        p = tmp_csv("size,chest_cm,length_cm\nS,,66\nM,48,68\nL,50,70\n")
        out = p + ".body.csv"
        run("body", p, "--category", "tops", "--fit", "regular", "--out", out)
        lines = read(out).splitlines()
        self.assertEqual(lines[0], "size,garment_chest_cm,garment_length_cm,body_chest_min_cm,body_chest_max_cm")
        # M: 48 flat -> 96 around, regular ease 8-12 -> body 84-88.
        self.assertEqual(lines[2], "M,96,68,84,88")
        self.assertEqual(lines[1], "S,,66,,")

    def test_bracket_unit_headers_and_no_measurements(self):
        r = run("validate", tmp_csv("Size,Chest (cm),Waist (in)\nS,92,30\nM,96,32\n"))
        self.assertEqual(r["measurements"], ["chest_(cm)", "waist_(in)"])
        self.assertEqual(r["counts"]["error"], 0)
        r = run("validate", tmp_csv("size,chest,margin\nS,92,1\nM,96,1\n"))
        self.assertIn("no_measurements", [i["type"] for i in r["issues"]])
        self.assertFalse(r["ok"])

    def test_fractions_and_arabic_decimal(self):
        self.assertEqual(sc.parse_value("36 1/2"), (36.5, None))
        self.assertEqual(sc.parse_value("38½"), (38.5, None))
        self.assertEqual(sc.parse_value("3/4"), (0.75, None))
        self.assertEqual(sc.parse_value("٩٤٫٥"), (94.5, None))
        self.assertEqual(sc.parse_value("1/0"), (None, "1/0"))
        self.assertEqual(sc.parse_value("abc"), (None, "abc"))

    def test_optional_half_sizes_not_gaps(self):
        r = run("validate", tmp_csv("size,foot_length_cm\n39,24.5\n40,25\n40.5,25.5\n41,26\n42,26.5\n42.5,27\n43,27.5\n"))
        self.assertEqual([i for i in r["issues"] if i["type"] == "size_gap"], [])
        r = run("validate", tmp_csv("size,foot_length_cm\n39,24.5\n39.5,25\n40,25.5\n42,26.5\n"))
        gaps = [i for i in r["issues"] if i["type"] == "size_gap"]
        self.assertEqual(gaps[0]["missing"], ["41"])

    def test_big_snippet_warns_metafield_limit(self):
        rows = "\n".join(f"{30 + i},{80 + 2 * i},{60 + 2 * i},{88 + 2 * i},{60 + i}" for i in range(40))
        p = tmp_csv("size,chest_cm,waist_cm,hip_cm,length_cm\n" + rows + "\n")
        r = run("render", p, "--out", p + ".html", "--lang", "both", "--units", "both")
        self.assertGreater(r["bytes"], 65536)
        self.assertTrue(any("64 KB" in w for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main()
