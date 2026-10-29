"""Shopify orders export + courier file helpers (Python 3 standard library only).

Used by the analysis script in this folder. Preview how an orders file is read:
    python3 orders.py <orders.csv|xlsx> [courier.csv]

- load_orders(path): one dict per order from a Shopify order export (one row per line item).
- load_courier(path, courier_name, overrides): courier rows with columns mapped by meaning.
- CourierIndex: join courier rows to orders by order number or tracking number.
- classify(order, setup, courier_row): delivered / failed / open / cancelled_before_shipping /
  cancelled_other / not_shipped.
"""
import datetime, json, re, sys
from tabular import read_rows, pick, num, norm

# Order export columns (normalised by tabular.norm). Connector-built files may use the
# GraphQL names on the right; both are accepted.
ORDER_COLS = {
    "name": ["name", "order", "order_name", "order_number"],
    "created": ["created_at", "created", "processed_at", "date"],
    "financial": ["financial_status", "display_financial_status"],
    "fulfillment": ["fulfillment_status", "display_fulfillment_status"],
    "cancelled_at": ["cancelled_at", "canceled_at"],   # Shopify spells it "Canceled at" since 2026
    "cancel_reason": ["cancel_reason", "cancellation_reason"],
    "payment": ["payment_method", "payment_gateway_names", "gateway", "payment_gateway"],
    "tags": ["tags"],
    "total": ["total", "total_price"],
    "subtotal": ["subtotal", "subtotal_price"],
    "shipping": ["shipping", "total_shipping_price", "shipping_price"],
    "taxes": ["taxes", "total_tax"],
    "discount": ["discount_amount", "total_discounts"],
    "refunded": ["refunded_amount", "total_refunded"],
    "source": ["source", "source_name", "channel"],
    "email": ["email", "customer_email"],
    "phone": ["phone", "shipping_phone", "billing_phone", "customer_phone"],
    "country": ["shipping_country", "shipping_country_code", "country"],
    "province_name": ["shipping_province_name", "province_name"],
    "province": ["shipping_province", "shipping_province_code", "province_code", "province"],
    "city": ["shipping_city", "city"],
    "tracking": ["tracking_number", "tracking_numbers", "tracking"],
    "currency": ["currency"],
    "gift_card": ["gift_card_amount", "gift_card_paid", "gift_card"],   # connector-built files only
}
LINE_COLS = {
    "name": ["lineitem_name", "line_item_name", "product"],
    "sku": ["lineitem_sku", "line_item_sku", "sku"],
    "qty": ["lineitem_quantity", "line_item_quantity", "quantity"],
    "price": ["lineitem_price", "line_item_price", "unit_price"],
    # Units the customer sent back after delivery (connector refundLineItems with restockType RETURN).
    "returned": ["lineitem_returned_quantity", "line_item_returned_quantity", "returned_quantity"],
}

COURIER_COLS = {
    "ref": ["order_number", "order_no", "order", "order_id", "order_reference", "business_reference",
            "merchant_reference", "reference", "ref", "order_ref", "shopify_order", "رقم_الطلب"],
    "tracking": ["tracking_number", "tracking_no", "tracking", "awb", "awb_number", "airwaybill",
                 "shipment_number", "shipment_id", "barcode", "رقم_الشحنة"],
    "status": ["status", "delivery_status", "shipment_status", "state", "current_status",
               "last_status", "shipment_state", "delivery_state", "الحالة", "حالة_الشحنة", "حالة_الطلب"],
    "cod_amount": ["cod_amount", "cod", "cod_value", "collected_amount", "cash_amount",
                   "amount_collected", "قيمة_التحصيل"],
    "shipping_fee": ["shipping_fee", "shipping_fees", "shipping_cost", "delivery_fee",
                     "delivery_fees", "delivery_cost", "fees", "shipping", "مصاريف_الشحن"],
    "return_fee": ["return_fee", "return_fees", "rto_fee", "return_shipping", "return_cost",
                   "مصاريف_الارتجاع"],
    "cod_fee": ["cod_fee", "cod_fees", "collection_fee", "cod_commission", "عمولة_التحصيل"],
    "reason": ["reason", "failure_reason", "return_reason", "exception_reason", "fail_reason",
               "undelivered_reason", "comment", "comments", "notes", "سبب"],
    "courier": ["courier", "carrier", "courier_name", "shipping_company"],
    "date": ["last_update", "last_updated", "updated_at", "update_date", "status_date", "last_status_date",
             "date", "delivery_date", "تاريخ_التحديث", "تاريخ_الحالة", "التاريخ"],
}


