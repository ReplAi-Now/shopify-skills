---
name: shopify-catalog-upload
description: Upload finished product photos to Shopify as complete listings with variants, SKUs, swatches and copy, or add new colours. Use for "upload these products" or "put these on Shopify".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Shopify catalog upload

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Uploads finished product photos from a local folder to a Shopify store as complete listings. One product per subfolder, one Color variant per colour crossed with sizes, photos linked to their colour, titles and descriptions written from the photos (English, Arabic or both), prices, sizes and stock from the merchant's message or spreadsheet, SKUs numbered from the store's own pattern, colour swatches linked so they show on collection pages, collections suggested, products verified before going live. Also adds new colours to products already in the store (variant mode). Store rules like taxes, continue selling, sales channels and SKU format are set once at first run. Use when the merchant says "upload these products", "put these on Shopify", "create the listings", "add the new products to the store", "add this colour to the existing product", or after a catalog-photoshoot run when they want the photos in the store.

Takes a folder of finished catalog photos (normally the output of the **catalog-photoshoot** skill: one subfolder per product, files named `<colour>-<view>.png`, plus `report.csv`) and creates complete Shopify listings. Talk to the merchant in their language; store copy uses the language chosen at setup.

Everything here creates real, customer-visible records. So: confirm the store, show the full plan and wait for an OK before the first write. That OK covers the plan as shown, nothing more. Each product is built as a DRAFT and switched to ACTIVE only after it passes verification, so customers never see a half-built listing.

## Requirements

