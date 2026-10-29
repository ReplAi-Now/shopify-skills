# Data sources for weekly-kpi-digest

Use the first source that works, in this order. Every KPI except sessions and conversion rate works from exports alone.

## 1. Shopify connector (MCP)

Read-only queries only. Paginate (`first: 250`, follow `pageInfo.endCursor`). Pull orders created from 180 days before the report week start (new vs returning needs that history; the minimum for the comparisons and stock velocity is the start of the "4 weeks ago" week minus 21 days) up to the end of the report week. The script decides new vs returning only from the orders in the file, so `customer.numberOfOrders` is not a substitute for history.

```graphql
query Orders($cursor: String, $q: String!) {
  orders(first: 250, after: $cursor, query: $q, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name createdAt cancelledAt cancelReason displayFinancialStatus displayFulfillmentStatus tags test note
      email phone
      paymentGatewayNames
      subtotalPriceSet { shopMoney { amount currencyCode } }
      totalDiscountsSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      customer { id numberOfOrders createdAt }
      refunds { refundLineItems(first: 50) { nodes { quantity restockType } } }
      lineItems(first: 100) {
        nodes { name sku quantity
          originalUnitPriceSet { shopMoney { amount } }
          totalDiscountSet { shopMoney { amount } } }
      }
    }
  }
}
```
with `$q = "created_at:>=2026-08-29 created_at:<=2026-10-24"` (dates in the store timezone).

Write the result into a CSV with the export column names below (one row per line item, order fields on every row is fine) and run the script on it. Map `displayFulfillmentStatus` to `Fulfillment Status`, `cancelReason` to `Cancel Reason`, and add a column `Returned Units`: per order, the sum of `refundLineItems.quantity` where `restockType` is `RETURN` (items that came back and were restocked). Leave out `CANCEL` lines (an order cancelled before shipping is not a return) and `NO_RESTOCK` lines. When this column is present the digest shows a "Returned units (restocked)" KPI.

**Returns without a refund.** Many COD stores (Try & Buy at the door, exchanges, store credit) take items back and restock them without refunding money, so `Refunded Amount` stays 0 and the orders export cannot see the return at all. Only the connector (the `restockType: RETURN` quantities above) shows these. If refunds are 0 in every week and no `Returned Units` column was given, the digest adds a note saying so. Field names can change between API versions: if a field errors, look it up with the connector's schema tool. Never guess IDs or fields.

Stock: `productVariants(first: 250) { nodes { sku inventoryQuantity title product { title } } }` gives SKU and available quantity across locations.

### Sessions and conversion rate (ShopifyQL, may be unavailable)

Only through Shopify analytics. Run a ShopifyQL query with the connector's analytics query tool, or through Admin GraphQL `shopifyqlQuery(query: "...")` if the connector exposes it. It needs the `read_reports` scope and a plan that includes analytics. Example for one week (dates are inclusive, store timezone):

```
FROM sessions
  SHOW sessions, conversion_rate
  SINCE 2026-10-17 UNTIL 2026-10-23
```

Run it three times (this week, last week, the week 4 weeks ago). Cross-check net sales if you like:

```
FROM sales
  SHOW net_sales, orders
  SINCE 2026-10-17 UNTIL 2026-10-23
```

Dataset and column names differ between ShopifyQL versions. If a query errors, read the error (it usually lists valid columns), adjust once, and if it still fails, mark sessions and conversion rate as unavailable. Write the numbers you got into `analytics.json`:

```json
{"this": {"sessions": 4210, "conversion_rate": 1.6},
 "last": {"sessions": 3980, "conversion_rate": 1.4},
 "four_weeks_ago": {"sessions": 3500, "conversion_rate": 1.5}}
```

`conversion_rate` is a percentage (1.6 means 1.6%). If Shopify returns a fraction (0.016), multiply by 100. Leave a week out if you could not get it. Never fill this file with estimates: no analytics means no sessions or conversion rate in the digest, with a note saying why.

## 2. Exports (always works)

### Orders (required)

`Shopify admin > Orders > (filter Date: last 90 days or more) > Export > Current page / All orders matching your search > CSV for Excel`.

