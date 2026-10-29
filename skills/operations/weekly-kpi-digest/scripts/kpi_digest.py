"""Compute the weekly KPI digest from a Shopify orders export (Python 3 standard library only).

Usage:
    python3 kpi_digest.py --orders orders_export.csv --setup replai-setup/weekly-kpi-digest.json
        [--inventory inventory_export.csv] [--courier courier.csv] [--analytics analytics.json]
        [--as-of YYYY-MM-DD | --week-start YYYY-MM-DD] [--out digest.json]

--orders     Shopify admin > Orders > Export > CSV for Excel (one row per line item). Required.
--setup      The saved setup JSON (same keys as assets/setup.example.json). Optional, defaults apply.
--inventory  Shopify inventory or products export (SKU + available quantity) for stock warnings.
--courier    Any courier export with an order reference and a delivery status column.
             Without one, delivery outcomes come from the orders file with the same rules as the
             cod-rto-analysis skill: failed tags, cancelled after fulfilment (a refused COD parcel),
             voided after fulfilment, paid after fulfilment = delivered, else still open.
--analytics  JSON with sessions / conversion_rate per week, written by the agent from a ShopifyQL
             query. Shape: {"this": {"sessions": 1200, "conversion_rate": 1.4}, "last": {...},
             "four_weeks_ago": {...}}. Never write this file with guessed numbers.
--as-of      Report the last COMPLETE week before this date (default: today in the store timezone).
--week-start Report the week starting on this date instead.

Prints one JSON object (the digest). The agent turns it into a report, dashboard, spreadsheet or
email draft (see render_digest.py). Never touches the network.
"""
import argparse, datetime as dt, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, pick, num  # noqa: E402

DEFAULTS = {
    "currency": "",
    "timezone": "Africa/Cairo",
    "week_start": "saturday",
    "kpis": ["net_sales", "orders", "aov", "units", "new_customers", "returning_customers",
             "top_products", "bottom_products", "discount_share", "refunds", "cod_share",
             "cod_delivery_success", "cancelled_orders", "failed_deliveries", "inventory_warnings",
             "sessions", "conversion_rate"],
    "targets": {},
    "flag_threshold_pct": 15,
    "flag_threshold_pp": 3,
    "inventory_cover_days": 14,
    "product_grouping": "product",
    "cod_keywords": ["cash on delivery", "cod", "الدفع عند الاستلام", "عند الاستلام"],
    "delivered_tags": ["delivered"],
    # Failed-delivery definition: same keys and defaults as the cod-rto-analysis skill so the two
    # skills report the same delivered / failed numbers.
    "failed_tags": ["rto", "returned", "return to origin", "refused", "rejected", "undelivered",
                    "failed delivery", "مرتجع", "رفض الاستلام"],
    "count_cancelled_after_fulfillment_as_failed": True,
    "failed_cancel_reasons": ["customer", "declined", "other"],
    "failed_financial_statuses": ["voided"],
    "failed_courier_statuses": ["undelivered", "not delivered", "return", "rto", "refused", "rejected",
                                "cancel", "failed", "lost", "damaged", "مرتجع", "رفض", "مرفوض", "ملغي",
                                "ملغى", "لم يتم التسليم", "لم يتم التوصيل", "ارتجاع", "إرجاع", "ارجاع"],
    "delivered_courier_statuses": ["delivered", "تم التسليم", "تم التوصيل"],
    "min_rate_base": 5,
}

# A first data day counts as cut when its first order comes this many hours later than the store's
# usual first order of the day (median over the other days).
PARTIAL_MARGIN_HOURS = 2

SHIPPED = ("fulfilled", "partial", "partially_fulfilled", "shipped")
PAID = ("paid", "partially_refunded", "refunded", "partially_paid")
RETURNED_COLS = ("returned_units", "returned_quantity", "return_restock_quantity")

TEST_TAGS = {"test", "test order", "test-order", "test_order", "testorder", "testing"}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# key: (label, kind, polarity). kind: money | count | rate (percent 0-100). polarity: +1 higher is
# better, -1 lower is better, 0 neutral (watch only).
KPI_META = {
    "net_sales": ("Net sales", "money", 1),
    "orders": ("Orders", "count", 1),
    "aov": ("Average order value", "money", 1),
    "units": ("Units sold", "count", 1),
    "new_customers": ("New customers", "count", 1),
    "returning_customers": ("Returning customers", "count", 1),
    "discount_share": ("Discount share of gross sales", "rate", -1),
    "refunds": ("Refunds", "money", -1),
    "refund_rate": ("Orders with a refund", "rate", -1),
    "cod_share": ("COD share of orders", "rate", 0),
    "cod_delivery_success": ("COD delivery success", "rate", 1),
    "returned_units": ("Returned units (restocked)", "count", -1),
    "cancelled_orders": ("Cancelled before shipping", "count", -1),
    "failed_deliveries": ("Failed deliveries", "count", -1),
    "sessions": ("Sessions", "count", 1),
    "conversion_rate": ("Conversion rate", "rate", 1),
}

