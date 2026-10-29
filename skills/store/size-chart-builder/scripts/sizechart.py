"""Size chart helper: validate, convert units, garment to body guidance, render HTML.

Python 3 standard library only. Reads CSV or XLSX in the standard size chart shape:
first column `size`, measurement columns ending in `_cm` or `_in` (chest_cm, waist_in),
optional size system columns (eu, uk, us, it, fr, jp, us_waist). See
references/csv-format.md.

Usage:
    python3 sizechart.py validate chart.csv [--tolerance-cm 1.0] [--tolerance-rel 0.5]
    python3 sizechart.py convert chart.csv --to in|cm [--step 0.5] [--out converted.csv]
    python3 sizechart.py body flat.csv --category tops|dresses|bottoms
            --fit stretch|fitted|regular|relaxed|oversized [--measured flat|full]
            [--ease-file ease.json] [--out body.csv]
    python3 sizechart.py render chart.csv --out snippet.html [--lang en|ar|both]
            [--units cm|in|both] [--basis body|garment] [--fit-note true-to-size|runs-small|runs-large]
            [--fit-note-text "..."] [--title "..."] [--title-ar "..."] [--arabic-digits eastern|western]
            [--measured flat|full]   (basis garment: flat widths are doubled on the chart)
            [--fit-note-text-ar "..."]  (with a custom note and --lang both, give both texts: a note
                                         given in one language only is left out of the other, with a warning)

render prints "table" (and "tables" per language): the json metafield value with display headers and
the same values the HTML shows.

Every command prints JSON. Nothing touches the network.
"""
import argparse, html, json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, write_csv  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE_SYSTEM_COLS = ["eu", "uk", "us", "it", "fr", "jp", "us_waist"]
LETTERS = ["XXXS", "XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL", "5XL", "6XL"]
LETTER_ALIASES = {"2XS": "XXS", "3XS": "XXXS", "2XL": "XXL", "3XL": "XXXL", "XXXXL": "4XL",
                  "XXXXXL": "5XL", "SMALL": "S", "MEDIUM": "M", "LARGE": "L"}
# Measurements that should get bigger with every size. Others (length, sleeve, inseam, rise)
# may legitimately stay the same between sizes.
GROWS = {"chest", "bust", "underbust", "waist", "hip", "hips", "seat", "thigh", "neck", "bicep",
         "shoulder", "hem", "foot_length", "across_back"}
CIRCUMFERENCE = {"chest", "bust", "underbust", "waist", "hip", "hips", "seat", "thigh", "bicep",
                 "hem", "leg_opening", "sleeve_opening"}
EASE_KEY = {"chest": "chest", "bust": "chest", "waist": "waist", "hip": "hip", "hips": "hip",
            "seat": "hip", "thigh": "thigh"}


def round_half(v, step=0.5):
    """Round half up to the nearest step (0.5 by default). 35.25 -> 35.5, 35.24 -> 35.0."""
    return math.floor(v / step + 0.5 + 1e-9) * step


def fmt(v):
    if v is None:
        return ""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%.2f" % v).rstrip("0").rstrip(".")


FRACTIONS = {"\u00bd": 0.5, "\u00bc": 0.25, "\u00be": 0.75}


def parse_value(s):
    raw = str(s or "").strip()
    s = raw.replace(",", ".").replace("\u066b", ".")
    if s == "":
        return None, None
    try:
        return float(s), None
    except ValueError:
        pass
    # Inch sheets often use fractions: "36 1/2", "36-1/2", "38\u00bd".
    m = re.fullmatch(r"(\d+(?:\.\d+)?)?[\s\-]*(?:(\d+)/(\d+)|([\u00bd\u00bc\u00be]))", s)
    if m and (m.group(3) is None or int(m.group(3)) > 0):
        whole = float(m.group(1) or 0)
        frac = FRACTIONS[m.group(4)] if m.group(4) else int(m.group(2)) / int(m.group(3))
        return whole + frac, None
    return None, raw


