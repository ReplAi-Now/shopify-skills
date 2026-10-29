"""Load Shopify exports (orders, products, inventory) into simple per-variant records.

Imported by the other scripts in this folder (Python 3 standard library only):
    from store_data import load_orders, load_variants, parse_date

Columns are matched after tabular.norm() (lowercase, spaces become "_").
Shopify writes order level fields (Created at, Cancelled at, Subtotal) only on the
first row of each order and product level fields (Title, Type, Tags, Vendor) only on
the first row of each product, so both are carried forward here.
Both the 2026 Shopify export headers and the older ones are read: URL handle / Handle, SKU /
Variant SKU, Price / Variant Price, Compare-at price / Variant Compare At Price, Inventory quantity /
Variant Inventory Qty, Option1 value / Option1 Value / Option 1 Value (inventory export), and
Canceled at / Cancelled at (orders export).
Stock is returned as exported: negative numbers (oversold) are kept so callers can flag them.
Variants are keyed by SKU (upper case). A variant without a SKU is keyed by
"NAME:<product title> - <option values>", which is how Shopify writes "Lineitem name".
A SKU used by several products is kept once (the first product's price and cost, stock
added up) and the other handles are listed in "duplicate_handles".

Refunds: an order whose Financial Status is "refunded" or "voided" gets "refunded": True and
callers drop it like a cancelled one (use counts_as_sale). For "partially_refunded" orders each
line's "qty" is the ordered quantity minus the refunded quantity when the file has a refunded
quantity column (Lineitem refunded quantity); without one the line is kept whole and the order
gets "partial_refund_unknown": True so the caller can say so.
"""
import datetime as dt
import re

from tabular import read_rows, num, norm


class DataError(ValueError):
    """A required column or file is missing. The message says which one."""


def col(row, *names):
    """First non-empty value for any of the names. Also matches Shopify headers
    with a suffix in brackets, e.g. 'available' matches 'available_(not_editable)'."""
    for n in names:
        n = norm(n)
        v = row.get(n)
        if v not in (None, ""):
            return v
        for k, v in row.items():
            if k.startswith(n + "_(") and v not in (None, ""):
                return v
    return ""


def has_col(rows, *names):
    keys = set()
    for r in rows[:50]:
        keys.update(r.keys())
    for n in names:
        n = norm(n)
        if n in keys or any(k.startswith(n + "_(") for k in keys):
            return True
    return False


