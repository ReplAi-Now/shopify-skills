#!/usr/bin/env python3
"""Demand planner: daily demand, safety stock, reorder point, order quantity and cash per variant.

Usage:
  python3 demand_plan.py --orders orders.csv --inventory inventory.csv [--products products.csv]
      [--suppliers suppliers.csv] [--stock-history stock.csv]
      [--setup replai-setup/demand-planner.json] [--as-of 2026-10-28]
      [--event "White Friday,2026-11-20,2026-11-30,40"] [--estimate SKU=1.5]
      [--calendar ../assets/seasonal-calendar.json] [--csv-out demand-plan.csv]

Inputs (CSV or XLSX, Shopify exports or any sheet with the same meaning):
  --orders         Shopify admin > Orders > Export (one row per line item)
  --inventory      Shopify admin > Products > Inventory > Export (Available, On hand, Incoming)
  --products       Shopify admin > Products > Export (Cost per item, Type, Vendor, Variant Inventory Qty)
                   At least one of --inventory / --products is required.
  --suppliers      optional: sku or vendor, lead_time_days, lead_time_sd_days, moq, case_pack, unit_cost
  --stock-history  optional: date, sku, stock (end of day). Makes demand stockout aware.
  --event          optional, repeatable: "name,start,end,uplift_pct" for an upcoming event.
  --estimate       optional, repeatable: SKU=units_per_day for new products, or one estimate for a
                   whole group from "estimate_groups": TYPE:<product type>=units_per_day or
                   PRODUCT:<handle>=units_per_day (applied to each variant in the group that has no sales).

Draft and archived products (Status column of the products export) are left out unless the setup
has "include_drafts": true. Negative stock (oversold) is planned as 0 and the units owed to customers
are added to the order (listed under "oversold"). A missing unit cost is unknown, never 0: cash totals
are null when no item in them has a cost, and partial when some do (see the *_items_with_cost counts).

Prints one JSON object (see references/method.md for every formula). Never touches the network.
"""
import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tabular import read_rows, num, write_csv  # noqa: E402
from store_data import (DataError, col, counts_as_sale, has_col, load_orders, load_variants,  # noqa: E402
                        parse_date, slash_dayfirst)

DEFAULTS = {
    "currency": "EGP",
    "default_lead_time_days": 14,
    "lead_time_sd_days": 0,
    "review_period_days": 7,
    "service_level_pct": 95,
    "default_moq": 0,
    "default_case_pack": 1,
    "history_days": 90,
    "half_life_days": 30,
    "min_history_days": 28,
    "seasonality": "auto",
    "baseline_days": 28,
    "include_drafts": False,
}
INACTIVE_STATUSES = ("draft", "archived")
ESTIMATE_GROUPS_SHOWN = 10
URGENCY_ORDER = ["order_now", "this_week", "later", "no_demand", "needs_estimate"]
TRADEOFF_LEVELS = [85, 90, 95, 98, 99]
EPS = 1e-9
MOQ_WARN_DAYS = 180


def z_for(service_level_pct):
    """Service level (percent, 50 to 99.9) to z score (standard normal inverse)."""
    pct = num(service_level_pct)
    if not 50 - EPS <= pct <= 99.9 + EPS:
        raise DataError("service_level_pct must be between 50 and 99.9")
    return statistics.NormalDist().inv_cdf(min(max(pct, 50.0), 99.9) / 100.0)


def weighted_demand(points, half_life):
    """points: list of (age_days, units). Weight = 0.5 ** (age / half_life).
    Returns (weighted mean, weighted standard deviation)."""
    if not points:
        return None, None
    ws = [(0.5 ** (a / float(half_life)), x) for a, x in points]
    sw = sum(w for w, _ in ws)
    mean = sum(w * x for w, x in ws) / sw
    var = sum(w * (x - mean) ** 2 for w, x in ws) / sw
    return mean, math.sqrt(var)


def safety_stock(z, lead_time, sigma_d, d, sigma_lt):
    return z * math.sqrt(lead_time * sigma_d ** 2 + d ** 2 * sigma_lt ** 2)