ACTIONS = {
    ("net_sales", -1): "Net sales fell {chg}. Check which top products dropped, whether any went out of stock, and whether ad spend or a promotion changed.",
    ("net_sales", 1): "Net sales rose {chg}. Find what drove it (product, campaign, channel) and keep it running; check stock can carry the extra demand.",
    ("orders", -1): "Orders fell {chg}. Look at traffic and conversion first, then at stock-outs on best sellers.",
    ("orders", 1): "Orders rose {chg}. Make sure fulfilment and order confirmation keep up so delivery success does not slip.",
    ("aov", -1): "Average order value fell {chg}. Check discount depth and whether bundles or free-shipping thresholds still show.",
    ("aov", 1): "Average order value rose {chg}. Note what changed (bundles, prices, product mix) so you can repeat it.",
    ("units", -1): "Units sold fell {chg}. Compare with orders: fewer items per order points to basket size, fewer orders points to traffic.",
    ("units", 1): "Units sold rose {chg}. Check days of cover on the fastest movers.",
    ("new_customers", -1): "New customers fell {chg}. Review acquisition: ads, influencer posts, and first-order offers.",
    ("new_customers", 1): "New customers rose {chg}. Plan a second-order follow-up for them within 30 days.",
    ("returning_customers", -1): "Returning customers fell {chg}. Send a win-back message or offer to past buyers.",
    ("returning_customers", 1): "Returning customers rose {chg}. Whatever brought them back (message, drop, offer) is worth repeating.",
    ("discount_share", 1): "Discounts took a bigger share of sales ({chg}). Check which codes drove it and whether they paid for themselves.",
    ("discount_share", -1): "Discount share dropped ({chg}). If sales held, you kept more margin; keep the lighter discounting.",
    ("refunds", 1): "Refunds rose {chg}. Run the returns-reason-analysis skill to see which products and reasons drive it.",
    ("refunds", -1): "Refunds fell {chg}. Keep whatever fix you made (size chart, photos, packaging).",
    ("refund_rate", 1): "More orders were refunded ({chg}). Look at the products behind the refunds this week.",
    ("refund_rate", -1): "Fewer orders were refunded ({chg}).",
    ("cod_share", 1): "COD share rose ({chg}). Confirm high-value COD orders before shipping to protect delivery success.",
    ("cod_share", -1): "COD share fell ({chg}). Prepaid orders deliver more reliably; keep any prepaid incentive that caused it.",
    ("cod_delivery_success", -1): "COD delivery success fell ({chg}). Run the cod-rto-analysis skill to find the areas, couriers and products failing.",
    ("cod_delivery_success", 1): "COD delivery success improved ({chg}). Keep the confirmation or courier change that caused it.",
    ("cancelled_orders", 1): "Orders cancelled before shipping rose {chg}. Read the cancel reasons: stock, fake orders, or customers unreachable at confirmation.",
    ("cancelled_orders", -1): "Orders cancelled before shipping fell {chg}.",
    ("failed_deliveries", 1): "Failed deliveries rose {chg}. These parcels went out and came back (refused, unreachable, returned to origin). Run the cod-rto-analysis skill to find the areas, couriers and products behind them.",
    ("failed_deliveries", -1): "Failed deliveries fell {chg}. Keep the confirmation or courier change that caused it.",
    ("returned_units", 1): "Returned units rose {chg}. Run the returns-reason-analysis skill to see which products and reasons drive it.",
    ("returned_units", -1): "Returned units fell {chg}. Keep whatever fix you made (size chart, photos, packaging).",
    ("sessions", -1): "Sessions fell {chg}. Check ad delivery, budget changes and organic posting this week.",
    ("sessions", 1): "Sessions rose {chg}. Watch conversion: more traffic with flat orders means the store is not converting it.",
    ("conversion_rate", -1): "Conversion rate fell ({chg}). Check the product pages of top sellers on a phone, stock, prices and delivery info.",
    ("conversion_rate", 1): "Conversion rate rose ({chg}). Find the change on the store that caused it and keep it.",
}


def fail(msg):
    print(json.dumps({"error": msg}, ensure_ascii=False))
    sys.exit(2)