def load(path):
    rows = read_rows(path)
    if not rows:
        sys.exit(json.dumps({"error": f"no rows found in {path}"}))
    cols = list(rows[0].keys())
    if "size" not in cols:
        sys.exit(json.dumps({"error": "column 'size' not found", "columns": cols,
                             "hint": "first column must be named size (see references/csv-format.md)"}))
    meas = []
    for c in cols:
        # "Chest (cm)" normalises to chest_(cm); accept it like chest_cm.
        m = re.fullmatch(r"(.+?)(?:_+|_*[(\[])(cm|in)[)\]]?", c)
        if m and c not in SIZE_SYSTEM_COLS:
            meas.append({"col": c, "name": m.group(1), "unit": m.group(2)})
    systems = [c for c in cols if c in SIZE_SYSTEM_COLS]
    ignored = [c for c in cols if c != "size" and c not in systems and c not in [x["col"] for x in meas]]
    return rows, meas, systems, ignored


# ---------------------------------------------------------------- validate

def _label_index(label):
    u = label.strip().upper().replace(" ", "")
    u = LETTER_ALIASES.get(u, u)
    return LETTERS.index(u) if u in LETTERS else None


def check_labels(sizes):
    issues = []
    seen = set()
    for s in sizes:
        if s.lower() in seen:
            issues.append({"level": "error", "type": "duplicate_size", "size": s,
                           "message": f"size '{s}' appears more than once"})
        seen.add(s.lower())
    idx = [_label_index(s) for s in sizes]
    if sizes and all(i is not None for i in idx):
        for a, b, ia, ib in zip(sizes, sizes[1:], idx, idx[1:]):
            if ib <= ia:
                issues.append({"level": "error", "type": "size_order", "between": [a, b],
                               "message": f"'{b}' comes after '{a}' but is not a bigger letter size"})
            elif ib - ia > 1:
                missing = LETTERS[ia + 1:ib]
                issues.append({"level": "warning", "type": "size_gap", "between": [a, b], "missing": missing,
                               "message": f"gap between {a} and {b}: {', '.join(missing)} missing"})
        return issues
    nums = [parse_value(s)[0] for s in sizes]
    if len(sizes) >= 2 and all(n is not None for n in nums):
        diffs = [round(b - a, 4) for a, b in zip(nums, nums[1:])]
        pos = [d for d in diffs if d > 0]
        step = min(pos) if pos else None
        if step == 0.5 and any(d >= 1 for d in pos):
            step = 1.0  # half sizes are optional (39, 40, 40.5, 41): only a skipped whole size is a gap
        for a, b, d in zip(sizes, sizes[1:], diffs):
            if d <= 0:
                issues.append({"level": "error", "type": "size_order", "between": [a, b],
                               "message": f"'{b}' comes after '{a}' but is not bigger"})
            elif step and d > step * 1.5:
                n_missing = int(round(d / step)) - 1
                missing = [fmt(parse_value(a)[0] + step * (k + 1)) for k in range(n_missing)]
                issues.append({"level": "warning", "type": "size_gap", "between": [a, b], "missing": missing,
                               "message": f"gap between {a} and {b}: {', '.join(missing)} missing"})
    return issues