def _first(rows, cands):
    for r in rows:
        v = pick(r, *cands)
        if v != "":
            return v
    return ""


def _iso_date(value, day_first):
    """'YYYY-MM-DD' from ISO text, d/m/Y or m/d/Y (Excel re-saved CSV) or an Excel serial; '' if unknown."""
    s = str(value or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.match(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
        if m:
            a, b, y = (int(x) for x in m.groups())
            d, mo = (a, b) if day_first else (b, a)
        elif re.fullmatch(r"\d{5}(\.\d+)?", s):
            return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(s)))).isoformat()
        else:
            return ""
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _day_first(values):
    """Slash dates: day first if any first part is above 12, else month first (Excel US default)."""
    for v in values:
        m = re.match(r"\s*(\d{1,2})[/.](\d{1,2})[/.]\d{4}", str(v or ""))
        if m and int(m.group(1)) > 12:
            return True
    return False


def order_key(value):
    """Join key for an order reference: the digits, else the cleaned text. A split-shipment
    suffix after the order number (#1001-2, 1001_2, 1001-F1) is dropped, so it joins on #1001."""
    s = str(value or "").strip()
    s = re.sub(r"(\d{3,})\s*[-_/]\s*[A-Za-z]{0,2}\d{1,2}$", r"\1", s)
    d = re.sub(r"\D", "", s)
    return d.lstrip("0") or d or s.lower().lstrip("#")


def load_orders(path):
    rows = read_rows(path)
    if not rows:
        raise SystemExit(json.dumps({"error": "orders file is empty", "file": path}))
    cols = set(rows[0].keys())
    for need in ("name", "financial", "fulfillment"):
        if not any(norm(c) in cols for c in ORDER_COLS[need]):
            raise SystemExit(json.dumps({"error": "missing column", "wanted": ORDER_COLS[need][0],
                                         "accepted": ORDER_COLS[need], "file": path}))
    grouped, order = {}, []
    for r in rows:
        n = pick(r, *ORDER_COLS["name"])
        if not n:
            continue
        if n not in grouped:
            grouped[n] = []
            order.append(n)
        grouped[n].append(r)
    out = []
    day_first = _day_first(pick(r, *ORDER_COLS["created"]) for r in rows)
    for n in order:
        rs = grouped[n]
        o = {k: _first(rs, c) for k, c in ORDER_COLS.items()}
        o["name"] = n
        o["key"] = order_key(n)
        o["date"] = _iso_date(o["created"], day_first)
        o["financial"] = o["financial"].lower().replace(" ", "_")
        o["fulfillment"] = o["fulfillment"].lower().replace(" ", "_")
        o["cancelled"] = bool(o["cancelled_at"].strip())
        o["cancel_reason"] = o["cancel_reason"].lower()
        o["tags"] = [t.strip().lower() for t in o["tags"].split(",") if t.strip()]
        o["tracking"] = [t.strip() for t in re.split(r"[,;\s]+", o["tracking"]) if t.strip()]
        for k in ("total", "subtotal", "shipping", "taxes", "discount", "refunded"):
            o[k] = num(o[k])
        o["discount"], o["refunded"] = abs(o["discount"]), abs(o["refunded"])   # some exports sign them
        o["gift_card"] = abs(num(o["gift_card"]))
        lines = []
        for r in rs:
            ln = pick(r, *LINE_COLS["name"])
            if not ln:
                continue
            lines.append({"name": ln, "sku": pick(r, *LINE_COLS["sku"]),
                          "qty": num(pick(r, *LINE_COLS["qty"]), 1.0),
                          "price": num(pick(r, *LINE_COLS["price"])),
                          "returned": abs(num(pick(r, *LINE_COLS["returned"])))})
        o["lines"] = lines
        out.append(o)
    return out


