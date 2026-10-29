# Data sources for true-profit

Order of preference: Shopify connector, then exports, then files the merchant uploads. Exports alone must always work. All files should cover the same dates.

## 1. Shopify orders

Export: `Shopify admin > Orders > filter the date range > Export > "All orders" or "Current page" > "CSV for Excel"`. One row per line item; order-level columns are on the first row of each order.

| Column | Used for |
|---|---|
| `Name` | order number, join key to courier files (required) |
| `Financial Status`, `Fulfillment Status`, `Cancelled at` (2026 exports: `Canceled at`, both read), `Tags` | delivered / failed (RTO) / open / not shipped (required: the two statuses) |
| `Payment Method` | COD vs card/wallet, e.g. `Cash on Delivery (COD)` |
| `Created at` | period |
| `Lineitem name` | product (the part before the last ` - ` is the product title; with group_by `variant` the full name) |
| `Lineitem sku` | match to product cost |
| `Lineitem quantity`, `Lineitem price` | units and gross sales |
| `Discount Amount` | order discount, split across lines by line value |
| `Shipping` | shipping charged to the customer (income) |
| `Taxes` | removed from revenue only if setup `prices_include_tax` is true |
| `Total` | base for percentage fees |
| `Refunded Amount` | refunds after delivery |
| `Source` | sales channel (web, pos, shopify_draft_order, an app name) |
| `Lineitem returned quantity` | optional, connector-built only: units sent back after delivery (see below) |
| `Gift Card Amount` | optional, connector-built only: gift card part of a COD order, so the COD % fee applies to the cash part |

Blind spot: when a delivered order's items come back and are restocked without a refund (Try & Buy, exchanges handled by restock), the export shows nothing: `Refunded Amount` stays 0 and revenue is overstated. Only the connector sees it (`refunds.refundLineItems` with `restockType: RETURN`). Without that data the result says so.

Connector (read-only, paginate 100 per page with `pageInfo.endCursor`, filter with `query: "created_at:>=2026-09-01 created_at:<2026-10-01"`):

```graphql
query Orders($cursor: String, $q: String) {
  orders(first: 100, after: $cursor, query: $q, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name createdAt cancelledAt cancelReason sourceName tags
      displayFinancialStatus displayFulfillmentStatus paymentGatewayNames
      totalPriceSet { shopMoney { amount currencyCode } }
      totalShippingPriceSet { shopMoney { amount } }
      totalTaxSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      fulfillments { trackingInfo { number } }
      lineItems(first: 50) { nodes { name sku quantity originalUnitPriceSet { shopMoney { amount } } } }
      refunds(first: 20) {
        refundLineItems(first: 50) { nodes { restockType quantity lineItem { sku name } } }
      }
      transactions(first: 20) { gateway kind status amountSet { shopMoney { amount } } }
    }
  }
}
```

Write it as a CSV with the export headers above (`Total`, `Shipping`, `Taxes`, `Discount Amount`, `Refunded Amount`, `Source` from `sourceName`, `Payment Method` from gateway names joined with ` + `, `Tracking Number` from tracking numbers), one row per line item. Add `Lineitem returned quantity` = sum of `quantity` over `refundLineItems` with `restockType` `RETURN` for that line (matched by SKU, else name), and `Gift Card Amount` = sum of successful `SALE`/`CAPTURE` transactions with gateway `gift_card`.

**Returns file instead** (`--returns returns.csv`): one row per returned line, columns `order` (order name, e.g. `#1001`), `sku` (or `product`, the line item name), `quantity`, optional `restock_type` (only `RETURN` rows count when present). Rows for orders that were not delivered are ignored. The returned value net of discount comes off revenue only where `Refunded Amount` does not already cover it, so rows that were also refunded are not counted twice.

## 2. Product costs

Any of these, passed with `--costs`:

**Shopify products export**: `Shopify admin > Products > Export > All products > CSV for Excel`. Columns used: `Handle` (2026 exports: `URL handle`), `Title` (only on the first row of each product, filled down by handle), `Variant SKU` (2026: `SKU`), `Cost per item`. Both header sets are read. Rows with an empty `Cost per item` are skipped (cost missing).

**Connector**: read-only query of variants with their cost:
```graphql
query Costs($cursor: String) {
  productVariants(first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { sku title product { title } inventoryItem { unitCost { amount currencyCode } } }
  }
}
```
Write `sku, product, variant, unit_cost, currency` rows (`product.title`, variant `title`, `unitCost.amount`).