def load_setup(path):
    setup = dict(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as fh:
            setup.update({k: v for k, v in json.load(fh).items() if v is not None})
    return setup


# Common city or country names merchants type at setup, mapped to IANA zone names.
TZ_ALIASES = {
    "cairo": "Africa/Cairo", "egypt": "Africa/Cairo", "alexandria": "Africa/Cairo",
    "riyadh": "Asia/Riyadh", "jeddah": "Asia/Riyadh", "saudi arabia": "Asia/Riyadh", "ksa": "Asia/Riyadh",
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "uae": "Asia/Dubai", "kuwait": "Asia/Kuwait",
    "doha": "Asia/Qatar", "qatar": "Asia/Qatar", "bahrain": "Asia/Bahrain", "manama": "Asia/Bahrain",
    "muscat": "Asia/Muscat", "oman": "Asia/Muscat", "amman": "Asia/Amman", "jordan": "Asia/Amman",
}


def get_tz(name):
    name = TZ_ALIASES.get(str(name).strip().lower(), name)
    m = re.fullmatch(r"(?:UTC|GMT)?\s*([+-])(\d{1,2}):?(\d{2})?", str(name).strip())
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return dt.timezone(sign * dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        fail(f"Unknown timezone '{name}'. Use a name like Africa/Cairo or a fixed offset like +03:00.")


_TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?")


def parse_ts(value, tz):
    """Parse a Shopify timestamp ('2026-10-20 14:03:11 +0200' or ISO) to a local datetime."""
    m = _TS.search(str(value or ""))
    if not m:
        return None
    y, mo, d, h, mi, s, off = m.groups()
    t = dt.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
    if off:
        if off == "Z":
            t = t.replace(tzinfo=dt.timezone.utc)
        else:
            o = off.replace(":", "")
            sign = 1 if o[0] == "+" else -1
            t = t.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(o[1:3]), minutes=int(o[3:5]))))
        return t.astimezone(tz)
    return t.replace(tzinfo=tz)


def phone_key(p):
    digits = re.sub(r"\D", "", p or "")
    return digits[-9:] if len(digits) >= 8 else ""


def has_word(text, words):
    t = (text or "").lower()
    for w in words:
        w = w.lower().strip()
        if not w:
            continue
        if re.search(r"[a-z0-9]", w):
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
                return True
        elif w in t:
            return True
    return False


def product_name(line_name, grouping):
    if grouping == "variant" or " - " not in line_name:
        return line_name
    return line_name.rsplit(" - ", 1)[0]


def ref_key(v):
    return re.sub(r"[^0-9a-z]", "", str(v or "").lower())


def group_orders(rows, tz, setup):
    """Collapse line-item rows into orders. Order fields come from the first row that has them."""
    need = ["name", "created_at"]
    if rows:
        missing = [c for c in need if c not in rows[0]]
        if missing:
            fail(f"Orders file is missing column(s) {missing}. Export from Shopify admin > Orders > Export > CSV for Excel.")
    orders = {}
    for r in rows:
        name = r.get("name", "")
        if not name:
            continue
        o = orders.get(name)
        if o is None:
            o = orders[name] = {"name": name, "lines": [], "f": {}}
        for k, v in r.items():
            if v and k not in o["f"]:
                o["f"][k] = v
        if r.get("lineitem_name") or r.get("lineitem_quantity"):
            o["lines"].append({
                "name": r.get("lineitem_name", ""),
                "sku": r.get("lineitem_sku", ""),
                "qty": num(r.get("lineitem_quantity"), 0),
                "price": num(r.get("lineitem_price"), 0),
                "discount": num(r.get("lineitem_discount"), 0),
            })
    out = []
    for o in orders.values():
        f = o["f"]
        created = parse_ts(f.get("created_at"), tz)
        if created is None:
            continue
        fin = f.get("financial_status", "").lower()
        email = (f.get("email") or "").strip().lower()
        phone = phone_key(pick(f, "phone", "billing_phone", "shipping_phone"))
        gateway = " ".join([f.get("payment_method", ""), f.get("payment_gateway", ""), f.get("gateway", "")])
        tags = [t.strip().lower() for t in f.get("tags", "").split(",") if t.strip()]
        note = pick(f, "notes", "note")
        is_test = ("bogus" in gateway.lower() or any(t in TEST_TAGS for t in tags)
                   or bool(re.search(r"(?<![a-z])test(?![a-z])", note.lower()))
                   or str(f.get("test", "")).strip().lower() in ("true", "yes", "1"))
        out.append({
            "name": o["name"],
            "date": created.date(),
            "ts": created,
            # Shopify renamed the column "Cancelled at" to "Canceled at" (one L); accept both.
            "cancelled": bool(pick(f, "cancelled_at", "canceled_at")) or fin == "voided",
            "cancelled_at": bool(pick(f, "cancelled_at", "canceled_at")),
            "financial": fin.replace(" ", "_"),
            "fulfillment": pick(f, "fulfillment_status", "display_fulfillment_status").lower().replace(" ", "_"),
            "cancel_reason": pick(f, "cancel_reason", "cancellation_reason").lower(),
            "returned_units": num(pick(f, *RETURNED_COLS), 0),
            "subtotal": num(f.get("subtotal"), 0),
            "discount": num(f.get("discount_amount"), 0),
            "refunded": num(f.get("refunded_amount"), 0),
            "customer": ("e:" + email) if email else (("p:" + phone) if phone else ""),
            "cod": has_word(gateway, setup["cod_keywords"]),
            "tags": tags,
            "test": is_test,
            "lines": o["lines"],
        })
    return out


