"""COD failed-delivery (RTO) analysis. Python 3 standard library only, no network.

Usage:
    python3 rto_analysis.py --orders orders_export.csv
        [--setup replai-setup/cod-rto-analysis.json]
        [--courier courier_a.csv::CourierName] [--courier courier_b.xlsx::OtherCourier]
        [--courier-map status="Shipment State" --courier-map ref="Order Ref"]
        [--products products_export.csv]   # optional: exact product titles for the product segment
        [--out-dir results/]

Reads a Shopify orders export (one row per line item) and optional courier files, classifies
each order as delivered / failed / open / cancelled using the setup's failed-order definition,
groups by region (normalised governorate/emirate), city, courier (courier file, else order tags
via setup courier_tags), product (variants grouped unless setup product_group is "variant"), order value band,
customer history, day of week and payment method, and prints one JSON object:
overall rates, money lost, segments (with sample-size confidence), worst segments,
unknown regions, failure reasons and suggested actions with estimated savings.
With --out-dir it also writes orders_classified.csv and segments.csv.
"""
import argparse, datetime, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, pick, write_csv  # noqa: E402
from orders import load_orders, load_courier, CourierIndex, classify, is_cod, courier_from_tags, DEFAULT_COURIER_TAGS  # noqa: E402
from regions import Regions  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETUP = os.path.join(HERE, "..", "assets", "setup.example.json")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DIMENSIONS = ["region", "city", "courier", "product", "value_band", "customer_history",
              "day_of_week", "payment_method"]


def r2(x):
    return None if x is None else round(x + 0.0, 2)


def wilson(failed, n, z=1.96):
    if n == 0:
        return None, None
    p = failed / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def band(total, edges, cur):
    edges = sorted(edges)
    prev = 0
    for e in edges:
        if total < e:
            return f"{prev:g}-{e - 1:g} {cur}" if prev else f"under {e:g} {cur}"
        prev = e
    return f"{prev:g}+ {cur}"


def load_setup(path):
    with open(DEFAULT_SETUP, encoding="utf-8") as fh:
        base = json.load(fh)
    if path:
        with open(path, encoding="utf-8") as fh:
            base.update(json.load(fh))
    return base


def cost(value, default):
    return value if value is not None else (default or 0.0)


def load_product_titles(path):
    """(sku -> title, titles longest first) from a Shopify products export (legacy or 2026 headers)."""
    by_sku, titles, last = {}, set(), {}
    for r in read_rows(path):
        handle = pick(r, "handle", "url_handle")
        title = pick(r, "title", "product", "product_title")
        if handle:
            title = title or last.get(handle, "")
            if title:
                last[handle] = title
        if not title:
            continue
        titles.add(title.strip())
        sku = pick(r, "variant_sku", "sku")
        if sku:
            by_sku[sku.strip().lower()] = title.strip()
    return by_sku, sorted(titles, key=len, reverse=True)