**Cost sheet or supplier invoices**: use `assets/product-costs-template.csv`:

| Column | Meaning |
|---|---|
| `sku` | variant SKU as in Shopify (best match key) |
| `product` | product title as in Shopify (used when an order line has no SKU match; the average of that product's rows) |
| `variant` | optional, for the merchant's reading |
| `unit_cost` | cost of one unit (column names `cost per item`, `unit cost`, `cost`, `landed cost` are also accepted) |
| `currency` | optional; if not the store currency, setup `fx_rates` must have the rate |
| `source`, `invoice_ref`, `invoice_date` | optional, for the audit trail |

Extracting invoices: one row per SKU. Unit cost = invoice line total / quantity. For landed cost, spread freight, customs and clearance over the lines by value and add it (say so). If two invoices give different costs for one SKU, use the latest one, or the one the merchant picks. Show the extracted table and wait for a yes before running.

## 3. Ad exports

Pass each with `--ads platform=file`. Spend header with a currency, like `Amount spent (USD)`, sets the currency; otherwise a `Currency` / `Currency code` column, otherwise setup `ad_currency[platform]`, otherwise the store currency (stated).

**Meta**: `Ads Manager > Campaigns (or Ad sets / Ads tab) > choose the date range > Reports > Export table data > .csv`. Add `Breakdown > By time > Day` if the merchant wants daily rows. Columns used: `Campaign name`, `Ad set name`, `Ad name`, `Amount spent (<CUR>)`, `Purchases`, `Purchases conversion value`, `Reporting starts` (or `Day`).

**TikTok**: `TikTok Ads Manager > Campaign > Campaign / Ad group / Ad tab > date range > Export (download icon)`. Columns used: `Campaign name`, `Ad group name`, `Ad name`, `Cost`, `Conversions` or `Complete payment` / `Total complete payment`, `Total complete payment value` if present, `Date` or `By Day`, `Currency`.

**Google Ads**: `Google Ads > Campaigns > date range > Download (arrow icon) > .csv` (or .xlsx). The file starts with a report title and a date line before the header; the script skips them in CSV and XLSX, and skips `Total:` rows.

**Arabic interface**: exports from an Arabic Ads Manager are read too: `اسم الحملة` (campaign), `اسم مجموعة الإعلانات` (ad set), `اسم الإعلان` (ad), `المبلغ المنفق` (spend, with or without a currency suffix), `التكلفة` (cost), `عمليات الشراء` (purchases), `قيمة تحويل عمليات الشراء` (purchase value), `التاريخ` / `بداية التقارير` (date), `العملة` (currency); `الإجمالي` rows are skipped. Columns used: `Campaign`, `Ad group` (if downloaded at ad group level), `Cost`, `Conversions`, `Conv. value`, `Day`, `Currency code`.

Other platforms (Snapchat, X): any CSV with a campaign name and a spend/cost column works.

## 4. Ad to product map

`--ad-map` file, shape of `assets/ad-map-template.csv`:

| Column | Meaning |
|---|---|
| `platform` | meta / tiktok / google, or blank for any |
| `level` | `campaign`, `adset` (ad group) or `ad` |
| `contains` | text the name contains, case ignored |
| `product` | product title as in Shopify, several joined with `|`, or `SHARED` |

Most specific rule wins (ad before ad set before campaign, then the longer text). Spend that matches no rule, or `SHARED`, is split across all products by net revenue. The agent proposes this file from campaign names and product titles; the merchant confirms it.

## 5. Courier files

Same as the cod-rto-analysis skill: any courier export (CSV/XLSX), columns mapped by meaning. Used: order number or tracking number, `status` (decides delivered vs failed), `shipping_fee`, `return_fee`, `cod_fee`. Blank fee cells use setup defaults. Accepted header names are listed in `scripts/orders.py` (`COURIER_COLS`): order number, reference, AWB, tracking, status, shipping fees, delivery fee, return fees, RTO fee, COD fee, collection fee, plus the Arabic equivalents. Override with `--courier-map meaning="Header"`.

## 6. Payment fees

Card and wallet gateways (Paymob, Tap, Moyasar, Checkout.com, Shopify Payments, others) charge a % plus a fixed amount per order; ask the merchant for the rate on their statement and save it in setup. Couriers charge a COD fee, often a % of cash collected; the courier file's COD fee column, when present, replaces the setup rate.