def week_bounds(setup, tz, as_of=None, week_start=None):
    wanted = str(setup["week_start"]).strip().lower()[:3]
    ws = next((i for i, d in enumerate(WEEKDAYS) if d.startswith(wanted)), None) if len(wanted) == 3 else None
    if ws is None:
        fail(f"Unknown week_start '{setup['week_start']}'. Use saturday, sunday or monday.")
    if week_start:
        start = dt.date.fromisoformat(week_start)
    else:
        today = dt.date.fromisoformat(as_of) if as_of else dt.datetime.now(tz).date()
        current = today - dt.timedelta(days=(today.weekday() - ws) % 7)
        start = current - dt.timedelta(days=7)
    return {
        "this": start,
        "last": start - dt.timedelta(days=7),
        "four_weeks_ago": start - dt.timedelta(days=28),
    }


def in_week(d, start):
    return start <= d <= start + dt.timedelta(days=6)


def _has(text, words):
    t = str(text or "").lower()
    return any(w and str(w).lower() in t for w in words)


def courier_outcome(status, setup):
    """'failed', 'delivered' or None from a courier status text (failed words checked first).
    "Out for delivery" matches neither, so it stays open."""
    if not status:
        return None
    if _has(status, setup.get("failed_courier_statuses", [])):
        return "failed"
    if _has(status, setup.get("delivered_courier_statuses", [])):
        return "delivered"
    return None


def delivery_outcome(order, courier, setup):
    """delivered / failed / open / not_shipped / cancelled_before_shipping / cancelled_other.

    Same rules as cod-rto-analysis (scripts/orders.py classify), so both skills agree. On COD stores a
    refused parcel is usually recorded as "cancelled after fulfilment" (Fulfillment Status fulfilled,
    Cancelled at set, Financial Status voided), not with a tag. delivered_tags is the one extra rule:
    a delivered tag on a shipped or unshipped order that is not cancelled counts as delivered."""
    failed_tags = {str(t).strip().lower() for t in setup.get("failed_tags", [])}
    delivered_tags = {str(t).strip().lower() for t in setup.get("delivered_tags", [])}
    shipped = order["fulfillment"] in SHIPPED
    cancelled = order["cancelled_at"]
    if any(t in failed_tags for t in order["tags"]):
        outcome = "failed"
    elif cancelled and not shipped:
        outcome = "cancelled_before_shipping"
    elif cancelled:
        reasons = [str(x).lower() for x in setup.get("failed_cancel_reasons", [])]
        if not setup.get("count_cancelled_after_fulfillment_as_failed", True):
            outcome = "cancelled_other"
        elif order["cancel_reason"] and reasons and order["cancel_reason"] not in reasons:
            outcome = "cancelled_other"
        else:
            outcome = "failed"
    elif any(t in delivered_tags for t in order["tags"]):
        outcome = "delivered"
    elif shipped and order["financial"] in [str(x).lower() for x in setup.get("failed_financial_statuses", [])]:
        outcome = "failed"
    elif order["financial"] == "voided":
        outcome = "cancelled_before_shipping"   # voided and never shipped: a cancellation
    elif shipped and order["financial"] in PAID:
        outcome = "delivered"
    elif shipped:
        outcome = "open"
    else:
        outcome = "not_shipped"
    st = courier.get(ref_key(order["name"]))
    c = courier_outcome(st, setup)
    if c:   # the courier saw the parcel, so its status wins over Shopify's
        outcome = c
    return outcome


def pct(a, b):
    return round(a / b * 100, 1) if b else None


def week_kpis(orders, start, first_seen, courier, setup):
    wk = [o for o in orders if in_week(o["date"], start)]
    live = [o for o in wk if not o["cancelled"]]
    outcome = {o["name"]: delivery_outcome(o, courier, setup) for o in wk}
    n = len(live)
    subtotal = sum(o["subtotal"] for o in live)
    refunded = sum(o["refunded"] for o in live)
    gross = sum(l["qty"] * l["price"] for o in live for l in o["lines"])
    discount = sum(o["discount"] for o in live)
    custs = {o["customer"] for o in live if o["customer"]}
    new = sum(1 for c in custs if in_week(first_seen[c], start))
    cod = [o for o in live if o["cod"]]
    # COD delivery success: every COD order of the week that was not cancelled before shipping,
    # including refused parcels recorded as cancellations (they are not in "orders").
    cod_out = [outcome[o["name"]] for o in wk if o["cod"]
               and outcome[o["name"]] not in ("cancelled_before_shipping", "cancelled_other")]
    dl, fl = cod_out.count("delivered"), cod_out.count("failed")
    failed_n = sum(1 for o in wk if outcome[o["name"]] == "failed")
    return {
        "net_sales": round(subtotal - refunded, 2),
        "orders": n,
        "aov": round(subtotal / n, 2) if n else None,
        "units": sum(l["qty"] for o in live for l in o["lines"]),
        "new_customers": new,
        "returning_customers": len(custs) - new,
        "discount_share": pct(discount, gross),
        "refunds": round(refunded, 2),
        "refund_rate": pct(sum(1 for o in live if o["refunded"] > 0), n),
        "cod_share": pct(len(cod), n),
        "cod_delivery_success": pct(dl, dl + fl),
        "returned_units": sum(o["returned_units"] for o in live),
        # Cancelled orders that are not failed deliveries (mostly cancelled before shipping).
        "cancelled_orders": sum(1 for o in wk if o["cancelled"] and outcome[o["name"]] != "failed"),
        "failed_deliveries": failed_n,
        "_cod": {"cod_orders": len(cod_out), "delivered": dl, "failed": fl, "unknown": len(cod_out) - dl - fl},
        # How many orders each rate is computed from (small bases are not ranked in "act on this").
        "_base": {"discount_share": n, "refund_rate": n, "cod_share": n, "cod_delivery_success": dl + fl},
        "_no_customer_key": sum(1 for o in live if not o["customer"]),
    }