def parse_date(value, dayfirst=True):
    """ISO dates (2026-10-28, '2026-10-28 14:05:00 +0200'), DD/MM/YYYY (or MM/DD/YYYY with
    dayfirst=False, as Excel writes them on a US locale), or an Excel serial. None if invalid."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            day, month = (a, b) if dayfirst else (b, a)
            if month > 12 >= day:  # cannot be read the chosen way: swap
                day, month = month, day
            return dt.date(y, month, day)
        if re.fullmatch(r"\d{5}(\.\d+)?", s):
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(s)))
    except ValueError:
        return None
    return None


def slash_dayfirst(values):
    """Decide whether slash dates in one column are DD/MM (True) or MM/DD (False).
    MM/DD when some value has a second part above 12 and none has a first part above 12."""
    first_big = second_big = False
    for v in values:
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})/\d{4}", str(v or ""))
        if m:
            first_big = first_big or int(m.group(1)) > 12
            second_big = second_big or int(m.group(2)) > 12
    return not (second_big and not first_big)


def name_key(title, variant_title=""):
    t = (title or "").strip().lower()
    v = (variant_title or "").strip().lower()
    return "NAME:" + (t + " - " + v if v and v != "default title" else t)


def variant_key(sku, title="", variant_title=""):
    sku = (sku or "").strip()
    return sku.upper() if sku else name_key(title, variant_title)


REFUND_QTY_COLS = ("lineitem_refunded_quantity", "lineitem_refunded_qty", "refunded_quantity", "refunded_qty")
FULL_REFUND_STATUSES = ("refunded", "voided")


def counts_as_sale(order):
    """False for cancelled orders and fully refunded or voided orders."""
    return not order["cancelled"] and not order["refunded"]


def load_orders(path):
    """Return a list of orders: {name, date, cancelled, refunded, financial_status, partial_refund_unknown,
    subtotal, lines: [{key, sku, name, qty, ordered_qty, price}]}. "qty" is net of refunded units."""
    rows = read_rows(path)
    if not rows:
        raise DataError(f"{path}: no rows found")
    for need, alts in (("Name", ("name", "order", "order_name")),
                       ("Created at", ("created_at", "date", "order_date")),
                       ("Lineitem quantity", ("lineitem_quantity", "quantity", "qty"))):
        if not has_col(rows, *alts):
            raise DataError(f"orders file is missing the column '{need}'")
    if not has_col(rows, "lineitem_sku", "sku", "lineitem_name"):
        raise DataError("orders file needs 'Lineitem sku' or 'Lineitem name'")
    dayfirst = slash_dayfirst(col(r, "created_at", "date", "order_date") for r in rows)
    has_refund_qty = has_col(rows, *REFUND_QTY_COLS)
    orders, by_name = [], {}
    for r in rows:
        name = col(r, "name", "order", "order_name")
        if not name:
            continue
        o = by_name.get(name)
        if o is None:
            o = {"name": name, "date": None, "cancelled": False, "refunded": False, "financial_status": "",
                 "partial_refund_unknown": False, "subtotal": None, "lines": []}
            by_name[name] = o
            orders.append(o)
        if o["date"] is None:
            o["date"] = parse_date(col(r, "created_at", "date", "order_date"), dayfirst)
        if col(r, "cancelled_at", "canceled_at"):
            o["cancelled"] = True
        fin = col(r, "financial_status").strip().lower().replace(" ", "_")
        if fin and not o["financial_status"]:
            o["financial_status"] = fin
            o["refunded"] = fin in FULL_REFUND_STATUSES
            o["partial_refund_unknown"] = fin == "partially_refunded" and not has_refund_qty
        sub = col(r, "subtotal")
        if sub and o["subtotal"] is None:
            o["subtotal"] = num(sub)
        qty = num(col(r, "lineitem_quantity", "quantity", "qty"))
        sku = col(r, "lineitem_sku", "sku")
        lname = col(r, "lineitem_name")
        if qty <= 0 or not (sku or lname):
            continue
        key = sku.strip().upper() if sku.strip() else "NAME:" + lname.strip().lower()
        net = qty - num(col(r, *REFUND_QTY_COLS)) if has_refund_qty else qty
        if net <= 0:
            continue  # every unit of this line was refunded
        o["lines"].append({"key": key, "sku": sku.strip(), "name": lname, "qty": net, "ordered_qty": qty,
                           "price": num(col(r, "lineitem_price", "price"))})
    return [o for o in orders if o["date"] is not None]


HANDLE_COLS = ("handle", "url_handle")


def _options(r):
    vals = [col(r, f"option{i}_value", f"option_{i}_value") for i in (1, 2, 3)]
    vals = [v for v in vals if v and v.lower() != "default title"]
    return " / ".join(vals)


def _blank(key, sku, handle, title, vtitle):
    return {"key": key, "sku": sku, "handle": handle, "title": title, "variant_title": vtitle,
            "type": "", "vendor": "", "tags": "", "price": None, "compare_at": None, "cost": None,
            "available": None, "on_hand": None, "incoming": None, "status": "",
            "variant_id": "", "product_id": "", "duplicate_handles": []}


def load_variants(products=None, inventory=None):
    """Merge Products > Export and Products > Inventory > Export into {key: record}.

    Inventory numbers (summed over locations) win over 'Variant Inventory Qty'."""
    recs = {}
    if products:
        rows = read_rows(products)
        if not rows:
            raise DataError(f"{products}: no rows found")
        if not has_col(rows, *HANDLE_COLS):
            raise DataError("products file is missing the column 'URL handle' (older exports: 'Handle')")
        carry = {}
        for r in rows:
            h = col(r, *HANDLE_COLS)
            if not h:
                continue
            c = carry.setdefault(h, {"title": "", "type": "", "vendor": "", "tags": "", "status": ""})
            for k, names in (("title", ("title",)), ("type", ("type", "product_type", "product_category")),
                             ("vendor", ("vendor",)), ("tags", ("tags",)), ("status", ("status",))):
                v = col(r, *names)
                if v and not c[k]:
                    c[k] = v
            sku = col(r, "variant_sku", "sku")
            price = col(r, "variant_price", "price")
            if not (sku or price or col(r, "option1_value", "option_1_value")):
                continue  # image-only row
            vt = _options(r)
            key = variant_key(sku, c["title"], vt)
            if key in recs and recs[key]["handle"] != h:
                # Same SKU on another product: orders cannot tell them apart. Keep the first
                # product's price and cost, add up the stock, and list the other handle.
                dup = recs[key]
                if h not in dup["duplicate_handles"]:
                    dup["duplicate_handles"].append(h)
                q = col(r, "variant_inventory_qty", "inventory_quantity", "inventory")
                if q != "" and dup["available"] is not None:
                    dup["available"] += num(q)
                    dup["on_hand"] += num(q)
                continue
            rec = recs.get(key) or _blank(key, sku, h, c["title"], vt)
            rec.update({"type": c["type"], "vendor": c["vendor"], "tags": c["tags"], "status": c["status"]})
            rec["price"] = num(price) if price else None
            ca = col(r, "variant_compare_at_price", "compare_at_price")
            rec["compare_at"] = num(ca) if ca else None
            cost = col(r, "cost_per_item", "unit_cost", "cost")
            rec["cost"] = num(cost) if cost else None
            q = col(r, "variant_inventory_qty", "inventory_quantity", "inventory")
            if q != "":
                rec["available"] = num(q)
                rec["on_hand"] = num(q)
            rec["variant_id"] = col(r, "variant_id")
            rec["product_id"] = col(r, "product_id", "id")
            recs[key] = rec
    if inventory:
        rows = read_rows(inventory)
        if not rows:
            raise DataError(f"{inventory}: no rows found")
        if not has_col(rows, "available", "on_hand"):
            raise DataError("inventory file is missing the column 'Available' (or 'On hand')")
        titles, seen = {}, set()
        for r in rows:
            h = col(r, *HANDLE_COLS)
            t = col(r, "title")
            if h and t:
                titles[h] = t
            title = t or titles.get(h, "")
            sku = col(r, "sku", "variant_sku")
            vt = _options(r)
            key = variant_key(sku, title, vt)
            rec = recs.get(key)
            if rec is None:
                rec = _blank(key, sku, h, title, vt)
                recs[key] = rec
            if h and rec["handle"] and h != rec["handle"] and h not in rec["duplicate_handles"]:
                rec["duplicate_handles"].append(h)
            if key not in seen:
                rec["available"], rec["on_hand"], rec["incoming"] = 0.0, 0.0, 0.0
                seen.add(key)
            avail = col(r, "available")
            onhand = col(r, "on_hand")
            rec["available"] += num(avail if avail != "" else onhand)
            rec["on_hand"] += num(onhand if onhand != "" else avail)
            rec["incoming"] += num(col(r, "incoming"))
    return recs
