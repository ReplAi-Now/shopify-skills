"""Catalogue folder and product-data helper for shopify-catalog-upload (Python 3 standard library only).

Usage:
  python3 sheet.py scan <catalogue_dir>
      JSON summary: products (subfolders), colours and photos in display order (front, back, side, other).
  python3 sheet.py template <catalogue_dir> <out.csv>
      Product-data sheet for the merchant: one row per product + colour.
  python3 sheet.py read <file.csv|file.xlsx>
      Rows as JSON (headers lowercased, spaces to "_").
  python3 sheet.py import-csv <catalogue_dir> <product_data.csv|xlsx> <plan.json> <out.csv>
      Shopify product import CSV (fallback when the agent has no write access).
      sizes: "S, M, L", "S/M/L", "S-M-L" or "S M L" are split; "38-40" and "2-3Y" stay one size.
      stock_per_size: one number for every size ("5"), one per size in order ("3,5,2"),
      or by size name ("S:3, M:5"). plan.json:
      {"products": [{"subfolder", "title", "body_html", "type", "tags", "vendor", "sku_base"}],
       "taxable": false, "continue_selling": true, "status": "draft",
       "image_urls": {"<subfolder>/<file>": "https://..."}}
"""
import csv, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, num  # noqa: E402

COLUMNS = ["subfolder", "colour", "sizes", "price", "compare_at_price", "stock_per_size", "cost_per_item", "notes"]
IMG = (".png", ".jpg", ".jpeg", ".webp")
VIEW_ORDER = {"front": 0, "back": 1, "side": 2, "three-quarter": 2}
NAME_RE = re.compile(r"(.+?)-(front|back|side|three-quarter|top|detail)(?:-(\d+))?\.[a-z]+$", re.I)


def photos_in(folder):
    out = []
    for f in sorted(os.listdir(folder)):
        if f.startswith(".") or not f.lower().endswith(IMG):
            continue
        m = NAME_RE.match(f)
        if m:
            colour, view, n = m.group(1).lower(), m.group(2).lower(), int(m.group(3) or 1)
        else:
            colour, view, n = None, "other", 1
        out.append({"file": f, "colour": colour, "view": view, "n": n})
    return out


def scan(root):
    products = []
    for sub in sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")):
        photos = photos_in(os.path.join(root, sub))
        colours = []
        for p in photos:
            if p["colour"] and p["colour"] not in colours:
                colours.append(p["colour"])
        ordered = sorted(photos, key=lambda p: (colours.index(p["colour"]) if p["colour"] in colours else 99,
                                                VIEW_ORDER.get(p["view"], 3), p["n"], p["file"]))
        products.append({"subfolder": sub, "colours": colours, "colour_titles": [title_colour(c) for c in colours],
                         "photos": ordered, "unnamed": [p["file"] for p in photos if not p["colour"]]})
    return {"root": os.path.abspath(root), "products": products}


def title_colour(c):
    """black-beige -> Black/Beige (two basic colours), light-grey -> Light Grey."""
    parts = c.split("-")
    if len(parts) == 2 and all(x in BASIC for x in parts) and c not in COMPOUND:
        return "/".join(x.title() for x in parts)
    return c.replace("-", " ").title()


BASIC = {"black", "white", "beige", "grey", "gray", "navy", "red", "blue", "green", "pink", "brown", "cream",
         "yellow", "orange", "purple", "burgundy", "olive", "camel", "khaki", "gold", "silver", "ivory", "mint"}
COMPOUND = {"olive-green", "mint-green", "navy-blue", "khaki-green", "army-green"}  # one colour, not two


def template(root, out):
    rows = [{"subfolder": p["subfolder"], "colour": c} for p in scan(root)["products"] for c in (p["colours"] or [""])]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"rows": len(rows), "file": out}))