def compare(cur, prev, kind, setup):
    if cur is None or prev is None:
        return None
    if kind == "rate":
        change = round(cur - prev, 1)
        unit, threshold = "pp", setup["flag_threshold_pp"]
    else:
        if prev == 0 and cur == 0:
            return {"change": 0.0, "unit": "%", "arrow": "→", "flag": False, "severity": 0.0}
        if prev == 0:
            return {"change": None, "unit": "%", "arrow": "↑" if cur > 0 else "→", "flag": False, "severity": 0}
        change = round((cur - prev) / abs(prev) * 100, 1)
        unit, threshold = "%", setup["flag_threshold_pct"]
    arrow = "↑" if change > 0 else ("↓" if change < 0 else "→")
    severity = abs(change) / threshold if threshold else 0
    return {"change": change, "unit": unit, "arrow": arrow, "flag": severity >= 1, "severity": round(severity, 3)}


def fmt_change(c, absolute=False):
    """'+12.5%' / '-3.2 pp'. absolute=True drops the sign, for text that already says rose/fell."""
    v = abs(c["change"]) if absolute else c["change"]
    sign = "+" if v > 0 and not absolute else ""
    return f"{sign}{v}{' pp' if c['unit'] == 'pp' else '%'}"


def product_sales(orders, start, days, grouping):
    end = start + dt.timedelta(days=days - 1)
    out = {}
    for o in orders:
        if o["cancelled"] or not (start <= o["date"] <= end):
            continue
        for l in o["lines"]:
            p = product_name(l["name"], grouping)
            s = out.setdefault(p, {"units": 0.0, "revenue": 0.0})
            s["units"] += l["qty"]
            s["revenue"] += l["qty"] * l["price"] - l["discount"]
    return out


def sku_units(orders, start, days):
    end = start + dt.timedelta(days=days - 1)
    out = {}
    for o in orders:
        if o["cancelled"] or not (start <= o["date"] <= end):
            continue
        for l in o["lines"]:
            if l["sku"]:
                out[l["sku"]] = out.get(l["sku"], 0) + l["qty"]
    return out


def inventory_warnings(path, orders, start, setup):
    rows = read_rows(path)
    if not rows:
        return [], "Inventory file is empty."
    stock, names, titles = {}, {}, {}
    for r in rows:
        handle = pick(r, "handle", "url_handle")
        if pick(r, "title", "product_title"):
            titles[handle] = pick(r, "title", "product_title")
        sku = pick(r, "sku", "variant_sku")
        if not sku:
            continue
        qty_raw = pick(r, "available", "available_(not_editable)", "on_hand", "on_hand_(current)",
                       "variant_inventory_qty", "inventory_quantity", "quantity", default=None)
        if qty_raw is None:
            continue
        stock[sku] = stock.get(sku, 0) + num(qty_raw, 0)
        title = pick(r, "title", "product_title") or titles.get(handle, "")
        # Product export: "Option1 Value"; inventory export: "Option 1 Value" (with a space).
        opt = " / ".join(x for x in [pick(r, "option1_value", "option_1_value"), pick(r, "option2_value", "option_2_value")]
                         if x and x != "Default Title")
        if title:
            names[sku] = title + (f" - {opt}" if opt else "")
    if not stock:
        return [], "Inventory file has no SKU plus quantity columns (wanted SKU and Available or Variant Inventory Qty)."
    window_start = start - dt.timedelta(days=21)
    sold = sku_units(orders, window_start, 28)
    limit = setup["inventory_cover_days"]
    out = []
    for sku, units in sold.items():
        if sku not in stock or units <= 0:
            continue
        per_day = units / 28
        cover = stock[sku] / per_day
        if cover < limit:
            out.append({"sku": sku, "name": names.get(sku, sku), "available": stock[sku],
                        "units_sold_28d": units, "per_day": round(per_day, 2),
                        "days_of_cover": round(max(cover, 0), 1)})
    out.sort(key=lambda x: (x["days_of_cover"], -x["units_sold_28d"], x["sku"]))
    return out, None


def load_courier(path):
    out = {}
    for r in read_rows(path):
        ref = pick(r, "order", "order_number", "order_name", "order_id", "business_reference",
                   "reference", "ref")
        status = pick(r, "status", "delivery_status", "state", "shipment_status")
        if ref and status:
            out[ref_key(ref)] = status
    return out


