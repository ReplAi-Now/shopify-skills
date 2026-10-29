# Method: COD failed-delivery (RTO) analysis

Everything the script does, step by step, so an agent without code execution can do it by hand (a spreadsheet or careful counting). Use the same definitions so results match.

## 1. One row per order

The export has one row per line item. Group rows by `Name`. Order-level fields (statuses, total, address, tags, dates) come from the first row that has them. Keep the list of line item names for the product view.

## 2. COD or not

An order is COD when `Payment Method` contains any `cod_payment_keywords` (default: "cash on delivery", "cod" as a whole word, "الدفع عند الاستلام"). With `cod_only: true` (default) every view except the payment method view uses COD orders only.

## 3. Outcome of each order

Check in this order; the first rule that applies wins.

1. Any tag equals one of `failed_tags` (case ignored): **failed**.
2. `Cancelled at` is set and the order was never fulfilled: **cancelled before shipping** (not a delivery, left out of rates).
3. `Cancelled at` is set and the order was fulfilled (or partial): **failed** when `count_cancelled_after_fulfillment_as_failed` is true. If a cancel reason column exists and the reason is not in `failed_cancel_reasons`, it is **cancelled, other** (left out).
4. Fulfilled and `Financial Status` in `failed_financial_statuses` (default voided): **failed**.
5. Fulfilled and financial status paid, partially paid, refunded or partially refunded: **delivered**. (A refund after delivery is a return, not an RTO.)
6. Fulfilled and still pending: **open** (in transit, or the store never marked it paid). Left out of rates and reported.
7. Not fulfilled, not cancelled: **not shipped**, left out.

Then, if a courier row matches the order: a status containing a failed word makes it **failed**; a status containing a delivered word makes it **delivered**. The courier saw the parcel, so its status wins. Exception: a cancel status (`cancel`, `ملغي`) on an order Shopify never fulfilled is **cancelled before shipping** (cancelled before pickup, no shipping cost). Other statuses leave the Shopify outcome. Several courier rows for one order: the latest by date, else the most final status.

**Resolved orders** = delivered + failed. Only resolved orders enter the rates.

## 4. Rates

- Failure (RTO) rate = failed / resolved.
- Delivery success rate = delivered / resolved = 1 - failure rate.

Example: 6 delivered and 4 failed: failure rate 4 / 10 = 40%, success 60%.

## 5. Money lost per failed order

Money lost = outbound shipping + return shipping + COD fee + packaging.

- Outbound, return and COD fee come from the matched courier row when the cell is filled; otherwise from setup (`default_outbound_shipping`, `default_return_shipping`, `default_cod_fee_failed`). Missing setup costs count as 0 and the result says money lost is understated. With no cost anywhere (setup and courier file both empty), money lost is unknown (null), never 0.
- Packaging always comes from setup (`packaging_cost`).
- Delivered orders lose nothing in this view.

Example: courier says shipping 55, return 45, COD fee 5; packaging 10: 115 lost. Without a courier row and setup 50 / 40 / 0 / 10: 100 lost.

Money lost per month = money lost x 30 / days in the period (first to last order date, both included).

## 6. Region (governorate / emirate)

Normalise with `assets/regions.json`:
1. Country from `Shipping Country` (EG, SA, AE, KW, QA, BH, OM, or the name).
2. Try `Shipping Province Name`, then the province code (`Shipping Province`, only codes of that country), then `Shipping City`.
3. Matching ignores case, hyphens, spaces, Arabic letter forms (أ إ آ = ا, ة = ه, ى = ي), the article (al, el, ال) and filler words (governorate, province, emirate, region, city, محافظة).
4. A name may be a governorate, a spelling variant or a city inside it: "6th of October", "Sheikh Zayed", "Dokki", "الجيزة", "gizeh" are all Giza; "Nasr City", "New Cairo", "التجمع الخامس", "Maadi" are Cairo; "Mansoura" is Dakahlia.
5. No match: **Unknown (country)**. Never dropped; listed with counts so a spelling can be added.

Qatar is one region. The GCC countries use emirates (UAE), regions (KSA) and governorates (Kuwait, Bahrain, Oman).

## 7. Segments

For resolved orders, count resolved, delivered, failed and money lost per value of each dimension:

| Dimension | Value |
|---|---|
| region | normalised governorate / emirate |
| city | `Shipping City` as typed, title case |
| courier | courier name from the courier file (`--courier file::Name`), else the first order tag containing a setup `courier_tags` key ("Sent to ShipBlu" -> ShipBlu), else setup `default_courier`, else Unknown |
| product | each distinct product in the order: line item name before the last ` - ` (variants grouped), or the product title from `--products`; full line name with `product_group: "variant"` (an order with 2 products counts once for each) |
| value_band | `Total` against `value_bands`: with 500/1000/2000: under 500, 500-999, 1000-1999, 2000+ |
| customer_history | sort all orders by date; customer = email, else last 9 phone digits. First order in data / repeat, failed before / repeat, no earlier failure / unknown customer |
| day_of_week | weekday of `Created at` |
| payment_method | `Payment Method` text, over all orders (not only COD) |

## 8. Small samples and confidence

- A segment with fewer than `min_orders` resolved orders is shown but **not ranked** ("too few orders").
- Confidence: medium below 3 x `min_orders`, high at or above.
- 95% range (Wilson interval), with n resolved, f failed, p = f / n, z = 1.96:
  - centre = (p + z² / 2n) / (1 + z² / n)
  - half width = z x sqrt(p(1 - p) / n + z² / 4n²) / (1 + z² / n)
  - range = centre - half width to centre + half width.
  - Example: 3 failed of 5: 23% to 88%. That is why 5 orders are not enough to blame an area.

**Worst** list per dimension: ranked segments whose failure rate is above the overall rate, highest first (ties by money lost), top 5.

## 9. Actions and estimated savings

Gap = `rate_gap_for_action` (default 0.10 = 10 points). Only ranked segments qualify.

| Action | When | Estimated saving |
|---|---|---|
| Deposit or prepayment in a region | region rate >= overall + gap (not Unknown) | region money lost x `prepay_failure_reduction` (default 0.5) |
| Confirm orders in a value band | band rate >= overall + gap | band money lost x `confirmation_failure_reduction` (default 0.3) |
| Confirm first-time customers | "first order in data" rate >= overall + gap | money lost x confirmation reduction |
| Prepayment for customers who failed before | "repeat, failed before" rate >= overall + gap | money lost x prepay reduction |
| Check product listing and confirm its orders | product rate >= overall + gap | money lost x confirmation reduction |
| Switch courier in a region | two couriers each with >= `min_orders` in the region, rates differ by >= gap | (failed with worse courier - its resolved x better courier's rate) x worse courier's average loss per failed order |

Saving per month = saving x 30 / days in period. All savings are **estimates**: say the assumption, and say they overlap (prepaying an area also removes some of its high-value failures), so they are not added up.

Example switch: courier X had 2 failures out of 3 in Cairo, courier Y 0 out of 3, each failure cost 100. Avoided = 2 - 3 x 0 = 2, saving 200 in the period.

## 10. Reasons

From the courier `reason` column on failed orders, lowercased and counted, top 15.

## 11. What is not counted

Lost profit on the sale, ad spend that brought the failed order, staff time and cash tied up in remittance cycles are not in money lost. Say so if the merchant asks for the "full" cost; the true-profit skill covers margin.
