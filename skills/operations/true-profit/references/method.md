# Method: true profit

Everything `scripts/profit.py` does, step by step, so an agent without code execution can do it by hand or in a spreadsheet. Use the same definitions so results match.

## 1. Orders and outcomes

Group export rows by `Name`. Classify each order (same rules as cod-rto-analysis):

1. A tag in `failed_tags`: **failed (RTO)**.
2. Cancelled (`Cancelled at` or `Canceled at`) and never fulfilled: **cancelled before shipping**, ignored.
3. Cancelled after fulfillment: **failed** (if `count_cancelled_after_fulfillment_as_failed`).
4. Fulfilled with financial status in `failed_financial_statuses` (voided): **failed**.
5. Fulfilled and paid (or refunded / partially refunded): **delivered**.
6. Fulfilled but still pending (with the courier, or never updated): **open**, left out of profit, the count is given as a warning (same as cod-rto-analysis).
7. Not fulfilled: **not shipped**, ignored.
8. A matched courier status overrides: failed words make it failed, delivered words make it delivered. A cancel status on an order never fulfilled stays **cancelled before shipping** (no shipping cost).

## 2. Splitting order amounts across lines

Line value g = `Lineitem price` x `Lineitem quantity`; order gross G = sum of g. Share = g / G (if G is 0, quantity / total quantity). Every order-level amount (discount, shipping charged, taxes, refunds, shipping cost, fees, packaging, RTO cost) is split by this share.

## 3. Delivered order, per line

- Net revenue = g - discount x share + shipping charged x share - refund x share (- taxes x share if prices include tax).
- Returned units (units sent back after delivery: `Lineitem returned quantity` column or `--returns` file): returned value = price x returned units x (1 - discount / G); the part not covered by the order refund (max(0, returned value - refunded)) comes off net revenue, split over the returned lines by value. Units sold = quantity - returned units.
- Product cost (COGS) = unit cost x quantity x (1 - max(refund fraction, returned units / quantity)), where refund fraction = min(1, refunded / (G - discount)) when `refund_restock` is true, else 0. (Refunded and returned goods are assumed back in stock.)
- Unit cost: by SKU first; else by product title (average of that title's cost rows). None: **cost missing**; the product shows no profit and is left out of totals. A product is cost missing whatever happened to its orders (also when all of them failed). When no product has a cost, profit is unknown: no contribution total, no money-losing bestsellers, ask for costs.
- Shipping cost = courier shipping fee, else `shipping_cost_per_order`; x share.
- Payment fee: COD orders: courier COD fee, else (`Total` - gift card amount) x `cod_fee_pct` / 100 + `cod_fee_fixed` (the gift card amount is only known in connector-built files with a `Gift Card Amount` column; otherwise the full total is used and a warning says so). Other orders: `Total` x `gateway_fee_pct` / 100 + `gateway_fee_fixed`. x share.
- Packaging = `packaging_cost_per_order` x share.

Example: Hoodie 600 + 2 caps at 200 = 1,000 gross, discount 100, shipping charged 50. Shares 0.6 and 0.4. Hoodie net = 600 - 60 + 30 = 570.

## 4. Failed (RTO) order

No revenue and no product cost (goods come back). RTO cost = outbound shipping (courier or `shipping_cost_per_order`) + return shipping (courier `return_fee` or `return_shipping_per_order`) + COD fee (courier `cod_fee` or `cod_fee_fixed`, COD orders only) + packaging, split across its lines by share. Its gross value is kept as "RTO gross" for the platform break-even ROAS.

Example: shipping 70 + return 55 + COD fee 0 + packaging 10 = 135.

## 5. Products

Product = the line name before the last ` - ` (Shopify writes "Product - Variant"), or a cost-sheet title the line starts with; with `group_by: variant`, the full line name. Sum per product: units sold (delivered), units RTO, gross sales, discounts, refunds, shipping charged, net revenue, COGS, shipping cost, payment fees, packaging, RTO cost.

## 6. Ad spend allocation

1. Convert spend to the store currency: spend x rate (`fx_rates`, store currency per 1 unit). If a currency has no rate, stop and ask the merchant for it; state the rate in the output.
2. With an ad map (`ad_allocation: mapping`): each ad row takes the most specific matching rule (ad, then ad set, then campaign; longer text first). Its spend goes to that product, or is split among the listed products by their net revenue.
3. Everything unmatched or `SHARED` (and everything, with `revenue_share`) is split across all products by net revenue share: product ads += spend x product net revenue / total net revenue.

Example: 170 shared, net revenue 1,220 / 440 / 40 of 1,700: 122 / 44 / 4.

## 7. Product results

- Contribution before ads (CBA) = net revenue - COGS - shipping cost - payment fees - packaging - RTO cost.
- Contribution = CBA - ads.
- Margin = contribution / net revenue.
- Break-even ROAS = net revenue / CBA (only when CBA > 0; otherwise the product never breaks even with ads).
- Platform break-even ROAS = (gross sales + RTO gross) / CBA. Ads Manager counts purchases before delivery and before discounts and refunds, so its ROAS must beat this number.
- Actual ROAS = net revenue / ads.

Example: net 1,220, CBA 319.8, ads 322: contribution -2.2, break-even ROAS 3.81, actual 3.79. Profitable before ads, so it is an ad problem.

## 8. Bestsellers that lose money

Top `bestseller_top_n` products by units sold (ties by net revenue). Those with contribution < 0 are listed with:
- price increase per unit to break even = -contribution / units sold;
- ad cut to break even = -contribution (when ads are at least that much);
- problem = `ads` if CBA > 0, else `price_or_cost`.

## 9. Orders

Order ads = sum over its lines of line net revenue x (product ads / product net revenue). Delivered order contribution = net revenue - COGS - (shipping + fee + packaging) - ads (none if any line has a missing cost). Failed order contribution = - RTO cost. Report averages per delivered order, cost per failed order, the count of delivered orders losing money and the 10 worst orders.

## 10. Channels

- Sales channel = Shopify `Source`. Sum delivered, failed, net revenue and known contribution. Channel contribution is n/a when any delivered order in it has a missing cost; the known part is n/a when none has a cost.
- Ad platform: spend (store currency), platform purchases, cost per platform purchase = spend / purchases, delivered purchases estimate = purchases x store delivery rate (delivered / (delivered + failed)), true cost per delivered order estimate = spend / delivered purchases estimate, break-even cost per order = (sum of contribution before ads of delivered orders with full costs - RTO cost of failed orders) / number of delivered orders with full costs. Platform ROAS = purchase value / spend when the file has a value column.

## 11. Totals

Sum the product columns. Contribution and margin use products with a known cost; revenue of products with missing cost is shown separately. Fixed costs for the period = `fixed_monthly_costs` x days / 30 (days from first to last order date, inclusive). Net profit = known contribution - fixed costs. Open orders are not in any total; give their count.

## 12. Not counted

Return shipping on refunds after delivery (unless the courier file lists it as a fee on that order), damaged returned goods, cash tied up in COD remittance cycles, and taxes on profit.
