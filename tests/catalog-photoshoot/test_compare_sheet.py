import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "skills", "store", "catalog-photoshoot", "scripts", "compare_sheet.py")
try:
    from PIL import Image
except ImportError:
    Image = None


class CompareSheet(unittest.TestCase):
    def test_odd_count(self):
        r = subprocess.run([sys.executable, SCRIPT, "a.png", "--out", "x.png"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pairs", r.stderr)

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_exif_upright_rows_and_new_folder(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "src photo.jpg")          # stored 600x400, EXIF says rotate: portrait
        im = Image.new("RGB", (600, 400), "red")
        ex = im.getexif()
        ex[0x0112] = 6
        im.save(src, exif=ex)
        gen = os.path.join(tmp, "black-front.png")
        Image.new("RGB", (400, 600), "blue").save(gen)
        out = os.path.join(tmp, "sheets", "sheet-a.png")   # folder does not exist yet
        res = json.loads(subprocess.check_output([sys.executable, SCRIPT, src, gen, src, gen, "--out", out,
                                                  "--height", "300"]))
        self.assertEqual(res["mode"], "png")
        w, h = Image.open(out).size
        self.assertEqual(w, 10 + 200 + 10 + 200 + 10)        # source shown upright (portrait), one pair per row
        self.assertEqual(h, 2 * (300 + 40 + 10) + 10)


if __name__ == "__main__":
    unittest.main()