def usual_first_hour(orders, skip_day):
    """Median hour of the day (local, with fractions) of each day's first order, the first data day left out."""
    first = {}
    for o in orders:
        if o["date"] == skip_day:
            continue
        h = o["ts"].hour + o["ts"].minute / 60
        first[o["date"]] = min(first.get(o["date"], 24), h)
    if len(first) < 3:
        return None   # too few days to know the store's rhythm
    vals = sorted(first.values())
    return vals[len(vals) // 2]


def build(args):
    setup = load_setup(args.setup)
    tz = get_tz(setup["timezone"])
    rows = read_rows(args.orders)
    if not rows:
        fail("Orders file has no rows.")
    orders = group_orders(rows, tz, setup)
    tests = [o for o in orders if o["test"]]
    orders = [o for o in orders if not o["test"]]
    if not orders:
        fail("No orders with a readable Created at date (test orders are not counted).")
    weeks = week_bounds(setup, tz, args.as_of, args.week_start)
    history_start_ts = min(o["ts"] for o in orders)
    history_start = history_start_ts.date()
    history_end = max(o["date"] for o in orders)
    first_seen = {}
    for o in sorted(orders, key=lambda x: x["date"]):
        if o["customer"] and not o["cancelled"]:
            first_seen.setdefault(o["customer"], o["date"])
    courier = load_courier(args.courier) if args.courier else {}
    analytics = {}
    if args.analytics:
        with open(args.analytics, encoding="utf-8") as fh:
            analytics = json.load(fh)

    notes = []
    this_end = weeks["this"] + dt.timedelta(days=6)
    if tests:
        in_week_n = sum(1 for o in tests if in_week(o["date"], weeks["this"]))
        notes.append(f"{len(tests)} test orders (Shopify test gateway, or tagged or noted as test) were left out of "
                     f"every KPI, {in_week_n} of them in the report week.")
    if history_end < weeks["this"]:
        notes.append(f"STALE DATA: the latest order in the data is {history_end}, before the report week starts ({weeks['this']}). Export fresh orders; these numbers are not this week's.")
    elif history_end < this_end:
        notes.append(f"The latest order in the data is {history_end}, before the report week ends ({this_end}). If the export was made before the week ended, this week is incomplete.")
    currencies = sorted({r.get("currency", "").upper() for r in rows if r.get("currency")})
    if len(currencies) > 1:
        notes.append(f"The orders use more than one currency ({', '.join(currencies)}). Amounts are added as they appear in the export, without conversion.")
    vals, partial = {}, []
    usual = usual_first_hour(orders, history_start)
    for w, start in weeks.items():
        if history_start > start:
            vals[w] = None
            if w == "this":
                notes.append(f"The order data starts {history_start}, after the report week starts, so this week's numbers are left blank. Export a longer date range.")
            else:
                notes.append(f"No order data for the whole {w.replace('_', ' ')} week (data starts {history_start}); that comparison is left blank.")
        else:
            vals[w] = week_kpis(orders, start, first_seen, courier, setup)
            # Data starting on the week's first day but hours into it: the week is probably cut.
            gap = (history_start_ts.replace(tzinfo=None) - dt.datetime.combine(start, dt.time())).total_seconds() / 3600
            if history_start == start and usual is not None and gap > usual + PARTIAL_MARGIN_HOURS:
                partial.append(w)
                label = {"this": "report week", "last": "last week", "four_weeks_ago": "week of 4 weeks ago"}[w]
                notes.append(f"PARTIAL WEEK: the order data starts {history_start_ts.strftime('%Y-%m-%d %H:%M')}, "
                             f"{int(gap)} hours into the {label} (orders usually start by {int(usual)}:{int(usual % 1 * 60):02d}), so that week is probably missing orders. Its "
                             f"comparisons are marked (partial) and not used in 'act on this'. Export a longer date range.")
            a = analytics.get(w) or {}
            for k in ("sessions", "conversion_rate"):
                vals[w][k] = a.get(k)

    chosen = list(setup["kpis"])
    # Older setups list "cancelled_orders" only: failed deliveries were inside it, so show both.
    if "cancelled_orders" in chosen and "failed_deliveries" not in chosen:
        chosen.append("failed_deliveries")
    has_returns = any(c in rows[0] for c in RETURNED_COLS)
    if has_returns and "refunds" in chosen:
        chosen.append("returned_units")   # only when connector data with restock quantities was given
    keys = [k for k in KPI_META if k in chosen or (k == "refund_rate" and "refunds" in chosen)]
    if not analytics:
        if "sessions" in chosen or "conversion_rate" in chosen:
            notes.append("Sessions and conversion rate are not shown: Shopify analytics was not reachable (no ShopifyQL result). They are never estimated.")
        keys = [k for k in keys if k not in ("sessions", "conversion_rate")]

    kpis = []
    for k in keys:
        label, kind, pol = KPI_META[k]
        get = lambda w: vals[w][k] if vals[w] else None  # noqa: E731
        row = {"key": k, "label": label, "kind": kind, "polarity": pol,
               "this": get("this"), "last": get("last"), "four_weeks_ago": get("four_weeks_ago"),
               "vs_last": compare(get("this"), get("last"), kind, setup),
               "vs_four_weeks_ago": compare(get("this"), get("four_weeks_ago"), kind, setup)}
        for vs, w in (("vs_last", "last"), ("vs_four_weeks_ago", "four_weeks_ago")):
            if row[vs] and ("this" in partial or w in partial):
                row[vs]["partial"] = True
        if kind == "rate" and k in (vals["this"] or {}).get("_base", {}):
            row["base"] = {w: (vals[w]["_base"][k] if vals[w] else None) for w in weeks}
        tgt = (setup.get("targets") or {}).get(k)
        tgt = num(tgt, 0) if isinstance(tgt, str) else tgt
        if tgt not in (None, "", 0) and row["this"] is not None:
            row["target"] = tgt
            row["vs_target_pct"] = round((row["this"] - tgt) / tgt * 100, 1)
        kpis.append(row)

    this = vals["this"] or {}
    cod = this.get("_cod")
    settling = bool(cod and cod["cod_orders"] and cod["unknown"] / cod["cod_orders"] > 0.3)
    if settling:
        for row in kpis:
            if row["key"] == "cod_delivery_success":
                row["settling"] = True
    if cod and "cod_delivery_success" in chosen:
        if settling:
            notes.append(f"COD delivery success is still settling: {cod['unknown']} of {cod['cod_orders']} COD orders this week have no final delivery status yet.")
        if not courier and cod["delivered"] + cod["failed"] == 0:
            notes.append("COD delivery success needs a final status per COD order: a courier export, delivered/failed "
                         "order tags, or Fulfillment and Financial Status columns (paid after fulfilment = delivered, "
                         "cancelled or voided after fulfilment = failed). None gave a result this week.")
    if "fulfillment_status" not in rows[0] and "display_fulfillment_status" not in rows[0] and this.get("cancelled_orders"):
        notes.append("The orders file has no Fulfillment Status column, so cancelled orders could not be split into "
                     "cancelled before shipping and failed deliveries; all are counted as cancelled before shipping.")
    if (not has_returns and "refunds" in chosen
            and all(v is None or not v["refunds"] for v in vals.values()) and this.get("orders")):
        notes.append("Refunds are 0 in every week shown. If you take returns without refunding (Try & Buy at the door, "
                     "exchanges, store credit), the orders export cannot see them; the Shopify connector can add "
                     "returned units (see references/data-sources.md).")
    if this.get("_no_customer_key"):
        notes.append(f"{this['_no_customer_key']} orders had no email or phone, so they are not counted as new or returning.")
    if (weeks["this"] - history_start).days < 180:
        notes.append(f"Order history starts {history_start}; customers who first bought before that are counted as new. Export more history for accurate new vs returning.")

    grouping = setup["product_grouping"]
    top, bottom = [], []
    if "top_products" in chosen or "bottom_products" in chosen:
        cur = product_sales(orders, weeks["this"], 7, grouping)
        prev = product_sales(orders, weeks["last"], 7, grouping)
        recent = product_sales(orders, weeks["this"] - dt.timedelta(days=21), 28, grouping)

        def entry(p):
            c, l = cur.get(p, {"units": 0, "revenue": 0}), prev.get(p, {"units": 0, "revenue": 0})
            ch = compare(c["revenue"], l["revenue"], "money", setup) if l["revenue"] else None
            return {"product": p, "units": c["units"], "revenue": round(c["revenue"], 2),
                    "last_week_revenue": round(l["revenue"], 2),
                    "change_pct": ch["change"] if ch else None}
        ranked = sorted(cur, key=lambda p: (-cur[p]["revenue"], -cur[p]["units"], p))
        top = [entry(p) for p in ranked[:5]]
        top_names = {t["product"] for t in top}
        pool = [p for p in set(recent) | set(prev) if p not in top_names]
        pool.sort(key=lambda p: (cur.get(p, {}).get("revenue", 0), -prev.get(p, {}).get("revenue", 0), p))
        bottom = [entry(p) for p in pool[:5]]

    inv = []
    if "inventory_warnings" in chosen:
        if args.inventory:
            inv, err = inventory_warnings(args.inventory, orders, weeks["this"], setup)
            if err:
                notes.append(err)
        else:
            notes.append("Inventory warnings need an inventory export (Products > Inventory > Export) or connector access.")

    have_delivery = bool(courier) or any(v and (v["_cod"]["delivered"] + v["_cod"]["failed"]) for v in vals.values())
    act = action_items(kpis, inv, setup, have_analytics=bool(analytics), have_delivery_data=have_delivery,
                       missing_history=vals["last"] is None or vals["four_weeks_ago"] is None)
    fmt = lambda d: {"start": str(d), "end": str(d + dt.timedelta(days=6))}  # noqa: E731
    return {
        "skill": "weekly-kpi-digest",
        "store_name": setup.get("store_name", ""),
        "currency": setup.get("currency") or (rows[0].get("currency", "") if rows else ""),
        "timezone": setup["timezone"],
        "week_start": setup["week_start"],
        "weeks": {w: fmt(d) for w, d in weeks.items()},
        "history_start": str(history_start),
        "history_end": str(history_end),
        "partial_weeks": partial,
        "kpis": kpis,
        "cod_delivery": cod,
        "top_products": top if "top_products" in chosen else [],
        "bottom_products": bottom if "bottom_products" in chosen else [],
        "inventory_warnings": inv,
        "inventory_cover_days": setup["inventory_cover_days"],
        "thresholds": {"pct": setup["flag_threshold_pct"], "pp": setup["flag_threshold_pp"]},
        "act_on": act,
        "notes": notes,
    }


def small_base(k, week, setup):
    """True when a rate KPI rests on fewer than min_rate_base orders in that week (too few to act on)."""
    base = (k.get("base") or {}).get(week)
    return base is not None and base < setup.get("min_rate_base", DEFAULTS["min_rate_base"])


def action_items(kpis, inv, setup, have_analytics=False, have_delivery_data=False, missing_history=False):
    """Exactly 3 items. Flagged bad changes first, then stock risk, then flagged good, then the rest.
    Rate changes on a small base and COD success for a week still settling are not ranked."""
    cands = []
    for k in kpis:
        if k.get("settling"):
            continue  # most COD orders this week have no final status yet: the rate will still move
        # Last week is the main comparison. If it is missing or flat, use 4 weeks ago at half weight.
        c, vs, weight, wk = k["vs_last"], "vs last week", 1.0, "last"
        if not c or not c["change"] or c.get("partial"):
            c, vs, weight, wk = k["vs_four_weeks_ago"], "vs 4 weeks ago", 0.5, "four_weeks_ago"
        if c and c.get("partial"):
            c = None   # a week cut by the start of the data is not a real change
        if c and c["change"] and (small_base(k, "this", setup) or small_base(k, wk, setup)):
            c = None
        if c and c["change"]:
            direction = 1 if c["change"] > 0 else -1
            good = k["polarity"] * direction
            fallback = f"{k['label']} {'rose' if direction > 0 else 'fell'} {{chg}}."
            text = ACTIONS.get((k["key"], direction), fallback).format(chg=fmt_change(c, absolute=True) + " " + vs)
            rank = (0 if c["flag"] and good < 0 else 1 if c["flag"] and good == 0 else 3 if c["flag"] else 4)
            cands.append({"rank": rank, "severity": round(c["severity"] * weight, 3), "kpi": k["key"], "text": text})
        if (k.get("vs_target_pct") is not None and k["vs_target_pct"] * k["polarity"] < 0
                and not small_base(k, "this", setup)):
            sev = abs(k["vs_target_pct"]) / setup["flag_threshold_pct"]
            if sev >= 1:
                cands.append({"rank": 0, "severity": round(sev, 3), "kpi": k["key"],
                              "text": f"{k['label']} is {abs(k['vs_target_pct'])}% off your weekly target of {k['target']}."})
    if inv:
        worst = inv[0]
        sev = setup["inventory_cover_days"] / max(worst["days_of_cover"], 1)
        cands.append({"rank": 2 if sev < 2 else 0, "severity": round(sev, 3), "kpi": "inventory_warnings",
                      "text": f"{len(inv)} variant(s) have under {setup['inventory_cover_days']} days of stock. Reorder first: {worst['name']} ({worst['days_of_cover']} days left at {worst['per_day']}/day)."})
    cands.sort(key=lambda c: (c["rank"], -c["severity"], c["kpi"]))
    seen, out = set(), []
    for c in cands:
        if c["kpi"] in seen:
            continue
        seen.add(c["kpi"])
        out.append({"kpi": c["kpi"], "text": c["text"], "flagged": c["rank"] < 4})
        if len(out) == 3:
            break
    # Fillers: only suggest data the merchant has not already given.
    fillers = []
    if missing_history:
        fillers.append("Not enough history to compare more KPIs yet. Keep running the digest weekly so trends appear.")
    if not have_analytics:
        fillers.append("Connect Shopify analytics (or the Shopify connector) to add sessions and conversion rate.")
    if not have_delivery_data:
        fillers.append("Add a courier export or delivered/failed tags to track COD delivery success.")
    fillers += ["No other KPI moved enough to act on this week. Keep doing what works.",
                "Some rates rest on fewer than %d orders this week, too few to act on; they will firm up as "
                "orders come in." % setup.get("min_rate_base", DEFAULTS["min_rate_base"]),
                "Keep running the digest weekly so trends show up early."]
    for text in fillers:
        if len(out) == 3:
            break
        out.append({"kpi": None, "text": text, "flagged": False})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--setup")
    ap.add_argument("--inventory")
    ap.add_argument("--courier")
    ap.add_argument("--analytics")
    ap.add_argument("--as-of")
    ap.add_argument("--week-start")
    ap.add_argument("--out")
    args = ap.parse_args()
    digest = build(args)
    text = json.dumps(digest, ensure_ascii=False, indent=1, default=str)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
