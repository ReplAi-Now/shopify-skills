# Shopify recipes (Admin GraphQL)

Tool names vary by connector: `create-product`, `get-product`, `update-product`, `search_collections`, `add-to-collection`, `get-inventory-levels`, `set-inventory`, `graphql_query`, `graphql_mutation` (official Shopify connector), or `shopify store execute` through Shopify CLI. If a field below is rejected, check the current schema (`graphql_schema` or shopify.dev) before retrying; the Admin API changes every quarter.

`create-product` / `update-product` accept only public HTTPS image URLs, not local files.

## SKUs

Real stores use many SKU shapes. At setup, read the SKUs of the 50 most recent products and classify the store's pattern, then save it:

| Shape | Example | Product base | Variant part |
|---|---|---|---|
| prefix + number + index | `ABC-1104-1`, `ABC-1104-2` | `ABC-1104` | running index |
| number + size | `1126071-36/37`, `1126071-38/39` | `1126071` | size value as written |
| code + colour code + size | `O-251-BLK-S`, `O-251-BLK-M` | `O-251` | 3-letter colour code + size |
| no SKUs or no clear pattern | | propose `<PREFIX>-<number>-<n>` and ask | |

Continue the store's own shape; never switch a store to a new shape without asking. Colour codes: reuse the codes the store already uses (`BLK`, `WHT`...); for a new colour, propose a 3-letter code in the plan.

Finding the next free product number (numeric bases):
1. Shopify sorts SKUs alphabetically (`X-999` above `X-1050`), and `sku:X-10*` also matches suffixes, so neither gives the max. Query recent products:
   `products(first: 50, sortKey: CREATED_AT, reverse: true) { nodes { title createdAt variants(first: 3) { nodes { sku } } } }`
   and parse the base number with a regex for the store's shape (e.g. `^<PREFIX>-(\d+)(?:-|$)` or `^(\d+)-`). Take the max.