Longer history makes "new vs returning" more accurate: a customer whose first order is older than the export is counted as new. 6-12 months is good.

One row per line item. Order-level fields are filled on the first row of each order and blank on the others; the script reads them from the first row that has them. Columns used (headers are matched case-insensitively, spaces and dashes become `_`):

| Export column | Used for |
|---|---|
| `Name` | order id (required) |
| `Created at` | week assignment, converted to the setup timezone (required) |
| `Email`, `Phone` (or `Billing Phone`, `Shipping Phone`) | customer identity for new vs returning (email first, else last 9 digits of the phone) |
| `Financial Status` | `voided` counts as cancelled; `paid` after fulfilment = delivered (COD delivery success) |
| `Fulfillment Status` | splits cancelled orders into cancelled before shipping and failed deliveries (cancelled after fulfilment) |
| `Cancelled at` or `Canceled at` | cancelled orders (newer exports spell it `Canceled at`, both are read) |
| `Cancel Reason` (connector only) | with `failed_cancel_reasons`, which cancellations after fulfilment count as failed deliveries |
| `Returned Units` (connector only) | returned and restocked units, also when no money was refunded |
| `Subtotal` | net sales, AOV (products after discounts, before shipping and tax) |
| `Discount Amount` | discount share |
| `Refunded Amount` | refunds, net sales |
| `Payment Method` (or `Payment Gateway`) | COD detection using `cod_keywords`; `bogus` (Shopify's test gateway) marks a test order |
| `Tags` | delivery outcome using `delivered_tags` / `failed_tags` (whole tag, case-insensitive); a tag `test` (or `test order`) marks a test order |
| `Notes` | the word "test" in the order note marks a test order |
| `Test` (connector only) | `true` marks a test order (write the connector's `test` field to this column) |
| `Lineitem quantity`, `Lineitem name`, `Lineitem price`, `Lineitem sku`, `Lineitem discount` | units, products, gross sales, stock velocity |
| `Currency` | currency if setup has none |

### Inventory (optional, for stock warnings)

Either:
- `Shopify admin > Products > Inventory > Export` (columns `Handle`, `Title`, `Option 1 Value`, `Option 2 Value`, `SKU`, `Available (not editable)` or `On hand (current)`, one row per variant per location; locations are summed), or
- `Shopify admin > Products > Export > All products > CSV for Excel` (columns `Handle`, `Title`, `Option1 Value`, `Option2 Value`, `Variant SKU`, `Variant Inventory Qty`).

Variants without a SKU cannot be matched to sales and are skipped (say so if many are missing).

### Courier export (optional, for COD delivery success)

Any courier (Bosta, Aramex, J&T, SMSA, Mylerz, R2S, others). The script looks for an order reference column (`Order`, `Order Number`, `Order Name`, `Order ID`, `Business Reference`, `Reference`) and a status column (`Status`, `Delivery Status`, `State`). A status containing any of `failed_courier_statuses` counts as failed, else any of `delivered_courier_statuses` counts as delivered, else it is still in transit ("Out for delivery" is in transit). If the courier's columns are named differently, rename them or tell the merchant the mapping in one line.

Without a courier file, delivery outcomes come from the orders file with the same rules and setup keys as the cod-rto-analysis skill, so both skills give the same numbers: a `failed_tags` tag = failed; cancelled before fulfilment = cancelled before shipping (not a delivery attempt); cancelled after fulfilment = failed (a refused COD parcel is usually recorded this way, with Financial Status `voided`); fulfilled and `voided` = failed; a `delivered_tags` tag = delivered; fulfilled and paid = delivered; fulfilled and pending = still in transit. Only when none of these give a result is COD delivery success shown as n/a with a note.

## Scheduled runs and exports

A scheduled run cannot download exports by itself. With exports only, the merchant drops fresh files into `exports_folder` (default `replai-exports/`) before the run time. The run takes the newest file whose name contains `orders_export` (and `inventory` / `products_export` for stock). If the newest orders file does not cover the report week, the run writes a short note saying the export is stale and stops, instead of reporting old numbers.
