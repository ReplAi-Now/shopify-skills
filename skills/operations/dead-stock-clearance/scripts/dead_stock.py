#!/usr/bin/env python3
"""Dead stock clearance: classify variants (healthy / slow / dead), cash stuck, and a clearance plan.

Usage:
  python3 dead_stock.py --orders orders.csv --products products.csv [--inventory inventory.csv]
      [--first-stocked first_stocked.csv] [--setup replai-setup/dead-stock-clearance.json]
      [--as-of 2026-10-28] [--out-dir clearance]

Inputs (CSV or XLSX):
  --orders         Shopify admin > Orders > Export (one row per line item)
  --products       Shopify admin > Products > Export (Variant Price, Compare At, Cost per item, Tags, Type)
  --inventory      optional: Products > Inventory > Export (Available summed over locations wins)
  --first-stocked  optional: sku, first_stocked (date the variant was first in stock)

Prints one JSON object. With --out-dir it also writes:
  dead-stock-classification.csv  every variant with its numbers and category
  dead-stock-changes.csv         the proposed store changes (price, compare-at, tag, collection)
  dead-stock-rollback.csv        the old values, to undo every change
Nothing is changed in the store by this script. Formulas: references/method.md.

Evidence: with less order history than "min_evidence_days" (default 60), an item that sold recently is
"too_early" instead of slow (a few sales over a few weeks prove nothing about 6 months of cover).
Negative stock (oversold) counts as 0 units and is flagged. A missing unit cost is unknown, never 0:
cash stuck is null for those items and totals say how many items had a cost.
Expected cash recovered uses an assumed sell-through per tactic (assumed_sell_through_<tactic>_pct,
an estimate the merchant can change); "cash_recovered" is the ceiling if every unit sells.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tabular import read_rows, num, write_csv  # noqa: E402
from store_data import (DataError, col, counts_as_sale, has_col, load_orders, load_variants,  # noqa: E402
                        parse_date, slash_dayfirst)

DEFAULTS = {
    "currency": "EGP",
    "slow_days": 60,
    "dead_days": 120,
    "slow_cover_days": 180,
    "slow_sell_through_pct": 10,
    "sell_through_window_days": 90,
    "cover_window_days": 30,
    "min_age_days": 30,
    "margin_floor_pct": 10,
    "allow_below_cost": False,
    "markdown_steps_pct": [10, 20, 30],
    "price_rounding": 5,
    "allowed_tactics": ["markdown", "bundle", "gift", "clearance_collection", "liquidate"],
    "clearance_tag": "clearance",
    "clearance_collection": "Clearance",
    "bundle_tag": "clearance-bundle",
    "gift_tag": "free-gift",
    "bundle_discount_pct": 15,
    "min_co_orders": 2,
    "gift_threshold_multiplier": 1.3,
    "gift_max_cost_pct_of_aov": 15,
    "liquidation_recovery_pct": 30,
    "min_evidence_days": 60,
    "assumed_sell_through_markdown_pct": 60,
    "assumed_sell_through_bundle_pct": 40,
    "assumed_sell_through_gift_pct": 50,
    "assumed_sell_through_clearance_collection_pct": 25,
    "assumed_sell_through_liquidate_pct": 100,
}
TACTICS = ("markdown", "bundle", "gift", "clearance_collection", "liquidate")
EPS = 1e-9
CHANGE_COLS = ["handle", "product_title", "variant_title", "sku", "variant_id", "level", "field",
               "old_value", "new_value", "tactic", "note"]
ROLLBACK_COLS = ["handle", "product_title", "variant_title", "sku", "variant_id", "level", "field",
                 "action", "restore_value"]


def floor_to(x, step):
    step = step or 1
    return math.floor(x / step + EPS) * step


def ceil_to(x, step):
    step = step or 1
    return math.ceil(x / step - EPS) * step


def clean(x):
    """Whole numbers as int, others rounded to 2 decimals (for JSON and CSV)."""
    if isinstance(x, float):
        r = round(x, 2)
        return int(r) if r == int(r) else r
    return x


def price_floor(cost, st):
    if st["allow_below_cost"]:
        return 0.0
    return ceil_to(cost * (1 + st["margin_floor_pct"] / 100.0), st["price_rounding"])


def markdown_price(price, cost, step_pct, st):
    """Return (new_price, floor, clamped) or (None, floor, reason) when not possible."""
    if cost is None:
        return None, None, "needs unit cost to check the margin floor"
    if not price:
        return None, None, "no current price"
    fl = price_floor(cost, st)
    new = floor_to(price * (1 - step_pct / 100.0), st["price_rounding"])
    clamped = False
    if new < fl - EPS:
        new, clamped = fl, True
    if new >= price - EPS:
        return None, fl, "the margin floor is at or above the current price"
    return new, fl, clamped


def cash_total(values):
    """(total, n_items, n_with_cost). None marks a missing cost. The total is None when no item has a
    cost (unknown, never 0) and 0 only for an empty set."""
    vals = list(values)
    known = [x for x in vals if x is not None]
    return (sum(known) if known or not vals else None), len(vals), len(known)


def load_first_stocked(path):
    out = {}
    if not path:
        return out
    rows = read_rows(path)
    if not has_col(rows, "sku"):
        raise DataError("first-stocked file is missing the column 'sku'")
    if not has_col(rows, "first_stocked", "date", "created_at"):
        raise DataError("first-stocked file is missing the column 'first_stocked'")
    dayfirst = slash_dayfirst(col(r, "first_stocked", "date", "created_at") for r in rows)
    for r in rows:
        d = parse_date(col(r, "first_stocked", "date", "created_at"), dayfirst)
        sku = col(r, "sku").strip().upper()
        if d and sku:
            out[sku] = d
    return out


def run(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--products", required=True)
    ap.add_argument("--inventory")
    ap.add_argument("--first-stocked")
    ap.add_argument("--setup")
    ap.add_argument("--as-of")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    st = dict(DEFAULTS)
    if a.setup:
        with open(a.setup, encoding="utf-8") as fh:
            st.update(json.load(fh))
    for k, v in DEFAULTS.items():  # "10%" or "120 days" typed into the setup still work
        if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(st.get(k), str):
            st[k] = num(st[k], v)
    steps = sorted(num(s) for s in st["markdown_steps_pct"]) or [10.0]
    allowed = set(st["allowed_tactics"])

    all_orders = load_orders(a.orders)
    # Fully refunded or voided orders are not sales (same rule as cancelled ones).
    orders = [o for o in all_orders if counts_as_sale(o)]
    n_refunded = sum(1 for o in all_orders if o["refunded"] and not o["cancelled"])
    n_partial = sum(1 for o in orders if o["partial_refund_unknown"])
    variants = load_variants(a.products, a.inventory)
    first_stocked = load_first_stocked(a.first_stocked)
    as_of = parse_date(a.as_of) if a.as_of else max((o["date"] for o in orders), default=None)
    if as_of is None:
        raise DataError("no dated, non-cancelled orders found")
    orders = [o for o in orders if o["date"] <= as_of]
    earliest = min((o["date"] for o in orders), default=as_of)
    history_days = (as_of - earliest).days + 1
    cov_start = as_of - dt.timedelta(days=int(st["cover_window_days"]) - 1)
    st_start = as_of - dt.timedelta(days=int(st["sell_through_window_days"]) - 1)

    last_sale, units_cov, units_st, pairs, first_sale = {}, {}, {}, {}, {}
    order_values = []
    for o in orders:
        keys = set()
        for ln in o["lines"]:
            k = ln["key"]
            keys.add(k)
            if k not in last_sale or o["date"] > last_sale[k]:
                last_sale[k] = o["date"]
            if k not in first_sale or o["date"] < first_sale[k]:
                first_sale[k] = o["date"]
            if o["date"] >= cov_start:
                units_cov[k] = units_cov.get(k, 0) + ln["qty"]
            if o["date"] >= st_start:
                units_st[k] = units_st.get(k, 0) + ln["qty"]
        for x in keys:
            for y in keys:
                if x != y:
                    pairs.setdefault(x, {})
                    pairs[x][y] = pairs[x].get(y, 0) + 1
        if o["date"] >= st_start:
            v = o["subtotal"] if o["subtotal"] is not None else sum(ln["qty"] * ln["price"] for ln in o["lines"])
            order_values.append(v)
    aov = sum(order_values) / len(order_values) if order_values else None

    items = []
    for k, v in variants.items():
        raw = v["available"]
        owed = max(-raw, 0.0) if raw is not None else 0.0
        stock = max(raw, 0.0) if raw is not None else None  # oversold (negative) stock is 0 units on the shelf
        it = {"key": k, "sku": v["sku"] or "", "handle": v["handle"], "title": v["title"],
              "variant_title": v["variant_title"], "type": v["type"], "variant_id": v["variant_id"],
              "price": v["price"], "compare_at": v["compare_at"], "unit_cost": v["cost"], "tags": v["tags"],
              "stock": stock, "oversold_units": owed, "flags": []}
        if owed:
            it["flags"].append("oversold: stock is %g, so %g units are owed to customers (counted as 0 in stock)"
                               % (raw, owed))
        ls = last_sale.get(k)
        it["last_sale"] = ls.isoformat() if ls else None
        it["days_since_last_sale"] = (as_of - ls).days if ls else None
        uc = units_cov.get(k, 0)
        # With less history than the window, divide by the days actually covered.
        rate = uc / float(max(min(int(st["cover_window_days"]), history_days), 1))
        it["units_sold_cover_window"] = uc
        it["recent_daily_sales"] = rate
        it["days_of_cover"] = (stock / rate) if (rate > 0 and stock is not None) else None
        us = units_st.get(k, 0)
        it["units_sold_sell_through_window"] = us
        it["sell_through_pct"] = (100.0 * us / (us + stock)) if stock is not None and (us + stock) > 0 else None
        fsd = first_stocked.get(k)
        it["first_stocked"] = fsd.isoformat() if fsd else None
        it["age_days"] = (as_of - fsd).days if fsd else None
        if stock is None or stock <= 0:
            it["cash_stuck"] = 0.0
        else:
            it["cash_stuck"] = stock * v["cost"] if v["cost"] is not None else None  # unknown, never 0
        if v["cost"] is None:
            it["flags"].append("missing unit cost")
        it["duplicate_handles"] = list(v["duplicate_handles"])
        if v["duplicate_handles"]:
            it["flags"].append("SKU also used by: %s (no store change proposed; give each variant its own SKU)"
                               % ", ".join(v["duplicate_handles"]))

        # classification
        age = it["age_days"]
        dsl = it["days_since_last_sale"]
        if stock is None:
            cat, why = "unknown", "stock unknown"
        elif stock <= 0:
            cat, why = "no_stock", ("oversold: %g units owed to customers" % owed) if owed else "nothing in stock"
        elif age is not None and age < st["min_age_days"]:
            cat, why = "new", f"in stock for {age} days only"
        elif dsl is None:
            span = age if age is not None else history_days
            if span >= st["dead_days"]:
                cat, why = "dead", (f"never sold in {span} days" if age is not None else
                                    f"no sale in the whole order history ({history_days} days)")
            else:
                cat, why = "unknown", f"no sale yet, only {span} days of data"
        elif dsl >= st["dead_days"]:
            cat, why = "dead", f"last sale {dsl} days ago"
        elif dsl >= st["slow_days"]:
            cat, why = "slow", f"last sale {dsl} days ago"
        elif history_days < st["min_evidence_days"] and (
                (it["days_of_cover"] is not None and it["days_of_cover"] >= st["slow_cover_days"])
                or (it["days_of_cover"] is None and dsl >= st["cover_window_days"])):
            cat, why = "too_early", (f"only {history_days} days of order history (need {st['min_evidence_days']} "
                                     f"to judge); {units_st.get(k, 0):g} sold so far")
        elif it["days_of_cover"] is not None and it["days_of_cover"] >= st["slow_cover_days"]:
            cat, why = "slow", f"{round(it['days_of_cover'])} days of cover at the current sales rate"
        elif it["days_of_cover"] is None and dsl >= st["cover_window_days"]:
            cat, why = "slow", f"no sale in the last {st['cover_window_days']} days"
        elif (it["sell_through_pct"] is not None and it["sell_through_pct"] < st["slow_sell_through_pct"]
              and (age is None or age >= st["sell_through_window_days"])
              and history_days >= st["sell_through_window_days"]):
            cat, why = "slow", f"sell-through {it['sell_through_pct']:.1f}% over {st['sell_through_window_days']} days"
        else:
            cat, why = "healthy", ""
        it["category"], it["reason"] = cat, why
        if cat == "dead":
            span = dsl if dsl is not None else (age if age is not None else history_days)
            it["extreme"] = span >= 2 * st["dead_days"]
        else:
            it["extreme"] = False
        items.append(it)

    by_key = {i["key"]: i for i in items}
    fast = [i for i in items if i["category"] == "healthy" and (i["stock"] or 0) > 0 and i["units_sold_cover_window"] > 0]

    def partner_for(it):
        co = pairs.get(it["key"], {})
        best = None
        for f in fast:
            n = co.get(f["key"], 0)
            if n >= st["min_co_orders"]:
                cand = (n, f["recent_daily_sales"], f["key"])
                if best is None or cand > best[0]:
                    best = (cand, f)
        if best:
            return best[1], "co_purchase", best[0][0]
        same = [f for f in fast if f["type"] and f["type"] == it["type"]]
        if same:
            f = max(same, key=lambda x: (x["recent_daily_sales"], x["key"]))
            return f, "same_category", co.get(f["key"], 0)
        return None, None, 0

    gift_threshold = ceil_to(aov * st["gift_threshold_multiplier"], st["price_rounding"]) if aov else None

    for it in items:
        it["options"], it["recommended"] = [], None
        if it["category"] not in ("slow", "dead"):
            continue
        p, c, n = it["price"], it["unit_cost"], it["stock"]
        before = (p - c) if (p is not None and c is not None) else None
        if it["category"] == "slow":
            step = steps[0]
        elif it["extreme"]:
            step = steps[-1]
        else:
            step = steps[1] if len(steps) > 1 else steps[-1]
        opts = {}
        if "markdown" in allowed:
            new, fl, info = markdown_price(p, c, step, st)
            if new is not None:
                opts["markdown"] = {"tactic": "markdown", "step_pct": step, "new_price": new, "floor_price": fl,
                                    "discount_pct": 100.0 * (p - new) / p, "floor_applied": bool(info),
                                    "cash_recovered": new * n, "profit_if_all_sell": (new - c) * n,
                                    "margin_per_unit_before": before, "margin_per_unit_after": new - c,
                                    "revenue_given_up": (p - new) * n,
                                    "note": "cash if every unit sells at this price"}
            else:
                it["flags"].append("markdown not possible: " + info)
        if "bundle" in allowed:
            f, basis, nco = partner_for(it)
            if f is not None:  # kept so the dashboard can re-check the bundle when inputs change
                it["bundle_partner"] = {"sku": f["sku"] or f["key"], "title": f["title"], "basis": basis,
                                        "co_orders": nco, "price": f["price"]}
            if f is not None and c is not None and p:
                bp = max(floor_to(p * (1 - st["bundle_discount_pct"] / 100.0), st["price_rounding"]),
                         price_floor(c, st))
                if bp < p - EPS or st["bundle_discount_pct"] == 0:
                    opts["bundle"] = {"tactic": "bundle", "partner_sku": f["sku"] or f["key"],
                                      "partner_title": f["title"], "basis": basis, "co_orders": nco,
                                      "item_price_in_bundle": bp, "bundle_price": bp + (f["price"] or 0),
                                      "cash_recovered": bp * n, "profit_if_all_sell": (bp - c) * n,
                                      "margin_per_unit_before": before, "margin_per_unit_after": bp - c,
                                      "revenue_given_up": (p - bp) * n,
                                      "note": "bought together in %d orders" % nco if basis == "co_purchase"
                                      else "no co-purchase data: fast mover from the same product type"}
        if "gift" in allowed and c is not None and aov:
            if c <= aov * st["gift_max_cost_pct_of_aov"] / 100.0 + EPS:
                opts["gift"] = {"tactic": "gift", "threshold": gift_threshold, "aov": aov,
                                "cash_recovered": 0.0, "profit_if_all_sell": -c * n,
                                "margin_per_unit_before": before, "margin_per_unit_after": -c,
                                "revenue_given_up": (p or 0) * n,
                                "note": "free with orders above the threshold; the cost is already paid, "
                                        "this is the accounting loss"}
        if "clearance_collection" in allowed and p is not None:
            opts["clearance_collection"] = {"tactic": "clearance_collection", "cash_recovered": p * n,
                                            "profit_if_all_sell": (p - c) * n if c is not None else None,
                                            "margin_per_unit_before": before, "margin_per_unit_after": before,
                                            "revenue_given_up": 0.0,
                                            "note": "visibility only, price unchanged"}
        if "liquidate" in allowed and c is not None:
            rec = c * st["liquidation_recovery_pct"] / 100.0
            opts["liquidate"] = {"tactic": "liquidate", "recovery_per_unit": rec, "cash_recovered": rec * n,
                                 "profit_if_all_sell": (rec - c) * n, "margin_per_unit_before": before,
                                 "margin_per_unit_after": rec - c, "revenue_given_up": ((p or 0) - rec) * n,
                                 "note": "estimate: %g%% of cost from a stock buyer; donating recovers 0"
                                         % st["liquidation_recovery_pct"]}

        md = opts.get("markdown")
        rec = None
        if it["category"] == "slow":
            b = opts.get("bundle")
            if b and b["basis"] == "co_purchase":
                rec = "bundle"
            elif md:
                rec = "markdown"
            elif "gift" in opts:
                rec = "gift"
            elif "clearance_collection" in opts:
                rec = "clearance_collection"
        elif it["extreme"]:
            if md and not md["floor_applied"]:
                rec = "markdown"
            elif "liquidate" in opts:
                rec = "liquidate"
            elif md:
                rec = "markdown"
        else:
            if md:
                rec = "markdown"
            elif "gift" in opts:
                rec = "gift"
            elif "liquidate" in opts:
                rec = "liquidate"
        if rec == "markdown" and it["category"] == "dead" and "clearance_collection" in allowed:
            rec = "markdown_clearance"
        for t, o in opts.items():
            # Expected result with an assumed share of the units selling (an estimate, editable in setup).
            pct = float(st["assumed_sell_through_%s_pct" % t])
            o["assumed_sell_through_pct"] = pct
            o["expected_units_sold"] = n * pct / 100.0
            o["expected_cash_recovered"] = o["cash_recovered"] * pct / 100.0
            per_unit = o["margin_per_unit_after"]
            o["expected_profit"] = per_unit * o["expected_units_sold"] if per_unit is not None else None
        it["options"] = [opts[k] for k in TACTICS if k in opts]
        if it["duplicate_handles"]:
            rec = None  # a shared SKU cannot be changed safely: the change could hit the wrong product
        it["recommended"] = rec

    # change list and rollback
    changes, rollback, done_product = [], [], set()

    def add(it, level, field, old, new, tactic, note=""):
        base = {"handle": it["handle"], "product_title": it["title"], "variant_title": it["variant_title"],
                "sku": it["sku"], "variant_id": it["variant_id"], "level": level, "field": field}
        changes.append(dict(base, old_value=old, new_value=new, tactic=tactic, note=note))
        if field in ("price", "compare_at_price"):
            rollback.append(dict(base, action="set", restore_value=old))
        elif field == "tag":
            rollback.append(dict(base, action="remove_tag", restore_value=new))
        elif field == "collection":
            rollback.append(dict(base, action="remove_from_collection", restore_value=new))

    def fmt(x):
        return "" if x is None else clean(float(x))

    def tag(it, t, tactic, note=""):
        existing = [s.strip().lower() for s in (it["tags"] or "").split(",")]
        if t.lower() in existing or (it["handle"], "tag", t) in done_product:
            return
        done_product.add((it["handle"], "tag", t))
        add(it, "product", "tag", "", t, tactic, note)

    def collection(it, name, tactic):
        if (it["handle"], "collection", name) in done_product:
            return
        done_product.add((it["handle"], "collection", name))
        add(it, "product", "collection", "", name, tactic)

    for it in items:
        rec = it["recommended"]
        if not rec:
            continue
        o = {x["tactic"]: x for x in it["options"]}
        if rec in ("markdown", "markdown_clearance"):
            md = o["markdown"]
            add(it, "variant", "price", fmt(it["price"]), fmt(md["new_price"]), rec,
                "%d%% off" % round(md["discount_pct"]) + (" (held at margin floor)" if md["floor_applied"] else ""))
            ca = it["compare_at"]
            if ca is None or ca < it["price"] - EPS:
                add(it, "variant", "compare_at_price", fmt(ca), fmt(it["price"]), rec, "shows the old price struck out")
            if rec == "markdown_clearance":
                tag(it, st["clearance_tag"], rec)
                collection(it, st["clearance_collection"], rec)
        elif rec == "bundle":
            b = o["bundle"]
            tag(it, st["bundle_tag"], rec, "bundle with %s at %s (create the bundle or discount after approval)"
                % (b["partner_sku"], fmt(b["bundle_price"])))
        elif rec == "gift":
            tag(it, st["gift_tag"], rec, "free gift on orders above %s (create the discount after approval)"
                % fmt(gift_threshold))
        elif rec == "clearance_collection":
            tag(it, st["clearance_tag"], rec)
            collection(it, st["clearance_collection"], rec)

    def chosen(it):
        if not it["recommended"]:
            return None
        t = "markdown" if it["recommended"] == "markdown_clearance" else it["recommended"]
        return next(x for x in it["options"] if x["tactic"] == t)

    def stuck(sel):
        # Only items with units on the shelf can have cash stuck; a missing cost there is unknown.
        return cash_total(i["cash_stuck"] for i in sel if (i["stock"] or 0) > 0)

    cats = {}
    for it in items:
        cats.setdefault(it["category"], []).append(it)
    cat_out = {}
    for k, sel in cats.items():
        t, n, nc = stuck(sel)
        cat_out[k] = {"count": len(sel), "units": clean(float(sum(i["stock"] or 0 for i in sel))),
                      "cash_stuck": clean(t), "items_in_stock": n, "items_with_cost": nc,
                      "oversold_units": clean(float(sum(i["oversold_units"] for i in sel)))}
    rec_items = [i for i in items if i["recommended"]]
    s_slow, s_dead, s_all = stuck(cats.get("slow", [])), stuck(cats.get("dead", [])), stuck(items)
    summary = {
        "categories": cat_out,
        "cash_stuck_slow": clean(s_slow[0]),
        "cash_stuck_dead": clean(s_dead[0]),
        "cash_stuck_total": clean(s_all[0]),
        "cash_stuck_items": {"slow": s_slow[1], "slow_with_cost": s_slow[2], "dead": s_dead[1],
                             "dead_with_cost": s_dead[2], "all": s_all[1], "all_with_cost": s_all[2]},
        "plan_cash_recovered": clean(sum(chosen(i)["cash_recovered"] for i in rec_items)),
        "plan_expected_cash_recovered": clean(sum(chosen(i)["expected_cash_recovered"] for i in rec_items)),
        "plan_profit_if_all_sell": clean(sum(chosen(i)["profit_if_all_sell"] or 0 for i in rec_items)),
        "plan_expected_profit": clean(sum(chosen(i)["expected_profit"] or 0 for i in rec_items)),
        "assumed_sell_through_pct": {t: st["assumed_sell_through_%s_pct" % t] for t in TACTICS},
        "oversold": sorted(({"sku": i["sku"] or i["key"], "title": i["title"], "units_owed": clean(i["oversold_units"])}
                            for i in items if i["oversold_units"] > 0), key=lambda x: (-x["units_owed"], x["sku"])),
        "plan_by_tactic": {},
        "aov": clean(aov) if aov is not None else None,
        "gift_threshold": clean(gift_threshold) if gift_threshold is not None else None,
        "items_missing_cost": sorted(i["sku"] or i["key"] for i in items if i["unit_cost"] is None
                                     and i["category"] in ("slow", "dead")),
    }
    for i in rec_items:
        t = summary["plan_by_tactic"].setdefault(i["recommended"], {"items": 0, "cash_recovered": 0.0,
                                                                    "expected_cash_recovered": 0.0})
        t["items"] += 1
        t["cash_recovered"] = clean(t["cash_recovered"] + chosen(i)["cash_recovered"])
        t["expected_cash_recovered"] = clean(t["expected_cash_recovered"] + chosen(i)["expected_cash_recovered"])

    def out_item(i):
        o = {k: clean(v) for k, v in i.items() if k != "options"}
        o["options"] = [{k: clean(v) for k, v in x.items()} for x in i["options"]]
        return o

    order = {"dead": 0, "slow": 1, "too_early": 2, "unknown": 3, "new": 4, "healthy": 5, "no_stock": 6}
    items.sort(key=lambda i: (order.get(i["category"], 9), -(i["cash_stuck"] or 0), i["key"]))
    result = {
        "skill": "dead-stock-clearance",
        "as_of": as_of.isoformat(),
        "currency": st["currency"],
        "settings": {k: st[k] for k in ("slow_days", "dead_days", "slow_cover_days", "slow_sell_through_pct",
                                        "sell_through_window_days", "cover_window_days", "margin_floor_pct",
                                        "allow_below_cost", "markdown_steps_pct", "price_rounding",
                                        "allowed_tactics", "liquidation_recovery_pct",
                                        "bundle_discount_pct", "gift_threshold_multiplier", "min_evidence_days")
                     + tuple("assumed_sell_through_%s_pct" % t for t in TACTICS)},
        "history": {"first_order": earliest.isoformat(), "days_of_history": history_days},
        "summary": summary,
        "items": [out_item(i) for i in items],
        "changes": changes,
        "rollback": rollback,
        "data_notes": [],
    }
    if not first_stocked:
        result["data_notes"].append("No first-stocked dates: age is unknown, so a product that never sold is "
                                    "judged on the length of the order history instead.")
    dups = sorted(i["sku"] for i in items if i["duplicate_handles"])
    if dups:
        result["data_notes"].append("These SKUs are used by more than one product, so sales cannot be split and "
                                    "no store change is proposed for them: " + ", ".join(dups) + ".")
    if n_refunded:
        result["data_notes"].append(f"{n_refunded} fully refunded or voided orders are not counted as sales "
                                    f"(same as cancelled orders).")
    if n_partial:
        result["data_notes"].append(f"{n_partial} partially refunded orders are counted in full: the export has "
                                    f"no refunded quantity per line.")
    n_early = len(cats.get("too_early", []))
    if n_early:
        result["data_notes"].append(f"{n_early} items are 'too early to judge': only {history_days} days of order "
                                    f"history, less than the {st['min_evidence_days']} days needed before calling "
                                    f"an item slow. Export a longer period (at least {st['min_evidence_days']} days).")
    if summary["oversold"]:
        result["data_notes"].append("%d variants show negative stock (oversold, %g units owed to customers). They count "
                                    "as 0 units here; check their open orders." % (
                                        len(summary["oversold"]), sum(x["units_owed"] for x in summary["oversold"])))
    ci = summary["cash_stuck_items"]
    if ci["all"] and not ci["all_with_cost"]:
        result["data_notes"].append("No unit costs found, so cash stuck is unknown (shown as null, not 0) and no "
                                    "markdown can be checked against a margin floor. Add 'Cost per item' in Shopify "
                                    "(Products > open a product > variant > Cost per item) or give a cost sheet.")
    elif ci["all_with_cost"] < ci["all"]:
        result["data_notes"].append(f"Cash stuck covers {ci['all_with_cost']} of {ci['all']} items in stock: the "
                                    f"others have no unit cost.")
    result["data_notes"].append("Expected cash recovered assumes these shares of units sell (estimates, change them "
                                "in the setup or the dashboard): " + ", ".join(
                                    "%s %g%%" % (t.replace("_", " "), st["assumed_sell_through_%s_pct" % t])
                                    for t in TACTICS) + ". 'If every unit sells' is the ceiling.")
    if history_days < st["dead_days"]:
        result["data_notes"].append(f"Order history is only {history_days} days, shorter than the dead stock "
                                    f"threshold ({st['dead_days']} days). Export a longer period for a firm answer.")
    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
        cls_cols = ["sku", "title", "variant_title", "type", "category", "reason", "stock", "oversold_units",
                    "unit_cost", "price",
                    "cash_stuck", "last_sale", "days_since_last_sale", "recent_daily_sales", "days_of_cover",
                    "sell_through_pct", "age_days", "recommended"]
        write_csv(os.path.join(a.out_dir, "dead-stock-classification.csv"), result["items"], cls_cols)
        write_csv(os.path.join(a.out_dir, "dead-stock-rollback.csv"), rollback, ROLLBACK_COLS)
        write_csv(os.path.join(a.out_dir, "dead-stock-changes.csv"), changes, CHANGE_COLS)
        result["files"] = {k: os.path.join(a.out_dir, f) for k, f in (
            ("classification", "dead-stock-classification.csv"), ("changes", "dead-stock-changes.csv"),
            ("rollback", "dead-stock-rollback.csv"))}
    return result


def main():
    try:
        res = run(sys.argv[1:])
    except (DataError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(2)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
