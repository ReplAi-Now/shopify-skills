"""Regression tests for size-chart-builder QA minors (Oct 2026), synthetic fixtures only."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_sizechart import FX, read, run  # noqa: E402


def render(fixture, *args):
    out = os.path.join(tempfile.mkdtemp(), "s.html")
    r = run("render", os.path.join(FX, fixture), "--out", out, *args)
    return r, read(out)


class GarmentWording(unittest.TestCase):
    def test_garment_basis_uses_lay_flat_wording(self):
        _, h = render("flat_tops.csv", "--basis", "garment", "--lang", "both")
        self.assertNotIn("around the fullest part of your chest", h)
        self.assertIn("Chest: lay the item flat and measure straight across from armpit to armpit", h)
        self.assertIn("doubled", h)
        self.assertIn("Length: lay the item flat", h)
        self.assertIn("افرد القطعة", h)
        self.assertNotIn("قِس حول أعرض جزء من الصدر تحت الإبط", h)

    def test_garment_measured_full_says_all_the_way_round(self):
        _, h = render("flat_tops.csv", "--basis", "garment", "--measured", "full")
        self.assertIn("Chest: measure all the way around the item just under the arms.", h)
        self.assertNotIn("doubled", h.split("How to measure")[1].split("<ul")[1])

    def test_body_basis_keeps_body_wording(self):
        _, h = render("flat_tops.csv")
        self.assertIn("around the fullest part of your chest", h)


class EasternDigits(unittest.TestCase):
    def test_numeric_size_labels_and_size_systems(self):
        _, h = render("numeric_gap.csv", "--lang", "ar", "--arabic-digits", "eastern", "--units", "cm")
        self.assertIn(">٣٦<", h)          # size label and EU column
        self.assertIn(">٤٢<", h)
        self.assertNotIn(">36<", h)
        self.assertIn(">٦٨<", h)          # measurement

    def test_letter_sizes_unchanged_and_english_block_western(self):
        _, h = render("good_chart.csv", "--lang", "both", "--arabic-digits", "eastern", "--units", "cm")
        ar = h[h.index('lang="ar"'):]
        en = h[:h.index('lang="ar"')]
        self.assertIn(">M<", ar)
        self.assertIn(">86<", en)
        self.assertIn(">٨٦<", ar)


class FitNoteLanguages(unittest.TestCase):
    def test_custom_english_note_not_paired_with_default_arabic(self):
        r, h = render("good_chart.csv", "--lang", "both", "--fit-note", "runs-small",
                      "--fit-note-text", "Cut slim through the waist.")
        ar = h[h.index('lang="ar"'):]
        self.assertIn("Cut slim through the waist.", h)
        self.assertNotIn("يأتي صغيرًا", ar)                    # default Arabic note no longer shown
        self.assertTrue(any("--fit-note-text-ar" in w for w in r["warnings"]))
        self.assertEqual(r["tables"]["ar"]["fit_note"].startswith("بين مقاسين"), True)

    def test_both_texts_given_no_warning(self):
        r, h = render("good_chart.csv", "--lang", "both", "--fit-note-text", "Cut slim.",
                      "--fit-note-text-ar", "قصة ضيقة.")
        self.assertIn("قصة ضيقة.", h)
        self.assertFalse(any("fit note" in w for w in r["warnings"]))


class JsonTable(unittest.TestCase):
    def test_table_matches_html_labels_and_doubled_values(self):
        r, h = render("flat_tops.csv", "--basis", "garment", "--lang", "both", "--units", "cm")
        t = r["table"]
        self.assertEqual(t["columns"], ["Size", "Chest (cm)", "Length (cm)"])
        self.assertEqual(t["rows"][0], ["S", "100", "70"])     # chest flat 50 shown doubled, length not
        self.assertIn(">100<", h)
        self.assertEqual((t["dir"], t["unit"], t["title"]), ("ltr", "cm", "Size chart"))
        ar = r["tables"]["ar"]
        self.assertEqual(ar["columns"][0], "المقاس")
        self.assertEqual(ar["dir"], "rtl")

    def test_table_in_inches_when_units_in(self):
        r, _ = render("good_chart.csv", "--units", "in")
        self.assertEqual(r["table"]["columns"][1], "Bust (in)")
        self.assertEqual(r["table"]["rows"][0][1], "34")       # 86 cm -> 33.86 -> 34


if __name__ == "__main__":
    unittest.main()
