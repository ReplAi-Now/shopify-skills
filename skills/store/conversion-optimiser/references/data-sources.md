# Data sources

The audit works from the public storefront alone. The connector or exports only make it faster and more exact.

## Public storefront (always available)

| What | Where |
|---|---|
| Pages to audit | home `/`, collections `/collections/<handle>`, products `/products/<handle>`, cart `/cart` |
| Product images count, alt text, variants, price | `/products/<handle>.js` (public JSON) |
| Best sellers when nothing else is available | `/collections/all?sort_by=best-selling` (first 3 products) |
| All URLs | `/sitemap.xml` |
| Robots rules | `/robots.txt` |
| Arabic version | `/ar` or the language switcher |

## No browser and no fetch tool (chat apps with uploads only)

Many chat sandboxes cannot open web pages. Then the storefront is NOT available to you: say so in one line and ask the merchant for, in one message:
1. Phone screenshots (full page, scrolled): home, one collection, the 3 top product pages, cart, first checkout step, payment step, and the Arabic version of one product page if bilingual.
2. The products export (columns below) and, if they have it, the Sales by product export.
3. Two screenshots from `https://pagespeed.web.dev/` for the home page (Mobile and Desktop tabs).
Judge each check from these. Mark checks that need a live page (broken links E4, search N2, sideways scroll M1 when the screenshot cannot show it, structured data E6, robots E7) `unknown` with "no page access" as the reason. Write the speed checks S1-S5 by hand from the screenshot numbers using the thresholds in `checklist.md`.

## Shopify connector (read-only queries for the audit)

- Top products: orders from the last 90 days grouped by product, or `products(first: 10, sortKey: ...)` if the connector offers sales ranking; else use best-selling collection order.
- Live theme ID: `themes(first: 20, roles: [MAIN])`.
- Image alt text and SEO fields: see `content-edits.md`.

## Exports (if no connector)

Products export: `Shopify admin > Products > Export > All products > CSV for Excel`. Columns used:

| Column | Used for |
|---|---|
| `Handle` | building product URLs |
| `Title` | report labels |
| `Body (HTML)` | description checks (P10) |
| `Image Src`, `Image Position` | photo count per product (P1) |
| `Image Alt Text` | alt text check (E3) |
| `SEO Title`, `SEO Description` | E1, E2 |
| `Variant Inventory Qty` | honest stock messages (P12) |

Read it with `python3 scripts/tabular.py products_export.csv` (column names are normalised, for example `image_alt_text`).

Top products: `Shopify admin > Analytics > Reports > Sales by product > Export`, columns `Product title` and `Net sales` (or `Total sales`).

Checkout: if the browser tool cannot open checkout, ask the merchant for two phone screenshots: the first checkout step and the payment step.
