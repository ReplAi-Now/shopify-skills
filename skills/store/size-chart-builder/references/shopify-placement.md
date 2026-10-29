# Putting the chart in the store

Four options. Ask which one at setup (`placement`), confirm per run. Every write follows the same rule: read the current value first and save it (the "before"), show the merchant the exact change list, wait for an explicit yes for THAT list, write, then read back to verify. Approval does not carry to the next batch.

Change list format to show the merchant:

```
Store: <store>.myshopify.com
1. Product "Linen shirt" (gid://shopify/Product/123): append size chart block to description (2 languages, 21 KB)
2. Product "Linen trousers" (gid://shopify/Product/456): set metafield custom.size_chart (multi_line_text_field)
Reply "yes" to apply these 2 changes, or tell me what to change.
```

Save the before values to `replai-size-chart-log-<date>.json` (or print them in chat) so any change can be put back.

## A. Product description HTML

Best when: few products, each with its own chart, no theme work wanted.

Manual steps: Shopify admin > Products > open the product > Description box > click the `<>` (Show HTML) button > paste the snippet at the end > Save. Check the product page on a phone.

Connector steps:

1. Read: `query { product(id: "gid://shopify/Product/123") { id title descriptionHtml } }`
2. If the description already contains `class="replai-size-chart"`, replace that block instead of adding a second one.
3. Write (after yes):

```graphql
mutation SetDescription($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id descriptionHtml }
    userErrors { field message }
  }
}
```
Variables: `{"product": {"id": "gid://shopify/Product/123", "descriptionHtml": "<existing html><div class=\"replai-size-chart\" ...>...</div>"}}`

Older API versions use `productUpdate(input: ProductInput!)`; if the connector reports that `product` is unknown, use `input` with the same fields.

## B. One shared Page

Best when: many products share one chart (for example all women's tops). Link it from product pages.

Manual steps: Online Store > Pages > Add page > title "Size chart" > Content box `<>` (Show HTML) > paste > Visibility: Visible > Save. Then link it: in the theme editor (on a duplicate theme, see Safety) open the product template and add a "Pop-up" or "Collapsible row" block that points to this page (most free Shopify themes have one), or add the page to the footer menu.

Connector steps (after yes):

```graphql
mutation CreateSizePage($page: PageCreateInput!) {
  pageCreate(page: $page) {
    page { id title handle }
    userErrors { code field message }
  }
}
```
Variables: `{"page": {"title": "Size chart", "handle": "size-chart-women-tops", "body": "<div class=\"replai-size-chart\" ...>...</div>", "isPublished": true}}`

Check first that the handle is free: `query { pages(first: 5, query: "handle:size-chart-women-tops") { nodes { id handle } } }`. To change an existing page use `pageUpdate(id:, page: {body:})` and save the old body first.

## C. Product metafield

Best when: each product has its own chart and the theme should place it consistently. The merchant picks the namespace and key (default `custom.size_chart`).

Types:

| Type | Holds | Theme display |
|---|---|---|
| `multi_line_text_field` (default) | the rendered HTML snippet as text | Custom liquid block: `{{ product.metafields.custom.size_chart.value }}` |
| `json` | the table data: `table` from the render output as is (it already holds unit, dir, title, fit_note, display columns and the shown values; `tables.ar` for Arabic) | Custom liquid block: `{% render 'replai-size-chart', chart: product.metafields.custom.size_chart.value %}` with `assets/size-chart-snippet.liquid` saved as `snippets/replai-size-chart.liquid` |
| `rich_text_field` | formatted text only. Shopify rich text has no tables, so use it only for the fit note and how-to-measure text, never the table | Dynamic source on a theme text block |

Manual steps:

1. Settings > Custom data > Products > Add definition. Name "Size chart", namespace and key as chosen (for example `custom.size_chart`), type "Multi-line text" (or JSON). Save.
2. Products > open the product > scroll to Metafields > Size chart > paste the HTML (or JSON) > Save.
3. Theme, on a duplicate (see Safety): Online Store > Themes > the copy > Customize > Products > Default product > Add block > Custom liquid > paste the display line from the table above > Save > Preview > publish only when the merchant says yes.

Connector steps:

Optional definition (once, after yes), so the field shows in admin:

```graphql
mutation DefineSizeChart($definition: MetafieldDefinitionInput!) {
  metafieldDefinitionCreate(definition: $definition) {
    createdDefinition { id namespace key type { name } }
    userErrors { field message code }
  }
}
```
Variables: `{"definition": {"name": "Size chart", "namespace": "custom", "key": "size_chart", "type": "multi_line_text_field", "ownerType": "PRODUCT"}}`

Read the before value: `query { product(id: "gid://shopify/Product/123") { metafield(namespace: "custom", key: "size_chart") { id type value } } }`

Write (after yes, up to 25 metafields per call):

```graphql
mutation SetSizeCharts($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id namespace key ownerType }
    userErrors { field message code }
  }
}
```
Variables: `{"metafields": [{"ownerId": "gid://shopify/Product/123", "namespace": "custom", "key": "size_chart", "type": "multi_line_text_field", "value": "<div class=\"replai-size-chart\" ...>...</div>"}]}`

For `json`, `value` is a JSON string: `"{\"unit\":\"cm\",\"dir\":\"ltr\",\"columns\":[\"Size\",\"Chest (cm)\"],\"rows\":[[\"S\",\"92\"]]}"`. Make column headers human labels, not CSV names. For a bilingual store, store one metafield per language (`size_chart` and `size_chart_ar`) or use Shopify Translate & Adapt for the metafield.

If a definition exists with a different type, the write fails with a type error: use the existing type or ask the merchant.

## D. Size chart app

If the merchant already uses a size chart app, do not write to the store. Give them the CSV (or the HTML) and the exact fields to paste, and tell them to follow the app's import screen. Mention that the app's own styling replaces the snippet's styling.

## Image output

If the merchant wants an image (for Instagram or a marketplace listing), open the HTML in a browser at 1080 px wide and screenshot it, or ask the merchant to do so. Keep Arabic and English as separate images.

**Size limit:** a `multi_line_text_field` metafield holds at most 64 KB. `render` reports `bytes`; if it is above 65,536, do not attempt `metafieldsSet`: use a shared Page, a `json` metafield with the table data, or split the languages into two metafields.