def round_order(qty, moq, case_pack):
    """Round up to a whole unit, then to at least the MOQ, then up to a full case."""
    if qty <= EPS:
        return 0
    q = max(math.ceil(qty - EPS), moq or 0)
    cp = max(int(case_pack or 1), 1)
    return int(math.ceil(q / float(cp)) * cp)


def overlap_days(start, end, h_start, h_end):
    s, e = max(start, h_start), min(end, h_end)
    return max((e - s).days + 1, 0)


IN_PROGRESS_NOTE = ("in progress today: recent sales already include this uplift, so it is not "
                    "applied again to the days of this event inside the horizon")


def baseline_days_before(start, n, windows, max_lookback=180):
    """The n days before `start`, walking back and skipping every day inside any calendar event
    window (so Eid is measured against normal weeks, not the Ramadan weeks just before it).
    Returns a list of dates (newest first); shorter than n if max_lookback runs out."""
    days, day = [], start - dt.timedelta(days=1)
    while len(days) < n and (start - day).days <= max_lookback:
        if not any(ws <= day <= we for ws, we in windows):
            days.append(day)
        day -= dt.timedelta(days=1)
    return days


def compute_events(daily_totals, earliest, as_of, horizon_days, calendar, manual, baseline_days, mode):
    """Upcoming events inside [as_of+1, as_of+horizon_days] with an uplift factor each.

    Factor from last year = (avg daily units in last year's window) / (avg daily units on the
    baseline_days non-event days before it). Needs order history back to that baseline. Merchant
    events win. An event that is in progress on as_of is listed with in_progress=True and is not
    applied (recent demand already contains it)."""
    h_start, h_end = as_of + dt.timedelta(days=1), as_of + dt.timedelta(days=horizon_days)
    out, needs = [], []
    for m in manual:
        if overlap_days(m["start"], m["end"], h_start, h_end):
            ev = dict(m, source="merchant")
            if m["start"] <= as_of <= m["end"]:
                ev.update(in_progress=True, note=IN_PROGRESS_NOTE)
            out.append(ev)
    if mode == "off":
        return out, needs
    evs = calendar.get("events", [])
    windows = [(parse_date(x["start"]), parse_date(x["end"])) for x in evs]
    for ev in evs:
        s, e = parse_date(ev["start"]), parse_date(ev["end"])
        if not overlap_days(s, e, h_start, h_end):
            continue
        if any(o["source"] == "merchant" and overlap_days(o["start"], o["end"], s, e) for o in out):
            continue
        base = {"name": ev["label"], "event": ev["event"], "start": s, "end": e}
        if s <= as_of <= e:
            out.append(dict(base, source="in_progress", in_progress=True, note=IN_PROGRESS_NOTE))
            continue
        prev = next((p for p in evs if p["event"] == ev["event"] and p["year"] == ev["year"] - 1), None)
        if prev is None:
            needs.append(dict(base, reason="no row for last year in the calendar table"))
            continue
        ps, pe = parse_date(prev["start"]), parse_date(prev["end"])
        bdays = baseline_days_before(ps, baseline_days, windows)
        if len(bdays) < baseline_days:
            needs.append(dict(base, reason="not enough normal (non-event) days before last year's window"))
            continue
        bs = bdays[-1]
        if earliest is None or earliest > bs:
            needs.append(dict(base, reason=f"order history starts after {bs.isoformat()}, so last year's "
                                           f"{ev['label']} cannot be measured"))
            continue
        win_units = sum(daily_totals.get(ps + dt.timedelta(days=i), 0) for i in range((pe - ps).days + 1))
        base_units = sum(daily_totals.get(d, 0) for d in bdays)
        if base_units <= 0:
            needs.append(dict(base, reason="no sales in the baseline weeks before last year's window"))
            continue
        factor = (win_units / float((pe - ps).days + 1)) / (base_units / float(baseline_days))
        out.append(dict(base, factor=factor, source="last_year",
                        detail={"last_year_start": ps.isoformat(), "last_year_end": pe.isoformat(),
                                "baseline_start": bs.isoformat(), "baseline_end": bdays[0].isoformat(),
                                "window_units": win_units, "baseline_units": base_units}))
    return out, needs


