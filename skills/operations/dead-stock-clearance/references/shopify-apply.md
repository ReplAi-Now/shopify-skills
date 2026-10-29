# Applying the approved change list in Shopify

Only after the merchant has reviewed `dead-stock-changes.csv` and said yes to that exact list. Approval covers that list once. A new or edited list needs a new yes.

## 0. Before any write

1. Confirm the store: read the shop name (`{ shop { name myshopifyDomain currencyCode } }`) and say it back.
2. Re-read the live values for every row (prices may have changed since the export):
   ```graphql
   query ($q: String!) {
     productVariants(first: 50, query: $q) {
       nodes { id sku price compareAtPrice product { id handle title tags } }
     }
   }
   ```
   with `$q = "sku:D1 OR sku:S2"` (batch 25 SKUs per query). Never guess IDs. A variant without a SKU: look it up by product handle (`products(first: 1, query: "handle:wool-coat") { nodes { id variants(first: 100) { nodes { id title price compareAtPrice } } } }`) and match the variant title.
3. If a live value differs from `old_value` in the CSV, stop for that row and show the difference.
4. Write the rollback file from the LIVE values before the first change: `dead-stock-rollback-<YYYYMMDD-HHMM>.csv` with columns `handle, product_title, variant_title, sku, variant_id, level, field, action, restore_value` (same shape as the script's `dead-stock-rollback.csv`, with real IDs filled in). Tell the merchant where it is.

## 1. Price and compare-at price (variant level)

One call per product, all its variants together:

```graphql
mutation ($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price compareAtPrice }
    userErrors { field message }
  }
}
```

Variables:

```json
{"productId": "gid://shopify/Product/111",
 "variants": [{"id": "gid://shopify/ProductVariant/222", "price": "175.00", "compareAtPrice": "199.00"}]}
```

- Prices are strings in the store currency.
- `compareAtPrice` must be higher than `price` to show as a sale. To clear it (a rollback row whose `restore_value` is empty), send `"compareAtPrice": null`.
- Check `userErrors` after every call. On any error, stop, report which rows were applied, and offer the rollback for those rows.

## 2. Tags (product level)

```graphql
mutation ($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) { node { id } userErrors { field message } }
}
```

`$id` is the product GID, `$tags` for example `["clearance"]`. Tags apply to the whole product (all variants). If only some variants of a product are on the list, say so before applying.

Rollback: `tagsRemove(id: $id, tags: ["clearance"])` with the same shape.

## 3. Clearance collection

Best: a smart (automated) collection whose rule is "product tag equals clearance". Then the tag from step 2 is enough and removing the tag removes the product.

If the collection does not exist yet, creating it is a store change: list it in the change list and get the yes first.

```graphql
mutation ($input: CollectionInput!) {
  collectionCreate(input: $input) { collection { id handle } userErrors { field message } }
}
```

```json
{"input": {"title": "Clearance",
  "ruleSet": {"appliedDisjunctively": false,
              "rules": [{"column": "TAG", "relation": "EQUALS", "condition": "clearance"}]}}}
```

A new collection is not visible until published to the Online Store sales channel (`Shopify admin > Products > Collections > Clearance > Sales channels`), which is a separate yes.

If the merchant already has a manual (custom) Clearance collection, add products instead:

```graphql
mutation ($id: ID!, $productIds: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $productIds) { collection { id } userErrors { field message } }
}
```

Rollback: `collectionRemoveProducts(id: $id, productIds: [...])` (returns a job; check it finished).

## 4. Bundle and free gift discounts (manual, separate approval)

The change list only tags these products. The discount itself is a second, separate change the merchant approves on its own:

- Bundle (buy the fast mover, get the slow item at X% off): `Shopify admin > Discounts > Create discount > Buy X get Y`. Customer buys: minimum quantity 1 of the partner product. Customer gets: 1 of the slow item, at a discounted value of the bundle discount %. Automatic discount. Or use Shopify's free Bundles app to sell them as one product.
- Free gift above a threshold: `Shopify admin > Discounts > Create discount > Buy X get Y`. Customer spends: minimum purchase amount = the threshold. Customer gets: 1 of the gift item, free. Set an end date and a usage limit equal to the units in stock.
- Via API the same discounts are made with `discountAutomaticBxgyCreate`; show the merchant the full input first and check the result in admin.

## 5. Manual path (no connector)

Give the merchant the CSV and these steps: `Shopify admin > Products > Export` the affected products, edit `Variant Price`, `Variant Compare At Price` and `Tags` to match `dead-stock-changes.csv`, then `Products > Import` with "Overwrite products with matching handles" ticked. Keep the original export file as the rollback. Warn that importing overwrites every column in the file, so they should delete columns they did not change (keep `Handle`, option columns, and the edited columns).

## 6. After applying

- Re-read the changed variants and products and show a before/after table.
- Report: rows applied, rows skipped (and why), rollback file path.
- Suggest checking the clearance collection and one product page on a phone.

## Rollback

Read the rollback CSV and, after a yes for that list: `set` rows go through `productVariantsBulkUpdate` with `restore_value` (empty = `null` for compare-at), `remove_tag` rows through `tagsRemove`, `remove_from_collection` rows through `collectionRemoveProducts` (manual collections only; smart collections follow the tag).
