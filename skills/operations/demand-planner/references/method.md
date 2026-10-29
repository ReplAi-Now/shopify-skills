# Demand planner method (do it by hand when code cannot run)

Everything below is what `scripts/demand_plan.py` computes. Work one variant (SKU) at a time. Keep full precision while calculating and round only what you show (demand to 2 decimals, money to whole units of currency).

Symbols: `d` average daily demand (units/day), `sigma_d` its standard deviation, `LT` supplier lead time in days, `sigma_LT` lead time variability in days, `R` review period (days between ordering checks), `z` the service level score.

## 1. Build the daily sales series

1. Take orders that are not cancelled and not fully refunded. An order whose `Financial Status` is `refunded` or `voided` is left out exactly like a cancelled one (the sale did not stick). A `partially_refunded` order keeps its lines: if the data has a refunded quantity per line (`Lineitem refunded quantity`), count `Lineitem quantity - refunded quantity`; if not (the standard Shopify export has none), count the line in full and say "N partially refunded orders are counted in full, so demand may be slightly overstated."
2. For each SKU add up the quantity per calendar day (store timezone, the date part of `Created at`).
3. Today = the "as of" date (the last order date in the export unless the merchant says otherwise).
4. Window = the last `history_days` days up to today (default 90). If orders start later than that, start the window at the first order and say so.
5. Short history: if the export covers fewer than `min_history_days` (default 28) days in total, still plan every SKU from the days you have, but mark the whole plan LOW CONFIDENCE and ask for a longer export (90 days or more). Do not hold back the plan or mark everything "needs estimate".
6. Days with no sales inside the window are zeros, except stockout days (step 2).

## 2. Stockout days (only with stock history)

A day is a stockout day when the end-of-day stock was 0 or less AND nothing sold that day. Leave stockout days out of the series completely (they are not zero demand, the shelf was empty). A day that sold units and ended at 0 is kept.

Without stock history you cannot tell, so keep the zeros and write in the output: "No stock history: demand for items that sold out is understated."

## 3. Recency weighted demand and its spread

Each day gets a weight `w = 0.5 ^ (age / half_life)`, where `age` = days before today (today is 0) and `half_life` defaults to 30 days (a sale 30 days ago counts half as much as one today).

- `d = sum(w * units) / sum(w)`
- `sigma_d = sqrt( sum(w * (units - d)^2) / sum(w) )`

By hand with 90 days of data, a close shortcut: use weekly totals, weight each week by `0.5 ^ (weeks_ago * 7 / half_life)`, compute the weighted weekly mean and spread, then divide the mean by 7 and the spread by `sqrt(7)`. Say it is an approximation.

Worked example (half life 1 day, 4 days, units 2, 4, 2, 4 from oldest to today): weights 0.125, 0.25, 0.5, 1 (sum 1.875). `d = (0.25 + 1 + 1 + 4) / 1.875 = 3.333`. Squared gaps 1.778, 0.444, 1.778, 0.444, weighted sum 1.667, so `sigma_d = sqrt(1.667 / 1.875) = 0.943`.

## 4. New products and products with no sales

- New: the first sale in the export is fewer than `min_history_days` (default 28) days ago AND the export reaches at least `min_history_days` further back than that first sale (so you can see it really did not sell before). With a short export a year-old slow seller can look new; if the export does not reach back far enough, treat the SKU as established (section 3) and do not call it new.
- Demand for a new SKU: the merchant's estimate if given. Otherwise its own rate since launch, `d = units sold since the first sale / days since the first sale (counting today)`. The average `d` of established SKUs with the same product `Type` is only an upper cap: `d = min(own rate, category average)`. Never raise a new SKU to the category average (one sale 10 days ago is 0.1/day, not the category's 1.4/day). Set `sigma_d = d` (a cautious assumption) and label it "new product, estimate".
- Never sold: do not plan a reorder unless the merchant gives an estimate (it may be dead stock, not a new product).
- Asking for estimates: group the never-sold variants by product `Type` (or by product when the type is blank), biggest groups first, and ask once per group for the top 10 ("one variant of X sells about how many per day?"). The answer applies to every variant in the group with no sales. Never ask per SKU.
- Draft and archived products (`Status` in the products export) are left out of the plan unless the merchant asks to include them.

## 5. Seasonality (Ramadan, Eid, White Friday)

Use the fixed dates in `assets/seasonal-calendar.json`. Never work out Islamic dates yourself.

The horizon is tomorrow through `LT + R` days ahead. For every event window that overlaps the horizon:

