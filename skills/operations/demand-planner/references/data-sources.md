# Data sources for demand-planner

The planner needs three things: what sold (order line items), what is in stock now, and what each unit cost. Everything else (lead times, MOQ, case packs, stock history) is optional and makes the plan sharper.

## 1. Shopify connector (preferred when connected)

Read-only GraphQL queries. Paginate with `first: 100` and `after: <cursor>` until `pageInfo.hasNextPage` is false. Never guess IDs.

- Orders, last `history_days` (default 90) plus one year if seasonality is wanted:
  `orders(query: "created_at:>=2025-10-01 status:any", first: 100)` with `name`, `createdAt`, `cancelledAt`, `lineItems(first: 100) { nodes { quantity sku name variant { id sku } } }`.
  Drop orders where `cancelledAt` is set or `displayFinancialStatus` is `REFUNDED` or `VOIDED`; write it to a `Financial Status` column in lower case (`partially_refunded`).
- Variants and cost: `productVariants(first: 100)` with `id sku title price compareAtPrice inventoryQuantity product { title productType vendor } inventoryItem { unitCost { amount } inventoryLevels(first: 20) { edges { node { location { name } quantities(names: ["available", "on_hand", "incoming"]) { name quantity } } } } }`.
- Connections need a page size: `lineItems(first: 100)`. The API returns only the last 60 days of orders unless the app has the `read_all_orders` scope: check the earliest order you got, and if it is too recent, ask for the orders export instead.
- `createdAt` is in UTC: convert it to the store timezone before writing `Created at`, or late evening orders land on the next day.
- Write the results to CSV files with the same column names as the exports below, then run the script. That keeps one code path.

## 2. Shopify exports (always works)

| File | Admin path | Columns used (exact Shopify headers) |
|---|---|---|
| Orders | `Shopify admin > Orders > Export > All orders (or a date range) > CSV for Excel` | `Name`, `Created at`, `Cancelled at`, `Financial Status`, `Lineitem quantity`, `Lineitem sku`, `Lineitem name`, `Lineitem price`, optional `Lineitem refunded quantity` |
| Inventory | `Shopify admin > Products > Inventory > Export > All products > CSV` (pick all locations) | `Handle`, `Title`, `Option1 Value`, `Option2 Value`, `Option3 Value`, `SKU`, `Location`, `Available (not editable)`, `On hand (current)`, `Incoming (not editable)` |
| Products | `Shopify admin > Products > Export > All products > CSV for Excel` | `Handle`, `Title`, `Vendor`, `Type`, `Option1 Value`, `Option2 Value`, `Option3 Value`, `Variant SKU`, `Variant Price`, `Cost per item`, `Variant Inventory Qty` |

Shopify renamed headers in 2026 exports. Both spellings are read: `URL handle` / `Handle`, `SKU` / `Variant SKU`, `Price` / `Variant Price`, `Compare-at price` / `Variant Compare At Price`, `Inventory quantity` / `Variant Inventory Qty`, `Option1 value` / `Option1 Value` (inventory export: `Option 1 Value`), `Canceled at` / `Cancelled at`. The products export `Status` (Active, Draft, Archived) decides which products are planned.

Notes on how the exports behave:
- The orders export has one row per line item. `Created at` and `Cancelled at` are only filled on the first row of each order; the script carries them forward by `Name`.
- Orders exports above 50 orders are emailed to the store owner rather than downloaded. Tell the merchant to check their inbox.
- The products export writes `Title`, `Vendor`, `Type` only on the first row of each product (carried forward by `Handle`). Rows with only an image are skipped.
- `Cost per item` is only in the products export. If it is blank for a variant, its cash is unknown (never 0): totals cover only items with a cost and say how many, and the variant is listed under "missing unit cost".
- Negative `Available` or `Inventory quantity` means oversold: planned as 0 on the shelf with the owed units ordered now, and listed under `oversold`.
- Inventory is summed over all location rows of the same SKU. If only the products export is given, `Variant Inventory Qty` is used as both available and on hand, and incoming stock is taken as zero.
- Variants are matched by SKU (case-insensitive). A variant without a SKU is matched by `Lineitem name` = `Title - Option1 / Option2`. Tell the merchant that missing SKUs make matching fragile.
- A SKU used by more than one product cannot be split: the plan combines their sales and stock, keeps the first product's cost, and lists the SKU in `data_notes`.
- Dates like `10/28/2026` (Excel on a US locale) are read as month/day when a value above 12 shows the column is month first; otherwise slash dates are day/month.
- `Financial Status` `refunded` or `voided`: the order is left out like a cancelled one. `partially_refunded`: kept, minus `Lineitem refunded quantity` when a file has that column (the standard export does not; build it from the connector's `refunds { refundLineItems { quantity lineItem { sku } } }` if you can), otherwise kept whole and noted.
- The stock history file's `date` column uses the same day/month detection as `Created at`.
- Lines on orders whose SKU is not in the inventory file (deleted products) are listed under `unmatched_order_skus`.

## 3. Optional files the merchant can add

| File | Columns | Purpose |
|---|---|---|
| Suppliers sheet (`assets/suppliers.example.csv`) | `sku` or `vendor`, `lead_time_days`, `lead_time_sd_days`, `moq`, `case_pack`, `unit_cost` | Per product or per supplier lead time, variability, MOQ, case pack, cost. A `sku` row beats a `vendor` row, which beats the setup defaults. `vendor` matches the Shopify `Vendor` field. |
| Stock history (`assets/stock-history.example.csv`) | `date`, `sku`, `stock` (end of day units) | Makes demand stockout aware. Shopify admin does not export a daily stock history, so sources are: an inventory app's history export, or the inventory export saved once a day (the agent can do this on a schedule where scheduled tasks exist). Without it the plan says demand may be understated for items that sold out. |
| Supplier invoice (PDF, image, sheet) | read unit cost by meaning | Fills a missing `Cost per item`. Confirm the mapping in one line. |

Map columns by meaning when headers differ (for example `Qty` for `Lineitem quantity`, `Supplier` for `vendor`), and confirm the mapping with the merchant in one line when unsure.

## Seasonality calendar

`assets/seasonal-calendar.json` holds the Ramadan, Eid al Fitr, Eid al Adha and White Friday shopping windows for 2024-2028 as fixed dates. The script reads that table and never computes Islamic dates. Rows marked `expected` can move by one day after moon sighting: edit the file if the official date differs.
