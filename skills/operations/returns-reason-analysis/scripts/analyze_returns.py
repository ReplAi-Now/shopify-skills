"""Return rates, reasons, money lost and fixes per product, variant, size, colour and vendor.

Usage:
    python3 analyze_returns.py --returns classified.csv [--orders orders_export.csv] [--setup setup.json]
        [--products products_export.csv] [--lexicon ../assets/reason-lexicon.json]
        [--as-of YYYY-MM-DD] [--start YYYY-MM-DD --end YYYY-MM-DD] [--csv-dir folder]

--returns   Output of classify_reasons.py (every row has a category).
--orders    Shopify orders export (CSV for Excel). Needed for return RATES (units sold). Without it
            you get reasons, money and counts only.
--products  Shopify products export, for "Cost per item" by Variant SKU (restocking loss).
--as-of     Analysis date (default today). The order window ends return_window_days +
            transit_buffer_days before it, so every order in the window had time to come back.
--start/--end  Order-date window override (inclusive). Default: analysis_days ending at maturity.
--csv-dir   Also write by_product.csv, by_variant.csv, by_size.csv, by_colour.csv, top_fixes.csv.

Return rate = units returned (refund or exchange) from orders PLACED in the window / units sold in
those same orders. Refused-at-door rows are reported separately and never count as returns.
Prints JSON. Python 3 standard library only, no network access.
"""
import argparse, datetime as dt, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, pick, num, write_csv  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {
    "currency": "",
    "return_window_days": 14,
    "transit_buffer_days": 7,
    "analysis_days": 90,
    "min_units_sold": 20,
    "min_returns": 3,
    "top_n": 10,
    "default_return_shipping_cost": None,
    "exchange_reship_cost": None,
    "handling_cost_per_return": 0,
    "unsellable_share": {},
    "size_option": "auto",
    "colour_option": "auto",
}
SIZE_RX = re.compile(r"^(xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl|\d{1,3}(\.5)?|\d{1,3}(\.5)? ?/ ?\d{1,3}(\.5)?|free ?size|one ?size|os|small|medium|large|x-large|"
                     r"\d{1,2}-\d{1,2} ?(y|yrs|years|m|months)?|مقاس واحد|فري سايز)$", re.I)


def fail(msg):
    print(json.dumps({"error": msg}, ensure_ascii=False))
    sys.exit(2)


def split_variant(title, setup):
    """Return (size, colour) from a variant title like 'M / Black'.

    Only " / " (spaced) separates options: that is Shopify's variant title format, and a bare "/" is
    part of a value such as the shoe size "36/37". Colours are shown in Title Case so "Red" and "red"
    are one row."""
    parts = [p.strip() for p in str(title or "").split(" / ") if p.strip() and p.strip() != "Default Title"]
    size = colour = ""
    so, co = setup.get("size_option", "auto"), setup.get("colour_option", "auto")
    if so != "auto" and int(so) <= len(parts):
        size = parts[int(so) - 1]
    if co != "auto" and int(co) <= len(parts):
        colour = parts[int(co) - 1]
    for p in parts:
        if so == "auto" and not size and SIZE_RX.match(p):
            size = p
        elif co == "auto" and not colour and not SIZE_RX.match(p):
            colour = p
    if re.fullmatch(r"(?i)x*[sml]|x+l|[2-6]xl", size):
        size = size.upper()   # letter sizes: "s" and "S" are one row
    return size, colour_name(colour)


def colour_name(c):
    """'red', 'RED', ' Red ' -> 'Red'; 'navy blue' -> 'Navy Blue'. Arabic is left as is."""
    c = " ".join(str(c or "").split())
    return c.title() if re.search(r"[A-Za-z]", c) else c


def okey(name):
    return re.sub(r"[^0-9a-z]", "", str(name or "").lower())


