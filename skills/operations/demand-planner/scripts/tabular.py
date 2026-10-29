"""Read CSV or XLSX files into a list of dicts (Python 3 standard library only).

Shared by every skill in this pack. Import it from a script in the same folder:
    from tabular import read_rows, write_csv, num
or run it to preview a file:
    python3 tabular.py <file.csv|file.xlsx> [sheet_name]

Header names are normalised: lowercased, trimmed, spaces and dashes become "_".
"""
import csv, io, json, re, sys, zipfile
import xml.etree.ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def norm(key):
    return re.sub(r"[\s\-]+", "_", str(key or "").strip().lower()).strip("_")


_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
                        "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9\u066b\u066c",
                        "01234567890123456789.,")


def num(value, default=0.0):
    """Parse money/quantity text into a float.

    Handles '1,250.00 EGP', 'EGP. 500', '500 ج.م.', 'ر.س 1,250', '(30)', '-30', '1.234,56',
    '1234,56' (decimal comma), '1 250', Arabic-Indic digits. Returns default when there is no number.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().translate(_DIGITS).replace("\u00a0", " ")
    m = re.search(r"\d[\d.,' ]*", s)
    if not m:
        return default
    tok = m.group(0).rstrip(".,' ").replace(" ", "").replace("'", "")
    before = s[:m.start()]
    neg = (s.startswith("(") and s.rstrip(".").endswith(")")) or before.rstrip().endswith("-")
    if "," in tok and "." in tok:
        dec = "." if tok.rfind(".") > tok.rfind(",") else ","
        tok = tok.replace("," if dec == "." else ".", "").replace(",", ".")
    elif "," in tok:
        parts = tok.split(",")
        # 1,250 / 12,500,000 are thousands; 1234,56 and 12,5 are decimal commas.
        if len(parts) == 2 and len(parts[1]) != 3:
            tok = parts[0] + "." + parts[1]
        else:
            tok = tok.replace(",", "")
    elif tok.count(".") > 1:
        tok = tok.replace(".", "")  # 1.250.000 thousands dots
    try:
        v = float(tok)
    except ValueError:
        return default
    return -abs(v) if neg else v


def _cell_index(ref):
    col = re.match(r"[A-Z]+", ref).group(0)
    idx = 0
    for ch in col:
        idx = idx * 26 + ord(ch) - 64
    return idx - 1


def _read_xlsx(path, sheet_name=None):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(_NS + "t")))
    sheet_file = None
    if sheet_name and "xl/workbook.xml" in names:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        for s in wb.iter(_NS + "sheet"):
            if s.get("name", "").lower() == sheet_name.lower():
                t = target.get(s.get(_REL + "id"), "")
                sheet_file = "xl/" + t.lstrip("/").replace("xl/", "", 1)
    if not sheet_file:
        sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.split("/")[-1]).group(1)))
        if not sheets:
            return []
        sheet_file = sheets[0]
    grid = []
    for row in ET.fromstring(z.read(sheet_file)).iter(_NS + "row"):
        vals = {}
        for c in row.findall(_NS + "c"):
            v = c.find(_NS + "v")
            t = c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(_NS + "t"))
            else:
                val = v.text if v is not None else ""
            if re.fullmatch(r"-?\d+\.0", val or ""):
                val = val[:-2]
            vals[_cell_index(c.get("r"))] = val
        if vals:
            grid.append([vals.get(i, "") for i in range(max(vals) + 1)])
    if not grid:
        return []
    head = [norm(h) for h in grid[0]]
    out = []
    for r in grid[1:]:
        if any(str(x).strip() for x in r):
            r = r + [""] * (len(head) - len(r))
            out.append({h: str(v).strip() for h, v in zip(head, r) if h})
    return out


def read_rows(path, sheet_name=None):
    """Return a list of dicts. Works for .csv, .tsv, .txt (sniffed) and .xlsx."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        return _read_xlsx(path, sheet_name)
    with open(path, "rb") as fh:
        raw = fh.read()
    encs = ("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1256", "latin-1")
    for enc in encs:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for r in csv.DictReader(io.StringIO(text), dialect=dialect):
        d = {norm(k): (v or "").strip() for k, v in r.items() if k is not None}
        if any(d.values()):
            rows.append(d)
    return rows


def pick(row, *candidates, default=""):
    """First non-empty value among candidate column names (already normalised)."""
    for c in candidates:
        v = row.get(norm(c))
        if v not in (None, ""):
            return v
    return default


def write_csv(path, rows, columns=None):
    """Write rows to CSV (UTF-8, no BOM)."""
    columns = columns or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rows = read_rows(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps({"rows": len(rows), "columns": list(rows[0].keys()) if rows else [],
                      "sample": rows[:3]}, ensure_ascii=False, indent=1))
