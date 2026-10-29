# Method: how every number in the digest is computed

Use this when you cannot run `scripts/kpi_digest.py` (chat apps without code execution). Follow it exactly so a hand-made digest matches the script.

## 1. Weeks

1. Take today's date in the store timezone (setup `timezone`).
2. Find the start of the current week: go back to the most recent `week_start` day (Saturday, Sunday or Monday), counting today if it is that day.
3. The report week ("this week") is the 7 days before that: start = current week start minus 7 days, end = start + 6 days.
4. "Last week" = report week minus 7 days. "4 weeks ago" = report week minus 28 days (same weekday alignment, so Ramadan-free weeks compare like with like).
5. Convert every order's `Created at` to the store timezone before deciding its week. Example: `2026-10-16 22:30:00 +0000` is 01:30 on 17 October in Riyadh (+03:00), so with Saturday weeks it belongs to the week starting Saturday 17 October.

If the data starts after a comparison week begins, leave that whole comparison blank. Do not compare against a partial week.

If the data starts ON a week's first day but its first order comes more than 2 hours later than the store's usual first order of the day (median of each other day's first order time), that week is probably cut by the export: mark its comparisons "(partial)", add a note, and do not use them for "act on this". Example: the export starts 19 Sep at 16:32 and orders usually start around 00:30, so the week starting 19 Sep is missing about 16 hours.

## 2. Orders

Group export rows by `Name` (one order can have several line-item rows). An order is **cancelled** if `Cancelled at` (or `Canceled at`) is filled or `Financial Status` is `voided`. Cancelled orders are left out of every KPI except "Cancelled before shipping", "Failed deliveries" and COD delivery success (section 4), which split them:
- cancelled and `Fulfillment Status` not fulfilled: **cancelled before shipping**;
- cancelled and fulfilled: **failed delivery** (the parcel went out and came back; on COD stores a refused parcel is usually recorded this way). If setup has `count_cancelled_after_fulfillment_as_failed: false`, or the order's cancel reason is not in `failed_cancel_reasons`, it counts as cancelled before shipping instead.

**Test orders** are removed before anything else and left out of every KPI, including "Cancelled orders", new vs returning and stock velocity: payment gateway `bogus` (Shopify's test gateway), a tag `test` / `test order`, the word "test" in the order note, or the connector's `test` field. Add a note: "N test orders were left out of every KPI, M of them in the report week."

For each week, using only non-cancelled orders created in that week:

| KPI | Formula |
|---|---|
| Orders | count of orders |
| Net sales | sum of `Subtotal` minus sum of `Refunded Amount` |
| Average order value (AOV) | sum of `Subtotal` / Orders |
| Units sold | sum of `Lineitem quantity` |
| Gross sales (helper) | sum of `Lineitem quantity` x `Lineitem price` |
| Discount share | sum of `Discount Amount` / gross sales x 100 |
| Refunds | sum of `Refunded Amount` |
| Orders with a refund | orders with `Refunded Amount` > 0 / Orders x 100 |
| COD share | orders whose payment method matches a COD keyword / Orders x 100 |
| Cancelled before shipping | count of cancelled orders created in the week that are not failed deliveries |
| Failed deliveries | count of orders created in the week whose outcome (section 4) is failed, any payment method |
| Returned units (restocked) | sum of `Returned Units` (connector only, see data-sources.md); shown only when that column exists |

Refunds are attached to the week the ORDER was placed (the export has no refund date). Shopify's own Sales report books refunds on the refund date, so its numbers can differ slightly. Say so if the merchant compares.

COD keyword match: `cod_keywords` from setup, matched as whole words for Latin text (so "cod" matches "Cash on Delivery (COD)" but not "code") and as plain text for Arabic.

## 3. New vs returning customers

1. Customer key: lowercased email; if no email, the last 9 digits of the phone (so `+20 100 123 4567` and `01001234567` are the same person). Orders with neither are not counted; report how many.
2. First order date = the earliest non-cancelled order date for that key in ALL the data you have (not just the 3 weeks).
3. For a week: take the distinct keys ordering that week. **New** = first order date falls inside the week. **Returning** = first order date is before the week.
4. If the data starts less than 180 days before the report week, add a note that some returning customers may show as new.

## 4. COD delivery success

Same rules and setup keys as the cod-rto-analysis skill, so both skills agree. For each COD order in the week (cancelled ones included), decide an outcome, first rule that applies:
1. A tag in `failed_tags` (whole tag, any case): failed.
2. Cancelled and not fulfilled: cancelled before shipping (left out of this KPI).
3. Cancelled and fulfilled: failed (see section 2 for the cancel-reason exception).
4. A tag in `delivered_tags`: delivered.
5. Fulfilled and `Financial Status` in `failed_financial_statuses` (default `voided`): failed.
6. Fulfilled and paid (`paid`, `partially_paid`, `partially_refunded`, `refunded`): delivered (the cash was collected).
7. Fulfilled otherwise (`pending`): unknown, still in transit. Not fulfilled: unknown, not shipped yet.
8. A courier file status for that order (match order numbers ignoring `#` and spaces) overrides all of the above: failed if it contains a word from `failed_courier_statuses`, else delivered if it contains one from `delivered_courier_statuses`.

COD delivery success = delivered / (delivered + failed) x 100. Unknown orders are left out. COD orders cancelled before shipping are not in the base. If more than 30% of this week's remaining COD orders are unknown, say the figure is still settling and point to last week's number as the more reliable one.

## 5. Comparisons, arrows and flags

For money and counts: change % = (this - previous) / previous x 100, rounded to 1 decimal. If previous is 0, show "new" (no %); if both are 0, show "no change".
For rates (anything shown as %): change = this - previous in percentage points (pp), computed from the rounded values.

Arrow: ↑ if the change is above 0, ↓ if below, → if exactly 0.
Flag (!) when |change %| >= `flag_threshold_pct` (default 15) or |change pp| >= `flag_threshold_pp` (default 3).
Severity = |change| / threshold (so 1.0 means exactly at the threshold).

Each KPI has a direction: higher is better (sales, orders, AOV, units, customers, COD delivery success, sessions, conversion), lower is better (discount share, refunds, orders with a refund, cancelled orders), or neutral (COD share: watch it, it is not good or bad by itself).

Targets (optional, weekly): vs target % = (this - target) / target x 100.

## 6. Products

Product name = `Lineitem name` up to the last " - " (that strips the variant, e.g. "Linen Shirt - M / Black" becomes "Linen Shirt"). With `product_grouping: variant`, keep the full name.
Product revenue = quantity x price minus `Lineitem discount`, non-cancelled orders only.

- **Top 5**: highest revenue this week (ties: more units, then name).
- **Bottom 5**: from products that sold at least once in the last 28 days (the report week and the 3 weeks before) or last week, and are not in the top 5, the lowest revenue this week (0 counts). Ties: the one that sold more last week first (biggest faller), then name.

## 7. Stock warnings

1. Units sold per SKU over the 28 days ending on the report week's last day (non-cancelled orders).
2. Sold per day = units / 28.
3. Days of cover = available stock / sold per day.
4. Warn when days of cover < `inventory_cover_days` (default 14). Sort by days of cover, lowest first. SKUs with no sales in 28 days are not warned here (that is dead stock, a different problem).

## 8. Sessions and conversion rate

Only from Shopify analytics (ShopifyQL, see [data-sources.md](data-sources.md)). If not available, leave them out and add the note "Sessions and conversion rate are not shown: Shopify analytics was not reachable." Never estimate them from orders.

## 9. The 3 "act on this" items

Build a candidate list:
1. For each KPI, take the change vs last week. If that is missing or exactly 0, use the change vs 4 weeks ago at half severity.
2. Rank candidates: (a) flagged changes in the bad direction and target misses of at least the % threshold, and stock warnings where the worst variant has under half the cover limit; (b) flagged neutral changes; (c) other stock warnings; (d) flagged good changes; (e) everything else. Inside a rank, higher severity first. Stock severity = cover limit / max(worst days of cover, 1).
3. Small samples are not ranked. A rate KPI (discount share, orders with a refund, COD share: base = orders; COD delivery success: base = delivered + failed) is skipped when either week of the comparison rests on fewer than `min_rate_base` (default 5) orders, and so is its target miss. One refused order out of 4 is not a trend.
4. COD delivery success is not ranked at all for a report week that is still settling (more than 30% of its COD orders have no final status).
5. One item per KPI. Take the first 3. If there are fewer than 3, fill with a data gap the merchant has not already closed: more history (only if a comparison week is missing), Shopify analytics (only if no analytics was given), courier data (only if there is no courier file and no delivered/failed tags). After that use "No other KPI moved enough to act on this week."

Each item says what changed, by how much, compared with what, and one concrete next step (see the action texts in `kpi_digest.py`). Bad news first. Write the size of the change without a sign next to "rose" or "fell": "fell 34.5%", never "fell -34.5%".
