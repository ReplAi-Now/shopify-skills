import csv, json, os, struct, subprocess, sys, tempfile, unittest, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "skills", "store", "catalog-photoshoot", "scripts", "plan_batch.py")


def png(path, w, h, pad_kb=0):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"tEXt", b"pad\x00" + b"x" * (pad_kb * 1024)) \
        + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(data)


def run(*args):
    return json.loads(subprocess.check_output([sys.executable, SCRIPT, *args]))


class PlanBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "shoot")
        os.makedirs(os.path.join(self.src, "dress-a"))
        os.makedirs(os.path.join(self.src, "coat-b"))
        png(os.path.join(self.src, "dress-a", "IMG_1.png"), 400, 600, pad_kb=80)
        png(os.path.join(self.src, "dress-a", "IMG_2.png"), 400, 600, pad_kb=80)
        png(os.path.join(self.src, "dress-a", "swatch.png"), 50, 50)        # tiny square: skipped
        png(os.path.join(self.src, "coat-b", "front.png"), 400, 600, pad_kb=80)
        open(os.path.join(self.src, "coat-b", "notes.txt"), "w").write("x")  # not an image
        open(os.path.join(self.src, "coat-b", ".DS_Store"), "w").write("x")  # hidden: ignored
        png(os.path.join(self.src, "loose.png"), 400, 600, pad_kb=80)        # root image: extra product

    def test_plan(self):
        p = run(self.src)
        names = [x["name"] for x in p["products"]]
        self.assertEqual(names, ["coat-b", "dress-a", "shoot"])
        self.assertEqual(p["to_generate"], 4)
        dress = p["products"][1]
        self.assertEqual([x["file"] for x in dress["photos"]], ["IMG_1.png", "IMG_2.png"])
        self.assertEqual(dress["skipped"][0]["reason"], "colour swatch or tiny image")
        coat = p["products"][0]
        self.assertEqual(coat["skipped"], [{"file": "notes.txt", "reason": "not an image"}])
        self.assertTrue(p["output"].endswith("shoot_catalog"))

    def test_resume(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(os.path.join(out, "dress-a"))
        png(os.path.join(out, "dress-a", "black-front.png"), 10, 10)
        with open(os.path.join(out, "report.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["subfolder", "source_file", "output_file", "mode", "view", "pose", "provider_id", "status"])
            w.writerow(["dress-a", "IMG_1.png", "black-front.png", "worn", "front", "F1", "x", "ok"])
            w.writerow(["dress-a", "IMG_2.png", "black-back.png", "worn", "back", "B1", "y", "ok"])  # file missing: redo
        p = run(self.src, "--output", out)
        self.assertEqual(p["already_done"], 1)
        self.assertEqual(p["to_generate"], 3)

    def test_output_inside_source_nested_heic_minor(self):
        out = os.path.join(self.src, "shoot_catalog")              # output inside the source folder
        os.makedirs(os.path.join(out, "dress-a"))
        png(os.path.join(out, "dress-a", "black-front.png"), 400, 600, pad_kb=80)
        with open(os.path.join(out, "report.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["subfolder", "source_file", "output_file", "mode", "view", "pose", "provider_id", "status"])
            w.writerow(["dress-a", "IMG_1.png", "black-front.png", "worn", "front", "F1", "x", "MINOR: hem 2 cm short"])
        os.makedirs(os.path.join(self.src, "coat-b", "black"))        # nested colour folder
        png(os.path.join(self.src, "coat-b", "black", "f.png"), 400, 600, pad_kb=80)
        open(os.path.join(self.src, "coat-b", "front.HEIC"), "wb").write(b"x" * 100000)  # converted copy exists
        p = run(self.src, "--output", out)
        names = [x["name"] for x in p["products"]]
        self.assertNotIn("shoot_catalog", names)
        self.assertEqual(p["already_done"], 1)
        coat = p["products"][0]
        reasons = {x["file"]: x["reason"] for x in coat["skipped"]}
        self.assertIn("nested folder", reasons["black/"])
        self.assertIn("HEIC", reasons["front.HEIC"])
        self.assertEqual([x["file"] for x in coat["photos"]], ["front.png"])

    def test_small_progressive_jpeg_with_exif_not_swatch(self):
        d = os.path.join(self.src, "dress-a", "IMG_3.jpg")
        app1 = b"Exif\x00\x00II*\x00" + b"\x00" * 40
        sof = b"\x08" + struct.pack(">HH", 600, 400) + b"\x03" + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        with open(d, "wb") as fh:  # SOF2 (progressive) after an EXIF block and a fill byte
            fh.write(b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
                     + b"\xff\xff\xc2" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9")
        dress = run(self.src)["products"][1]
        self.assertIn("IMG_3.jpg", [x["file"] for x in dress["photos"]])


if __name__ == "__main__":
    unittest.main()
