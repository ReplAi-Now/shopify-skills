"""True profit per product, per order and per channel. Python 3 standard library only, no network.

Usage:
    python3 profit.py --orders orders_export.csv --setup replai-setup/true-profit.json
        [--costs product_costs.csv]              # Shopify products export, cost sheet or invoice CSV
        [--ads meta=meta.csv --ads tiktok=tiktok.csv --ads google=google.csv]
        [--ad-map ad_product_map.csv]            # campaign / ad set / ad name -> product
        [--courier courier.csv::CourierName] [--courier-map status="State"]
        [--returns returns.csv]                  # units sent back after delivery (Try & Buy, restock without refund)
        [--out-dir results/]

Prints one JSON object: totals, products (units, revenue, COGS, ads, shipping, RTO cost,
returns, fees, contribution, margin, break-even ROAS), bestsellers that lose money,
orders summary, sales channels, ad platforms, assumptions and warnings.
Exit code 2 with {"error": "need_fx_rate", ...} when an ad or cost currency differs from the
store currency and setup has no rate for it. With --out-dir writes products.csv,
orders.csv, channels.csv, ad_platforms.csv.
"""
import argparse, csv, datetime, json, os, re, sys, tempfile, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tabular  # noqa: E402
from tabular import read_rows, pick, num, norm, write_csv  # noqa: E402
from orders import load_orders, load_courier, CourierIndex, classify, is_cod, _iso_date, order_key  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETUP = os.path.join(HERE, "..", "assets", "setup.example.json")


def r2(x):
    return None if x is None else round(x + 0.0, 2)


def r4(x):
    return None if x is None else round(x + 0.0, 4)


def die(obj, code=2):
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    sys.exit(code)


def load_setup(path):
    with open(DEFAULT_SETUP, encoding="utf-8") as fh:
        base = json.load(fh)
    if path:
        with open(path, encoding="utf-8") as fh:
            base.update(json.load(fh))
    return base


def fx(currency, S, what):
    cur = (currency or "").upper().strip()
    store = S.get("currency", "").upper()
    if not cur or cur == store:
        return 1.0
    rate = (S.get("fx_rates") or {}).get(cur)
    if not rate:
        die({"error": "need_fx_rate", "currency": cur, "store_currency": store, "for": what,
             "fix": f"Ask the merchant: how many {store} is 1 {cur} for this period? Save it in setup fx_rates."})
    return float(rate)


# ---------- product costs ----------

def load_costs(path, S):
    """Return (by_sku, by_title, titles). Accepts the Shopify products export (legacy headers Handle,
    Title, Variant SKU, Cost per item, or the 2026 headers URL handle, Title, SKU, Cost per item),
    a cost sheet, or the invoice template in assets/."""
    rows = read_rows(path)
    if not rows:
        return {}, {}, []
    cols = set(rows[0].keys())
    cost_col = next((c for c in ("cost_per_item", "unit_cost", "cost", "cost_per_unit", "unit_price_cost",
                                 "landed_cost", "unitcost") if c in cols), None)
    if not cost_col:
        die({"error": "missing column", "wanted": "Cost per item (or unit_cost)", "file": path,
             "columns": sorted(cols)}, 1)
    by_sku, titles_cost, last_title = {}, {}, {}
    for r in rows:
        handle = pick(r, "handle", "url_handle")
        title = pick(r, "title", "product", "product_title", "name")
        if handle:
            if title:
                last_title[handle] = title
            else:
                title = last_title.get(handle, "")
        raw = r.get(cost_col, "")
        if str(raw).strip() == "":
            continue
        rate = fx(pick(r, "currency"), S, f"product cost in {os.path.basename(path)}")
        c = num(raw) * rate
        sku = pick(r, "variant_sku", "sku")
        if sku:
            by_sku[sku.strip().lower()] = c
        if title:
            titles_cost.setdefault(title.strip(), []).append(c)
    by_title = {t.lower(): sum(v) / len(v) for t, v in titles_cost.items()}
    return by_sku, by_title, sorted(titles_cost, key=len, reverse=True)


def product_key(line_name, titles, group_by):
    if group_by == "variant":
        return line_name
    low = line_name.lower()
    for t in titles:
        tl = t.lower()
        if low == tl or low.startswith(tl + " - "):
            return t
    return line_name.rsplit(" - ", 1)[0] if " - " in line_name else line_name


# ---------- ads ----------

SPEND = re.compile(r"^(amount_spent|spend|cost|total_cost|spent|المبلغ_المنفق|المبلغ_الذي_تم_إنفاقه|الإنفاق|التكلفة)"
                   r"(_\(([a-z]{3})\))?$")