A Shopify connector with write access (the official Shopify connector or the Shopify AI Toolkit / Admin API through Shopify CLI). Needed tools: shop info, product create/update, GraphQL query and mutation, collections, inventory. If the agent has no Shopify write access, stop and explain how to connect one; offer to prepare a Shopify product import CSV instead (`Products > Import` in Shopify admin; build it with `python3 scripts/sheet.py import-csv`, see [references/shopify-recipes.md](references/shopify-recipes.md#csv-fallback)).

## Setup

1. Look for `replai-setup/shopify-catalog-upload.json` in the working folder, or a pasted setup card (`"skill": "shopify-catalog-upload"`). If found, say in one line which store and rules you are using and skip to "Run an upload". "Change my setup" reruns the interview with current answers pre-filled.
2. Read the connected store (`get-shop-info` or `shop { name myshopifyDomain currencyCode }`) and the 50 most recent products with their SKUs, options, vendor and product type. From these, detect the store's SKU pattern, size naming, vendor, title style and whether Color options are already linked to swatches. Use what you found as the defaults below.
3. Ask in ONE message, numbered, defaults in brackets:
   1. Is `<store name> (<domain>, <currency>)` the right store? [yes]
   2. SKU format [detected, e.g. `ABC-<number>-<n>`; or `<PREFIX>-<number>-<n>` if none found]. Variants numbered sizes within colour.
   3. Charge taxes on these products [off] (on / off).
   4. Keep selling when out of stock [off] (off: shows sold out at 0, safest; on: never shows sold out, for made-to-order or pre-order stock). If on and no stock numbers were given, warn in the plan that these products can be ordered without limit.
   5. Sales channels to publish to [Online Store + Facebook & Instagram if installed] (list the store's channels).
   6. Copy language [English] (English / Arabic / both: second language added through Shopify Translate & Adapt translations).
   7. Title style [short descriptive, no colour when several colours, e.g. "Belted Linen Midi Dress"].
   8. Brand voice for descriptions [clear and warm, 2-3 sentences plus a short bullet list of visible details].
   9. Default vendor [store name].
   10. Go live after verification, or leave as drafts for you to review [go live].
   11. Inventory location [the store's primary location].
4. Save to `replai-setup/shopify-catalog-upload.json` (shape in [assets/setup.example.json](assets/setup.example.json)); without a file system print the setup card. Store the shop domain so a later run on a different connected store is caught.
5. Smoke test: list the sales channels (`publications`) and the store's colour swatch entries (`metaobjects(type: "shopify--color-pattern")`) and report counts in one line.

Never carry a store confirmation over from a previous session: at the start of every run, re-read the connected store and say its name. If it does not match the saved domain, stop and ask.

## Run an upload

### 1. Read the folder
- Each direct subfolder = one product. Images `.png .jpg .jpeg .webp`.
- File names `<colour>-<view>[-n].<ext>` give the colours and order (front, back, side, extras). If names do not follow that, look at the photos and propose a grouping.
- If `report.csv` from catalog-photoshoot is present, use it for views. Always look at the photos yourself to write copy.
- Skip subfolders already `created` in `upload_report.csv` (resume).
- Skip catalog-photoshoot rows marked `failed` in `report.csv`, and list images marked `minor` in the plan so the merchant knows what goes live.
- Run `python3 scripts/sheet.py scan <folder>` for a JSON summary of products, colours and photos.

### 2. Get prices, sizes and stock
Never invent them. Accept text in chat ("dress-a: 1450, S-M-L, 5 each") or a sheet. To give the merchant a sheet: `python3 scripts/sheet.py template <folder> <folder>/product_data.csv` (columns `subfolder, colour, sizes, price, compare_at_price, stock_per_size, cost_per_item, notes`). To read one back: `python3 scripts/sheet.py read <file.csv|xlsx>`. Sizes: a hyphen between letters is a list (`S-M-L`), between numbers it is one size (`38-40`, `2-3Y`); confirm in the plan when unsure. Stock: one number for every size (`5`), one per size in order (`3,5,2`), or by name (`S:3, M:5`). Warn Excel users that a size typed as `2-3` turns into a date unless the cell is text.
Needed per product: sizes (or "One Size") and price. Optional: compare-at price, stock per variant, cost per item (helps profit reports), vendor. Ask once for everything missing. No stock given: track inventory at 0 and say so.

### 3. Prepare the plan (one message, before any write)
For each product, from the photos and setup:
- **Title**, **description** (`descriptionHtml`: intro + `<ul>` of visible details: fabric look, neckline, sleeves, closure, length, fit, trims; never claim composition, care or measurements you cannot see), **product type**, **tags** (type, style, colours).
- **Options**: `Color` then `Size`. Colour names in Title Case from file names (`black-beige` becomes "Black/Beige"). One-size products keep Size = "One Size". Max 3 options and the store's variant limit.
- **SKUs** from the setup format, next free numbers in the store (method in [references/shopify-recipes.md](references/shopify-recipes.md#skus)). Never leave SKUs empty.
- **Category** (taxonomy, needed for swatches), found with a taxonomy search; pick the adult apparel or correct product branch.
- **Colour swatches**: reuse existing `shopify--color-pattern` entries by name; list the ones that will be created.
- **Collections**: suggest existing ones. Smart collections (with rules) get the matching tag instead of a direct add. New collections only if the merchant agrees.
- **Second language** copy if setup says both.
Show it as one compact table (subfolder, title, type, colours x sizes = variants, price, SKU base, collections) plus the descriptions. Wait for OK or edits, apply edits, then run all products without asking again except on errors.

### 4. Build each product (one at a time)
Follow [references/shopify-recipes.md](references/shopify-recipes.md) for the exact calls:
1. Photos: public URLs if they exist (route A), otherwise staged upload of local files (route B).
2. Create the product as DRAFT with all variants, prices, SKUs, inventory tracking.
3. Attach photos ordered colour by colour (front first), alt text `<Title> - <Colour> - front|back`. Wait until media is READY.
4. Link each variant to its colour's front photo.
5. Bulk update variants: taxes and continue-selling per setup, SKUs re-sent.
6. Set category and link the Color option to the colour-pattern metafield (create missing swatch entries first).
7. Stock per variant at the setup location.
8. Collections; sales channels per setup.
9. Second-language translations if set (`translationsRegister`).
10. **Verify** (variant count, prices, SKUs, every variant has an image, media count, stock, swatches non-null, channels). Fix before moving on.
11. Go live (ACTIVE) if setup says so and verification passed. Otherwise leave DRAFT and log why.
12. One-line progress update ("2/6 Linen Midi Dress: live, 2 colours x 3 sizes, 4 photos").

Batch similar mutations across products with GraphQL aliases so the merchant approves fewer calls. If a step fails mid-product, never create a duplicate on retry: check `upload_report.csv` and the product id, continue from the failed step.

### 5. Variant mode: new colours of existing products
When the photos are new colours of products already in the store, never create a duplicate. Match each subfolder to its product (title, SKU, photos), confirm the match in the plan, then add the colour value to the linked Color option first and create the new variants with their photos in one call. Exact steps in [references/shopify-recipes.md](references/shopify-recipes.md#variant-mode).

### 6. Final report
One verification query over everything created, then tell the merchant: products (title, storefront link, admin link `https://admin.shopify.com/store/<handle>/products/<id>`), variants and photos each, collections, channels, and anything skipped, failed or left as draft with the reason. End with the line `Made with the free ReplAi skills pack`.

### 7. Log
Append to `<folder>/upload_report.csv`: `subfolder, title, sku, product_id, admin_url, variants, photos, collections, status` (`created` or `failed: <reason>`).

## Safety

- Confirm the store at the start of every run. Never write to a store the merchant has not confirmed in this session.
- No write before the merchant approves the full plan. Changes outside the plan (renaming existing products, changing prices of existing variants, deleting anything) need their own explicit yes.
- Never delete products, variants, media or collections. Mistakes are fixed by updating, or by setting the product back to DRAFT and telling the merchant.
- Products stay DRAFT until verified.
- Prices, stock and sizes only from the merchant. Descriptions only claim what the photos show.
- Do not publish to channels beyond the setup list.