def horizon_demand(d, lead_time, review, as_of, events):
    """Average daily demand over the next lead_time + review days, including event uplifts."""
    H = lead_time + review
    if H <= 0 or not d:
        return d or 0.0, 0.0
    hd = int(math.ceil(H - EPS))
    h_start, h_end = as_of + dt.timedelta(days=1), as_of + dt.timedelta(days=hd)
    extra = sum((ev["factor"] - 1.0) * overlap_days(ev["start"], ev["end"], h_start, h_end)
                for ev in events if not ev.get("in_progress"))
    return d * (H + extra) / H, extra


def plan_item(d, sigma, lt, lt_sd, review, z, position, available, as_of, events, moq, case_pack):
    d_eff, extra = horizon_demand(d, lt, review, as_of, events)
    s_eff = sigma * d_eff / d if d else 0.0
    ss = safety_stock(z, lt, s_eff, d_eff, lt_sd)
    rop = d_eff * lt + ss
    S = rop + d_eff * review
    raw = S - min(position, rop)
    qty = round_order(raw, moq, case_pack)
    r = {"horizon_daily_demand": d_eff, "event_extra_days": extra, "safety_stock": ss,
         "reorder_point": rop, "order_up_to": S, "order_qty_raw": raw, "order_qty": qty}
    if d_eff <= EPS:
        r.update(urgency="no_demand", days_until_reorder=None, reorder_date=None,
                 days_to_stockout=None, stockout_date=None, order_qty=0)
        return r
    until = (position - rop) / d_eff
    if position <= rop + EPS:
        urg = "order_now"
    elif until <= 7 + EPS:
        urg = "this_week"
    else:
        urg = "later"
    r["urgency"] = urg
    r["days_until_reorder"] = max(until, 0.0)
    r["reorder_date"] = (as_of + dt.timedelta(days=int(math.floor(max(until, 0) + EPS)))).isoformat()
    dts = max(available, 0) / d_eff
    r["days_to_stockout"] = dts
    r["stockout_date"] = (as_of + dt.timedelta(days=int(math.floor(dts + EPS)))).isoformat()
    return r


