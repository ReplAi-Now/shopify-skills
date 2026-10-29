# Dead stock method (do it by hand when code cannot run)

This is exactly what `scripts/dead_stock.py` does. Work one variant (SKU) at a time. Today = the "as of" date (last order date unless the merchant says otherwise). Thresholds come from setup (defaults in brackets).

## 1. Numbers per variant

From orders that are not cancelled and not fully refunded (`Financial Status` `refunded` or `voided` counts as no sale, exactly like a cancelled order; a `partially_refunded` order is kept, minus the refunded quantity per line when the data has it, otherwise in full with a note):
- **Last sale date** and **days since last sale** = today minus last sale date.
- **Recent daily sales** = units sold in the last `cover_window_days` [30] / 30 (if the order history is shorter than 30 days, divide by the days of history instead).
- **Days of cover** = stock / recent daily sales (how many days the stock lasts at today's pace). No recent sales = unlimited cover.
- **Sell-through %** over `sell_through_window_days` [90] = units sold in the window / (units sold in the window + stock now) x 100.
- **Age** = today minus first stocked date, if known.
- **Stock**: a negative number (oversold, units sold but not in stock) counts as 0 and is listed as oversold.
- **Cash stuck** = stock x unit cost. A missing unit cost makes it unknown, never 0: totals add only the items with a cost and say "for N of M items with a cost"; with no costs at all the total is unknown.

## 2. Category (first rule that matches wins)

1. Stock 0 or less: no stock (skip).
2. Age known and under `min_age_days` [30]: new (too early to judge).
3. Never sold: dead if age (or, when age is unknown, the order history length) is at least `dead_days` [120]; otherwise unknown.
4. Days since last sale >= `dead_days` [120]: **dead**.
5. Days since last sale >= `slow_days` [60]: **slow**.
6. Days of cover >= `slow_cover_days` [180], or no sale in the last 30 days: **slow**, but only when the order history covers at least `min_evidence_days` [60] days. With less history the item is **too early to judge** (2 or 3 sales over a few weeks prove nothing about half a year of cover): say so and ask for a longer export.
7. Sell-through < `slow_sell_through_pct` [10%] (only when the order history covers the 90 day window, and the item is at least 90 days old or age is unknown): **slow**.
8. Otherwise **healthy**.

A dead item is **extreme** when days since last sale (or never-sold span) is at least 2 x `dead_days` [240].

## 3. Price floor and rounding

- Floor price = unit cost x (1 + `margin_floor_pct` / 100) [10%], rounded UP to `price_rounding` [5]. If the merchant allowed below-cost clearance (`allow_below_cost`), the floor is 0.
- A markdown price = current price x (1 - step), rounded DOWN to `price_rounding`; if it falls under the floor, use the floor. If the floor is at or above the current price, no markdown is possible.
- No unit cost: no markdown (the floor cannot be checked). Say what is missing.

Example: price 199, cost 80, step 10%, rounding 5: 179.10 rounds down to 175; floor 88 rounds up to 90; 175 stands.
Example: price 100, cost 85, step 20%: 80, floor 93.5 rounds up to 95, so 95 (5% off, held at the floor).

## 4. Markdown step

Steps from `markdown_steps_pct` [10, 20, 30]: slow items get the first step, dead items the second, extreme dead items the last.

## 5. Co-purchase (for bundles)

- For every order, list the distinct SKUs in it; each pair of SKUs in the same order counts 1 co-order.
- Fast movers = healthy items with stock that sold in the last 30 days.
- Partner for a slow or dead item = the fast mover with the most co-orders with it, if at least `min_co_orders` [2]. Ties: higher recent daily sales.
- No such partner: the fastest healthy item of the same product type (marked "same category", weaker evidence, offered but not recommended).
- Price of the slow item in the bundle = price x (1 - `bundle_discount_pct` [15%]), rounded down, never below the floor. Bundle price = that + partner price.

## 6. Tactics and their numbers

For every tactic show: new price, expected cash recovered (with the assumed sell-through below, an estimate), cash recovered if every unit sells (the ceiling), profit, margin per unit before and after, revenue given up versus full price.

Assumed sell-through per tactic (estimates from setup, the merchant can change them): markdown `assumed_sell_through_markdown_pct` [60%], bundle [40%], free gift given away [50%], clearance collection with the price unchanged [25%], liquidation [100%, the buyer takes the lot]. Expected cash = cash if all sell x that share; expected profit = profit per unit x expected units sold. Compare tactics on expected cash, never on "if all sell" alone: a clearance collection at full price always wins on "if all sell" but moves far fewer units.

| Tactic | New price per unit | Cash recovered | Profit if all sell |
|---|---|---|---|
| Markdown | markdown price | units x new price | units x (new price - cost) |
| Bundle | price in bundle | units x price in bundle | units x (bundle item price - cost) |
| Free gift above threshold | 0 | 0 | -units x cost (the cost is already paid; this is the accounting loss) |
| Clearance collection only | unchanged | units x price | units x (price - cost) |
| Liquidate | cost x `liquidation_recovery_pct` [30%] (estimate) | units x that | units x (that - cost) |
| Donate | 0 | 0 | -units x cost |

Free gift threshold = average order value over the last 90 days x `gift_threshold_multiplier` [1.3], rounded up. An item qualifies as a gift only if its cost is at most `gift_max_cost_pct_of_aov` [15%] of the average order value.

## 7. Recommended tactic (only tactics allowed in setup)

- **Slow**: bundle if a co-purchase partner exists; else markdown; else free gift; else clearance collection.
- **Dead**: markdown plus clearance collection; if no markdown is possible, free gift; else liquidate.
- **Extreme dead**: markdown at the deepest step plus clearance collection, but only if the floor did not cut the discount; otherwise liquidate (or donate).

## 8. Change list

| Tactic | Rows |
|---|---|
| Markdown | `price` old to new; `compare_at_price` set to the old price when it is empty or lower than the old price (keeps an existing higher compare-at) |
| Markdown + clearance | as markdown, plus `tag` = clearance tag, plus `collection` = clearance collection |
| Bundle | `tag` = bundle tag, note naming the partner and bundle price (the discount is made separately after approval) |
| Free gift | `tag` = gift tag, note with the threshold (discount made separately after approval) |
| Clearance collection | `tag` + `collection` |
| Liquidate / donate | no store change; listed in the report as an offline action |

A SKU used by more than one product gets no change rows (the row could hit the wrong product); list it and ask the merchant to give each variant its own SKU.

Tags and collections are product level (one row per product even if several variants qualify). Skip a tag the product already has.

The rollback file holds, for every change row, how to undo it: `set` the old price or compare-at (empty means clear it), `remove_tag`, `remove_from_collection`.

## 9. Summary

- Cash stuck in slow and in dead stock (separately), and the total.
- Count and units per category.
- For the recommended plan: expected cash recovered and expected profit (stating the sell-through assumptions), plus the "if all sell" ceiling, totals and per tactic.
- Oversold items (negative stock) and items too early to judge, with counts.
- Data notes: order history length, unknown ages, missing costs.

## Checks before showing results

- No markdown below the floor unless below-cost clearance was allowed.
- Every number marked "if all units sell" is an estimate, and liquidation recovery is labelled as an assumption.
- Healthy bestsellers never appear in the change list.
