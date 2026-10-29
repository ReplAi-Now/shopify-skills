# Data sources for dead-stock-clearance

Needed: what sold and when (order line items), what is in stock now, price and unit cost per variant. Optional: the date each variant was first stocked.

## 1. Shopify connector (preferred when connected)

Read-only GraphQL. Paginate (`first: 100`, `after: <cursor>`) until `pageInfo.hasNextPage` is false. Never guess IDs.

- Orders for at least `dead_days` x 2 (default 240 days) so "never sold" is meaningful:
  `orders(query: "created_at:>=2026-03-01 status:any", first: 100)` with `name createdAt cancelledAt displayFinancialStatus subtotalPriceSet { shopMoney { amount } } lineItems(first: 100) { nodes { quantity sku name originalUnitPriceSet { shopMoney { amount } } } }`. Write `displayFinancialStatus` in lower case to a `Financial Status` column.
- Variants: `productVariants` with `id sku title price compareAtPrice inventoryQuantity createdAt product { id handle title productType tags } inventoryItem { unitCost { amount } }`.
  `createdAt` of the variant is a usable "first stocked" date when the merchant has no better one (say it is the date the variant was created, not received).
- Connections need a page size: `lineItems(first: 100)`. The API returns only the last 60 days of orders unless the app has the `read_all_orders` scope: check the earliest order you got, and if it is too recent, ask for the orders export instead. `createdAt` is UTC: convert to the store timezone.
- Save the results as CSV with the export headers below and run the script, so there is one code path.

## 2. Shopify exports (always works)

| File | Admin path | Columns used (exact Shopify headers) |
|---|---|---|
| Orders | `Shopify admin > Orders > Export > All orders (or a date range) > CSV for Excel` | `Name`, `Created at`, `Cancelled at`, `Financial Status`, `Subtotal`, `Lineitem quantity`, `Lineitem sku`, `Lineitem name`, `Lineitem price` |
| Products | `Shopify admin > Products > Export > All products > CSV for Excel` | `Handle`, `Title`, `Type`, `Tags`, `Option1 Value`, `Option2 Value`, `Option3 Value`, `Variant SKU`, `Variant Price`, `Variant Compare At Price`, `Cost per item`, `Variant Inventory Qty` |
| Inventory (optional, multi-location stores) | `Shopify admin > Products > Inventory > Export > All products` | `Handle`, `Title`, `Option1 Value`, `SKU`, `Location`, `Available (not editable)`, `On hand (current)` |

How the exports behave:
- Shopify renamed headers in 2026 exports. Both spellings are read: `URL handle` / `Handle`, `SKU` / `Variant SKU`, `Price` / `Variant Price`, `Compare-at price` / `Variant Compare At Price`, `Inventory quantity` / `Variant Inventory Qty`, `Option1 value` / `Option1 Value` (inventory export: `Option 1 Value`), `Canceled at` / `Cancelled at`.
- Negative stock (oversold) counts as 0 units and is listed under `summary.oversold`.
- Orders: one row per line item; `Created at`, `Cancelled at` and `Subtotal` are on the first row of each order only (the script carries them forward by `Name`). Cancelled orders and orders with `Financial Status` `refunded` or `voided` are ignored (a refunded sale is not a sale). `partially_refunded` orders count minus `Lineitem refunded quantity` when a file has that column, otherwise in full. Exports above 50 orders arrive by email.
- Products: `Title`, `Type`, `Tags` are on the first row of each product only (carried forward by `Handle`); image-only rows are skipped.
- Stock comes from the inventory export (summed over locations) when given, else `Variant Inventory Qty`.
- Matching is by SKU (case-insensitive), else by `Lineitem name` = `Title - Option1 / Option2`. A SKU used by more than one product is listed in `data_notes` and gets no store change.
- `Cost per item` blank: the item still gets classified, but no markdown is proposed (the margin floor cannot be checked) and it is listed under "missing unit cost". Its cash stuck is unknown (null), never 0.
- `Subtotal` is used for the average order value (gift threshold). If missing, line price x quantity is used.

## 3. Optional: first stocked dates

A sheet with `sku, first_stocked` (any date format the script reads: 2026-10-15, 15/10/2026, or 10/15/2026 when the column is month first, detected the same way as the orders file). Sources: supplier invoices or receiving records, a purchase order app, or the variant `createdAt` from the connector. Without it, age is unknown and a product that never sold is judged on the length of the order history (the output says so).

Map columns by meaning when headers differ and confirm the mapping with the merchant in one line when unsure.

## Outputs written by the script (`--out-dir`)

| File | Columns |
|---|---|
| `dead-stock-classification.csv` | `sku, title, variant_title, type, category, reason, stock, unit_cost, price, cash_stuck, last_sale, days_since_last_sale, recent_daily_sales, days_of_cover, sell_through_pct, age_days, recommended` |
| `dead-stock-changes.csv` | `handle, product_title, variant_title, sku, variant_id, level, field, old_value, new_value, tactic, note` where `field` is `price`, `compare_at_price`, `tag` or `collection` and `level` is `variant` or `product` |
| `dead-stock-rollback.csv` | `handle, product_title, variant_title, sku, variant_id, level, field, action, restore_value` where `action` is `set`, `remove_tag` or `remove_from_collection` |