def map_columns(columns, overrides=None):
    """Map courier file columns by meaning. overrides: {meaning: header or [headers]}; the first
    header present in this file wins, and a meaning with none present is detected as usual, so
    one override list can serve several courier files."""
    mapping = {}
    for meaning, cands in COURIER_COLS.items():
        want = (overrides or {}).get(meaning, [])
        hit = next((norm(h) for h in ([want] if isinstance(want, str) else want) if norm(h) in columns), None)
        if hit:
            mapping[meaning] = hit
            continue
        for c in cands:
            if c in columns:
                mapping[meaning] = c
                break
        else:
            # fuzzy: header containing the first candidate's words, e.g. "cod_fees_(egp)"
            for col in columns:
                base = re.sub(r"_?\(.*\)$", "", col)
                if base in cands:
                    mapping[meaning] = col
                    break
    return mapping


def load_courier(path, courier_name="", overrides=None):
    rows = read_rows(path)
    if not rows:
        return [], {}
    mapping = map_columns(set(rows[0].keys()), overrides)
    if "ref" not in mapping and "tracking" not in mapping:
        raise SystemExit(json.dumps({"error": "courier file has no order number or tracking column",
                                     "file": path, "columns": list(rows[0].keys()),
                                     "fix": "pass --courier-map ref=<column> or tracking=<column>"}))
    if "status" not in mapping:
        raise SystemExit(json.dumps({"error": "courier file has no status column", "file": path,
                                     "columns": list(rows[0].keys()),
                                     "fix": "pass --courier-map status=<column>"}))
    out = []
    day_first = _day_first(r.get(mapping["date"], "") for r in rows) if "date" in mapping else False
    for r in rows:
        rec = {"courier": courier_name or (r.get(mapping["courier"], "") if "courier" in mapping else "")}
        raw = r.get(mapping["date"], "").strip() if "date" in mapping else ""
        tm = re.search(r"\d{1,2}:\d{2}(:\d{2})?", raw)
        d = _iso_date(raw, day_first)
        rec["when"] = (d + " " + (tm.group(0).zfill(5) if tm else "")) if d else ""
        for m in ("ref", "tracking", "status", "reason"):
            rec[m] = r.get(mapping[m], "").strip() if m in mapping else ""
        for m in ("cod_amount", "shipping_fee", "return_fee", "cod_fee"):
            v = r.get(mapping[m], "").strip() if m in mapping else ""
            # None = not given ("", "N/A", "-"): use the setup default. A written 0 stays 0.
            rec[m] = abs(num(v)) if re.search(r"\d", v) else None
        out.append(rec)
    return out, mapping


class CourierIndex:
    """Join courier rows to orders. With several rows for one order, the latest by date wins when
    the file has a date column; otherwise the most final status (delivered or failed beats in
    transit), and among equals the later row."""

    def __init__(self, rows, setup=None):
        self.by_ref, self.by_tracking, self.used = {}, {}, set()
        self.rows = rows

        def rank(i):
            r = rows[i]
            final = 1 if (setup and courier_outcome(r["status"], setup)) else 0
            return (r.get("when", ""), final, i)

        def put(index, key, i):
            if key not in index or rank(i) > rank(index[key]):
                index[key] = i
        for i, r in enumerate(rows):
            if r["ref"]:
                put(self.by_ref, order_key(r["ref"]), i)
            if r["tracking"]:
                put(self.by_tracking, r["tracking"].strip().lower(), i)

    def match(self, order):
        i = self.by_ref.get(order["key"])
        if i is None:
            for t in order.get("tracking", []):
                i = self.by_tracking.get(t.lower())
                if i is not None:
                    break
        if i is None:
            return None
        self.used.add(i)
        return self.rows[i]

    def unmatched(self):
        return [r for i, r in enumerate(self.rows) if i not in self.used]


def _has(text, words):
    t = str(text or "").lower()
    return any(w and str(w).lower() in t for w in words)


