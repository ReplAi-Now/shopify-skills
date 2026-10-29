# Shopify connector queries for returns

Read-only Admin GraphQL. Paginate every connection (`pageInfo { hasNextPage endCursor }`). Field names move between API versions: if a field errors, check it with the connector's schema or introspection tool and adjust. Never guess IDs.

## 1. Orders that have returns or refunds

Pull orders PLACED in the analysis window plus the return window (so late returns are included), filtered to the ones with a return or refund:

```graphql
query ReturnedOrders($cursor: String, $q: String!) {
  orders(first: 50, after: $cursor, query: $q, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name createdAt cancelledAt displayFinancialStatus displayFulfillmentStatus tags note
      paymentGatewayNames
      returns(first: 10) {
        nodes {
          id name status createdAt
          returnLineItems(first: 50) {
            nodes {
              quantity
              returnReasonDefinition { handle name }   # size-too-small, color, defective, wrong-item ...
              returnReasonNote        # merchant or app note
              customerNote            # what the customer typed
              ... on ReturnLineItem {
                fulfillmentLineItem {
                  lineItem { name sku variantTitle vendor product { title } }
                }
              }
            }
          }
          exchangeLineItems(first: 20) { nodes { lineItems { name sku } } }
        }
      }
      refunds(first: 20) {
        createdAt note
        totalRefundedSet { shopMoney { amount currencyCode } }
        refundLineItems(first: 50) {
          nodes { quantity restockType subtotalSet { shopMoney { amount } } lineItem { name sku variantTitle vendor } }
        }
      }
    }
  }
}
```

`$q` example: `"created_at:>=2026-06-01 created_at:<=2026-10-29 (return_status:returned OR return_status:in_progress OR return_status:inspection_complete OR financial_status:refunded OR financial_status:partially_refunded)"`. If the `return_status` filter is not accepted by the store's API version, drop it and keep the financial status filter plus a tag filter (`tag:exchange`), then skip orders with no returns or refunds.

`returnReasonDefinition { handle name }` is the reason field (handles such as `size-too-small`, `color`, `defective`, `not-as-described`, `wrong-item`, `unwanted`, `style`, `other`); write the handle to `reason_code` and add `name` to `reason_text` when the handle is a store-defined one. The old `returnReason` enum is removed in current API versions: query it only if `returnReasonDefinition` errors on an old version. Both map through `reason_codes` in `assets/reason-lexicon.json`.

On older versions `exchangeLineItems` nodes have `lineItem` (singular) instead of `lineItems`.

## 2. Turn the result into the returns file

Write one CSV row per return line item (and per refund line item that is not already covered by a return):

| Column | From |
|---|---|
| `return_id` | `Return.name` (or the refund id for refunds without a return) |
| `order` | `Order.name` |
| `order_date` | `Order.createdAt` (date part, store timezone) |
| `return_date` | `Return.createdAt` or `Refund.createdAt` |
| `product` | `lineItem.product.title` |
| `variant` | `lineItem.variantTitle` |
| `sku` | `lineItem.sku` |
| `vendor` | `lineItem.vendor` |
| `quantity` | `ReturnLineItem.quantity` or `RefundLineItem.quantity` |
| `type` | `exchange` if the return has exchange line items, `refused` if the order is tagged refused or was cancelled after it was fulfilled (a failed COD delivery, same rule as cod-rto-analysis), else `refund` |
| `reason_code` | `returnReasonDefinition.handle` (`returnReason` only on old API versions) |
| `reason_text` | `returnReasonNote` |
| `customer_note` | `customerNote`, plus `Order.note` if it mentions the return |
| `refund_amount` | refund line `subtotalSet` (or the refund total split by line value). Blank for refused orders and for COD orders that were never paid: an uncollected amount is not a refund, no money moved. |
| `return_shipping_cost` | leave blank unless the merchant's courier data gives it (setup default is used) |

Then run `classify_reasons.py` on it.

Avoid double counting: a return that was refunded appears in both `returns` and `refunds`. Use the return line for reason and quantity, and the matching refund line (same SKU, same order) for the amount.

Refund lines that are NOT returns, skip them:
- `restockType: CANCEL` on an order cancelled before it was fulfilled (`cancelledAt` set, `displayFulfillmentStatus` not fulfilled). Shopify writes a refund line for every item of a cancelled order; on a COD store that turns every cancellation into a fake return (one real store showed about 140 of them).
- Any refund line on an order cancelled after fulfilment: that is a refused parcel, write one `type = refused` row per line instead (never a return).
- On COD orders that were never paid (`displayFinancialStatus` voided or pending), a "refund" line moves no money. Do not report its amount as refunded.

Only `restockType: RETURN` lines (and `NO_RESTOCK` lines on orders that were fulfilled and not cancelled, for example a refund for a damaged item kept by the customer) are returns. A store that restocks without refunding (Try & Buy) still has `RETURN` restock lines with no money: keep them as returns with `refund_amount` 0.

## 3. Units sold (for return rates)

Return rates need units sold in the same order window. Use the orders export (Orders > Export), or query:

```graphql
query Sold($cursor: String, $q: String!) {
  orders(first: 100, after: $cursor, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes { name createdAt cancelledAt displayFinancialStatus
      lineItems(first: 100) { nodes { name sku quantity vendor originalUnitPriceSet { shopMoney { amount } } } } }
  }
}
```
with `$q = "created_at:>=2026-07-11 created_at:<=2026-10-08"` and write it with orders-export column names (`Name`, `Created at`, `Cancelled at`, `Lineitem name`, `Lineitem sku`, `Lineitem quantity`, `Lineitem price`, `Vendor`). `Lineitem name` is `Product title - Variant title`.

## 4. Unit cost (for restocking loss)

```graphql
query Costs($cursor: String) {
  productVariants(first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { sku inventoryItem { unitCost { amount } } }
  }
}
```
Write `Variant SKU,Cost per item` and pass it as `--products`.