2. Confirm nothing higher exists: query `productVariants(first: 20, query: "sku:<base max+1>* OR sku:<base max+2>* ... OR sku:<base max+10>* OR sku:<base max+50>* OR sku:<base max+100>*")` (build each term in the store's shape, e.g. `sku:ABC-1105-1` or `sku:1126072-*`). It must return nothing; if it returns something, raise the max and check again.
3. Assign products in subfolder order max+1, max+2, ... For index shapes, variants go sizes within colour, colours in listing order (Black S = -1, Black M = -2, then the next colour continues); one-size products get one number per colour.
4. Code bases that are not numbers (`O-251` style, often the merchant's own style code): ask the merchant for the codes in the plan instead of guessing.

## Route A: public image URLs (preferred)

If the photos exist at public HTTPS URLs (for example image-generator download links listed in catalog-photoshoot's `report.csv`, still within their expiry), pass them in `create-product` `images` with `altText`, ordered colour by colour, front first. Before use, confirm each URL serves the same file (`curl -sI` Content-Length equals the local file size). Shopify copies the image at import. After create, media import is async: poll `product(id) { media(first: 50) { nodes { id alt status } } }` until every status is `READY`.

## Route B: staged upload of local files

1. One `graphql_mutation` per product (5 files or fewer per call; each signed URL carries a long signature that must be copied exactly):
   ```graphql
   mutation stage($input: [StagedUploadInput!]!) {
     stagedUploadsCreate(input: $input) {
       stagedTargets { url resourceUrl parameters { name value } }
       userErrors { field message }
     }
   }
   ```
   One input per file: `{filename, mimeType: "image/png", resource: "IMAGE", httpMethod: "PUT"}`.
2. Upload with only the Content-Type header (adding other headers from `parameters` breaks the signature):
   `curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: image/png" --data-binary @"<file>" "<url>"`, expect `200`. Save `file -> resourceUrl` immediately.
3. Create the product (below) without images, then attach:
   ```graphql
   mutation addMedia($product: ProductUpdateInput!, $media: [CreateMediaInput!]) {
     productUpdate(product: $product, media: $media) {
       product { id media(first: 50) { nodes { id alt status } } }
       userErrors { field message }
     }
   }
   ```
   `media`: `{originalSource: <resourceUrl>, mediaContentType: IMAGE, alt: "<Title> - <Colour> - front"}` per file. Poll until `READY`; `FAILED` gets re-staged once, then reported.

## Create the product

`create-product` with `title`, `descriptionHtml`, `productType`, `vendor`, `tags` (array), `status: "DRAFT"`, `options: ["Color","Size"]`, `variants` (every colour x size with `price`, `sku`, `optionValues: [{optionName: "Color", name: "Black"}, {optionName: "Size", name: "M"}]`, `inventoryItem: {tracked: true}`), and `collectionId` for the first manual collection. The connector's `create-product` has no compare-at price or cost fields: set those in the variant bulk update below, never drop them. Equivalent GraphQL: `productSet` with `productOptions` and `variants` (accepts `compareAtPrice` and `inventoryItem.cost` directly).

## Link photos to variants

`productVariantAppendMedia(productId, variantMedia: [{variantId, mediaIds: [<front media id of that colour>]}])` for every variant. Get variant ids and Color values from `get-product`.

## Variant settings (taxes, continue selling, SKU)

One mutation for all products with aliases:
```graphql
mutation v($p1: ID!, $v1: [ProductVariantsBulkInput!]!, $p2: ID!, $v2: [ProductVariantsBulkInput!]!) {
  a: productVariantsBulkUpdate(productId: $p1, variants: $v1) { productVariants { id sku taxable inventoryPolicy } userErrors { field message } }
  b: productVariantsBulkUpdate(productId: $p2, variants: $v2) { productVariants { id sku taxable inventoryPolicy } userErrors { field message } }
}
```
Each variant: `{id, taxable: <setup>, inventoryPolicy: CONTINUE | DENY (setup), compareAtPrice: "<if given>", inventoryItem: {sku: "<SKU>", cost: "<cost per item if given>"}}`. Check every alias: empty `userErrors`, right values.

## Category and colour swatches

Swatches show on collection pages only when the Color option is linked to the `shopify.color-pattern` category metafield, and that works only on products with a taxonomy category.
1. Category: `taxonomy { categories(first: 5, search: "<type>") { nodes { id fullName } } }`. The search also returns baby and pet categories; pick the correct branch (e.g. `Apparel & Accessories > Clothing > Dresses`). Set with `productUpdate(product: {id, category: "<TaxonomyCategory gid>"})`.
2. Existing swatches: `metaobjects(type: "shopify--color-pattern", first: 250) { nodes { id handle displayName } }`. Reuse by name.
3. Missing swatch: read one existing entry's fields (`metaobject(id) { fields { key value } }`) and copy its format:
   ```graphql
   metaobjectCreate(metaobject: {type: "shopify--color-pattern", handle: "<colour-handle>", fields: [
     {key: "label", value: "Black/Beige"},
     {key: "color", value: "#000000"},
     {key: "color_taxonomy_reference", value: "[\"gid://shopify/TaxonomyValue/<id>\"]"},
     {key: "pattern_taxonomy_reference", value: "gid://shopify/TaxonomyValue/<id>"}]})
   ```
   Copy taxonomy value ids from existing entries of the same colour or pattern (Solid, Striped); never guess them. If the store has no entries, look the values up with `taxonomy { categories(...) { nodes { attributes ... } } }` for the product's category, or ask the merchant to create one swatch in admin first and copy it.
4. Link: `productOptionUpdate(productId, option: {id: <Color option id>, linkedMetafield: {namespace: "shopify", key: "color-pattern"}}, optionValuesToUpdate: [{id: <value id>, linkedMetafieldValue: "<metaobject gid>"}, ...])`.
5. Verify each Color value returns non-null `swatch { color }`.

## Stock

`get-inventory-levels` for the product's variants, then `set-inventory` per variant with `compareQuantity` = current (usually 0) and `reason: "received"`. GraphQL equivalent: `inventorySetQuantities` with `name: "available"`.

## Collections

`search_collections` (paginate). `ruleSet: null` = manual collection: `add-to-collection` or `collectionAddProducts`. Smart collection (has rules such as `TAG EQUALS "New Arrival"`): add the matching tag to the product instead.

## Sales channels

`publications(first: 20) { nodes { id catalog { title } } }` (`Publication.name` is deprecated since API 2026-10 and some connectors refuse it). Titles look like "Channel Catalog 1234 for Online Store"; match the setup channels by the text after "for" (Online Store; "Facebook & Instagram" for Meta). Ids differ per store, always look them up. Publish all products in one mutation:
```graphql
mutation ch($p1: ID!, $p2: ID!, $c1: ID!, $c2: ID!) {
  a: publishablePublish(id: $p1, input: [{publicationId: $c1}, {publicationId: $c2}]) { userErrors { field message } }
  b: publishablePublish(id: $p2, input: [{publicationId: $c1}, {publicationId: $c2}]) { userErrors { field message } }
}
```
Channels take effect once the product is ACTIVE. Verify with `publishedOnPublication(publicationId: ...)`.

## Second language (Translate & Adapt)

1. The language must be enabled in the store (`shopLocales { locale published }`). If not, tell the merchant: `Settings > Languages > Add language`. Do not enable it yourself without asking.
2. Get digests: `translatableResource(resourceId: "<product gid>") { translatableContent { key value digest locale } }`.
3. `translationsRegister(resourceId, translations: [{locale: "ar", key: "title", value: "...", translatableContentDigest: "<digest>"}, {key: "body_html", ...}])`.
4. Arabic copy: natural Modern Standard Arabic or the dialect the merchant chose, never word-for-word machine output; keep sizes and numbers in Western digits unless the store uses Arabic-Indic digits.

## Go live

`update-product` with `status: "ACTIVE"` after verification. Verification query:
```graphql
nodes(ids: [...]) { ... on Product { legacyResourceId title status onlineStoreUrl totalInventory mediaCount { count }
  variants(first: 100) { nodes { title price compareAtPrice sku taxable inventoryPolicy inventoryQuantity inventoryItem { unitCost { amount } } media(first: 1) { nodes { id } } } }
  options { name optionValues { name swatch { color } } } } }
shop { myshopifyDomain }
```
Admin link: `https://admin.shopify.com/store/<myshopifyDomain without .myshopify.com>/products/<legacyResourceId>`.

## Variant mode

1. Match the subfolder to its product (title, SKU, recent products, compare photos). Read `options { id name linkedMetafield { namespace key } optionValues { id name linkedMetafieldValue } }`, variants (`sku price inventoryQuantity`), `category`.
2. Plan: new colour name, SKU = product base + next free variant index (product has `-1`, `-2`: new colour starts at `-3`, size by size), price same as the product unless told otherwise, stock.
3. Reuse or create the swatch entry.
4. Add the colour to the option first (a linked value cannot be created inside the variant call):
   `productOptionUpdate(productId, option: {id: <Color option id>}, optionValuesToAdd: [{linkedMetafieldValue: "<metaobject gid>"}], variantStrategy: LEAVE_AS_IS)`. If the Color option is a plain option, link it first (section above).
5. `productVariantsBulkCreate(productId, media: [{originalSource, mediaContentType: IMAGE, alt}], variants: [{price, taxable, inventoryPolicy, inventoryItem: {sku, tracked: true}, inventoryQuantities: [{locationId, availableQuantity}], optionValues: [{optionId: <Color>, id: <new value id>}, {optionId: <Size>, id: <size value id>}]}])`.
6. When media is READY, append the front photo to each new variant.
7. Stock changes to existing variants: read current levels, then set with `compareQuantity` and `reason: "correction"`.
8. Verify: new variants' sku, price, taxes, stock, image, swatch; product still ACTIVE and on its channels.

## CSV fallback

No write access: build a Shopify product import CSV (legacy column names, which Shopify still accepts) with `python3 scripts/sheet.py import-csv <folder> <product_data.csv> <plan.json> <out.csv>`, where `plan.json` holds the approved titles, descriptions, types, tags and SKU bases. Images need public URLs in the `Image Src` column (put them in `plan.json` `image_urls`); without them, the merchant adds photos in admin after import. `Variant Inventory Qty` only applies to stores with a single location; otherwise set stock in admin or with the inventory CSV. Arabic-only titles get a handle from the subfolder name; pass `"handle"` per product in `plan.json` to choose one. Read the `problems` list from the script and fix the sheet before importing. Import at `Shopify admin > Products > Import`. Swatch linking and channels are then done by hand in admin; list the steps.
