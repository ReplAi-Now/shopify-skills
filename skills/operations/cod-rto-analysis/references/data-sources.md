# Data sources for cod-rto-analysis

Order of preference: Shopify connector, then Shopify export, then files the merchant uploads. The export path must always work on its own.

## 1. Shopify orders export (always works)

Path: `Shopify admin > Orders > filter the date range > Export > "All orders" or "Current page" > "CSV for Excel"`. Shopify emails the file when it is large. XLSX saved from Excel also works.

The export has one row per line item. Order-level columns are filled on the first row of each order; later rows repeat `Name` and carry the line item columns. The script reads the first non-empty value per order.

Columns relied on (header names as Shopify writes them; matching ignores case and spaces):

| Column | Used for | Required |
|---|---|---|
| `Name` | order number (#1001), join key to courier files | yes |
| `Financial Status` | paid / pending / voided / refunded / partially_refunded | yes |
| `Fulfillment Status` | fulfilled / partial / unfulfilled (was it shipped) | yes |
| `Cancelled at` (2026 exports: `Canceled at`, both read) | cancelled before or after shipping | recommended |
| `Payment Method` | COD detection, e.g. `Cash on Delivery (COD)`; can list several gateways joined with `+` | recommended |
| `Tags` | failed-order tags (comma separated); courier name when there is no courier file (setup `courier_tags`, e.g. "Sent to ShipBlu", "bosta_synced") | recommended |
| `Total` | order value band, COD amount | recommended |
| `Created at` | period, weekday, first vs repeat order | recommended |
| `Email`, `Phone` (or `Shipping Phone`) | first vs repeat customer (never shown in outputs) | optional |
| `Shipping Province Name` | region (governorate / emirate), e.g. `Giza` | recommended |
| `Shipping Province` | province code, e.g. `GZ`, `C`, `DU` (matched inside the country) | recommended |
| `Shipping City` | city, and region when the province is blank or not recognised (a recognised but wrong province is not detected) | recommended |
| `Shipping Country` | country code (EG, SA, AE, KW, QA, BH, OM) | recommended |
| `Lineitem name` | product segment (the part before the last ` - `, so variants group under their product; setup `product_group: "variant"` keeps the full name; `--products` with a products export gives exact titles by SKU) | optional |
| `Lineitem quantity`, `Lineitem price`, `Lineitem sku` | read, not needed for RTO math | optional |
| `Source` | not used here | optional |

The standard export has no cancel reason and no tracking number. If the agent builds the file from the connector it can add `Cancel Reason` and `Tracking Number` columns; the script uses them when present.

## 2. Shopify connector (MCP)

Use a read-only GraphQL query, 100-250 orders per page, following `pageInfo.endCursor` until `hasNextPage` is false. Filter by date with the `query` argument, for example `created_at:>=2026-07-01 created_at:<2026-10-01`.

```graphql
query Orders($cursor: String, $q: String) {
  orders(first: 100, after: $cursor, query: $q, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name createdAt cancelledAt cancelReason
      displayFinancialStatus displayFulfillmentStatus
      paymentGatewayNames tags email phone sourceName
      totalPriceSet { shopMoney { amount currencyCode } }
      shippingAddress { city province provinceCode countryCodeV2 }
      fulfillments { trackingInfo { number company } }
      lineItems(first: 50) { nodes { name sku quantity } }
    }
  }
}
```

Write one CSV row per line item with these headers so the script reads it like an export: `Name, Created at, Cancelled at, Cancel Reason, Financial Status, Fulfillment Status, Payment Method` (gateway names joined with ` + `), `Tags` (comma separated), `Email, Phone, Total, Shipping City, Shipping Province Name` (address `province`), `Shipping Province` (`provinceCode`), `Shipping Country` (`countryCodeV2`), `Tracking Number` (comma separated), `Lineitem name, Lineitem sku, Lineitem quantity`. Status values like `PAID` or `PARTIALLY_FULFILLED` are fine (case does not matter).

`cancelReason` values are CUSTOMER, DECLINED, FRAUD, INVENTORY, STAFF, OTHER. With this column present, a cancellation after fulfillment only counts as failed when its reason is in `failed_cancel_reasons` (default customer, declined, other).

## 3. Courier files (optional, any courier)

Couriers in Egypt and the GCC (local and regional, any brand) export shipments from their merchant dashboard, usually under Shipments, Orders or Reports, as CSV or XLSX. Ask the merchant for the same date range as the orders.

Columns are mapped by meaning. The script tries these header names (case and spaces ignored) and the agent can override any of them with `--courier-map meaning="Header"` (repeat it with another header when two courier files name the column differently; each file uses the one it has):

| Meaning | Header names tried |
|---|---|
| `ref` (order number) | order number, order no, order, order id, order reference, business reference, merchant reference, reference, ref, رقم الطلب |
| `tracking` | tracking number, tracking no, tracking, awb, awb number, shipment number, shipment id, barcode, رقم الشحنة |
| `status` | status, delivery status, shipment status, shipment state, delivery state, state, current status, last status, الحالة, حالة الشحنة, حالة الطلب |
| `cod_amount` | cod amount, cod, cod value, collected amount, cash amount, قيمة التحصيل |
| `shipping_fee` | shipping fee(s), shipping cost, delivery fee(s), delivery cost, fees, shipping, مصاريف الشحن |
| `return_fee` | return fee(s), rto fee, return shipping, return cost, مصاريف الارتجاع |
| `cod_fee` | cod fee(s), collection fee, cod commission, عمولة التحصيل |
| `reason` | reason, failure reason, return reason, exception reason, comment(s), notes, سبب |
| `courier` | courier, carrier, courier name, shipping company |

Headers with a currency suffix such as `Shipping Fees (EGP)` are matched too. A file needs `status` and either `ref` or `tracking`.

Join rules: order numbers are compared by their digits (`#1001`, `1001` and `ORD-1001` all match order `#1001`); a split-shipment suffix is dropped first (`#1001-2`, `1001_2`, `1001-F1` join on `#1001`). Tracking numbers are compared exactly when the orders file has a `Tracking Number` column. If one order appears in several courier rows, the latest by date wins when the file has a date column (`date`, `last update`, `updated at`, `status date`, `التاريخ`); without one the most final status wins (delivered or failed beats in transit), then the later row. Rows that match no order are counted in `courier.unmatched`.

Status words: a status containing any `failed_courier_statuses` word (checked first, so "undelivered" is failed) means failed; any `delivered_courier_statuses` word means delivered; anything else (in transit, out for delivery) falls back to the Shopify outcome. A cancel status (`cancel`, `ملغي`) on an order Shopify never fulfilled means cancelled before pickup: `cancelled_before_shipping`, no shipping cost. Add the courier's own wording (English or Arabic) to the setup lists.

Blank fee cells (or text with no number, like `N/A` or `-`) use the setup defaults. A fee of 0 in the file is kept as 0.
