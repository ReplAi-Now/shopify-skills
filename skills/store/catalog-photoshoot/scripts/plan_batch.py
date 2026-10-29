"""Plan a catalog photoshoot batch from a folder of product photos (Python 3 standard library only).

Usage:
    python3 plan_batch.py <source_folder> [--output <output_folder>] [--min-kb 60]

Each direct subfolder of <source_folder> is one product. Images directly in the root are one
extra product named after the root. Prints JSON:
    {"source": ..., "output": ..., "products": [{"name", "photos": [...], "skipped": [...]}],
     "to_generate": N, "already_done": N}
Skipped: hidden files, non-images, small colour-swatch squares (under --min-kb and roughly square),
HEIC files that already have a JPEG/PNG copy with the same name, nested folders (listed so the agent
can ask), the output folder itself, and photos marked ok or minor in <output>/report.csv whose
output file exists (resume).
"""
import argparse, csv, json, os, struct, sys, unicodedata

IMG = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def image_size(path):
    """Return (width, height) for PNG/JPEG/WEBP without Pillow, or None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                chunk = head[12:16]
                if chunk == b"VP8X":
                    w = int.from_bytes(head[24:27], "little") + 1
                    h = int.from_bytes(head[27:30], "little") + 1
                    return w, h
                return None
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] == 0xFF:  # fill byte
                        fh.seek(-1, 1)
                        continue
                    if 0xD0 <= marker[1] <= 0xD9 or marker[1] == 0x01:  # markers with no length
                        continue
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        fh.read(3)
                        h, w = struct.unpack(">HH", fh.read(4))
                        return w, h
                    length = struct.unpack(">H", fh.read(2))[0]
                    fh.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def is_swatch(path, min_kb):
    if os.path.getsize(path) >= min_kb * 1024:
        return False
    size = image_size(path)
    if not size:
        return True
    w, h = size
    return 0.8 <= (w / h if h else 0) <= 1.25


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def done_sources(output):
    done = set()
    rep = os.path.join(output, "report.csv")
    if not os.path.exists(rep):
        return done
    with open(rep, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("status") or "").strip().lower().startswith(("ok", "minor")):
                out = os.path.join(output, r.get("subfolder") or "", r.get("output_file") or "")
                if os.path.isfile(out):
                    done.add((nfc(r.get("subfolder")), nfc(r.get("source_file"))))
    return done


def plan(source, output, min_kb):
    source = os.path.abspath(source)
    if not os.path.isdir(source):
        sys.exit(f"Not a folder: {source}")
    output = os.path.abspath(output or source.rstrip("/") + "_catalog")
    done = done_sources(output)
    groups = []
    root_imgs = [f for f in sorted(os.listdir(source)) if f.lower().endswith(IMG) and not f.startswith(".")]
    subs = [d for d in sorted(os.listdir(source)) if os.path.isdir(os.path.join(source, d)) and not d.startswith(".")
            and os.path.abspath(os.path.join(source, d)) != output]
    for d in subs:
        groups.append((d, os.path.join(source, d)))
    if root_imgs:
        groups.append((os.path.basename(source), source))
    products, todo, already = [], 0, 0
    for name, folder in groups:
        photos, skipped = [], []
        files = sorted(os.listdir(folder))
        stems = {os.path.splitext(f)[0].lower() for f in files if f.lower().endswith(IMG[:4])}
        for f in files:
            p = os.path.join(folder, f)
            if f.startswith(".") or os.path.abspath(p) == output:
                continue
            if os.path.isdir(p):
                if folder != source:
                    skipped.append({"file": f + "/", "reason": "nested folder (not scanned): ask whether it is a colour or a separate product"})
                continue
            if not os.path.isfile(p):
                continue
            if not f.lower().endswith(IMG):
                skipped.append({"file": f, "reason": "not an image"})
            elif is_swatch(p, min_kb):
                skipped.append({"file": f, "reason": "colour swatch or tiny image"})
            elif f.lower().endswith(".heic") and os.path.splitext(f)[0].lower() in stems:
                skipped.append({"file": f, "reason": "HEIC with a JPEG/PNG copy of the same name"})
            elif (nfc(name), nfc(f)) in done:
                skipped.append({"file": f, "reason": "already done (report.csv)"})
                already += 1
            else:
                photos.append({"file": f, "path": p, "heic": f.lower().endswith(".heic"),
                               "kb": round(os.path.getsize(p) / 1024)})
        todo += len(photos)
        products.append({"name": name, "photos": photos, "skipped": skipped})
    return {"source": source, "output": output, "products": products,
            "to_generate": todo, "already_done": already}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--output")
    ap.add_argument("--min-kb", type=float, default=60)
    a = ap.parse_args()
    print(json.dumps(plan(a.source, a.output, a.min_kb), ensure_ascii=False, indent=1))