- With at least a year of history (orders reaching back to 28 days before last year's same window): `uplift factor = (all units sold per day during last year's window) / (all units sold per day in the 28 days before it)`. Store-level totals, because a single SKU is too noisy.
- Otherwise ask the merchant for an uplift % for that event ("expect +40% during White Friday"). `factor = 1 + pct / 100`. A merchant's number always wins over the measured one.

Measuring last year's factor: the baseline is the 28 normal days before last year's window, skipping every day that falls inside any event window in the calendar. This matters for Eid al Fitr, which starts right after Ramadan: compare Eid with the normal weeks before Ramadan, not with the busy Ramadan weeks (otherwise the factor comes out near 1 and Eid is under-planned).

Event already running today: if today is inside an event window (calendar or merchant), the recency weighted `d` already contains that uplift. Do not apply that event's factor or merchant % again to its days inside the horizon (count them at factor 1), and do not ask the merchant for an uplift for it. Other events later in the horizon still get their factor. Simplification to say out loud: the days after the running event ends are planned at today's level, which can be a little high if today's sales are event-inflated.

Then `extra = sum over events not running today of (factor - 1) * days of the event inside the horizon`, and the demand used for planning is
`d_eff = d * (LT + R + extra) / (LT + R)`, with `sigma_eff = sigma_d * d_eff / d` (same relative spread).
With no events `d_eff = d`.

Example: `d = 2`, `LT = 10`, `R = 4`, horizon 14 days of which 10 fall inside White Friday with factor 2.5: `extra = 1.5 * 10 = 15`, `d_eff = 2 * 29 / 14 = 4.14`.

## 6. Service level to z

`z` is the standard normal inverse of the service level.

| Service level | 80% | 85% | 90% | 95% | 97.5% | 98% | 99% | 99.5% |
|---|---|---|---|---|---|---|---|---|
| z | 0.84 | 1.04 | 1.28 | 1.64 | 1.96 | 2.05 | 2.33 | 2.58 |

## 7. Safety stock, reorder point, order-up-to level

- Safety stock `SS = z * sqrt( LT * sigma_eff^2 + d_eff^2 * sigma_LT^2 )`
- Reorder point `ROP = d_eff * LT + SS`
- Order-up-to level `S = ROP + d_eff * R`
- Inventory position `P = available + incoming` (available already excludes units committed to open orders; negative available is oversold, see section 8)

The first term covers busy and quiet days during the lead time; the second covers late suppliers.

## 8. Urgency and order quantity

- Order now: `P <= ROP`.
- This week: `(P - ROP) / d_eff <= 7` days.
- Later: otherwise. Reorder date = today + `floor((P - ROP) / d_eff)` days.
- No demand: `d_eff = 0`. Needs estimate: no usable demand.
- Oversold (negative available stock, for example -3): use 0 as the stock on the shelf, and count the 3 units owed to customers as demand to fulfil now: `P = 0 + incoming - 3`. An item with no forecast demand but units owed is ordered now for the owed units (minus incoming). List every oversold item and tell the merchant to check its open orders.

Raw quantity `Q = S - min(P, ROP)`. If ordering now this is `S - P`; for later items it is the quantity to order on the reorder date (`d_eff * R`).
Round: up to a whole unit, then up to the MOQ, then up to a full case: `qty = ceil(max(ceil(Q), MOQ) / case_pack) * case_pack` (0 if `Q <= 0`).

Example: `Q = 6.8`, MOQ 10, case 6: 7, then 10, then 12.

MOQ warning: when the MOQ or case pack rounding pushes the quantity above what was needed and the rounded quantity covers more than 180 days of demand (`qty / d_eff > 180`), flag it: "MOQ forces N units, about X days of demand: ask the supplier for a smaller minimum, or skip this item." That cash sits on shelves for half a year or more.

## 9. Stockout date and risk

- Days to stockout = `max(available, 0) / d_eff`. Stockout date = today + `floor(days)`.
- At risk when available is 0 or less ("out of stock now"), or days to stockout < `LT` ("runs out before an order placed today can arrive").
- Lost sales estimate for at-risk items = `(LT - days to stockout) * d_eff * price`. Label it an estimate.

## 10. Cash

- Cash needed = `qty * unit cost` (unit cost from the suppliers sheet, else `Cost per item`). Sum separately for order now, this week, later.
- Cash in stock today (capital tied) = `max(on hand, 0) * unit cost`, summed over all variants.
- A missing unit cost is unknown, never 0. Each total counts the items in it and the items with a cost: when none has a cost the total is unknown (null), when some do it is labelled "for N of M items with a cost". Items without a cost are listed. Ask the merchant for costs (Shopify `Cost per item` or a cost sheet).

## 11. The trade-off in plain words

Recompute total safety stock value (`SS * unit cost`, summed) at 90%, the chosen level, and 99%. Say: "Going from 95% to 99% means about X more cash sitting on shelves as safety stock, to cut the chance of running out before each delivery from 5% to 1%." Higher service level means fewer stockouts and more cash tied; the right level is higher for bestsellers and high-margin items, lower for slow or low-margin ones.

## Checks before showing results

- Every SKU in the reorder list has a cost, or it is flagged.
- No SKU sold in the window is missing from the inventory file without being listed.
- The as of date and the history length are stated.
- Every estimate (new product rate, merchant uplift, lost sales) is labelled as an estimate.
- A short history (under 28 days) is called out as low confidence.
