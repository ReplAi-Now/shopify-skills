"""Build a side-by-side comparison sheet: source | generated pairs.

Usage:
    python3 compare_sheet.py <source1> <generated1> [<source2> <generated2> ...] --out <sheet.png>

Uses Pillow if it is installed (one PNG, one pair per row, every image resized to the same height
with a label, phone photos turned upright from their EXIF orientation).
Without Pillow it writes <sheet>.html showing the pairs, and prints the pairs as JSON so the agent
can open each image directly. Always prints a JSON summary.
"""
import argparse, html, json, os, pathlib, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args()
    if len(a.images) % 2:
        sys.exit("Give images in pairs: source then generated.")
    missing = [p for p in a.images if not os.path.isfile(p)]
    if missing:
        sys.exit("Missing files: " + ", ".join(missing))
    pairs = [(a.images[i], a.images[i + 1]) for i in range(0, len(a.images), 2)]
    if os.path.dirname(a.out):
        os.makedirs(os.path.dirname(a.out), exist_ok=True)

    def uri(p):
        return html.escape(pathlib.Path(os.path.abspath(p)).as_uri(), quote=True)
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError:
        out = os.path.splitext(a.out)[0] + ".html"
        cells = "".join(
            f"<tr><td><b>SOURCE</b><br><img src='{uri(s)}'></td>"
            f"<td><b>GENERATED</b><br><img src='{uri(g)}'></td></tr>"
            for s, g in pairs)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("<html><body><style>img{height:600px}td{padding:8px;vertical-align:top}</style>"
                     f"<table>{cells}</table></body></html>")
        print(json.dumps({"mode": "html", "sheet": out, "pairs": pairs}, indent=1))
        return
    label_h = 40
    rows = []
    for s, g in pairs:
        row = []
        for path, label in ((s, "SOURCE"), (g, "GENERATED")):
            try:
                im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            except Exception as e:  # HEIC without a plugin, corrupt or empty file
                sys.exit(f"Cannot open {path}: {e}. Convert it to JPEG or PNG first.")
            w = round(im.width * a.height / im.height)
            row.append((im.resize((w, a.height)), f"{label}: {os.path.basename(path)}"))
        rows.append(row)
    row_h = a.height + label_h + 10
    total_w = max(sum(t.width for t, _ in r) + 10 * (len(r) + 1) for r in rows)
    sheet = Image.new("RGB", (total_w, row_h * len(rows) + 10), "white")
    draw = ImageDraw.Draw(sheet)
    for i, row in enumerate(rows):
        x, y = 10, i * row_h
        for im, label in row:
            draw.text((x, y + 10), label, fill="black")
            sheet.paste(im, (x, y + label_h))
            x += im.width + 10
    sheet.save(a.out, format="PNG")
    print(json.dumps({"mode": "png", "sheet": a.out, "pairs": pairs}, indent=1))


if __name__ == "__main__":
    main()
