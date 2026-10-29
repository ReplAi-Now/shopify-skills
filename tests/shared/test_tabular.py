import os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "shared"))
from tabular import num, read_rows  # noqa: E402


class Num(unittest.TestCase):
    def test_money_formats(self):
        cases = {"1,250.00 EGP": 1250, "ر.س 1,250": 1250, "د.إ 100": 100, "EGP. 500": 500,
                 "500 ج.م.": 500, "1234,56": 1234.56, "١٢٣٤": 1234, "(30)": -30,
                 "-30": -30, "1.234,56": 1234.56, "12,500,000": 12500000, "1 250": 1250, "": 0, "N/A": 0,
                 "12,5": 12.5, "-": 0, "SAR -45.5": -45.5, "1.250.000": 1250000,
                 "١٬٢٥٠٫٥": 1250.5, "EGP 1,450": 1450}
        for raw, want in cases.items():
            self.assertAlmostEqual(num(raw), want, msg=raw)

    def test_utf16_csv(self):
        p = os.path.join(tempfile.mkdtemp(), "g.csv")
        with open(p, "w", encoding="utf-16") as fh:
            fh.write("Campaign\tCost\nSummer\t1,200.50\n")
        rows = read_rows(p)
        self.assertEqual(rows, [{"campaign": "Summer", "cost": "1,200.50"}])


if __name__ == "__main__":
    unittest.main()