def load_setup(path):
    s = dict(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as fh:
            s.update(json.load(fh))
    for k, v in DEFAULTS.items():  # "95%" or "14 days" typed into the setup still work
        if isinstance(v, bool):
            if isinstance(s.get(k), str):
                s[k] = s[k].strip().lower() in ("true", "yes", "1")
        elif isinstance(v, (int, float)) and isinstance(s.get(k), str):
            s[k] = num(s[k], v)
    return s


def estimate_key(text):
    """Normalise an --estimate key: SKUs upper case, NAME:/TYPE:/PRODUCT: keys lower case after the prefix."""
    k = text.strip()
    for prefix in ("NAME:", "TYPE:", "PRODUCT:"):
        if k.upper().startswith(prefix):
            return prefix + k[len(prefix):].strip().lower()
    return k.upper()


def cash_total(values):
    """(total, n_items, n_with_cost) for the cash values of a set of items. None marks a missing cost.
    The total is None when no item has a cost (unknown, never 0), and 0 only for an empty set."""
    vals = list(values)
    known = [x for x in vals if x is not None]
    total = round(sum(known), 2) if known or not vals else None
    return total, len(vals), len(known)


def load_suppliers(path):
    by_sku, by_vendor = {}, {}
    if not path:
        return by_sku, by_vendor
    rows = read_rows(path)
    if not has_col(rows, "sku", "vendor", "supplier"):
        raise DataError("suppliers file needs a 'sku' or 'vendor' column")
    for r in rows:
        rec = {}
        for k, names in (("lead_time_days", ("lead_time_days", "lead_time")),
                         ("lead_time_sd_days", ("lead_time_sd_days", "lead_time_sd", "lead_time_variability")),
                         ("moq", ("moq", "minimum_order")), ("case_pack", ("case_pack", "pack_size")),
                         ("unit_cost", ("unit_cost", "cost", "cost_per_item"))):
            v = col(r, *names)
            if v != "":
                rec[k] = num(v)
        sku = col(r, "sku", "variant_sku")
        vendor = col(r, "vendor", "supplier")
        if sku:
            by_sku[sku.strip().upper()] = rec
        elif vendor:
            by_vendor[vendor.strip().lower()] = rec
    return by_sku, by_vendor


def load_stock_history(path):
    hist = {}
    if not path:
        return hist
    rows = read_rows(path)
    for need in ("date", "sku"):
        if not has_col(rows, need):
            raise DataError(f"stock history file is missing the column '{need}'")
    if not has_col(rows, "stock", "available", "on_hand", "quantity"):
        raise DataError("stock history file is missing the column 'stock'")
    dayfirst = slash_dayfirst(col(r, "date") for r in rows)
    for r in rows:
        d = parse_date(col(r, "date"), dayfirst)
        sku = col(r, "sku").strip().upper()
        v = col(r, "stock", "available", "on_hand", "quantity")
        if d and sku and v != "":
            hist.setdefault(sku, {})[d] = num(v)
    return hist


def parse_event(text):
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise DataError(f"--event needs 'name,start,end,uplift_pct', got '{text}'")
    s, e = parse_date(parts[1]), parse_date(parts[2])
    if not s or not e or e < s:
        raise DataError(f"--event has bad dates: '{text}'")
    return {"name": parts[0], "event": parts[0].lower().replace(" ", "_"), "start": s, "end": e,
            "factor": 1 + num(parts[3]) / 100.0}


def run(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--inventory")
    ap.add_argument("--products")
    ap.add_argument("--suppliers")
    ap.add_argument("--stock-history")
    ap.add_argument("--setup")
    ap.add_argument("--as-of")
    ap.add_argument("--event", action="append", default=[])
    ap.add_argument("--estimate", action="append", default=[])
    ap.add_argument("--calendar", default=os.path.join(HERE, "..", "assets", "seasonal-calendar.json"))
    ap.add_argument("--csv-out")
    a = ap.parse_args(argv)
    if not (a.inventory or a.products):
        raise DataError("give --inventory (Products > Inventory > Export) or --products (Products > Export) "
                        "so current stock is known")
    st = load_setup(a.setup)
    z = z_for(st["service_level_pct"])
    R = max(float(st["review_period_days"]), 1.0)
    all_orders = load_orders(a.orders)
    orders = [o for o in all_orders if counts_as_sale(o)]
    n_refunded = sum(1 for o in all_orders if o["refunded"] and not o["cancelled"])
    n_partial = sum(1 for o in orders if o["partial_refund_unknown"])
    variants = load_variants(a.products, a.inventory)
    inactive = {k for k, v in variants.items() if (v["status"] or "").strip().lower() in INACTIVE_STATUSES}
    if not st["include_drafts"]:
        variants = {k: v for k, v in variants.items() if k not in inactive}
    sup_sku, sup_vendor = load_suppliers(a.suppliers)
    hist = load_stock_history(a.stock_history)
    manual = [parse_event(e) for e in a.event]
    estimates = {}
    for e in a.estimate:
        k, _, v = e.rpartition("=")
        # SKU keys are upper case; keys of variants without a SKU are "NAME:<lower case name>".
        estimates[estimate_key(k)] = num(v)
    calendar = {}
    if st.get("seasonality", "auto") != "off" and os.path.exists(a.calendar):
        with open(a.calendar, encoding="utf-8") as fh:
            calendar = json.load(fh)

    as_of = parse_date(a.as_of) if a.as_of else max((o["date"] for o in orders), default=None)
    if as_of is None:
        raise DataError("no dated, non-cancelled orders found")
    orders = [o for o in orders if o["date"] <= as_of]
    earliest = min((o["date"] for o in orders), default=as_of)
    notes = []
    min_h = int(st["min_history_days"])
    days_hist = (as_of - earliest).days + 1
    short_history = days_hist < min_h
    if short_history:
        notes.append(f"LOW CONFIDENCE: only {days_hist} days of order history (less than {min_h}). Demand is "
                     f"estimated from this short history; export at least 90 days for a reliable plan.")
    if n_refunded:
        notes.append(f"{n_refunded} fully refunded or voided orders are left out of demand, like cancelled ones.")
    if n_partial:
        notes.append(f"{n_partial} partially refunded orders are counted in full: the export has no refunded "
                     f"quantity per line, so demand for those items may be slightly overstated.")
    if inactive and not st["include_drafts"]:
        notes.append(f"{len(inactive)} variants of draft or archived products are left out of the plan "
                     f"(set include_drafts to true in the setup to plan them too).")
    nominal_start = as_of - dt.timedelta(days=int(st["history_days"]) - 1)
    win_start = max(nominal_start, earliest)
    if earliest > nominal_start:
        notes.append(f"Orders start on {earliest.isoformat()}, so demand uses {(as_of - earliest).days + 1} days "
                     f"instead of {st['history_days']}.")

    daily = {}
    totals = {}
    first_sale = {}
    for o in orders:
        for ln in o["lines"]:
            k = ln["key"]
            daily.setdefault(k, {})
            daily[k][o["date"]] = daily[k].get(o["date"], 0) + ln["qty"]
            totals[o["date"]] = totals.get(o["date"], 0) + ln["qty"]
            if k not in first_sale or o["date"] < first_sale[k]:
                first_sale[k] = o["date"]
    unmatched = sorted(k for k in daily if k not in variants and k not in inactive
                       and any(d >= win_start for d in daily[k]))

    stockout_aware = bool(hist)
    if not stockout_aware:
        notes.append("No stock history given: days when an item was out of stock count as zero demand, "
                     "so demand for items that sold out is understated.")

    dups = sorted(v["sku"] for v in variants.values() if v["duplicate_handles"])
    if dups:
        notes.append("These SKUs are used by more than one product, so their sales and stock are combined: "
                     + ", ".join(dups) + ". Give each variant its own SKU for a per-product plan.")

    items = []
    for k, v in variants.items():
        sp = dict(sup_vendor.get((v["vendor"] or "").strip().lower(), {}))
        sp.update(sup_sku.get(k, {}))
        lt = sp.get("lead_time_days", float(st["default_lead_time_days"]))
        lt_sd = sp.get("lead_time_sd_days", float(st["lead_time_sd_days"]))
        cost = sp.get("unit_cost", v["cost"])
        raw_avail = v["available"] if v["available"] is not None else 0.0
        owed = max(-raw_avail, 0.0)
        it = {"key": k, "sku": v["sku"] or "", "handle": v["handle"], "title": v["title"], "variant_title": v["variant_title"],
              "type": v["type"], "vendor": v["vendor"], "price": v["price"], "unit_cost": cost,
              "lead_time_days": lt, "lead_time_sd_days": lt_sd, "review_period_days": R,
              "moq": int(sp.get("moq", st["default_moq"]) or 0),
              "case_pack": int(sp.get("case_pack", st["default_case_pack"]) or 1),
              "available": max(raw_avail, 0.0), "oversold_units": owed,
              "on_hand": v["on_hand"] if v["on_hand"] is not None else max(raw_avail, 0.0),
              "incoming": v["incoming"] or 0.0, "flags": [], "stockout_days_excluded": 0, "days_used": 0}
        if owed:
            it["flags"].append("oversold: stock is %g, so %g units are owed to customers; planned from 0 stock "
                               "and the owed units are added to the order" % (raw_avail, owed))
        if v["available"] is None:
            it["flags"].append("stock unknown (not in the inventory file)")
        if v["duplicate_handles"]:
            it["flags"].append("SKU also used by: %s (sales, stock and cost of these products are combined; "
                               "give each variant its own SKU)" % ", ".join(v["duplicate_handles"]))
        fs = first_sale.get(k)
        if fs is None:
            it["status"] = "no_sales"
        elif (as_of - fs).days + 1 < min_h and (fs - earliest).days >= min_h:
            # New only when the export reaches far enough back to prove there were no earlier sales.
            age = (as_of - fs).days + 1
            units = sum(q for day, q in daily.get(k, {}).items() if day >= fs)
            it.update(status="new", days_used=age, own_daily_demand=units / float(age))
        else:
            it["status"] = "ok"
            if short_history:
                it["flags"].append(f"low confidence: only {days_hist} days of order history")
            pts, excl = [], 0
            sh = hist.get(k, {}) if v["sku"] else {}
            day = win_start
            while day <= as_of:
                units = daily.get(k, {}).get(day, 0)
                if day in sh and sh[day] <= 0 and units == 0:
                    excl += 1
                else:
                    pts.append(((as_of - day).days, units))
                day += dt.timedelta(days=1)
            d, sig = weighted_demand(pts, st["half_life_days"])
            it.update(daily_demand=d, daily_demand_sd=sig, demand_source="history",
                      days_used=len(pts), stockout_days_excluded=excl)
            if d is None:
                it["status"] = "needs_estimate"
                it["flags"].append("out of stock on every day of the window")
        items.append(it)

    cat = {}
    for it in items:
        if it["status"] == "ok" and it.get("daily_demand"):
            cat.setdefault(it["type"] or "", []).append(it["daily_demand"])
    for it in items:
        if it["status"] in ("new", "no_sales", "needs_estimate"):
            est = estimates.get(it["key"]) if it["key"] in estimates else estimates.get((it["sku"] or "").upper())
            group = None
            if est is None and it["status"] != "new":
                for gk in ("PRODUCT:" + (it["handle"] or "").strip().lower(),
                           "TYPE:" + (it["type"] or "").strip().lower()):
                    if gk in estimates and not gk.endswith(":"):
                        est, group = estimates[gk], gk
                        break
            if est is not None:
                it.update(daily_demand=est, daily_demand_sd=est, demand_source="merchant_estimate")
                it["flags"].append("demand is the merchant's estimate" +
                                   (" for the whole group %s" % group if group else ""))
            elif it["status"] == "new":
                own = it["own_daily_demand"]
                group = cat.get(it["type"] or "")
                avg = sum(group) / len(group) if group else None
                d = own if avg is None else min(own, avg)
                capped = avg is not None and own > avg + EPS
                it.update(daily_demand=d, daily_demand_sd=d,
                          demand_source="new_own_sales_capped" if capped else "new_own_sales")
                it["flags"].append(
                    "new product, estimate: first sale %d days ago, uses its own sales since then (%.2f/day)%s"
                    % (it["days_used"], own, (", capped at the '%s' average of %.2f/day"
                                               % (it["type"] or "uncategorised", avg)) if capped else ""))
            else:
                it.update(daily_demand=None, daily_demand_sd=None, demand_source="none")
                it["flags"].append("no sales history: give an estimate (--estimate SKU=units_per_day)"
                                   if it["status"] == "no_sales" else "no usable sales history: give an estimate")

    max_h = max([int(math.ceil(it["lead_time_days"] + R)) for it in items] or [0])
    events, needs = compute_events(totals, earliest, as_of, max_h, calendar, manual,
                                   int(st["baseline_days"]), st.get("seasonality", "auto"))

    for it in items:
        # Units owed to customers (oversold) are taken out of the position, so they are ordered now.
        it["position"] = it["available"] + it["incoming"] - it["oversold_units"]
        it["capital_tied"] = max(it["on_hand"], 0) * it["unit_cost"] if it["unit_cost"] is not None else None
        if it["daily_demand"] is None:
            it.update(urgency="needs_estimate", order_qty=0, cash_needed=None, at_risk=False, risk_reason="")
            continue
        r = plan_item(it["daily_demand"], it["daily_demand_sd"], it["lead_time_days"], it["lead_time_sd_days"],
                      R, z, it["position"], it["available"], as_of, events, it["moq"], it["case_pack"])
        it.update(r)
        if it["urgency"] == "no_demand" and it["position"] < -EPS:
            # No forecast demand, but customers are still owed units: order those now.
            it.update(urgency="order_now", order_qty=round_order(-it["position"], it["moq"], it["case_pack"]))
        it["cash_needed"] = it["order_qty"] * it["unit_cost"] if it["unit_cost"] is not None else None
        hd = it.get("horizon_daily_demand") or 0.0
        if it["order_qty"] > 0 and hd > EPS and it["order_qty"] > math.ceil(it["order_qty_raw"] - EPS):
            cover = it["order_qty"] / hd
            if cover > MOQ_WARN_DAYS:
                it["moq_cover_days"] = cover
                it["flags"].append("MOQ or case pack forces %d units, about %d days of demand (more than %d): "
                                   "ask the supplier for a smaller minimum, or skip this item"
                                   % (it["order_qty"], round(cover), MOQ_WARN_DAYS))
        risk = ""
        if it["available"] <= 0 and it["urgency"] != "no_demand":
            risk = "out of stock now"
        elif it.get("days_to_stockout") is not None and it["days_to_stockout"] < it["lead_time_days"] - EPS:
            risk = "runs out before an order placed today can arrive"
        it["at_risk"] = bool(risk)
        it["risk_reason"] = risk
        if risk and it.get("days_to_stockout") is not None and it["price"]:
            gap = max(it["lead_time_days"] - it["days_to_stockout"], 0)
            it["lost_sales_estimate"] = gap * it["horizon_daily_demand"] * it["price"]

    items.sort(key=lambda i: (URGENCY_ORDER.index(i["urgency"]),
                              i.get("days_until_reorder") if i.get("days_until_reorder") is not None else 1e9,
                              i["key"]))

    cash = {}
    for bucket in ("order_now", "this_week", "later"):
        t, n, nc = cash_total(i["cash_needed"] for i in items if i["urgency"] == bucket and i["order_qty"] > 0)
        cash.update({bucket: t, bucket + "_items": n, bucket + "_items_with_cost": nc})
    t, n, nc = cash_total(i["capital_tied"] for i in items if i["on_hand"] > 0)
    cash.update(capital_tied_now=t, capital_tied_items=n, capital_tied_items_with_cost=nc)
    missing = sorted(i["sku"] or i["key"] for i in items if i["unit_cost"] is None)
    cash["items_missing_cost"] = missing
    cash["items_missing_cost_count"] = len(missing)
    if missing and len(missing) == len(items):
        notes.append("No unit costs found, so every cash figure is unknown (shown as null, not 0). Add "
                     "'Cost per item' in Shopify (Products > open a product > variant > Cost per item) and export "
                     "again, or give a sheet with sku and unit_cost (--suppliers).")
    elif missing:
        notes.append(f"{len(missing)} of {len(items)} items have no unit cost: cash totals cover only the items "
                     f"with a cost (see the *_items_with_cost counts). Add their costs for full totals.")
    tradeoff = []
    planned = [i for i in items if i["daily_demand"] is not None and i.get("horizon_daily_demand") is not None]
    for lvl in sorted(set(TRADEOFF_LEVELS + [float(st["service_level_pct"])])):
        zz = z_for(lvl)
        units = val = 0.0
        n_cost = 0
        for i in planned:
            de = i["horizon_daily_demand"]
            se = i["daily_demand_sd"] * de / i["daily_demand"] if i["daily_demand"] else 0.0
            ss = safety_stock(zz, i["lead_time_days"], se, de, i["lead_time_sd_days"])
            units += ss
            if i["unit_cost"] is not None:
                val += ss * i["unit_cost"]
                n_cost += 1
        tradeoff.append({"service_level_pct": lvl, "z": round(zz, 4), "safety_stock_units": round(units, 2),
                         "safety_stock_value": round(val, 2) if n_cost or not planned else None,
                         "items": len(planned), "items_with_cost": n_cost})

    def rnd(i):
        o = {}
        for k2, v2 in i.items():
            if isinstance(v2, float):
                o[k2] = round(v2, 3 if k2 in ("daily_demand", "daily_demand_sd", "horizon_daily_demand") else 2)
            else:
                o[k2] = v2
        return o

    items_out = [rnd(i) for i in items]
    oversold = [{"sku": i["sku"] or i["key"], "title": i["title"], "variant_title": i["variant_title"],
                 "units_owed": i["oversold_units"], "incoming": i["incoming"], "urgency": i["urgency"],
                 "order_qty": i["order_qty"]} for i in items_out if i["oversold_units"] > 0]
    oversold.sort(key=lambda x: (-x["units_owed"], x["sku"]))
    if oversold:
        notes.append("%d variants show negative stock (oversold, %g units owed to customers in total). They are "
                     "planned from 0 stock and the owed units are added to their order. Check the open orders: an "
                     "old negative count may only be out of date." % (len(oversold), sum(x["units_owed"] for x in oversold)))
    # Group the items without any demand so the merchant is asked once per product type (or product),
    # not once per SKU. Biggest groups first; the agent asks about the top ESTIMATE_GROUPS_SHOWN only.
    groups = {}
    for i in items_out:
        if i["urgency"] != "needs_estimate":
            continue
        if i["type"]:
            gk, label, basis = "TYPE:" + i["type"].strip(), i["type"].strip(), "type"
        else:
            gk, label, basis = "PRODUCT:" + (i["handle"] or i["title"] or i["key"]), i["title"] or i["key"], "product"
        g = groups.setdefault(gk.lower(), {"group": label, "basis": basis, "estimate_key": gk, "variants": 0,
                                           "products": set(), "example_skus": []})
        g["variants"] += 1
        g["products"].add(i["handle"] or i["title"])
        if len(g["example_skus"]) < 3:
            g["example_skus"].append(i["sku"] or i["key"])
    estimate_groups = sorted(groups.values(), key=lambda g: (-g["variants"], g["group"].lower()))
    for g in estimate_groups:
        g["products"] = len(g["products"])
    for ev in events + needs:
        ev["start"], ev["end"] = ev["start"].isoformat(), ev["end"].isoformat()
        if "factor" in ev:
            ev["factor"] = round(ev["factor"], 3)
    result = {
        "skill": "demand-planner",
        "as_of": as_of.isoformat(),
        "currency": st["currency"],
        "settings": {"service_level_pct": st["service_level_pct"], "z": round(z, 4),
                     "review_period_days": R, "default_lead_time_days": st["default_lead_time_days"],
                     "lead_time_sd_days": st["lead_time_sd_days"], "history_days": st["history_days"],
                     "half_life_days": st["half_life_days"], "min_history_days": st["min_history_days"],
                     "include_drafts": st["include_drafts"]},
        "history": {"first_order": earliest.isoformat(), "window_start": win_start.isoformat(),
                    "days_of_history": days_hist},
        "stockout_aware": stockout_aware,
        "seasonality": {"events": events, "needs_merchant_uplift": needs},
        "data_notes": notes,
        "items": items_out,
        "reorder_list": [{"sku": i["sku"] or i["key"], "title": i["title"], "variant_title": i["variant_title"],
                          "urgency": i["urgency"], "order_qty": i["order_qty"], "cash_needed": i["cash_needed"],
                          "stockout_date": i.get("stockout_date")}
                         for i in items_out if i["urgency"] in ("order_now", "this_week") and i["order_qty"] > 0],
        "at_risk": [{"sku": i["sku"] or i["key"], "title": i["title"], "reason": i["risk_reason"],
                     "stockout_date": i.get("stockout_date"),
                     "lost_sales_estimate": i.get("lost_sales_estimate")} for i in items_out if i["at_risk"]],
        "needs_estimate": [i["sku"] or i["key"] for i in items_out if i["urgency"] == "needs_estimate"],
        "needs_estimate_count": sum(1 for i in items_out if i["urgency"] == "needs_estimate"),
        "estimate_groups": estimate_groups,
        "estimate_groups_to_ask": estimate_groups[:ESTIMATE_GROUPS_SHOWN],
        "oversold": oversold,
        "excluded_inactive_variants": 0 if st["include_drafts"] else len(inactive),
        "new_products": [i["sku"] or i["key"] for i in items_out if i["status"] == "new"
                         and i["demand_source"] != "merchant_estimate"],
        "moq_warnings": [{"sku": i["sku"] or i["key"], "order_qty": i["order_qty"],
                          "days_of_demand": round(i["moq_cover_days"])} for i in items_out if i.get("moq_cover_days")],
        "low_confidence": short_history,
        "cash": cash,
        "service_level_tradeoff": tradeoff,
        "unmatched_order_skus": unmatched,
    }
    if a.csv_out:
        cols = ["sku", "title", "variant_title", "urgency", "order_qty", "cash_needed", "unit_cost",
                "available", "oversold_units", "incoming", "daily_demand", "daily_demand_sd", "horizon_daily_demand",
                "lead_time_days", "safety_stock", "reorder_point", "order_up_to", "reorder_date",
                "stockout_date", "at_risk", "risk_reason", "capital_tied", "demand_source", "status"]
        write_csv(a.csv_out, items_out, cols)
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