def handleize(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


SIZE_TOKEN = re.compile(r"(\d{0,2}X{0,3}[SML]|\d{1,3}(\.5)?|XXL|XXXL|\d?XL)$", re.I)


def split_sizes(s):
    """Split a size list. A hyphen between letters splits (S-M-L); between digits it is a range size
    (38-40, 2-3Y) and stays whole. Spaces split only when every piece looks like a size code."""
    s = (s or "").strip()
    parts = [x.strip() for x in re.split(r"[,/|;\u060c]|\s-\s|(?<=[A-Za-z])-(?=[A-Za-z0-9])|(?<=\d)-(?=[A-Za-z])", s)
             if x.strip()]
    if len(parts) == 1 and " " in parts[0] and all(SIZE_TOKEN.match(t) for t in parts[0].split()):
        parts = parts[0].split()
    if len(parts) == 1 and parts[0].lower() in ("one size", "onesize", "free size", "os"):
        parts = ["One Size"]
    return parts or ["One Size"]


def stock_for(stock, sizes):
    """Map the stock cell to one integer per size, or (None, reason) when it cannot be read."""
    stock = (stock or "").strip()
    if not stock:
        return [0] * len(sizes), None
    pairs = re.findall(r"([^\s:=,;|/]+)\s*[:=]\s*(\d+)", stock)
    if pairs:
        by = {k.lower(): int(v) for k, v in pairs}
        missing = [x for x in sizes if x.lower() not in by]
        if missing:
            return None, "no stock for size " + ", ".join(missing)
        return [by[x.lower()] for x in sizes], None
    nums = re.findall(r"\d+", stock)
    if len(nums) == 1:
        return [int(nums[0])] * len(sizes), None
    if len(nums) == len(sizes):
        return [int(n) for n in nums], None
    return None, f"stock '{stock}' does not match {len(sizes)} sizes"


def money(v):
    v = (v or "").strip()
    return "" if not v else ("%.2f" % num(v)).rstrip("0").rstrip(".")


def colour_key(c):
    return handleize(c or "")


def import_csv(root, data_path, plan_path, out):
    data = read_rows(data_path)
    plan = json.load(open(plan_path, encoding="utf-8"))
    urls = plan.get("image_urls", {})
    scanned = {p["subfolder"]: p for p in scan(root)["products"]}
    header = ["Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Published", "Option1 Name",
              "Option1 Value", "Option2 Name", "Option2 Value", "Variant SKU", "Variant Inventory Tracker",
              "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service", "Variant Price",
              "Variant Compare At Price", "Variant Requires Shipping", "Variant Taxable", "Image Src",
              "Image Position", "Image Alt Text", "Variant Image", "Cost per item", "Status"]
    lines, problems, used = [], [], set()
    for prod in plan["products"]:
        sub = prod["subfolder"]
        handle = prod.get("handle") or handleize(prod["title"]) or handleize(sub) or "product"
        base, k = handle, 2
        while handle in used:  # same title twice, or an Arabic title with no Latin letters
            handle, k = f"{base}-{k}", k + 1
        used.add(handle)
        rows = [r for r in data if (r.get("subfolder") or "").strip() == sub]
        if not rows:
            problems.append(f"{sub}: no rows in product data")
            continue
        photos = scanned.get(sub, {}).get("photos", [])
        images = [(p, urls.get(f"{sub}/{p['file']}", "")) for p in photos]
        front_url = {colour_key(p["colour"]): u for p, u in images if p["view"] == "front" and u}
        first = True
        idx = 0
        for r in rows:
            colour = title_colour(colour_key(r.get("colour"))) or "Default"
            sizes = split_sizes(r.get("sizes"))
            qtys, why = stock_for(r.get("stock_per_size", ""), sizes)
            if why:
                problems.append(f"{sub} {colour}: {why}; stock left at 0")
                qtys = [0] * len(sizes)
            for size, qty in zip(sizes, qtys):
                idx += 1
                price = money(r.get("price", ""))
                if not price:
                    problems.append(f"{sub} {colour} {size}: missing price")
                line = {h: "" for h in header}
                line.update({
                    "Handle": handle, "Option1 Value": colour, "Option2 Value": size,
                    "Variant SKU": f"{prod['sku_base']}-{idx}", "Variant Inventory Tracker": "shopify",
                    "Variant Inventory Qty": str(qty),
                    "Variant Inventory Policy": "continue" if plan.get("continue_selling", True) else "deny",
                    "Variant Fulfillment Service": "manual", "Variant Price": price,
                    "Variant Compare At Price": money(r.get("compare_at_price", "")), "Variant Requires Shipping": "TRUE",
                    "Variant Taxable": "TRUE" if plan.get("taxable") else "FALSE",
                    "Variant Image": front_url.get(colour_key(r.get("colour")), ""),
                    "Cost per item": money(r.get("cost_per_item", "")),
                })
                if first:
                    line.update({"Title": prod["title"], "Body (HTML)": prod.get("body_html", ""),
                                 "Vendor": prod.get("vendor", ""), "Type": prod.get("type", ""),
                                 "Tags": prod.get("tags", ""), "Published": "TRUE", "Option1 Name": "Color",
                                 "Option2 Name": "Size", "Status": plan.get("status", "draft")})
                    first = False
                lines.append(line)
        pos = 0
        for i, (p, u) in enumerate(images):
            if not u:
                continue
            pos += 1
            alt = f"{prod['title']} - {title_colour(p['colour'] or '')} - {p['view']}"
            if pos <= idx:
                target = [l for l in lines if l["Handle"] == handle][pos - 1]
                target["Image Src"], target["Image Position"], target["Image Alt Text"] = u, str(pos), alt
            else:
                extra = {h: "" for h in header}
                extra.update({"Handle": handle, "Image Src": u, "Image Position": str(pos), "Image Alt Text": alt})
                lines.append(extra)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(lines)
    print(json.dumps({"file": out, "rows": len(lines), "problems": problems}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "scan":
        print(json.dumps(scan(a[1]), ensure_ascii=False, indent=1))
    elif len(a) == 3 and a[0] == "template":
        template(a[1], a[2])
    elif len(a) == 2 and a[0] == "read":
        print(json.dumps(read_rows(a[1]), ensure_ascii=False, indent=1))
    elif len(a) == 5 and a[0] == "import-csv":
        import_csv(*a[1:])
    else:
        print(__doc__)
        sys.exit(1)
