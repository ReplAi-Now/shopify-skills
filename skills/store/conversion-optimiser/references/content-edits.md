# Content changes through the connector

Content (product descriptions, SEO titles, alt text, policies, pages, navigation) is changed with the Shopify connector, never by editing the theme. One confirmed batch at a time, each with a before/after log so it can be rolled back.

## The batch loop

1. **Pick one area** (for example "alt text on the 3 top products"). Keep batches small: up to 25 changes.
2. **Read the before values** with a query (examples below). Never guess IDs; find them with a query first.
3. **Draft the after values** in the brand voice and language(s) from setup. Never invent facts (materials, delivery times, guarantees): use what the store already says or ask.
4. **Show the change list** and wait:
   ```
   Batch 2 of 4: alt text (6 changes)
   1. Linen dress, image 1: "" -> "Beige linen midi dress, front view"
   2. Linen dress, image 2: "IMG_2041" -> "Beige linen midi dress, back view"
   ...
   Reply "yes" to apply these 6 changes, or tell me what to change.
   ```
5. **Apply only after an explicit yes for this list.** "Yes" to batch 1 is not a yes to batch 2.
6. **Read back** each changed field and confirm it matches. Report failures (`userErrors`) in plain words.
7. **Log** the batch (format below). Save it as `replai-cro-change-log.json` in the working folder; in chat apps, print it as a JSON block for the merchant to keep.

## Change log format

```json
{
 "store": "example-store.myshopify.com",
 "previous_live_theme_id": "gid://shopify/OnlineStoreTheme/111",
 "batches": [
  {"batch": 1, "approved_at": "2026-10-29T14:05", "approved_text": "yes",
   "changes": [
    {"resource": "media_image", "id": "gid://shopify/MediaImage/9", "title": "Linen dress image 1",
     "field": "alt", "before": "", "after": "Beige linen midi dress, front view", "status": "applied"}
   ]}
 ]
}
```

`status`: applied, failed, skipped. To undo: `python3 scripts/rollback.py replai-cro-change-log.json [--batch N]` lists the changes to revert, newest first, with the value to restore. Read each field first: if it no longer equals `expect_current`, someone changed it since, so ask before overwriting. A rollback is a new batch and needs its own yes.

## Queries and mutations

Product description and SEO:
```graphql
query { product(id: "gid://shopify/Product/1") { id title descriptionHtml seo { title description } } }

mutation UpdateProduct($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id descriptionHtml seo { title description } }
    userErrors { field message }
  }
}
```
Variables: `{"product": {"id": "gid://shopify/Product/1", "descriptionHtml": "<p>...</p>", "seo": {"title": "...", "description": "..."}}}`. Older API versions take `input:` instead of `product:`.

Image alt text (product images are MediaImage files):
```graphql
query { product(id: "gid://shopify/Product/1") { media(first: 20) { nodes { id alt mediaContentType } } } }

mutation Alt($files: [FileUpdateInput!]!) {
  fileUpdate(files: $files) {
    files { id alt }
    userErrors { field message code }
  }
}
```
Variables: `{"files": [{"id": "gid://shopify/MediaImage/9", "alt": "Beige linen midi dress, front view"}]}`. Alt text describes the image (product, colour, view) in under about 125 characters. No keyword stuffing.

Policies (refund, shipping, privacy, terms):
```graphql
query { shop { shopPolicies { id type title body } } }

mutation Policy($shopPolicy: ShopPolicyInput!) {
  shopPolicyUpdate(shopPolicy: $shopPolicy) {
    shopPolicy { id type body }
    userErrors { field message }
  }
}
```
Variables: `{"shopPolicy": {"type": "REFUND_POLICY", "body": "<p>...</p>"}}`. Types include REFUND_POLICY, SHIPPING_POLICY, PRIVACY_POLICY, TERMS_OF_SERVICE, CONTACT_INFORMATION. Policies are legal text: draft only from what the merchant tells you about their real terms, and suggest they review it.

Pages (FAQ, delivery info, size guide):
```graphql
mutation NewPage($page: PageCreateInput!) { pageCreate(page: $page) { page { id handle } userErrors { code field message } } }
mutation EditPage($id: ID!, $page: PageUpdateInput!) { pageUpdate(id: $id, page: $page) { page { id } userErrors { code field message } } }
```

Navigation menus. `menuUpdate` REPLACES the whole item tree: any item you leave out is removed. Always read the full menu, change it, and send back every item with its `id`.
```graphql
query { menus(first: 10) { nodes { id handle title items { id title type url resourceId tags items { id title type url resourceId tags items { id title type url resourceId tags } } } } } }

mutation Menu($id: ID!, $title: String!, $handle: String!, $items: [MenuItemUpdateInput!]!) {
  menuUpdate(id: $id, title: $title, handle: $handle, items: $items) {
    menu { id items { id title } }
    userErrors { field message code }
  }
}
```
Log the full before tree as the `before` value so it can be restored in one call.

## Settings the merchant changes by hand

Some fixes are admin settings the connector cannot or should not change (checkout fields, customer accounts, payment method names, shipping rates). Give exact clicks, for example: Settings > Checkout > Customer contact method / Company name: "Don't include" > Save. Mark these `change_type: setting` and list them separately so the merchant can do them in one sitting.
