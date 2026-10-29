# Data sources for returns-reason-analysis

Use the best source available; combine them when the merchant has several (for example connector returns plus a courier file for refusals). Every source ends up as one returns file (one row per returned line) that `classify_reasons.py` reads.

## 1. Shopify connector (best: line-level reasons)

Returns with `returnLineItems { returnReason, returnReasonNote, customerNote }`, exchanges, and refunds with `refundLineItems`. Exact queries and the column mapping: [shopify-queries.md](shopify-queries.md).

## 2. Shopify orders export (always available)

`Shopify admin > Orders > (filter: Date, last 4-6 months) > Export > All orders matching your search > CSV for Excel`.

Used twice:
1. **Units sold** for return rates (`analyze_returns.py --orders`).
2. **Returns from refunds, tags and notes** when there is no connector and no returns app (`extract_from_orders.py`).

Columns relied on (matched case-insensitively, spaces become `_`):

| Export column | Used for |
|---|---|
| `Name` | order id, joins returns to orders (required) |
| `Created at` | order date, the cohort window (required) |
| `Cancelled at` (newer exports: `Canceled at`), `Financial Status` | cancelled or `voided` orders are not sold units; `refunded` / `partially_refunded` mark returns |
| `Fulfillment Status` | cancelled or voided AFTER fulfilment = refused at the door (a failed COD delivery), same rule as the cod-rto-analysis skill. Cancelled before fulfilment is skipped. |
| `Subtotal`, `Refunded Amount` | full vs partial refund, refund money |
| `Lineitem name` | product and variant (`Product - Size / Colour`) |
| `Lineitem sku` | variant key, joins to returns and costs |
| `Lineitem quantity`, `Lineitem price`, `Lineitem discount` | units sold, refund split by line value |
| `Vendor` | supplier grouping |
| `Tags` | `return_tags`, `exchange_tags`, `refused_tags` from setup; other tags are kept as reason text (for example `size-small`) |
| `Notes`, `Note Attributes` | free-text reason |

Limits of the export, say them in the report when they apply:
- It has no refund date and no line-level refund detail. A partial refund on a multi-item order becomes a row with product "(not identified)": its money is counted, it is not in any product's rate.
- A partial refund on a single-item order estimates the units as refund / unit price. A refund under half the unit price (a shipping fee or goodwill refund) is counted as money only, with no returned unit.
- Reasons exist only if the team writes them in notes or tags.
- Shopify return records are not in the orders export. A store that keeps returns as return records, or takes items back without refunding (Try & Buy at the door, exchanges, store credit), shows no refunds and no return tags, so the export finds no returns at all. `extract_from_orders.py` then prints `no_returns_found` explaining this: use the connector ([shopify-queries.md](shopify-queries.md)) or a returns app export. Refused-at-door orders are still found (from cancelled after fulfilment) and reported on their own.

## 3. Products export (optional, for restocking loss)

`Shopify admin > Products > Export > All products > CSV for Excel`. Columns: `Variant SKU`, `Cost per item`. Without unit costs, restocking loss is left out and the report says so.

## 4. Returns app or courier returns CSV (optional)

Any returns app export or a courier's returns / RTO sheet. Map columns by meaning; confirm the mapping with the merchant in one line when unsure. `classify_reasons.py` recognises these names (after lowercasing, spaces to `_`):

| Meaning | Accepted column names |
|---|---|
| return id | `return_id`, `return_name`, `rma`, `return_number` |
| order | `order`, `order_name`, `order_number`, `order_id` |
| order date | `order_date`, `order_created_at`, `ordered_at` |
| return date | `return_date`, `requested_at`, `created_at`, `date` |
| product | `product`, `product_title`, `product_name`, `item`, `item_name`, `lineitem_name` |
| variant | `variant`, `variant_title`, `option`, `options` |
| sku | `sku`, `variant_sku`, `lineitem_sku` |
| vendor | `vendor`, `supplier` |
| quantity | `quantity`, `qty`, `return_quantity`, `units` (blank = 1) |
| type | `type`, `resolution`, `return_type`, `action`, `outcome` (refund / exchange / refused) |
| reason code | `reason_code`, `return_reason`, `return_reason_handle`, `reason_handle` |
| reason text | `reason`, `reason_text`, `return_reason_note`, `reason_note`, `customer_note`, `note`, `notes`, `comment`, `message` |
| refund | `refund_amount`, `refund`, `refunded`, `amount_refunded`, `refunded_amount` |
| return shipping | `return_shipping_cost`, `return_shipping`, `shipping_cost` (per row; put a shipment's cost on one row or split it) |

If the file uses other names, rename the headers before running, or build the CSV yourself with the names above.

Courier refusals (refused at door, RTO) go in with `type = refused`. They are reported separately and never count as returns.

## 5. Support chat export (optional)

WhatsApp, Instagram, helpdesk or ReplAi exports. Read the conversations about returns and extract one row per returned item: `order`, `product`, `variant`, `quantity` (if stated), `reason_text` (the customer's own words, any language), `source = chat`. Only include conversations where a return or exchange actually happened or was requested; do not include questions. Do not copy names, phones or addresses into the file.

## Combining sources

- Prefer connector or app rows over export-derived rows for the same order (they have line detail). Drop the export row for an order already covered.
- Keep courier refusals from the courier file even if the order also appears in Shopify as cancelled.