def parse_date(s):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def load_orders(path, setup):
    rows = read_rows(path)
    if rows and "name" not in rows[0]:
        fail("Orders file has no 'Name' column. Use Shopify admin > Orders > Export > CSV for Excel.")
    orders, lines = {}, []
    for r in rows:
        n = r.get("name", "")
        if not n:
            continue
        o = orders.setdefault(okey(n), {"date": None, "cancelled": False})
        if r.get("created_at") and o["date"] is None:
            o["date"] = parse_date(r["created_at"])
        if pick(r, "cancelled_at", "canceled_at") or r.get("financial_status", "").lower() == "voided":
            o["cancelled"] = True
        q = num(r.get("lineitem_quantity"), 0)
        if q > 0:
            name = r.get("lineitem_name", "")
            product, variant = name.rsplit(" - ", 1) if " - " in name else (name, "")
            lines.append({"order": okey(n), "sku": r.get("lineitem_sku", ""), "product": product,
                          "variant": variant, "vendor": r.get("vendor", ""), "qty": q,
                          "price": num(r.get("lineitem_price"), 0)})
    for l in lines:
        o = orders[l["order"]]
        l["date"], l["cancelled"] = o["date"], o["cancelled"]
    return orders, lines


def vkey(sku, product, variant):
    return sku or (f"{product} - {variant}" if variant else product)


def load_costs(path):
    out = {}
    for r in read_rows(path):
        sku = pick(r, "variant_sku", "sku")
        cost = pick(r, "cost_per_item", "variant_cost", "cost", "unit_cost")
        if sku and cost != "":
            out[sku] = num(cost)
    return out


SIZE_MIXED = "size_inconsistent"
SIZE_MIXED_INFO = {
    "label": "Inconsistent sizing between batches",
    "fix": "As many customers say too small as too large: the sizes are not consistent between production batches. "
           "Measure units from different batches against the size chart and the supplier spec sheet, and fix it "
           "with the supplier before shifting the size chart.",
}


def reason_info(cat, lex):
    return SIZE_MIXED_INFO if cat == SIZE_MIXED else lex["categories"][cat]


def top_of(reasons):
    """Main reason: the most units, ignoring "other" unless it is the only one. A tie between too small
    and too large is not a size direction: it is reported as inconsistent sizing between batches."""
    ranked = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
    named = [c for c, _ in ranked if c != "other"]
    if not named:
        return ranked[0][0] if ranked else None
    best = reasons[named[0]]
    tied = {c for c in named if reasons[c] == best}
    if {"size_too_small", "size_too_large"} <= tied:
        return SIZE_MIXED
    return named[0]


def new_group():
    return {"sold_units": 0.0, "returned_units": 0.0, "refund_units": 0.0, "exchange_units": 0.0,
            "refunded": 0.0, "return_shipping": 0.0, "reship": 0.0, "restock_loss": 0.0, "handling": 0.0,
            "shipments": 0.0, "reasons": {}}


def finish(name, g, setup, have_sales, key="name"):
    money = g["refunded"] + g["return_shipping"] + g["reship"] + g["restock_loss"] + g["handling"]
    reasons = dict(sorted(g["reasons"].items(), key=lambda kv: (-kv[1], kv[0])))
    top = top_of(reasons)
    top_units = (reasons["size_too_small"] + reasons["size_too_large"]) if top == SIZE_MIXED else reasons.get(top)
    out = {key: name, "sold_units": g["sold_units"] if have_sales else None,
           "returned_units": g["returned_units"], "refund_units": g["refund_units"],
           "exchange_units": g["exchange_units"],
           "return_rate": round(g["returned_units"] / g["sold_units"] * 100, 1) if have_sales and g["sold_units"] else None,
           "low_sample": (g["sold_units"] < setup["min_units_sold"]) if have_sales else None,
           "refunded": round(g["refunded"], 2), "return_costs": round(money - g["refunded"], 2),
           "money_lost": round(money, 2), "top_reason": top,
           "top_reason_share": round(top_units / g["returned_units"] * 100, 1) if top and g["returned_units"] else None,
           "reasons": reasons}
    return out