TITLE_HINT = ("campaign", "حملة", "الحملة")
SPEND_HINT = ("cost", "spen", "المنفق", "إنفاق", "الإنفاق", "التكلفة")


def _is_header(cells):
    low = " ".join(str(c) for c in cells).lower()
    return any(h in low for h in TITLE_HINT) and any(h in low for h in SPEND_HINT)


def _xlsx_grid(path):
    """First sheet of an XLSX as a list of rows (lists of text), title rows included."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    ns = tabular._NS
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in tabular.ET.fromstring(z.read("xl/sharedStrings.xml")).findall(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)", n.split("/")[-1]).group(1)))
    grid = []
    for row in (tabular.ET.fromstring(z.read(sheets[0])).iter(ns + "row") if sheets else []):
        vals = {}
        for c in row.findall(ns + "c"):
            v, t = c.find(ns + "v"), c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(ns + "t"))
            else:
                val = v.text if v is not None else ""
            vals[tabular._cell_index(c.get("r"))] = val or ""
        if vals:
            grid.append([vals.get(i, "") for i in range(max(vals) + 1)])
    return grid


def read_ads_table(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        # Google Ads XLSX starts with a report title and a date line, like its CSV.
        grid = _xlsx_grid(path)
        start = next((i for i, r in enumerate(grid[:15]) if _is_header(r)), 0)
        if start:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
            csv.writer(tmp).writerows(grid[start:])
            tmp.close()
            try:
                return read_rows(tmp.name)
            finally:
                os.unlink(tmp.name)
        return read_rows(path)
    if path.lower().endswith((".csv", ".tsv", ".txt")):
        with open(path, "rb") as fh:
            raw = fh.read()
        text, enc = None, None
        for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        lines = text.splitlines()
        start = 0
        for i, ln in enumerate(lines[:15]):
            if _is_header([ln]):
                start = i
                break
        if start or enc == "utf-16":   # title lines to skip, or a UTF-16 file read_rows cannot decode
            tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
            tmp.write("\n".join(lines[start:]))
            tmp.close()
            try:
                return read_rows(tmp.name)
            finally:
                os.unlink(tmp.name)
    return read_rows(path)


def load_ads(platform, path, S):
    rows = read_ads_table(path)
    if not rows:
        return []
    cols = list(rows[0].keys())
    spend_col, cur_from_header = None, None
    for c in cols:
        m = SPEND.match(c)
        if m:
            spend_col, cur_from_header = c, (m.group(3) or "").upper() or None
            break
    if not spend_col:
        die({"error": "missing column", "wanted": "spend (Amount spent / Cost / Spend)", "file": path,
             "columns": cols}, 1)

    def col(*names):
        return next((n for n in names if n in cols), None)
    # English headers, then the Arabic ones Meta / TikTok / Google write in an Arabic interface.
    camp = col("campaign_name", "campaign", "اسم_الحملة", "الحملة")
    adset = col("ad_set_name", "adset_name", "ad_group_name", "ad_group", "ad_set",
                "اسم_مجموعة_الإعلانات", "مجموعة_الإعلانات", "اسم_المجموعة_الإعلانية")
    ad = col("ad_name", "ad", "اسم_الإعلان", "الإعلان")
    purch = col("purchases", "website_purchases", "conversions", "total_complete_payment",
                "complete_payment", "purchase", "orders", "عمليات_الشراء", "المشتريات", "التحويلات", "الإحالات_الناجحة")
    value = col("purchases_conversion_value", "purchase_conversion_value", "conversion_value",
                "conv._value", "total_complete_payment_value", "total_purchase_value", "purchase_value",
                "قيمة_تحويل_عمليات_الشراء", "قيمة_التحويل", "قيمة_الإحالات_الناجحة")
    date = col("day", "date", "reporting_starts", "by_day", "stat_time_day", "start_date",
               "التاريخ", "اليوم", "بداية_التقارير", "بدء_إعداد_التقارير")
    curc = col("currency", "currency_code", "العملة", "رمز_العملة")
    names = [c for c in (camp, adset, ad) if c]
    out = []
    for r in rows:
        cname = r.get(camp, "") if camp else ""
        low = cname.strip().lower()
        # Total rows: Google "Total: ...", TikTok "Total of N ...", "--". A campaign named "Total Look" is kept.
        if low in ("total", "totals", "--", "الإجمالي", "المجموع") or \
                low.startswith(("total:", "total of ", "totals:", "الإجمالي:", "الإجمالي ")):
            continue
        sp = num(r.get(spend_col, ""))
        # Meta "Include summary row": every name column blank. Real rows always carry a name.
        if names and not any(str(r.get(c, "")).strip() for c in names):
            continue
        if not cname and sp == 0:
            continue
        cur = cur_from_header or (r.get(curc, "") if curc else "") or \
            (S.get("ad_currency") or {}).get(platform) or S.get("currency", "")
        rate = fx(cur, S, f"{platform} ad spend")
        out.append({"platform": platform, "campaign": cname, "adset": r.get(adset, "") if adset else "",
                    "ad": r.get(ad, "") if ad else "", "spend": sp * rate, "spend_original": sp,
                    "currency": cur.upper(), "purchases": num(r.get(purch, "")) if purch else 0.0,
                    "value": num(r.get(value, "")) * rate if value else 0.0,
                    "date": _iso_date(r.get(date, ""), False) if date else ""})   # XLSX gives Excel serials
    return out


def load_ad_map(path):
    rules = []
    for i, r in enumerate(read_rows(path)):
        contains = pick(r, "contains", "pattern", "match", "name_contains").strip().lower()
        prod = pick(r, "product", "products", "product_title").strip()
        if not contains or not prod:
            continue
        level = (pick(r, "level", "match_on") or "campaign").strip().lower().replace(" ", "")
        level = {"adgroup": "adset", "ad_set": "adset", "ad_group": "adset"}.get(level, level)
        rules.append({"platform": pick(r, "platform").strip().lower(), "level": level,
                      "contains": contains, "product": prod, "order": i})
    prio = {"ad": 0, "adset": 1, "campaign": 2}
    rules.sort(key=lambda x: (prio.get(x["level"], 3), -len(x["contains"]), x["order"]))
    return rules


def match_rule(row, rules):
    for ru in rules:
        if ru["platform"] and ru["platform"] != row["platform"]:
            continue
        if ru["contains"] in str(row.get(ru["level"], "")).lower():
            return ru
    return None


# ---------- returns after delivery ----------

def load_returns(path):
    """Units sent back after delivery, by order key: {key: [(sku, name, qty)]}. Accepts a returns CSV
    with an order column (order / order name / order number), a SKU or product column and a quantity
    column; with a `restock_type` column only RETURN rows count (the connector's refundLineItems)."""
    rows = read_rows(path)
    if not rows:
        return {}
    cols = set(rows[0].keys())
    if not cols & {"order", "order_name", "order_number", "name", "order_id"}:
        die({"error": "missing column", "wanted": "order (order name, e.g. #1001)", "file": path,
             "columns": sorted(cols)}, 1)
    out = {}
    for r in rows:
        rt = pick(r, "restock_type", "restocktype").lower()
        if rt and "return" not in rt:
            continue
        q = abs(num(pick(r, "quantity", "returned_quantity", "qty", "units"), 1.0))
        k = order_key(pick(r, "order", "order_name", "order_number", "name", "order_id"))
        if q and k:
            out.setdefault(k, []).append((pick(r, "sku", "lineitem_sku", "variant_sku").strip().lower(),
                                          pick(r, "product", "lineitem_name", "line_item", "title").strip().lower(), q))
    return out


def returned_units(o, returns):
    """Returned quantity per order line (index -> qty), from the orders column and/or the returns file."""
    got = {i: ln.get("returned", 0.0) for i, ln in enumerate(o["lines"])}
    left = [list(x) for x in returns.get(o["key"], [])]
    for i, ln in enumerate(o["lines"]):
        sku, name = ln["sku"].strip().lower(), ln["name"].lower()
        q = 0.0
        for x in left:
            if x[2] > 0 and ((sku and x[0] == sku) or (not x[0] and x[1] and (name == x[1] or name.startswith(x[1] + " - ")))):
                take = min(x[2], ln["qty"] - q)
                q += take
                x[2] -= take
        got[i] = min(ln["qty"], max(got[i], q))
    return got


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--setup")
    ap.add_argument("--costs")
    ap.add_argument("--ads", action="append", default=[])
    ap.add_argument("--ad-map")
    ap.add_argument("--courier", action="append", default=[])
    ap.add_argument("--courier-map", action="append", default=[])
    ap.add_argument("--returns")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    S = load_setup(a.setup)
    cur = S.get("currency", "")
    warnings, assumptions = [], []

    orders = load_orders(a.orders)
    by_sku, by_title, titles = load_costs(a.costs, S) if a.costs else ({}, {}, [])
    if not a.costs:
        warnings.append("No product cost file given: every product shows cost missing and no profit. Give a costs file (see references/data-sources.md).")
    overrides = {}   # meaning -> [headers]; repeat --courier-map for files with different headers
    for x in a.courier_map:
        k, _, v = x.partition("=")
        overrides.setdefault(k.strip(), []).append(v.strip())
    crow = []
    for spec in a.courier:
        path, _, cname = spec.partition("::")
        rows, _ = load_courier(path, cname, overrides)
        crow += rows
    cidx = CourierIndex(crow, S)
    returns = load_returns(a.returns) if a.returns else {}
    has_returned_col = any(ln.get("returned") for o in orders for ln in o["lines"])

    def default(key, label):
        v = S.get(key)
        if v is None:
            warnings.append(f"No {label} in setup and no courier value: counted as 0, so profit is overstated.")
            S[key] = 0.0
            return 0.0
        return float(v)
    d_ship = default("shipping_cost_per_order", "shipping cost per order")
    d_ret = default("return_shipping_per_order", "return shipping cost per failed order")
    pack = float(S.get("packaging_cost_per_order") or 0)
    g_pct, g_fix = float(S.get("gateway_fee_pct") or 0), float(S.get("gateway_fee_fixed") or 0)
    c_pct, c_fix = float(S.get("cod_fee_pct") or 0), float(S.get("cod_fee_fixed") or 0)
    group_by = S.get("group_by", "product")
    incl_tax = bool(S.get("prices_include_tax", False))
    restock = bool(S.get("refund_restock", True))

    P = {}   # product -> metrics

    def prod(k):
        if k not in P:
            P[k] = {"product": k, "orders": set(), "units_sold": 0.0, "units_rto": 0.0, "gross_sales": 0.0,
                    "discounts": 0.0, "refunds": 0.0, "tax_removed": 0.0, "shipping_income": 0.0,
                    "net_revenue": 0.0, "cogs": 0.0, "cost_missing": False, "shipping_cost": 0.0,
                    "payment_fees": 0.0, "packaging": 0.0, "rto_cost": 0.0, "rto_gross": 0.0, "ads": 0.0,
                    "units_returned": 0.0, "returns_not_refunded": 0.0}
        return P[k]

    order_rows, counts, missing_cost_lines, zero_cost = [], {}, {}, set()
    gift_cod_unknown, try_buy_tagged, returned_total = 0, 0, 0.0
    for o in orders:
        c = cidx.match(o)
        # Same rules as cod-rto-analysis: shipped but neither paid nor failed is open (still with the
        # courier, or not updated) and is left out of profit, not counted as delivered.
        outcome = classify(o, S, c)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome not in ("delivered", "failed") or not o["lines"]:
            continue
        cod = is_cod(o, S.get("cod_payment_keywords", []))
        G = sum(ln["price"] * ln["qty"] for ln in o["lines"])
        Q = sum(ln["qty"] for ln in o["lines"]) or 1.0
        lines = []
        for ln in o["lines"]:
            g = ln["price"] * ln["qty"]
            share = g / G if G else ln["qty"] / Q
            unit = by_sku.get(ln["sku"].strip().lower()) if ln["sku"] else None
            key = product_key(ln["name"], titles, group_by)
            if unit is None:
                unit = by_title.get(ln["name"].lower(), by_title.get(key.lower()))
            lines.append((ln, g, share, key, unit))
        orow = {"order": o["name"], "date": o["date"], "outcome": outcome, "cod": cod,
                "channel": o["source"] or "unknown", "net_revenue": 0.0, "cogs": 0.0, "costs": 0.0,
                "ads": 0.0, "cost_missing": False, "lines": []}
        if outcome == "failed":
            out_fee = c["shipping_fee"] if c and c["shipping_fee"] is not None else d_ship
            ret_fee = c["return_fee"] if c and c["return_fee"] is not None else d_ret
            cod_fee = (c["cod_fee"] if c and c["cod_fee"] is not None else c_fix) if cod else 0.0
            rto = out_fee + ret_fee + cod_fee + pack
            for ln, g, share, key, unit in lines:
                p = prod(key)
                if unit is None:   # a product without a cost is unknown whatever happened to its orders
                    p["cost_missing"] = True
                    missing_cost_lines[key] = missing_cost_lines.get(key, 0) + ln["qty"]
                p["units_rto"] += ln["qty"]
                p["rto_gross"] += g
                p["rto_cost"] += rto * share
            orow.update({"costs": rto, "rto_cost": rto})
            order_rows.append(orow)
            continue
        ship = c["shipping_fee"] if c and c["shipping_fee"] is not None else d_ship
        if cod:
            # A COD % fee applies to the cash collected: total minus any gift card part.
            cash = max(0.0, o["total"] - o["gift_card"])
            if not o["gift_card"] and "gift" in str(o["payment"]).lower() and c_pct and not (c and c["cod_fee"] is not None):
                gift_cod_unknown += 1
            fee = c["cod_fee"] if c and c["cod_fee"] is not None else cash * c_pct / 100 + c_fix
        else:
            fee = o["total"] * g_pct / 100 + g_fix
        if any("try" in t and "buy" in t for t in o["tags"]):
            try_buy_tagged += 1
        goods = G - o["discount"]
        frac = min(1.0, o["refunded"] / goods) if (restock and goods > 0 and o["refunded"] > 0) else 0.0
        # Units sent back after delivery (Try & Buy, restock without refund): their value, net of
        # discount, comes off revenue where the refund does not already cover it.
        ret = returned_units(o, returns)
        dfac = (1 - o["discount"] / G) if G else 1.0
        ret_val = {i: ln["price"] * ret[i] * dfac for i, ln in enumerate(o["lines"])}
        tot_ret = sum(ret_val.values())
        unrefunded = max(0.0, tot_ret - o["refunded"])
        returned_total += unrefunded
        for idx, (ln, g, share, key, unit) in enumerate(lines):
            p = prod(key)
            p["orders"].add(o["name"])
            disc, si, rf = o["discount"] * share, o["shipping"] * share, o["refunded"] * share
            tx = o["taxes"] * share if incl_tax else 0.0
            back = unrefunded * ret_val[idx] / tot_ret if tot_ret else 0.0
            net = g - disc + si - tx - rf - back
            p["units_sold"] += ln["qty"] - ret[idx]
            p["units_returned"] += ret[idx]
            p["returns_not_refunded"] += back
            p["gross_sales"] += g
            p["discounts"] += disc
            p["shipping_income"] += si
            p["refunds"] += rf
            p["tax_removed"] += tx
            p["net_revenue"] += net
            if unit is None:
                p["cost_missing"] = True
                cogs = None
                orow["cost_missing"] = True
                missing_cost_lines[key] = missing_cost_lines.get(key, 0) + ln["qty"]
            else:
                if unit == 0:
                    zero_cost.add(key)
                back_frac = ret[idx] / ln["qty"] if ln["qty"] else 0.0   # returned units are back in stock
                cogs = unit * ln["qty"] * (1 - max(frac, back_frac))
                p["cogs"] += cogs
                orow["cogs"] += cogs
            p["shipping_cost"] += ship * share
            p["payment_fees"] += fee * share
            p["packaging"] += pack * share
            orow["net_revenue"] += net
            orow["lines"].append((key, net))
        orow["costs"] = ship + fee + pack
        order_rows.append(orow)

    # ---- ads ----
    ad_rows = []
    for spec in a.ads:
        platform, _, path = spec.partition("=")
        if not path:
            platform, path = os.path.splitext(os.path.basename(spec))[0], spec
        ad_rows += load_ads(platform.strip().lower(), path, S)
    rules = load_ad_map(a.ad_map) if (a.ad_map and S.get("ad_allocation", "mapping") == "mapping") else []
    base = {k: max(0.0, p["net_revenue"]) for k, p in P.items()}
    total_base = sum(base.values())
    lookup = {k.lower(): k for k in P}
    unknown_products, mapped_spend, shared_spend = set(), 0.0, 0.0

    def spread(amount, keys):
        b = sum(base.get(k, 0) for k in keys)
        for k in keys:
            P[k]["ads"] += amount * (base.get(k, 0) / b if b else 1.0 / len(keys))

    for row in ad_rows:
        ru = match_rule(row, rules) if rules else None
        targets = []
        if ru and ru["product"].upper() != "SHARED":
            for name in ru["product"].split("|"):
                k = lookup.get(name.strip().lower())
                if k:
                    targets.append(k)
                else:
                    unknown_products.add(name.strip())
        row["allocated_to"] = "|".join(targets) if targets else "shared"
        if targets:
            spread(row["spend"], targets)
            mapped_spend += row["spend"]
        else:
            shared_spend += row["spend"]
            if total_base:
                spread(row["spend"], [k for k in P if base.get(k, 0) > 0])
    if unknown_products:
        warnings.append("Ad map names products not found in the orders (spend shared by revenue instead): " + ", ".join(sorted(unknown_products)))
    total_ads = sum(r["spend"] for r in ad_rows)

    # ---- product results ----
    products = []
    for k, p in P.items():
        known = not p["cost_missing"]
        cba = (p["net_revenue"] - p["cogs"] - p["shipping_cost"] - p["payment_fees"] - p["packaging"] - p["rto_cost"]) if known else None
        contrib = cba - p["ads"] if known else None
        row = {kk: (r2(v) if isinstance(v, float) else v) for kk, v in p.items() if kk != "orders"}
        row["orders"] = len(p["orders"])
        row["units_sold"] = p["units_sold"]
        row["units_rto"] = p["units_rto"]
        row["units_returned"] = p["units_returned"]
        row["cogs"] = r2(p["cogs"]) if known else None
        row["contribution_before_ads"] = r2(cba)
        row["contribution"] = r2(contrib)
        row["margin"] = r4(contrib / p["net_revenue"]) if known and p["net_revenue"] else None
        row["break_even_roas"] = r2(p["net_revenue"] / cba) if known and cba and cba > 0 else None
        row["break_even_platform_roas"] = r2((p["gross_sales"] + p["rto_gross"]) / cba) if known and cba and cba > 0 else None
        row["actual_roas"] = r2(p["net_revenue"] / p["ads"]) if p["ads"] else None
        row["never_breaks_even"] = bool(known and cba is not None and cba <= 0)
        products.append(row)
    products.sort(key=lambda x: (-(x["net_revenue"] or 0), x["product"]))

    topn = int(S.get("bestseller_top_n", 10))
    best = sorted(products, key=lambda x: (-x["units_sold"], -(x["net_revenue"] or 0)))[:topn]
    losers = []
    for x in best:
        if x["contribution"] is not None and x["contribution"] < 0:
            loss = -x["contribution"]
            losers.append({"product": x["product"], "units_sold": x["units_sold"], "net_revenue": x["net_revenue"],
                           "contribution": x["contribution"], "ads": x["ads"],
                           "contribution_before_ads": x["contribution_before_ads"],
                           "price_increase_per_unit_to_break_even": r2(loss / x["units_sold"]) if x["units_sold"] else None,
                           "ad_cut_to_break_even": r2(loss) if x["ads"] and x["ads"] >= loss else None,
                           "problem": "ads" if (x["contribution_before_ads"] or 0) > 0 else "price_or_cost"})

    # ---- orders ----
    ads_per_rev = {k: (P[k]["ads"] / base[k]) if base.get(k) else 0.0 for k in P}
    out_orders, attached = [], 0.0
    for orow in order_rows:
        ads = sum(max(0.0, net) * ads_per_rev.get(k, 0) for k, net in orow["lines"])
        attached += ads
        if orow["outcome"] == "failed":
            contrib = -orow["costs"]
        elif orow["cost_missing"]:
            contrib = None
        else:
            contrib = orow["net_revenue"] - orow["cogs"] - orow["costs"] - ads
        out_orders.append({"order": orow["order"], "date": orow["date"], "outcome": orow["outcome"],
                           "channel": orow["channel"], "cod": orow["cod"], "net_revenue": r2(orow["net_revenue"]),
                           "cogs": None if orow["cost_missing"] else r2(orow["cogs"]),
                           "shipping_fees_packaging_or_rto": r2(orow["costs"]), "ads": r2(ads),
                           "contribution": r2(contrib)})
    delivered = [x for x in out_orders if x["outcome"] == "delivered"]
    failed = [x for x in out_orders if x["outcome"] == "failed"]
    known_del = [x for x in delivered if x["contribution"] is not None]
    orders_summary = {
        "delivered": len(delivered), "failed_rto": len(failed),
        "delivery_rate": r4(len(delivered) / (len(delivered) + len(failed))) if (delivered or failed) else None,
        "avg_net_revenue_per_delivered_order": r2(sum(x["net_revenue"] for x in delivered) / len(delivered)) if delivered else None,
        "avg_contribution_per_delivered_order": r2(sum(x["contribution"] for x in known_del) / len(known_del)) if known_del else None,
        "avg_cost_per_rto_order": r2(sum(-x["contribution"] for x in failed) / len(failed)) if failed else None,
        "delivered_orders_losing_money": sum(1 for x in known_del if x["contribution"] < 0),
        "orders_with_missing_cost": sum(1 for x in delivered if x["contribution"] is None),
        "worst_orders": sorted([x for x in out_orders if x["contribution"] is not None], key=lambda x: x["contribution"])[:10],
    }

    # ---- channels ----
    ch = {}
    for x in out_orders:
        c = ch.setdefault(x["channel"], {"channel": x["channel"], "delivered": 0, "failed_rto": 0, "net_revenue": 0.0,
                                         "contribution_known": 0.0, "orders_missing_cost": 0, "delivered_with_cost": 0})
        c["delivered" if x["outcome"] == "delivered" else "failed_rto"] += 1
        c["net_revenue"] += x["net_revenue"] or 0
        if x["contribution"] is None:
            c["orders_missing_cost"] += 1
        else:
            c["contribution_known"] += x["contribution"]
            if x["outcome"] == "delivered":
                c["delivered_with_cost"] += 1
    for c in ch.values():
        # contribution: n/a as soon as one delivered order lacks a cost. contribution_known: the part
        # with costs, n/a when no delivered order has one (failed-delivery costs alone are not a profit).
        c["contribution"] = None if c["orders_missing_cost"] else c["contribution_known"]
        if c["delivered"] and not c["delivered_with_cost"]:
            c["contribution_known"] = None
    channels = [{k: r2(v) if isinstance(v, float) else v for k, v in c.items()} for c in
                sorted(ch.values(), key=lambda c: -c["net_revenue"])]

    known_products = [x for x in products if x["contribution"] is not None]
    # Break-even cost per delivered order: contribution before ads of the delivered orders that have
    # costs, minus failed-delivery costs, divided by those delivered orders only.
    cba_orders = sum(x["contribution"] + x["ads"] for x in known_del) + sum(x["contribution"] for x in failed)
    be_cpa = cba_orders / len(known_del) if known_del else None
    drate = orders_summary["delivery_rate"] or 0
    plat = {}
    for row in ad_rows:
        q = plat.setdefault(row["platform"], {"platform": row["platform"], "spend": 0.0, "purchases": 0.0,
                                              "purchase_value": 0.0, "mapped_spend": 0.0, "currency_in_file": set()})
        q["spend"] += row["spend"]
        q["purchases"] += row["purchases"]
        q["purchase_value"] += row["value"]
        q["currency_in_file"].add(row["currency"])
        if row["allocated_to"] != "shared":
            q["mapped_spend"] += row["spend"]
    platforms = []
    for q in plat.values():
        dp = q["purchases"] * drate
        platforms.append({"platform": q["platform"], "spend": r2(q["spend"]), "mapped_spend": r2(q["mapped_spend"]),
                          "currency_in_file": sorted(q["currency_in_file"]),
                          "platform_purchases": q["purchases"],
                          "platform_roas": r2(q["purchase_value"] / q["spend"]) if q["spend"] and q["purchase_value"] else None,
                          "cost_per_platform_purchase": r2(q["spend"] / q["purchases"]) if q["purchases"] else None,
                          "delivered_purchases_estimate": r2(dp),
                          "true_cpa_estimate": r2(q["spend"] / dp) if dp else None,
                          "break_even_cpa": r2(be_cpa)})

    # ---- totals ----
    dates = sorted(o["date"] for o in orders if o["date"])
    days = 0
    if dates:
        try:
            days = (datetime.date.fromisoformat(dates[-1]) - datetime.date.fromisoformat(dates[0])).days + 1
        except ValueError:
            days = 0
    ad_dates = sorted(r["date"] for r in ad_rows if r["date"])
    if ad_dates and dates and (ad_dates[0] < dates[0] or ad_dates[-1] > dates[-1]):
        warnings.append(f"Ad data runs {ad_dates[0]} to {ad_dates[-1]} but orders run {dates[0]} to {dates[-1]}. Export both for the same dates.")
    fixed = float(S.get("fixed_monthly_costs") or 0) * days / 30.0 if days else 0.0
    sumk = lambda key: r2(sum((x[key] or 0) for x in products))  # noqa: E731
    profit_known = bool(known_products)
    contrib_known = sum(x["contribution"] for x in known_products) if profit_known else None
    totals = {
        "net_revenue": sumk("net_revenue"), "gross_sales": sumk("gross_sales"), "discounts": sumk("discounts"),
        "refunds": sumk("refunds"), "cogs_known": sumk("cogs"), "shipping_cost": sumk("shipping_cost"),
        "payment_fees": sumk("payment_fees"), "packaging": sumk("packaging"), "rto_cost": sumk("rto_cost"),
        "ads_total": r2(total_ads), "ads_mapped": r2(mapped_spend), "ads_shared_by_revenue": r2(shared_spend),
        "ads_not_attached_to_orders": r2(total_ads - attached),
        "contribution_known_products": r2(contrib_known),
        "returns_not_refunded": r2(returned_total),
        "net_revenue_with_missing_cost": r2(sum(x["net_revenue"] for x in products if x["contribution"] is None)),
        "fixed_costs_for_period": r2(fixed) if fixed else None,
        "net_profit_known": r2(contrib_known - fixed) if (fixed and profit_known) else None,
    }
    totals["margin_known"] = r4(contrib_known / sum(x["net_revenue"] for x in known_products)) if known_products and sum(x["net_revenue"] for x in known_products) else None

    if counts.get("open"):
        warnings.append(f"{counts['open']} shipped orders are still open (not marked paid or failed: with the courier, or not updated). They are left out of profit; a courier file or updated statuses would settle them.")
    if not profit_known:
        warnings.insert(0, "No product has a unit cost, so profit is unknown: no profit, margin or money-losing bestseller can be shown. Give product costs (Shopify products export with Cost per item, or the cost template) and rerun.")
    if gift_cod_unknown:
        warnings.append(f"{gift_cod_unknown} COD orders were partly paid by gift card but the gift card amount is not in the file: the COD % fee was charged on the full total, so fees are slightly overstated.")
    if returns or has_returned_col:
        assumptions.append("Units sent back after delivery (returns file or returned quantity column) are back in stock; their value comes off revenue where no refund covers it.")
    else:
        assumptions.append("No returned-units data: items a customer sends back without a refund (Try & Buy, restock without refund) are not visible in the export, so revenue can be overstated. The connector's refunds (restockType RETURN) fill this gap; see references/data-sources.md.")
        if try_buy_tagged:
            warnings.append(f"{try_buy_tagged} delivered orders are tagged Try & Buy but no returned-units data was given: items handed back at the door are counted as sold. Give a returns file (--returns) to correct revenue.")
    if missing_cost_lines:
        lost_ads = sum(P[k]["ads"] for k in P if P[k]["cost_missing"])
        warnings.append("Products with no cost (left out of profit totals): " + ", ".join(sorted(missing_cost_lines))
                        + (f". Their share of ad spend ({lost_ads:,.0f} {cur}) is left out of contribution too." if lost_ads else ""))
    if zero_cost:
        warnings.append("Products with a unit cost of 0 (check it is not a blank cost saved as 0): " + ", ".join(sorted(zero_cost)))
    assumptions += [
        "Revenue = item price x quantity, minus discounts and refunds" + (", minus taxes included in prices" if incl_tax else "") + ", plus shipping charged to the customer. Order-level amounts are split across lines by line value.",
        "Failed (RTO) orders earn nothing and cost outbound + return shipping + COD fee + packaging; their goods are assumed back in stock unharmed.",
        ("Refunded goods are assumed back in stock (their cost is reversed in proportion to the refund)." if restock else "Refunded goods are assumed lost (cost not reversed)."),
        f"Payment fees: COD {c_pct:g}% + {c_fix:g}, card/wallet {g_pct:g}% + {g_fix:g} per order, unless the courier file gives the COD fee.",
        "Ad spend: " + ("campaigns matched in the ad map go to their products; the rest is shared by net revenue." if rules else "all spend shared across products by net revenue (no confirmed ad map)."),
        "Break-even ROAS = net revenue / contribution before ads. Platform break-even ROAS adds failed orders' value, because ad platforms count purchases before delivery.",
    ]
    rates = {k: v for k, v in (S.get("fx_rates") or {}).items() if v}
    used = sorted({r["currency"] for r in ad_rows if r["currency"] and r["currency"] != cur.upper()})
    if used:
        assumptions.append("Currency conversion: " + ", ".join(f"1 {c} = {rates[c]:g} {cur}" for c in used if c in rates) + " (rate given by the merchant).")
    if shared_spend and total_base == 0:
        warnings.append("Shared ad spend could not be spread: no delivered revenue.")

    result = {"currency": cur,
              "period": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None, "days": days},
              "order_outcomes": counts, "profit_known": profit_known, "totals": totals, "products": products,
              "bestsellers": [x["product"] for x in best],
              "bestsellers_losing_money": losers, "orders": orders_summary,
              "sales_channels": channels, "ad_platforms": platforms,
              "courier": {"rows": len(crow), "matched": len(cidx.used)},
              "assumptions": assumptions, "warnings": warnings}
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
        write_csv(os.path.join(a.out_dir, "products.csv"), products)
        write_csv(os.path.join(a.out_dir, "orders.csv"), out_orders)
        write_csv(os.path.join(a.out_dir, "channels.csv"), channels)
        write_csv(os.path.join(a.out_dir, "ad_platforms.csv"), platforms)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


if __name__ == "__main__":
    main()