def product_of(line, group, by_sku, titles):
    """Product segment value of an order line: the product title (variants grouped) by default."""
    name = line["name"]
    if group == "variant":
        return name
    t = by_sku.get(str(line.get("sku", "")).strip().lower())
    if t:
        return t
    low = name.lower()
    for t in titles:
        if low == t.lower() or low.startswith(t.lower() + " - "):
            return t
    return name.rsplit(" - ", 1)[0] if " - " in name else name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--setup")
    ap.add_argument("--courier", action="append", default=[])
    ap.add_argument("--courier-map", action="append", default=[])
    ap.add_argument("--products")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    S = load_setup(a.setup)
    cur = S.get("currency", "")
    warnings, assumptions = [], []

    orders = load_orders(a.orders)
    overrides = {}   # meaning -> [headers]; repeat --courier-map for files with different headers
    for x in a.courier_map:
        k, _, v = x.partition("=")
        overrides.setdefault(k.strip(), []).append(v.strip())
    crow, cmaps = [], {}
    for spec in a.courier:
        path, _, cname = spec.partition("::")
        rows, mapping = load_courier(path, cname or S.get("default_courier", ""), overrides)
        crow += rows
        cmaps[os.path.basename(path)] = mapping
    cidx = CourierIndex(crow, S)
    p_sku, p_titles = load_product_titles(a.products) if a.products else ({}, [])
    p_group = S.get("product_group", "product")
    tag_map = S.get("courier_tags")
    tag_map = DEFAULT_COURIER_TAGS if tag_map is None else tag_map
    R = Regions()
    for region, spellings in (S.get("region_aliases") or {}).items():
        if not R.add_aliases(region, spellings):
            warnings.append(f"Setup region_aliases names a region that is not in the region table: {region}")

    no_default_cost = all(S.get(k) is None for k in ("default_outbound_shipping", "default_return_shipping", "packaging_cost"))
    for k, label in (("default_outbound_shipping", "outbound shipping"),
                     ("default_return_shipping", "return shipping"),
                     ("packaging_cost", "packaging")):
        if S.get(k) is None and not no_default_cost:
            warnings.append(f"No {label} cost in setup; counted as 0 where the courier file has no value, so money lost is understated.")
    if S.get("default_cod_fee_failed") is None:
        S["default_cod_fee_failed"] = 0.0

    # Customer history needs every order sorted by date, in any status.
    def cust(o):
        if o["email"]:
            return "e:" + o["email"].lower()
        digits = "".join(ch for ch in o["phone"] if ch.isdigit())
        return "p:" + digits[-9:] if len(digits) >= 7 else ""

    classified = []
    for o in orders:
        c = cidx.match(o)
        o["courier_row"] = c
        o["outcome"] = classify(o, S, c)
        o["is_cod"] = is_cod(o, S.get("cod_payment_keywords", []))
        reg, iso, src = R.resolve(o["province_name"], o["province"], o["city"], o["country"])
        o["region"] = reg or ("Unknown" + (f" ({iso})" if iso else ""))
        o["region_source"] = src
        o["courier"] = (c and c["courier"]) or courier_from_tags(o["tags"], tag_map) or S.get("default_courier") or "Unknown"
        o["value_band"] = band(o["total"], S.get("value_bands", [500, 1000, 2000]), cur)
        try:
            o["day_of_week"] = DAYS[datetime.date.fromisoformat(o["date"]).weekday()]
        except ValueError:
            o["day_of_week"] = "Unknown"
        o["payment_method"] = o["payment"] or "Unknown"
        o["city_label"] = o["city"].strip().title() or "Unknown"
        if o["outcome"] == "failed":
            o["loss_outbound"] = cost(c and c["shipping_fee"], S.get("default_outbound_shipping"))
            o["loss_return"] = cost(c and c["return_fee"], S.get("default_return_shipping"))
            o["loss_cod_fee"] = cost(c and c["cod_fee"], S.get("default_cod_fee_failed"))
            o["loss_packaging"] = S.get("packaging_cost") or 0.0
            o["loss"] = o["loss_outbound"] + o["loss_return"] + o["loss_cod_fee"] + o["loss_packaging"]
            o["loss_known"] = bool(c and any(c[k] is not None for k in ("shipping_fee", "return_fee", "cod_fee")))
        else:
            o["loss"] = 0.0
        classified.append(o)

    hist, prev_failed = {}, {}
    for o in sorted(classified, key=lambda x: (x["date"], x["created"], x["name"])):
        k = cust(o)
        if not k:
            o["customer_history"] = "unknown customer"
            continue
        if k not in hist:
            o["customer_history"] = "first order in data"
        elif prev_failed.get(k):
            o["customer_history"] = "repeat, failed before"
        else:
            o["customer_history"] = "repeat, no earlier failure"
        hist[k] = hist.get(k, 0) + 1
        if o["outcome"] == "failed":
            prev_failed[k] = True

    scope = [o for o in classified if o["is_cod"]] if S.get("cod_only", True) else classified
    resolved = [o for o in scope if o["outcome"] in ("delivered", "failed")]
    counts = {}
    for o in scope:
        counts[o["outcome"]] = counts.get(o["outcome"], 0) + 1
    n_res = len(resolved)
    n_fail = sum(1 for o in resolved if o["outcome"] == "failed")
    # Money lost is unknown (null), not 0, when setup has no costs and no courier file gives a fee.
    cost_known = not no_default_cost or any(o.get("loss_known") for o in resolved)
    if n_fail and not cost_known:
        warnings.append("No shipping, return or packaging cost is known (none in setup, none in a courier file), "
                        "so money lost cannot be computed and is shown as n/a. Add your costs in setup to see it.")
    money = sum(o["loss"] for o in resolved) if cost_known else None
    overall = n_fail / n_res if n_res else None
    if counts.get("open"):
        warnings.append(f"{counts['open']} shipped orders are neither marked paid nor failed (still in transit, or not updated). They are left out of the rates.")
    if not n_res:
        warnings.append("No delivered or failed orders found in scope. Check the failed-order definition and the payment keywords.")

    dates = sorted(o["date"] for o in scope if o["date"])
    days = 0
    if dates:
        try:
            days = (datetime.date.fromisoformat(dates[-1]) - datetime.date.fromisoformat(dates[0])).days + 1
        except ValueError:
            days = 0
    per_month = (30.0 / days) if days else None
    undated = sum(1 for o in scope if not o["date"])
    if undated:
        warnings.append(f"{undated} orders have no readable 'Created at' date: weekday, period and per-month figures leave them out.")
    if 0 < days < 28:
        warnings.append(f"The orders cover only {days} days: per-month figures are that period scaled to 30 days, so treat them as rough.")

    min_n = int(S.get("min_orders", 30))

    def seg_stats(items):
        n = len(items)
        f = sum(1 for o in items if o["outcome"] == "failed")
        m = sum(o["loss"] for o in items) if cost_known else None
        lo, hi = wilson(f, n)
        conf = "too few orders" if n < min_n else ("medium" if n < 3 * min_n else "high")
        return {"resolved": n, "delivered": n - f, "failed": f,
                "failure_rate": round(f / n, 4) if n else None,
                "ci95_low": lo, "ci95_high": hi, "money_lost": r2(m),
                "confidence": conf, "ranked": n >= min_n}

    segments = {}
    for dim in DIMENSIONS:
        base = resolved if dim != "payment_method" else [o for o in classified if o["outcome"] in ("delivered", "failed")]
        groups = {}
        for o in base:
            vals = sorted({product_of(ln, p_group, p_sku, p_titles) for ln in o["lines"]}) if dim == "product" else \
                [o["city_label"] if dim == "city" else o[dim]]
            for v in vals or ["Unknown"]:
                groups.setdefault(v, []).append(o)
        rows = []
        for v, items in groups.items():
            s = seg_stats(items)
            s["value"] = v
            rows.append(s)
        rows.sort(key=lambda s: (-s["resolved"], s["value"]))
        segments[dim] = rows

    worst = {}
    for dim, rows in segments.items():
        ref = overall if dim != "payment_method" else None
        cand = [s for s in rows if s["ranked"] and (ref is None or s["failure_rate"] > ref)]
        cand.sort(key=lambda s: (-s["failure_rate"], -(s["money_lost"] or 0)))
        worst[dim] = [s["value"] for s in cand[:5]]

    # Region x courier for switch suggestions.
    cross = {}
    for o in resolved:
        cross.setdefault(o["region"], {}).setdefault(o["courier"], []).append(o)

    gap = float(S.get("rate_gap_for_action", 0.10))
    red_p = float(S.get("prepay_failure_reduction", 0.5))
    red_c = float(S.get("confirmation_failure_reduction", 0.3))
    actions = []

    def add(kind, target, text, saving, basis, seg, avoided):
        saving = saving if cost_known else None
        actions.append({"type": kind, "target": target, "action": text,
                        "failures_avoided_estimate": r2(avoided),
                        "estimated_saving": r2(saving),
                        "estimated_saving_per_month": r2(saving * per_month) if (per_month and saving is not None) else None,
                        "basis": basis, "segment_failure_rate": seg["failure_rate"],
                        "segment_orders": seg["resolved"], "confidence": seg["confidence"],
                        "label": "estimate"})

    if overall is not None:
        for s in segments["region"]:
            if s["ranked"] and not s["value"].startswith("Unknown") and s["failure_rate"] >= overall + gap:
                add("prepay_area", s["value"],
                    f"Ask for a deposit or prepayment (or at least the shipping fee upfront) for COD orders to {s['value']}.",
                    (s["money_lost"] or 0) * red_p,
                    f"money lost in {s['value']} x {red_p:g} (assumed share of failures avoided)", s, s["failed"] * red_p)
        for s in segments["value_band"]:
            if s["ranked"] and s["failure_rate"] >= overall + gap:
                add("confirm_value", s["value"],
                    f"Confirm orders in the {s['value']} band by phone or WhatsApp before shipping.",
                    (s["money_lost"] or 0) * red_c, f"money lost in band x {red_c:g} (assumed share avoided by confirmation)", s,
                    s["failed"] * red_c)
        for s in segments["customer_history"]:
            if s["ranked"] and s["value"] in ("first order in data", "repeat, failed before") and s["failure_rate"] >= overall + gap:
                txt = ("Confirm first-time COD customers before shipping." if s["value"].startswith("first")
                       else "Require prepayment from customers who refused a COD order before.")
                r = red_c if s["value"].startswith("first") else red_p
                add("customer_rule", s["value"], txt, (s["money_lost"] or 0) * r, f"money lost in group x {r:g}", s, s["failed"] * r)
        for s in segments["product"]:
            if s["ranked"] and s["failure_rate"] >= overall + gap:
                add("product_check", s["value"],
                    f"Check the listing for {s['value']} (photos, size info, price shown) and confirm its orders before shipping.",
                    (s["money_lost"] or 0) * red_c, f"money lost on orders with this product x {red_c:g}", s, s["failed"] * red_c)
        for reg, by_c in cross.items():
            ok = {c: seg_stats(v) for c, v in by_c.items() if len(v) >= min_n and c != "Unknown"}
            if len(ok) < 2:
                continue
            best = min(ok, key=lambda c: ok[c]["failure_rate"])
            worst_c = max(ok, key=lambda c: ok[c]["failure_rate"])
            b, w = ok[best], ok[worst_c]
            if w["failure_rate"] - b["failure_rate"] >= gap and w["failed"]:
                avoided = w["failed"] - w["resolved"] * b["failure_rate"]
                saving = avoided * ((w["money_lost"] or 0) / w["failed"])
                add("switch_courier", f"{reg}: {worst_c} to {best}",
                    f"Ship {reg} orders with {best} instead of {worst_c}.", saving,
                    f"{worst_c} failures in {reg} minus what {best}'s rate would give, x average loss per failed order", w,
                    avoided)
        actions.sort(key=lambda x: (-(x["estimated_saving"] or 0), -(x["failures_avoided_estimate"] or 0)))

    unknown = {}
    for o in scope:
        if o["region"].startswith("Unknown"):
            k = (o["province_name"] or o["province"], o["city"], o["country"])
            unknown[k] = unknown.get(k, 0) + 1
    unknown_rows = [{"province": k[0], "city": k[1], "country": k[2], "orders": v}
                    for k, v in sorted(unknown.items(), key=lambda kv: -kv[1])]

    reasons = {}
    for o in resolved:
        if o["outcome"] == "failed" and o["courier_row"] and o["courier_row"]["reason"]:
            k = o["courier_row"]["reason"].strip().lower()
            reasons[k] = reasons.get(k, 0) + 1
    reason_rows = [{"reason": k, "orders": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])][:15]

    fails = [o for o in resolved if o["outcome"] == "failed"]
    breakdown = {k: r2(sum(o.get("loss_" + k, 0) for o in fails)) if cost_known else None
                 for k in ("outbound", "return", "cod_fee", "packaging")}

    assumptions += [
        f"Failed order = {S.get('failed_definition_note') or 'tagged with a failed tag, cancelled after fulfillment, financial status in the failed list, or a failed courier status'}. A courier status, when present, wins over Shopify.",
        "Orders cancelled before shipping are not deliveries and are left out of the rates.",
        f"Areas, products and segments with fewer than {min_n} delivered+failed orders are shown but not ranked.",
        f"Savings are estimates: prepayment assumed to avoid {red_p:.0%} of failures, confirmation {red_c:.0%}. Savings of different actions overlap, do not add them up.",
        "Money lost counts courier and packaging costs only, not lost profit or ad spend on the failed order.",
    ]
    if a.courier:
        assumptions.append("Courier fees come from the courier file where given, setup defaults otherwise.")

    result = {
        "currency": cur,
        "period": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None, "days": days},
        "scope": "COD orders only" if S.get("cod_only", True) else "all orders",
        "orders_in_file": len(orders),
        "orders_in_scope": len(scope),
        "outcomes": counts,
        "overall": {"resolved": n_res, "delivered": n_res - n_fail, "failed": n_fail,
                    "delivery_success_rate": round(1 - overall, 4) if overall is not None else None,
                    "failure_rate": round(overall, 4) if overall is not None else None,
                    "money_lost": r2(money),
                    "money_lost_per_month": r2(money * per_month) if (per_month and money is not None) else None,
                    "avg_loss_per_failed_order": r2(money / n_fail) if (n_fail and money is not None) else None,
                    "loss_breakdown": breakdown},
        "min_orders": min_n,
        "worst": worst,
        "segments": segments,
        "unknown_regions": unknown_rows,
        "failure_reasons": reason_rows,
        "actions": actions,
        "courier": {"rows": len(crow), "matched": len(cidx.used),
                    "unmatched": len(cidx.unmatched()), "columns": cmaps},
        "assumptions": assumptions,
        "warnings": warnings,
    }
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
        write_csv(os.path.join(a.out_dir, "orders_classified.csv"),
                  [{"order": o["name"], "date": o["date"], "outcome": o["outcome"], "cod": o["is_cod"],
                    "region": o["region"], "region_source": o["region_source"], "city": o["city_label"],
                    "courier": o["courier"], "total": o["total"], "value_band": o["value_band"],
                    "customer_history": o.get("customer_history", ""), "payment_method": o["payment_method"],
                    "money_lost": r2(o["loss"]) if cost_known else None} for o in classified])
        write_csv(os.path.join(a.out_dir, "segments.csv"),
                  [dict(dimension=d, **s) for d, rows in segments.items() for s in rows],
                  ["dimension", "value", "resolved", "delivered", "failed", "failure_rate",
                   "ci95_low", "ci95_high", "money_lost", "confidence", "ranked"])
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


if __name__ == "__main__":
    main()