def analyze(returns, setup, lex, orders=None, lines=None, costs=None, as_of=None, start=None, end=None):
    costs = costs or {}
    notes = []
    have_sales = lines is not None
    as_of = as_of or dt.date.today()
    explicit_window = bool(start or end)
    maturity = as_of - dt.timedelta(days=setup["return_window_days"] + setup["transit_buffer_days"])
    end = end or maturity
    start = start or (end - dt.timedelta(days=setup["analysis_days"] - 1))
    if end > maturity:
        notes.append(f"Orders after {maturity} may still be returned (return window {setup['return_window_days']} days plus {setup['transit_buffer_days']} days transit), so return rates for this window are understated.")
    share = {c: s.get("unsellable_share", 0) for c, s in lex["categories"].items()}
    share.update(setup.get("unsellable_share") or {})

    # Sold units in the window, by group.
    groups = {k: {} for k in ("product", "variant", "size", "colour", "vendor")}
    sku_info, name_info, name_sku, price = {}, {}, {}, {}
    if have_sales:
        for l in lines:
            info = (l["product"], l["variant"], l["vendor"])
            if l["sku"]:
                sku_info.setdefault(l["sku"], info)
                name_sku.setdefault(vkey("", l["product"], l["variant"]), l["sku"])
            name_info.setdefault(vkey("", l["product"], l["variant"]), info)
            if l["cancelled"] or not l["date"] or not (start <= l["date"] <= end):
                continue
            k = vkey(l["sku"], l["product"], l["variant"])
            price.setdefault(k, l["price"])
            size, colour = split_variant(l["variant"], setup)
            for gname, gkey in (("product", l["product"]), ("variant", k), ("size", size),
                                ("colour", colour), ("vendor", l["vendor"])):
                if gkey:
                    groups[gname].setdefault(gkey, new_group())["sold_units"] += l["qty"]

    # Which part of the window the orders file actually covers.
    coverage = None
    if have_sales:
        dates = [l["date"] for l in lines if l["date"]]
        if dates:
            c0, c1 = max(start, min(dates)), min(end, max(dates))
            days = (end - start).days + 1
            cdays = max((c1 - c0).days + 1, 0)
            coverage = {"start": str(c0), "end": str(c1), "days": cdays, "window_days": days}
            if cdays < days:
                if cdays == 0:
                    notes.append(f"The orders file ({min(dates)} to {max(dates)}) does not cover the window {start} to {end} at all, so no rates can be computed. Export orders for the window, or pass --start and --end.")
                else:
                    notes.append(f"The orders file covers only {cdays} of the {days} days in the window ({c0} to {c1}, not {start} to {end}). Rates are for those {cdays} days of orders; export a longer date range for the full window.")

    # Shipment sizes, to split per-shipment costs across rows.
    ship_units = {}
    for r in returns:
        if r["type"] != "refused":
            sk = (r.get("return_id") or r.get("order") or f"row{r['row']}", r["type"])
            ship_units[sk] = ship_units.get(sk, 0) + max(num(r.get("quantity"), 1), 1)

    total = new_group()
    by_cat, by_type_cat, refused, months = {}, {}, {}, {}
    variant_meta = {}
    counted = unmatched = outside = no_cost_units = 0
    refused_removed = 0.0
    shipments = set()
    unidentified_money = 0.0
    def_ship = setup.get("default_return_shipping_cost")
    reship_cost = setup.get("exchange_reship_cost")
    if reship_cost is None:
        reship_cost = def_ship
    for r in returns:
        cat = r.get("category") or "other"
        is_refused = r["type"] == "refused" or cat == "refused_at_door"
        # Blank quantity means 1 unit, except unidentified rows (money only, no units).
        qty = num(r.get("quantity"), 0.0 if r.get("product") == "(not identified)" else 1.0)
        sku = r.get("sku", "")
        product, variant, vendor = r.get("product", ""), r.get("variant", ""), r.get("vendor", "")
        if not sku and product:
            # Returns app or chat rows often have no SKU: use the SKU the same variant sold under.
            sku = name_sku.get(vkey("", product, variant), "")
        if sku and sku in sku_info and not product:
            product, variant, vendor0 = sku_info[sku]
            vendor = vendor or vendor0
        elif not vendor:
            vendor = (sku_info.get(sku) or name_info.get(vkey("", product, variant)) or ("", "", ""))[2]
        k = vkey(sku, product, variant)
        odate = parse_date(r.get("order_date"))
        if odate is None and orders is not None:
            odate = (orders.get(okey(r.get("order"))) or {}).get("date")
        if odate and not is_refused:
            mm = months.setdefault(odate.strftime("%Y-%m"), {"returned_units": 0.0, "reasons": {}})
            mm["returned_units"] += qty
            mm["reasons"][cat] = mm["reasons"].get(cat, 0) + qty
        if have_sales or explicit_window:
            if odate is None and have_sales:
                unmatched += 1
                continue
            if odate is not None and not (start <= odate <= end):
                outside += 1
                continue
        if is_refused:
            f = refused.setdefault(product or "(unknown)", {"units": 0.0, "orders": set()})
            f["units"] += qty
            f["orders"].add(r.get("order"))
            o = (orders or {}).get(okey(r.get("order")))
            if have_sales and o and not o["cancelled"] and product:
                # A refused parcel was never delivered: take its units out of units sold.
                size, colour = split_variant(variant, setup)
                for gname, gkey in (("product", product), ("variant", k), ("size", size), ("colour", colour), ("vendor", vendor)):
                    g = groups[gname].get(gkey)
                    if gkey and g:
                        g["sold_units"] = max(g["sold_units"] - qty, 0)
                refused_removed += qty
            continue
        counted += 1
        refund = num(r.get("refund_amount"), 0)
        sk = (r.get("return_id") or r.get("order") or f"row{r['row']}", r["type"])
        shipments.add(sk)
        frac = max(qty, 1) / ship_units.get(sk, 1)
        ship = num(r.get("return_shipping_cost"), 0) if str(r.get("return_shipping_cost", "")).strip() else (def_ship or 0) * frac
        reship = (reship_cost or 0) * frac if r["type"] == "exchange" else 0.0
        handling = (setup.get("handling_cost_per_return") or 0) * frac
        unit_cost = costs.get(sku)
        if unit_cost is None and qty:
            no_cost_units += qty
        restock = qty * (unit_cost or 0) * share.get(cat, 0)
        if product == "(not identified)":
            unidentified_money += refund + ship + reship + handling
        size, colour = split_variant(variant, setup)
        variant_meta.setdefault(k, {"product": product, "variant": variant, "size": size, "colour": colour})
        targets = [total]
        for gname, gkey in (("product", product), ("variant", k), ("size", size), ("colour", colour), ("vendor", vendor)):
            if gkey and product != "(not identified)":
                targets.append(groups[gname].setdefault(gkey, new_group()))
        for g in targets:
            g["returned_units"] += qty
            g["refund_units" if r["type"] == "refund" else "exchange_units"] += qty
            g["refunded"] += refund
            g["return_shipping"] += ship
            g["shipments"] += frac
            g["reship"] += reship
            g["restock_loss"] += restock
            g["handling"] += handling
            g["reasons"][cat] = g["reasons"].get(cat, 0) + qty
        c = by_cat.setdefault(cat, {"units": 0.0, "money_lost": 0.0})
        c["units"] += qty
        c["money_lost"] += refund + ship + reship + handling + restock
        t = by_type_cat.setdefault(cat, {"refund": 0.0, "exchange": 0.0})
        t["refund" if r["type"] == "refund" else "exchange"] += qty

    if unmatched:
        notes.append(f"{unmatched} return rows had no order date and no matching order in the orders export, so they are left out of the analysis (rates, reasons and money). Export a longer order history, or add an order_date column, to include them.")
    if refused_removed:
        notes.append(f"{refused_removed:g} units from orders refused at the door were taken out of units sold (they were never delivered).")
    if outside:
        notes.append(f"{outside} rows (returns or refusals) belong to orders placed outside the window {start} to {end} and are not counted.")
    if no_cost_units:
        notes.append(f"Restocking loss is not included for {no_cost_units:g} returned units with no unit cost (add Cost per item in Shopify or a products export).")
    if def_ship is None and not any(str(r.get("return_shipping_cost", "")).strip() for r in returns):
        notes.append("Return shipping cost is not included: no cost in the data and no default_return_shipping_cost in setup.")
    if not counted and refused:
        notes.append("No returns (refunds or exchanges) were found, only orders refused at the door, which are never counted as returns. If you keep returns as Shopify return records or take items back without refunding (Try & Buy, exchanges), the orders export cannot see them: use the Shopify connector or a returns app export.")
    if unidentified_money:
        notes.append(f"{round(unidentified_money, 2)} of money lost comes from partial refunds or exchanges the export cannot tie to a returned product (multi-item orders, or refunds under half a unit such as a shipping fee); use the connector for line detail.")

    tot = finish("store", total, setup, have_sales)
    if have_sales:
        sold_all = sum(g["sold_units"] for g in groups["product"].values())
        tot["sold_units"] = sold_all
        tot["return_rate"] = round(total["returned_units"] / sold_all * 100, 1) if sold_all else None
        tot["low_sample"] = None

    def table(gname, key):
        rows = [finish(n, g, setup, have_sales, key) for n, g in groups[gname].items()]
        rows.sort(key=lambda x: (-(x["return_rate"] or 0) if have_sales else 0, -x["returned_units"], str(x[key])))
        return rows

    by_product = table("product", "product")
    by_variant = table("variant", "variant")
    for v in by_variant:
        meta = variant_meta.get(v["variant"]) or {}
        info = sku_info.get(v["variant"]) or name_info.get(v["variant"])
        v["product"] = meta.get("product") or (info[0] if info else "")
        v["variant_title"] = meta.get("variant") or (info[1] if info else "")
    by_size, by_colour, by_vendor = table("size", "size"), table("colour", "colour"), table("vendor", "vendor")

    # Top products to fix.
    fixes = []
    for p in by_product:
        if p["returned_units"] < setup["min_returns"]:
            continue
        if have_sales and p["sold_units"] < setup["min_units_sold"]:
            continue
        cat = p["top_reason"] or "other"
        sizes = [v for v in by_variant if v["product"] == p["product"]]
        size_rows = {}
        for v in sizes:
            s = split_variant(v["variant_title"], setup)[0] or "(no size)"
            sr = size_rows.setdefault(s, {"size": s, "sold_units": 0.0, "returned_units": 0.0})
            sr["sold_units"] += v["sold_units"] or 0
            sr["returned_units"] += v["returned_units"]
        for sr in size_rows.values():
            sr["return_rate"] = round(sr["returned_units"] / sr["sold_units"] * 100, 1) if sr["sold_units"] else None
        g = groups["product"][p["product"]]
        fixes.append({
            "product": p["product"], "sold_units": p["sold_units"], "returned_units": p["returned_units"],
            "return_rate": p["return_rate"], "money_lost": p["money_lost"], "top_reason": cat,
            "top_reason_label": reason_info(cat, lex)["label"], "top_reason_share": p["top_reason_share"],
            "fix": reason_info(cat, lex)["fix"],
            # For the dashboard: swap this product's return shipping for (shipping per return x its shipments).
            "return_shipping": round(g["return_shipping"], 2), "return_shipments": round(g["shipments"], 4),
            "by_size": sorted(size_rows.values(), key=lambda s: (-(s["return_rate"] or 0), s["size"])) if cat.startswith(("size", "fit")) else [],
        })
    fixes.sort(key=lambda f: (-f["money_lost"], -f["returned_units"], f["product"]))
    fixes = fixes[: setup["top_n"]]

    # Trend by order month (cohort) when sales exist.
    trend = []
    if have_sales:
        sold_m = {}
        for l in lines:
            if not l["cancelled"] and l["date"]:
                m = l["date"].strftime("%Y-%m")
                sold_m[m] = sold_m.get(m, 0) + l["qty"]
        for m in sorted(sold_m):
            mm = months.get(m, {"returned_units": 0.0, "reasons": {}})
            y, mo = int(m[:4]), int(m[5:])
            month_end = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1))
            top = top_of(mm["reasons"])
            trend.append({"month": m, "sold_units": sold_m.get(m, 0), "returned_units": mm["returned_units"],
                          "return_rate": round(mm["returned_units"] / sold_m[m] * 100, 1) if sold_m.get(m) else None,
                          "mature": month_end <= maturity, "top_reason": top})
    else:
        for m in sorted(months):
            mm = months[m]
            top = top_of(mm["reasons"])
            trend.append({"month": m, "returned_units": mm["returned_units"], "top_reason": top})

    reasons = [{"category": c, "label": lex["categories"][c]["label"], "units": v["units"],
                "share": round(v["units"] / total["returned_units"] * 100, 1) if total["returned_units"] else None,
                "money_lost": round(v["money_lost"], 2),
                "refund_units": by_type_cat[c]["refund"], "exchange_units": by_type_cat[c]["exchange"]}
               for c, v in sorted(by_cat.items(), key=lambda kv: (-kv[1]["units"], kv[0]))]
    ref = [{"product": p, "units": v["units"], "orders": len(v["orders"])}
           for p, v in sorted(refused.items(), key=lambda kv: (-kv[1]["units"], kv[0]))]
    return {
        "skill": "returns-reason-analysis",
        "currency": setup.get("currency", ""),
        "window": {"start": str(start), "end": str(end), "as_of": str(as_of), "mature_until": str(maturity),
                   "covered": coverage},
        "rates_available": have_sales,
        "totals": tot,
        "money_breakdown": {"refunded": round(total["refunded"], 2), "return_shipping": round(total["return_shipping"], 2),
                            "exchange_reship": round(total["reship"], 2), "restock_loss": round(total["restock_loss"], 2),
                            "handling": round(total["handling"], 2), "return_shipments": len(shipments)},
        "exchanges_vs_refunds": {"refund_units": total["refund_units"], "exchange_units": total["exchange_units"],
                                 "exchange_share": round(total["exchange_units"] / total["returned_units"] * 100, 1) if total["returned_units"] else None},
        "reasons": reasons,
        "top_fixes": fixes,
        "by_product": by_product, "by_variant": by_variant, "by_size": by_size,
        "by_colour": by_colour, "by_vendor": by_vendor,
        "trend": trend,
        "refused_at_door": {"units": sum(v["units"] for v in refused.values()), "by_product": ref},
        "rows_counted": counted,
        "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--returns", required=True)
    ap.add_argument("--orders")
    ap.add_argument("--setup")
    ap.add_argument("--products")
    ap.add_argument("--lexicon", default=os.path.join(HERE, "..", "assets", "reason-lexicon.json"))
    ap.add_argument("--as-of")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--csv-dir")
    a = ap.parse_args()
    setup = dict(DEFAULTS)
    if a.setup:
        with open(a.setup, encoding="utf-8") as fh:
            setup.update({k: v for k, v in json.load(fh).items() if v is not None or k in ("default_return_shipping_cost", "exchange_reship_cost")})
    with open(a.lexicon, encoding="utf-8") as fh:
        lex = json.load(fh)
    returns = read_rows(a.returns)
    if not returns:
        fail("Returns file has no rows, so there is nothing to analyse. Stores that keep returns as Shopify return "
             "records, or take items back without refunding (Try & Buy, exchanges), do not show them in the orders "
             "export: use the Shopify connector (references/shopify-queries.md) or a returns app export.")
    if "category" not in returns[0]:
        fail("Returns file has no 'category' column. Run classify_reasons.py first.")
    for i, r in enumerate(returns, 1):
        r.setdefault("row", str(i))
        r["type"] = (r.get("type") or "refund").lower()
    orders = lines = None
    if a.orders:
        orders, lines = load_orders(a.orders, setup)
    costs = load_costs(a.products) if a.products else {}
    d = lambda s: dt.date.fromisoformat(s) if s else None  # noqa: E731
    res = analyze(returns, setup, lex, orders, lines, costs, d(a.as_of), d(a.start), d(a.end))
    if a.csv_dir:
        os.makedirs(a.csv_dir, exist_ok=True)
        flat = lambda rows: [dict(r, reasons=json.dumps(r.get("reasons", {}), ensure_ascii=False)) for r in rows]  # noqa: E731
        for name in ("by_product", "by_variant", "by_size", "by_colour", "by_vendor"):
            if res[name]:
                write_csv(os.path.join(a.csv_dir, name + ".csv"), flat(res[name]))
        if res["top_fixes"]:
            write_csv(os.path.join(a.csv_dir, "top_fixes.csv"),
                      [dict(f, by_size=json.dumps(f["by_size"], ensure_ascii=False)) for f in res["top_fixes"]])
        if res["reasons"]:
            write_csv(os.path.join(a.csv_dir, "reasons.csv"), res["reasons"])
        if res["trend"]:
            write_csv(os.path.join(a.csv_dir, "trend.csv"), res["trend"])
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