def courier_outcome(status, setup):
    """'failed', 'delivered' or None from a courier status text (failed words checked first)."""
    if not status:
        return None
    if _has(status, setup.get("failed_courier_statuses", [])):
        return "failed"
    if _has(status, setup.get("delivered_courier_statuses", [])):
        return "delivered"
    return None


def is_cod(order, keywords):
    p = str(order.get("payment", "")).lower()
    for k in keywords:
        k = str(k).lower()
        if len(k) <= 4:
            if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", p):
                return True
        elif k in p:
            return True
    return False


SHIPPED = ("fulfilled", "partial", "partially_fulfilled", "shipped")
PAID = ("paid", "partially_refunded", "refunded", "partially_paid")


def classify(order, setup, courier_row=None):
    """Delivery outcome of one order under the merchant's failed-order definition."""
    failed_tags = {str(t).strip().lower() for t in setup.get("failed_tags", [])}
    shipped = order["fulfillment"] in SHIPPED
    tagged = any(t in failed_tags for t in order["tags"])
    outcome = None
    if tagged:
        outcome = "failed"
    elif order["cancelled"] and not shipped:
        outcome = "cancelled_before_shipping"
    elif order["cancelled"] and shipped:
        reasons = [str(x).lower() for x in setup.get("failed_cancel_reasons", [])]
        if not setup.get("count_cancelled_after_fulfillment_as_failed", True):
            outcome = "cancelled_other"
        elif order["cancel_reason"] and reasons and order["cancel_reason"] not in reasons:
            outcome = "cancelled_other"
        else:
            outcome = "failed"
    elif shipped and order["financial"] in [str(s).lower() for s in setup.get("failed_financial_statuses", [])]:
        outcome = "failed"
    elif shipped and order["financial"] in PAID:
        outcome = "delivered"
    elif shipped:
        outcome = "open"
    else:
        outcome = "not_shipped"
    if courier_row is not None:
        c = courier_outcome(courier_row["status"], setup)
        if c == "failed" and not shipped and not tagged and is_cancel_status(courier_row["status"]):
            # Cancelled before pickup: the parcel never left, so it is not a failed delivery.
            outcome = "cancelled_before_shipping"
        elif c:   # the courier saw the parcel, so its status wins over Shopify's
            outcome = c
    return outcome


CANCEL_WORDS = ("cancel", "ملغي", "ملغى", "الغاء", "إلغاء")


def is_cancel_status(status):
    return _has(status, CANCEL_WORDS)


DEFAULT_COURIER_TAGS = {"bosta": "Bosta", "aramex": "Aramex", "j&t": "J&T", "jnt": "J&T", "j and t": "J&T",
                        "mylerz": "Mylerz", "shipblu": "ShipBlu", "ship blu": "ShipBlu", "r2s": "R2S",
                        "smsa": "SMSA", "naqel": "Naqel", "fetchr": "Fetchr", "turbo": "Turbo"}


def courier_from_tags(tags, mapping=None):
    """Courier name from order tags ("Sent to ShipBlu", "bosta_synced"): the first tag containing a
    mapping key (case ignored, longest key first). '' when none matches."""
    mapping = DEFAULT_COURIER_TAGS if mapping is None else mapping
    keys = sorted(((str(k).lower(), v) for k, v in mapping.items() if str(k).strip()), key=lambda kv: -len(kv[0]))
    for t in tags:
        t = str(t).lower()
        for k, v in keys:
            if k in t:
                return v
    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    orders = load_orders(sys.argv[1])
    dates = sorted(o["date"] for o in orders if o["date"])
    kw = ["cash on delivery", "cod", "الدفع عند الاستلام", "الدفع عند التسليم"]
    first = [dict(o, email="***" if o["email"] else "", phone="***" if o["phone"] else "") for o in orders[:2]]
    res = {"orders": len(orders), "from": dates[0] if dates else None, "to": dates[-1] if dates else None,
           "orders_without_date": len(orders) - len(dates), "cod_orders": sum(1 for o in orders if is_cod(o, kw)),
           "first": first}
    if len(sys.argv) > 2:
        rows, mapping = load_courier(sys.argv[2])
        res["courier_rows"] = len(rows)
        res["courier_columns"] = mapping
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
