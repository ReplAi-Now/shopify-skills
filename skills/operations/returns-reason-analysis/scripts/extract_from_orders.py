"""Build a returns file from a Shopify orders export (refunds, return/exchange/refused tags, notes).

Usage:
    python3 extract_from_orders.py --orders orders_export.csv --out returns_from_orders.csv [--setup setup.json]

Use this when there is no connector and no returns app export. One output row per returned line,
in the same columns classify_reasons.py reads. An order is picked up when:
  - it has a refund (Refunded Amount > 0, or Financial Status refunded / partially_refunded), or
  - a tag matches setup return_tags, exchange_tags or refused_tags (plus failed_tags if set), or
  - it was refused at the door: same rule as the cod-rto-analysis skill, cancelled (or voided) AFTER
    it was fulfilled. On COD stores that is how a failed delivery is usually recorded. These rows get
    type "refused" and are never counted as returns.
Line attribution: whole-order cases (fully refunded, refused, single-item orders) give one row per
line item; refunds are split by line value. A partial refund or exchange on a multi-item order cannot
be tied to a line from the export, so it becomes one row with product "(not identified)" and blank
quantity (money is kept, rates skip it). A partial refund on a single-item order estimates the units
as refund / unit price (counted in "estimated_units"); under half a unit it is money only. Orders
cancelled before shipping are skipped (refund lines with restockType CANCEL are not returns, and an
uncollected COD amount is not money refunded). The reason text is the order note, note attributes and
any tags other than the return / exchange / refused tags themselves.
Prints a JSON summary. When no return or exchange was found, "no_returns_found" explains why and
what data would show them. No network access.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, num, pick, write_csv  # noqa: E402

DEFAULTS = {
    "return_tags": ["returned", "return", "مرتجع"],
    "exchange_tags": ["exchange", "exchanged", "استبدال"],
    "refused_tags": ["refused", "rto", "returned to origin", "رفض", "مرفوض"],
    "failed_tags": [],
    # Same keys and defaults as cod-rto-analysis: a cancellation after fulfilment is a failed delivery.
    "count_cancelled_after_fulfillment_as_failed": True,
    "failed_cancel_reasons": ["customer", "declined", "other"],
    "failed_financial_statuses": ["voided"],
}
SHIPPED = ("fulfilled", "partial", "partially_fulfilled", "shipped")
COLUMNS = ["order", "order_date", "return_date", "product", "variant", "sku", "vendor", "quantity", "type",
           "reason_text", "refund_amount", "return_shipping_cost", "source"]
UNKNOWN = "(not identified)"


def tag_match(tags, words):
    for t in tags:
        for w in words:
            w = w.lower()
            if re.search(r"[a-z]", w):
                if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
                    return True
            elif w in t:
                return True
    return False


def split_name(name):
    if " - " in name:
        p, v = name.rsplit(" - ", 1)
        return p, v
    return name, ""


def extract(rows, setup):
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (setup or {}).items() if k in DEFAULTS and v is not None})
    refused_words = list(cfg["refused_tags"]) + list(cfg["failed_tags"] or [])
    if rows and "name" not in rows[0]:
        raise SystemExit(json.dumps({"error": "Orders file has no 'Name' column. Use Shopify admin > Orders > Export > CSV for Excel."}))
    orders = {}
    for r in rows:
        n = r.get("name", "")
        if not n:
            continue
        o = orders.setdefault(n, {"f": {}, "lines": []})
        for k, v in r.items():
            if v and k not in o["f"]:
                o["f"][k] = v
        if num(r.get("lineitem_quantity"), 0) > 0:
            o["lines"].append(r)
    out = []
    counts = {"refund": 0, "exchange": 0, "refused": 0, "refused_cancelled_after_fulfilment": 0,
              "not_identified": 0, "estimated_units": 0}
    has_fulfillment = bool(rows) and "fulfillment_status" in rows[0]
    for name, o in orders.items():
        f = o["f"]
        tags = [t.strip().lower() for t in f.get("tags", "").split(",") if t.strip()]
        fin = f.get("financial_status", "").lower()
        refunded = num(f.get("refunded_amount"), 0)
        subtotal = num(f.get("subtotal"), 0)
        is_exchange = tag_match(tags, cfg["exchange_tags"])
        is_return = refunded > 0 or fin in ("refunded", "partially_refunded") or tag_match(tags, cfg["return_tags"])
        cancelled_at = bool(pick(f, "cancelled_at", "canceled_at"))   # newer exports: "Canceled at"
        cancelled = cancelled_at or fin == "voided"
        shipped = pick(f, "fulfillment_status").lower().replace(" ", "_") in SHIPPED
        refused_by_status = False
        if shipped and cancelled_at:
            reason = pick(f, "cancel_reason", "cancellation_reason").lower()
            reasons = [str(x).lower() for x in cfg["failed_cancel_reasons"] or []]
            refused_by_status = bool(cfg["count_cancelled_after_fulfillment_as_failed"]) and not (
                reason and reasons and reason not in reasons)
        elif shipped and fin in [str(x).lower() for x in cfg["failed_financial_statuses"] or []]:
            refused_by_status = True
        is_refused = tag_match(tags, refused_words) or refused_by_status
        if not (is_refused or is_exchange or is_return) or (cancelled and not is_refused):
            continue
        if is_refused and not tag_match(tags, refused_words):
            counts["refused_cancelled_after_fulfilment"] += 1
        rtype = "refused" if is_refused else ("exchange" if is_exchange else "refund")
        structural = cfg["return_tags"] + cfg["exchange_tags"] + refused_words
        reason_tags = [t for t in tags if not tag_match([t], structural)]
        text = " | ".join(x for x in [f.get("notes", ""), f.get("note_attributes", ""), ", ".join(reason_tags)] if x)
        base = {"order": name, "order_date": f.get("created_at", "")[:10], "return_date": "",
                "type": rtype, "reason_text": text, "return_shipping_cost": "", "source": "orders_export"}
        lines = o["lines"]
        full = fin == "refunded" or (subtotal > 0 and refunded >= subtotal - 0.01)
        whole_order = rtype == "refused" or len(lines) == 1 or (rtype == "refund" and full)
        if whole_order and rtype == "refund" and not full and len(lines) == 1:
            price = num(lines[0].get("lineitem_price"))
            if price > 0 and round(refunded / price) < 1:
                # Refund under half a unit (shipping fee, goodwill, price adjustment): money only, no units.
                whole_order = False
        if rtype == "refused":
            refunded = 0.0   # an uncollected COD amount is not money refunded
        if not lines or not whole_order:
            out.append(dict(base, product=UNKNOWN, variant="", sku="", vendor="", quantity="",
                            refund_amount=round(refunded, 2)))
            counts["not_identified"] += 1
            counts[rtype] += 1
            continue
        values = [num(l.get("lineitem_quantity")) * num(l.get("lineitem_price")) - num(l.get("lineitem_discount")) for l in lines]
        total = sum(values) or 1
        for l, v in zip(lines, values):
            p, var = split_name(l.get("lineitem_name", ""))
            qty = num(l.get("lineitem_quantity"))
            price = num(l.get("lineitem_price"))
            if rtype == "refund" and not full and price > 0:
                # Single-item order, partial refund: estimate units from the refund (estimate).
                qty = min(qty, round(refunded / price))
                counts["estimated_units"] += 1
            out.append(dict(base, product=p, variant=var, sku=l.get("lineitem_sku", ""),
                            vendor=pick(l, "vendor") or f.get("vendor", ""),
                            quantity=qty, refund_amount=round(refunded * v / total, 2)))
        counts[rtype] += 1
    if not counts["refund"] and not counts["exchange"]:
        counts["no_returns_found"] = no_returns_reason(orders, counts, has_fulfillment)
    return out, counts


def no_returns_reason(orders, counts, has_fulfillment):
    """Plain explanation for an export that yields no returns, and what data would show them."""
    parts = [f"No returns or exchanges were found in this orders export ({len(orders)} orders): no refunds, "
             "no Financial Status refunded, and no return or exchange tags."]
    if counts["refused"]:
        parts.append(f"{counts['refused']} orders were refused at the door (failed COD deliveries); they are "
                     "listed as refused, never as returns.")
    parts.append("Stores that keep returns as Shopify return records, or take items back without refunding "
                 "(Try & Buy at the door, exchanges, store credit), do not show them in the orders export. "
                 "Use the Shopify connector (references/shopify-queries.md) or a returns app export instead.")
    if not has_fulfillment:
        parts.append("The file has no Fulfillment Status column, so refused-at-door orders recorded as "
                     "cancelled after fulfilment could not be detected.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--setup")
    a = ap.parse_args()
    setup = {}
    if a.setup:
        with open(a.setup, encoding="utf-8") as fh:
            setup = json.load(fh)
    out, counts = extract(read_rows(a.orders), setup)
    write_csv(a.out, out, COLUMNS)
    res = {"rows": len(out), "orders": counts, "written": a.out}
    if "no_returns_found" in counts:
        res["no_returns_found"] = counts.pop("no_returns_found")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