def validate_rows(rows, meas, systems, tol_cm=1.0, tol_rel=0.5):
    sizes = [r.get("size", "").strip() for r in rows]
    issues = check_labels(sizes)
    for m in meas:
        vals = []
        for r, s in zip(rows, sizes):
            v, bad = parse_value(r.get(m["col"]))
            if bad is not None:
                issues.append({"level": "error", "type": "not_a_number", "column": m["col"], "size": s,
                               "message": f"{m['col']} for size {s} is '{bad}', not a number"})
            elif v is None:
                issues.append({"level": "warning", "type": "blank_value", "column": m["col"], "size": s,
                               "message": f"{m['col']} is blank for size {s}"})
            vals.append(v)
        steps = []
        for i in range(len(vals) - 1):
            a, b = vals[i], vals[i + 1]
            if a is None or b is None:
                continue
            d = round(b - a, 4)
            pair = [sizes[i], sizes[i + 1]]
            if d < 0:
                issues.append({"level": "error", "type": "decreasing", "column": m["col"], "between": pair,
                               "message": f"{m['col']} goes down from {fmt(a)} ({pair[0]}) to {fmt(b)} ({pair[1]})"})
            elif d == 0:
                lvl = "warning" if m["name"] in GROWS else "info"
                issues.append({"level": lvl, "type": "no_change", "column": m["col"], "between": pair,
                               "message": f"{m['col']} is the same ({fmt(a)}) for {pair[0]} and {pair[1]}"})
            steps.append((d, pair))
        pos = sorted(d for d, _ in steps if d > 0)
        if len(steps) >= 3 and pos:
            n = len(pos)
            median = pos[n // 2] if n % 2 else (pos[n // 2 - 1] + pos[n // 2]) / 2
            abs_tol = tol_cm if m["unit"] == "cm" else tol_cm / 2.0
            limit = max(abs_tol, tol_rel * median)
            for d, pair in steps:
                if d > 0 and abs(d - median) > limit:
                    issues.append({"level": "warning", "type": "uneven_step", "column": m["col"], "between": pair,
                                   "step": d, "typical_step": median,
                                   "message": f"{m['col']} jumps {fmt(d)} from {pair[0]} to {pair[1]}; "
                                              f"typical step is {fmt(median)}. Check for a typo or a missing size."})
    for c in systems:
        vals = [parse_value(r.get(c))[0] for r in rows]
        for i in range(len(vals) - 1):
            a, b = vals[i], vals[i + 1]
            if a is not None and b is not None and b <= a:
                issues.append({"level": "error", "type": "decreasing", "column": c,
                               "between": [sizes[i], sizes[i + 1]],
                               "message": f"{c.upper()} size does not increase from {sizes[i]} to {sizes[i + 1]}"})
    if not meas:
        issues.append({"level": "error", "type": "no_measurements",
                       "message": "no measurement columns found: headers must end in _cm or _in (chest_cm, waist_in)"})
    counts = {k: sum(1 for x in issues if x["level"] == k) for k in ("error", "warning", "info")}
    return {"sizes": sizes, "measurements": [m["col"] for m in meas], "size_systems": systems,
            "counts": counts, "ok": counts["error"] == 0 and counts["warning"] == 0, "issues": issues}


# ---------------------------------------------------------------- convert

def convert_rows(rows, meas, to, step=0.5):
    out, cols = [], ["size"]
    for r in rows:
        nr = {"size": r.get("size", "")}
        for k, v in r.items():
            if k == "size":
                continue
            m = next((x for x in meas if x["col"] == k), None)
            if m is None or m["unit"] == to:
                nr[k] = v
                continue
            val, _ = parse_value(v)
            new_col = f"{m['name']}_{to}"
            if val is None:
                nr[new_col] = v
            else:
                nr[new_col] = fmt(round_half(val / 2.54 if to == "in" else val * 2.54, step))
        out.append(nr)
    if out:
        cols = list(out[0].keys())
    return out, cols


# ---------------------------------------------------------------- body guidance

def body_rows(rows, meas, category, fit, measured="flat", ease_file=None):
    with open(ease_file or os.path.join(HERE, "..", "assets", "ease.json"), encoding="utf-8") as fh:
        ease = json.load(fh)
    if category not in ease:
        sys.exit(json.dumps({"error": f"category '{category}' not in ease table", "options": [k for k in ease if not k.startswith("_")]}))
    out, notes = [], []
    for r in rows:
        nr = {"size": r.get("size", "")}
        for m in meas:
            v, _ = parse_value(r.get(m["col"]))
            cm = None if v is None else (v * 2.54 if m["unit"] == "in" else v)
            name = m["name"]
            if name in CIRCUMFERENCE:
                garment = None if cm is None else (cm * 2 if measured == "flat" else cm)
                nr[f"garment_{name}_cm"] = "" if garment is None else fmt(round_half(garment))
                key = EASE_KEY.get(name)
                rng = ease[category].get(key, {}).get(fit) if key else None
                if rng and garment is not None:
                    nr[f"body_{name}_min_cm"] = fmt(round_half(garment - rng[1]))
                    nr[f"body_{name}_max_cm"] = fmt(round_half(garment - rng[0]))
                elif not rng and key:
                    notes.append(f"no ease for {name} / {fit} in {category}")
            else:
                nr[f"garment_{name}_cm"] = "" if cm is None else fmt(round_half(cm))
        out.append(nr)
    return out, sorted(set(notes))


# ---------------------------------------------------------------- render

LABELS = {
    "size": ("Size", "المقاس"), "eu": ("EU", "أوروبي EU"), "uk": ("UK", "بريطاني UK"), "us": ("US", "أمريكي US"),
    "it": ("IT", "إيطالي IT"), "fr": ("FR", "فرنسي FR"), "jp": ("JP", "ياباني JP"), "us_waist": ("Waist (US)", "الوسط US"),
    "chest": ("Chest", "الصدر"), "bust": ("Bust", "الصدر"), "underbust": ("Under bust", "تحت الصدر"),
    "waist": ("Waist", "الوسط"), "hip": ("Hip", "الأرداف"), "hips": ("Hip", "الأرداف"), "seat": ("Seat", "المقعد"),
    "length": ("Length", "الطول"), "sleeve": ("Sleeve", "طول الكم"), "shoulder": ("Shoulder", "عرض الكتف"),
    "inseam": ("Inseam", "طول الساق الداخلي"), "outseam": ("Outseam", "طول البنطلون"), "rise": ("Rise", "ارتفاع الوسط"),
    "thigh": ("Thigh", "الفخذ"), "neck": ("Neck", "الرقبة"), "bicep": ("Bicep", "الذراع"), "hem": ("Hem", "عرض الذيل"),
    "leg_opening": ("Leg opening", "فتحة الرجل"), "foot_length": ("Foot length", "طول القدم"),
    "across_back": ("Across back", "عرض الظهر"), "height": ("Height", "الطول الكلي"),
}
UNIT = {"cm": ("cm", "سم"), "in": ("in", "إنش")}
HOW = {
    "chest": ("Chest: measure around the fullest part of your chest, under the arms, tape level.",
              "الصدر: قِس حول أعرض جزء من الصدر تحت الإبط، والشريط مستوٍ."),
    "bust": ("Bust: measure around the fullest part of your bust, tape level across the back.",
             "الصدر: قِس حول أعرض جزء من الصدر، والشريط مستوٍ على الظهر."),
    "waist": ("Waist: measure around your natural waist, the narrowest part above the belly button.",
              "الوسط: قِس حول الوسط الطبيعي، أضيق جزء فوق السُرّة."),
    "hip": ("Hip: stand with feet together and measure around the fullest part of your hips.",
            "الأرداف: قف والقدمان متلاصقتان وقِس حول أعرض جزء من الأرداف."),
    "length": ("Length: from the highest point of the shoulder down to the hem.",
               "الطول: من أعلى نقطة في الكتف حتى نهاية القطعة."),
    "sleeve": ("Sleeve: from the shoulder seam down to the cuff.",
               "طول الكم: من خياطة الكتف حتى نهاية الكم."),
    "shoulder": ("Shoulder: straight across the back from one shoulder point to the other.",
                 "عرض الكتف: بشكل مستقيم على الظهر من طرف الكتف إلى الطرف الآخر."),
    "inseam": ("Inseam: from the crotch down the inside of the leg to the ankle.",
               "طول الساق الداخلي: من أعلى الفخذ من الداخل حتى الكاحل."),
    "thigh": ("Thigh: around the fullest part of the upper leg.", "الفخذ: حول أعرض جزء من أعلى الساق."),
    "neck": ("Neck: around the base of the neck, one finger under the tape.",
             "الرقبة: حول أسفل الرقبة مع ترك مسافة إصبع تحت الشريط."),
    "foot_length": ("Foot length: stand on paper, mark heel and longest toe, measure the distance. Measure both feet and use the longer one.",
                    "طول القدم: قف على ورقة، علّم الكعب وأطول إصبع، وقِس المسافة. قِس القدمين واستخدم الأطول."),
}
HOW["hips"] = HOW["hip"]
# Garment charts describe the item, not the body: tell shoppers to lay a piece they own flat.
HOW_GARMENT = {
    "length": ("Length: lay the item flat and measure from the highest point of the shoulder down to the hem.",
               "الطول: افرد القطعة وقِس من أعلى نقطة في الكتف حتى نهاية القطعة."),
    "sleeve": ("Sleeve: lay the item flat and measure from the shoulder seam to the end of the cuff.",
               "طول الكم: افرد القطعة وقِس من خياطة الكتف حتى نهاية الكم."),
    "shoulder": ("Shoulder: lay the item flat and measure straight across from one shoulder seam to the other.",
                 "عرض الكتف: افرد القطعة وقِس بشكل مستقيم من خياطة الكتف إلى خياطة الكتف الأخرى."),
    "inseam": ("Inseam: lay the item flat and measure along the inside leg seam from the crotch to the hem.",
               "طول الساق الداخلي: افرد القطعة وقِس على الخياطة الداخلية للرجل من أعلاها حتى نهايتها."),
    "rise": ("Rise: lay the item flat and measure from the crotch seam up to the top of the waistband.",
             "ارتفاع الوسط: افرد القطعة وقِس من خياطة منطقة التقاء الرجلين حتى أعلى حزام الوسط."),
    "neck": ("Neck: lay the collar flat and measure from the centre of the button to the far end of the buttonhole.",
             "الرقبة: افرد الياقة وقِس من منتصف الزر حتى نهاية العروة."),
    "foot_length": ("Foot length: measure the inside of the shoe (insole) from heel to toe.",
                    "طول القدم: قِس داخل الحذاء (النعل الداخلي) من الكعب حتى المقدمة."),
}
# Where to measure each width on the garment: (flat en, flat ar, all round en, all round ar).
GARMENT_WIDTH = {
    "chest": ("from armpit to armpit", "من الإبط إلى الإبط", "just under the arms", "تحت الإبط مباشرة"),
    "waist": ("across the waistline", "عند خط الوسط", "at the waistline", "عند خط الوسط"),
    "hip": ("across the widest part of the hips", "عند أعرض جزء من الأرداف",
            "at the widest part of the hips", "عند أعرض جزء من الأرداف"),
    "thigh": ("across the top of the leg", "عند أعلى الرجل", "around the top of the leg", "حول أعلى الرجل"),
    "bicep": ("across the sleeve just below the armpit", "عرض الكم أسفل الإبط مباشرة",
              "around the sleeve just below the armpit", "حول الكم أسفل الإبط مباشرة"),
    "hem": ("along the bottom edge", "عند الحافة السفلية", "around the bottom edge", "حول الحافة السفلية"),
    "leg_opening": ("across the bottom of the leg", "عند فتحة الرجل", "around the bottom of the leg", "حول فتحة الرجل"),
}
for _a, _b in (("bust", "chest"), ("underbust", "chest"), ("hips", "hip"), ("seat", "hip")):
    GARMENT_WIDTH[_a] = GARMENT_WIDTH[_b]


def how_text(name, li, basis, double):
    """How-to-measure line for one measurement, in body or garment wording."""
    if basis != "garment":
        h = HOW.get(name)
        return h[li] if h else None
    w = GARMENT_WIDTH.get(name)
    if w:
        label = LABELS.get(name, (name.replace("_", " ").capitalize(),) * 2)[li]
        if double:
            return (f"{label}: lay the item flat and measure straight across {w[0]}. The chart shows this doubled "
                    f"(all the way round).", f"{label}: افرد القطعة وقِس بشكل مستقيم {w[1]}. الجدول يعرض الرقم "
                    f"مضروبًا في 2 (المحيط كاملًا).")[li]
        return (f"{label}: measure all the way around the item {w[2]}.",
                f"{label}: قِس حول القطعة بالكامل {w[3]}.")[li]
    h = HOW_GARMENT.get(name)
    return h[li] if h else None
GENERAL = {
    "body": ("Measure your body over light clothing with a soft tape. Keep the tape snug, not tight.",
             "قِس جسمك فوق ملابس خفيفة بشريط قياس مرن. الشريط ملامس للجسم بدون شد."),
    "garment": ("These are garment measurements. Width measurements were taken with the item laid flat and doubled. Compare with a piece you own that fits well.",
                "هذه مقاسات القطعة نفسها. مقاسات العرض أُخذت والقطعة مفرودة ثم ضُربت في 2. قارنها بقطعة عندك مقاسها مناسب."),
}
GENERAL["garment_full"] = (
    "These are garment measurements, taken all the way around the item. Compare with a piece you own that fits well.",
    "هذه مقاسات القطعة نفسها، مقاسة حول القطعة بالكامل. قارنها بقطعة عندك مقاسها مناسب.")
FIT = {
    "true-to-size": ("Fit: true to size. Choose your usual size.", "المقاس: طبيعي. اطلب مقاسك المعتاد."),
    "runs-small": ("Fit: runs small. We suggest one size up.", "المقاس: يأتي صغيرًا. ننصح بطلب مقاس أكبر."),
    "runs-large": ("Fit: runs large. We suggest one size down.", "المقاس: يأتي كبيرًا. ننصح بطلب مقاس أصغر."),
}
BETWEEN = ("Between two sizes? Pick the larger for a relaxed fit, the smaller for a closer fit.",
           "بين مقاسين؟ اختر الأكبر لراحة أكثر، والأصغر لقصة أقرب للجسم.")
TITLES = {"title": ("Size chart", "جدول المقاسات"), "how": ("How to measure", "طريقة القياس"),
          "inches": ("Show in inches", "عرض بالإنش"), "cm": ("Show in cm", "عرض بالسنتيمتر")}
EASTERN = str.maketrans("0123456789.", "٠١٢٣٤٥٦٧٨٩٫")
NUMERIC_LABEL = re.compile(r"[0-9][0-9\s./\-]*")


def digits_for(text, li, digits):
    """Eastern Arabic digits for numbers (measurements, numeric size labels like 38 or 36/37, EU/UK/US
    sizes) in the Arabic chart when that option is on. Letter sizes (S, XL) stay as they are."""
    t = str(text or "")
    if li == 1 and digits == "eastern" and NUMERIC_LABEL.fullmatch(t.strip()):
        return t.translate(EASTERN)
    return t


def _th(text, first, rtl):
    side = "right" if rtl else "left"
    sticky = f"position:sticky;{side}:0;z-index:1;" if first else ""
    return (f'<th scope="col" style="{sticky}background:#f4f4f4;color:#111;padding:8px 12px;border:1px solid #ddd;'
            f'text-align:center;font-weight:600">{html.escape(text)}</th>')


def _td(text, first, rtl):
    side = "right" if rtl else "left"
    if first:
        return (f'<th scope="row" style="position:sticky;{side}:0;background:#fafafa;color:#111;padding:8px 12px;'
                f'border:1px solid #ddd;text-align:center;font-weight:600">{html.escape(text)}</th>')
    return f'<td style="padding:8px 12px;border:1px solid #ddd;text-align:center">{html.escape(text)}</td>'


def _matrix(rows, meas, systems, unit, li, digits, warnings, double=False):
    """The chart exactly as shoppers see it: display headers and display values (flat widths doubled
    for garment charts, converted units, Eastern digits when chosen). Used by the HTML and the json table."""
    head = [LABELS["size"][li]]
    for c in systems:
        head.append(LABELS.get(c, (c.upper(), c.upper()))[li])
    for m in meas:
        lab = LABELS.get(m["name"])
        if lab is None:
            lab = (m["name"].replace("_", " ").capitalize(),) * 2
            warnings.add(f"no built-in label for '{m['name']}': check the {'Arabic' if li else 'English'} header")
        head.append(f"{lab[li]} ({UNIT[unit][li]})")
    body = []
    for r in rows:
        cells = [digits_for(r.get("size", ""), li, digits)]
        for c in systems:
            cells.append(digits_for(r.get(c, ""), li, digits))
        for m in meas:
            v, _ = parse_value(r.get(m["col"]))
            if v is not None and double and m["name"] in CIRCUMFERENCE:
                v = v * 2  # flat width -> full measurement around, as the garment note says
            if v is not None and m["unit"] != unit:
                v = round_half(v / 2.54 if unit == "in" else v * 2.54)
            cells.append(digits_for(fmt(v), li, digits) if v is not None else "-")
        body.append(cells)
    return head, body


def _table(rows, meas, systems, unit, li, rtl, digits, warnings, double=False):
    hdr, mat = _matrix(rows, meas, systems, unit, li, digits, warnings, double)
    head = [_th(t, i == 0, rtl) for i, t in enumerate(hdr)]
    body = ["<tr>" + "".join(_td(t, i == 0, rtl) for i, t in enumerate(cells)) + "</tr>" for cells in mat]
    return ('<div style="max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0">'
            '<table style="border-collapse:collapse;width:100%;min-width:max-content;white-space:nowrap;font-size:14px">'
            "<thead><tr>" + "".join(head) + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>")


def render_block(rows, meas, systems, lang, units, basis, fit_note, fit_text, title, digits, warnings, double=False):
    li = 1 if lang == "ar" else 0
    rtl = lang == "ar"
    attrs = 'dir="rtl" lang="ar" style="direction:rtl;text-align:right' if rtl else 'dir="ltr" lang="en" style="direction:ltr;text-align:left'
    parts = [f'<div class="replai-size-chart" {attrs};max-width:100%;margin:16px 0">']
    parts.append(f'<h3 style="margin:0 0 8px">{html.escape(title or TITLES["title"][li])}</h3>')
    first = "in" if units == "in" else "cm"
    parts.append(_table(rows, meas, systems, first, li, rtl, digits, warnings, double))
    if units == "both":
        parts.append(f'<details style="margin:4px 0 8px"><summary style="cursor:pointer;padding:8px 0">'
                     f'{TITLES["inches"][li]}</summary>'
                     + _table(rows, meas, systems, "in", li, rtl, digits, warnings, double) + "</details>")
    note = fit_note_for(fit_note, fit_text, li)
    strong = f"<strong>{html.escape(note)}</strong> " if note else ""
    parts.append(f'<p style="margin:8px 0">{strong}{html.escape(BETWEEN[li])}</p>')
    parts.append(f'<h4 style="margin:12px 0 4px">{TITLES["how"][li]}</h4>')
    general = GENERAL["garment_full"] if basis == "garment" and not double else GENERAL[basis]
    parts.append(f'<p style="margin:4px 0">{html.escape(general[li])}</p><ul style="margin:4px 0;padding-inline-start:20px">')
    done = set()
    for m in meas:
        h = how_text(m["name"], li, basis, double)
        if h and h not in done:
            done.add(h)
            parts.append(f'<li style="margin:2px 0">{html.escape(h)}</li>')
    parts.append("</ul></div>")
    return "".join(parts)


def fit_note_for(fit_note, fit_text, li):
    """The fit note for one language. fit_text is that language's custom text, "" when a custom note
    was given only in the other language (omitted rather than showing a default that contradicts it)."""
    if fit_text == "":
        return ""
    return fit_text or FIT.get(fit_note, FIT["true-to-size"])[li]


def custom_fit_texts(langs, fit_text, warnings):
    """A custom fit note in one language only: leave it out of the other language and warn."""
    out = dict(fit_text)
    given = [lg for lg in ("en", "ar") if fit_text.get(lg)]
    if given:
        for lang in langs:
            if not fit_text.get(lang):
                out[lang] = ""
                flag = "--fit-note-text-ar" if lang == "ar" else "--fit-note-text"
                warnings.add(f"custom fit note given only in {'English' if lang == 'ar' else 'Arabic'}: the "
                             f"{'Arabic' if lang == 'ar' else 'English'} chart has no fit note. Translate it and "
                             f"rerun with {flag} \"...\"")
    return out


def render(rows, meas, systems, langs, units, basis, fit_note, fit_text, titles, digits, measured="flat"):
    warnings = set()
    blocks = []
    double = basis == "garment" and measured == "flat"
    fit_text = custom_fit_texts(langs, fit_text, warnings)
    for lang in langs:
        t = titles.get(lang)
        ft = fit_text.get(lang)
        blocks.append(render_block(rows, meas, systems, lang, units, basis, fit_note, ft, t, digits, warnings, double))
    return "\n".join(blocks), sorted(warnings)


def table_json(rows, meas, systems, lang="en", units="cm", basis="body", fit_note="true-to-size", fit_text=None,
               title=None, digits="western", measured="flat"):
    """The json metafield value for one language (shape read by assets/size-chart-snippet.liquid):
    display headers and the same values the HTML shows (flat widths doubled, first unit of --units)."""
    li = 1 if lang == "ar" else 0
    unit = "in" if units == "in" else "cm"
    double = basis == "garment" and measured == "flat"
    hdr, mat = _matrix(rows, meas, systems, unit, li, digits, set(), double)
    note = fit_note_for(fit_note, fit_text, li)
    return {"unit": unit, "dir": "rtl" if li else "ltr", "title": title or TITLES["title"][li],
            "fit_note": (note + " " + BETWEEN[li]).strip(), "columns": hdr, "rows": mat}


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(description="Size chart helper (see module docstring).")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("file")
    v.add_argument("--tolerance-cm", type=float, default=1.0); v.add_argument("--tolerance-rel", type=float, default=0.5)
    c = sub.add_parser("convert"); c.add_argument("file"); c.add_argument("--to", choices=["cm", "in"], required=True)
    c.add_argument("--step", type=float, default=0.5); c.add_argument("--out")
    b = sub.add_parser("body"); b.add_argument("file")
    b.add_argument("--category", required=True); b.add_argument("--fit", required=True,
                   choices=["stretch", "fitted", "regular", "relaxed", "oversized"])
    b.add_argument("--measured", choices=["flat", "full"], default="flat")
    b.add_argument("--ease-file"); b.add_argument("--out")
    r = sub.add_parser("render"); r.add_argument("file"); r.add_argument("--out", required=True)
    r.add_argument("--lang", choices=["en", "ar", "both"], default="en")
    r.add_argument("--units", choices=["cm", "in", "both"], default="both")
    r.add_argument("--basis", choices=["body", "garment"], default="body")
    r.add_argument("--fit-note", choices=list(FIT), default="true-to-size")
    r.add_argument("--fit-note-text"); r.add_argument("--fit-note-text-ar")
    r.add_argument("--title"); r.add_argument("--title-ar")
    r.add_argument("--arabic-digits", choices=["western", "eastern"], default="western")
    r.add_argument("--measured", choices=["flat", "full"], default="flat",
                   help="with --basis garment: flat widths are doubled in the chart; full = already all the way round")
    a = p.parse_args(argv)

    rows, meas, systems, ignored = load(a.file)
    if a.cmd == "validate":
        res = validate_rows(rows, meas, systems, a.tolerance_cm, a.tolerance_rel)
        res["ignored_columns"] = ignored
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.cmd == "convert":
        out, cols = convert_rows(rows, meas, a.to, a.step)
        if a.out:
            write_csv(a.out, out, cols)
        print(json.dumps({"to": a.to, "step": a.step, "out": a.out, "rows": out}, ensure_ascii=False, indent=1))
    elif a.cmd == "body":
        out, notes = body_rows(rows, meas, a.category, a.fit, a.measured, a.ease_file)
        if a.out:
            cols = []
            for r in out:  # a blank first row must not drop columns other sizes have
                cols += [k for k in r if k not in cols]
            write_csv(a.out, [{c: r.get(c, "") for c in cols} for r in out], cols)
        print(json.dumps({"category": a.category, "fit": a.fit, "measured": a.measured, "notes": notes,
                          "estimate": "body ranges are estimates from typical ease; say so to shoppers",
                          "out": a.out, "rows": out}, ensure_ascii=False, indent=1))
    elif a.cmd == "render":
        langs = ["en", "ar"] if a.lang == "both" else [a.lang]
        fit_texts = {"en": a.fit_note_text, "ar": a.fit_note_text_ar}
        titles = {"en": a.title, "ar": a.title_ar}
        snippet, warnings = render(rows, meas, systems, langs, a.units, a.basis, a.fit_note,
                                   fit_texts, titles, a.arabic_digits, a.measured)
        shown_texts = custom_fit_texts(langs, fit_texts, set())
        tables = {lg: table_json(rows, meas, systems, lg, a.units, a.basis, a.fit_note, shown_texts.get(lg),
                                 titles.get(lg), a.arabic_digits, a.measured) for lg in langs}
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(snippet + "\n")
        size = len(snippet.encode("utf-8"))
        if size > 65536:
            warnings.append(f"snippet is {size} bytes: too big for a Shopify text metafield (64 KB limit). "
                            "Use fewer languages or units, or the json metafield, or a page")
        val = validate_rows(rows, meas, systems)
        print(json.dumps({"out": a.out, "chars": len(snippet), "bytes": size, "languages": langs, "units": a.units,
                          "basis": a.basis, "widths_doubled": a.basis == "garment" and a.measured == "flat",
                          "warnings": warnings, "validation_counts": val["counts"],
                          "table": tables[langs[0]], "tables": tables}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
