---
name: true-profit
description: Real profit per product and order after ads, shipping, COD fees, failed deliveries and returns. Use for "true profit", "am I making money" or "which products lose money".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# True profit

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Real profit per product, per order and per channel after every cost, for Shopify stores with many cash-on-delivery orders. Combines Shopify orders (connector or export), product costs (Shopify "Cost per item", a cost sheet, or supplier invoices), Meta, TikTok and Google Ads exports, courier files (shipping, COD fees, RTO charges), payment fees, packaging, discounts and refunds. Shows units, revenue, product cost, allocated ads, shipping, failed-delivery cost, returns, fees, contribution profit, margin and break-even ROAS per product, lists bestsellers that lose money with the price or ad fix, and converts ad spend in another currency at a rate the merchant confirms. Use when the merchant says "true profit", "real profit", "am I making money", "profit per product", "which products lose money", "break-even ROAS", "contribution margin", "unit economics", "الربح الحقيقي", "صافي الربح", or uploads ad exports with a Shopify export.

Answers "which products, orders and channels actually make money once every cost is paid", including the cost of COD orders that come back. Works from a Shopify orders export plus a cost sheet; ads and courier files make it complete.

Files in this skill:
Paths starting with `scripts/` or `assets/` are inside this skill's folder; `replai-setup/` and the merchant's files are in the working folder.
- `scripts/profit.py` does all the math and prints JSON. It uses `scripts/orders.py` (export parsing, courier join, delivered/failed rules) and `scripts/tabular.py` (CSV/XLSX reader).
- `scripts/render_dashboard.py` turns the JSON into a one-file HTML dashboard with scenario inputs.
- `assets/setup.example.json`: every setup key with its default.
- `assets/product-costs-template.csv`: the standard cost sheet (fill it from supplier invoices).
- `assets/ad-map-template.csv`: campaign, ad set or ad name to product mapping.
- [references/data-sources.md](references/data-sources.md): exact export paths and columns for Shopify, products, Meta, TikTok, Google Ads, couriers, invoices.
- [references/method.md](references/method.md): every definition and formula, for doing it by hand without code.

## Setup

1. Look for saved setup: `replai-setup/true-profit.json` in the working folder, else a pasted setup card (fenced JSON with `"skill": "true-profit"`). If found, say in one line "Using your saved profit setup (<currency>, costs from <source>, ads <method>)" and go to **Run**. If the merchant says "change my setup" or "redo setup", ask again with current answers as defaults.
2. Otherwise send ONE message with these questions. The merchant can reply "defaults" or answer only some numbers.

```
To set up true profit, answer any of these (or reply "defaults"):
1. Store currency? [read from Shopify, else EGP]
2. Where do product costs live? [Shopify "Cost per item"]
   (Shopify / a sheet I'll send / supplier invoices I'll send)
3. Do your prices include VAT? [no]
4. Card / wallet payment fee? [0% + 0 per order] (e.g. 2.9% + 3)
5. Courier COD fee? [0% of collected + 0] (e.g. 1% of cash collected)
6. If no courier file: shipping cost per order [ask], return cost per failed order [ask]
7. Packaging per order? [0]
8. Fixed monthly costs (rent, salaries, apps), optional? [skip]
9. Ad spend per product: map campaigns to products, or split by revenue? [map, I propose and you confirm]
10. Ad account currency, if not the store currency, and the rate? [same as store]
11. Output? [dashboard] (dashboard / spreadsheet / report)
```

3. Map answers to the keys in `assets/setup.example.json`: `currency`, `cost_source`, `prices_include_tax`, `gateway_fee_pct`, `gateway_fee_fixed`, `cod_fee_pct`, `cod_fee_fixed`, `shipping_cost_per_order`, `return_shipping_per_order`, `packaging_cost_per_order`, `fixed_monthly_costs`, `ad_allocation` (`mapping` or `revenue_share`), `ad_currency` (e.g. `{"meta": "USD"}`), `fx_rates` (e.g. `{"USD": 50.5}` = store currency per 1 USD), `output`. The failed-order words (`failed_tags`, courier statuses) have defaults; add the merchant's own.
4. Save it. With files: write `replai-setup/true-profit.json` in the shape of `assets/setup.example.json`. Without files: print the setup card as a fenced JSON block and tell the merchant to paste it at the start of the next chat.
5. Smoke test: parse the first rows of the orders export (`python3 scripts/orders.py <file>`) or read the store name and latest order from the connector; if costs come from Shopify, read the cost of one variant. Report in one line.

## Run

1. **Load setup**. Ask per run only for the date range (default: last full month) and which files the merchant has for it. Every file must cover the same dates.
2. **Orders**: connector query or `Shopify admin > Orders > filter dates > Export > CSV for Excel` (see [references/data-sources.md](references/data-sources.md)).
3. **Product costs** (one of):
   - Shopify: `Shopify admin > Products > Export > All products > CSV for Excel` (has `Variant SKU` and `Cost per item`), or the connector (`inventoryItem.unitCost` per variant).
   - A sheet from the merchant: map columns to sku, product, unit cost, currency.
   - Supplier invoices (PDF, photo or sheet): read each line and fill `assets/product-costs-template.csv` (one row per SKU: unit cost = line total / quantity, plus the share of freight and customs if the merchant wants landed cost). Show the extracted table and get a yes before using it. Never guess a cost you cannot read.
   Products with no cost are reported as "cost missing", never assumed free.
4. **Ads** (optional): export from Meta Ads Manager, TikTok Ads Manager and Google Ads at campaign, ad set or ad level with spend, purchases and date (exact paths in data-sources.md).
   - If setup says `mapping`: propose `ad_product_map.csv` (shape of `assets/ad-map-template.csv`) by reading campaign, ad set and ad names against product titles. Show it as a short table and get the merchant's yes or corrections before running. Unmatched or `SHARED` spend is split by net revenue.
   - If the spend currency differs from the store currency and setup has no rate, ask: "Your Meta spend is in USD. How many EGP per 1 USD should I use for this period?" Save it in `fx_rates` and state it in the output.
5. **Courier files** (optional): any courier, columns mapped by meaning (order number or tracking, status, shipping fee, return fee, COD fee). Confirm unsure columns in one line.
6. **Compute**:
   ```
   python3 scripts/profit.py --orders orders.csv --setup replai-setup/true-profit.json \
     --costs costs.csv [--ads meta=meta.csv --ads tiktok=tiktok.csv --ads google=google.csv] \
     [--ad-map ad_product_map.csv] [--courier courier.csv::CourierName] [--returns returns.csv] \
     [--out-dir replai-reports/profit-<month>/] > profit.json
   ```
   Exit code 2 with `need_fx_rate` (the JSON lands in profit.json) means ask the rate question above, save it, rerun. No code execution: follow [references/method.md](references/method.md) by hand.
   `--returns`: units sent back after delivery without a refund (Try & Buy, restock without refund) are invisible in the export; build this file from the connector (data-sources.md) when the store does Try & Buy or exchanges.
7. **Check before presenting**: `profit_known` false means no product has a cost: say profit is unknown and ask for costs, never show a profit number. `warnings` (missing costs, missing shipping cost, ad dates not matching order dates, open orders left out of profit); `ads_not_attached_to_orders` (spend mapped to products that sold nothing in the period, say so); a product with a very high margin usually means a wrong cost, ask before celebrating.

### What to show (all outputs)

1. **The answer first**: contribution profit and margin for the period, after fixed costs if given. Explain once: "Contribution profit = what is left from sales after product cost, shipping, fees, packaging, failed deliveries and ads, before rent and salaries."
2. **Bestsellers that lose money** (`bestsellers_losing_money`): each with units, loss, and the fix in numbers: `problem: ads` means it is profitable before ads, so cut or fix the ads (`ad_cut_to_break_even`); `problem: price_or_cost` means it loses money even before ads, so raise the price (`price_increase_per_unit_to_break_even` per unit), cut the cost, or stop pushing it.
3. **Profit per product table**: units, net revenue, product cost, ads, shipping + RTO, fees, contribution, margin, break-even ROAS. Explain break-even ROAS once: "the revenue every 1 of ad spend must bring back for this product to make zero. Ads Manager counts orders before delivery, so compare its ROAS with the platform break-even ROAS column, which includes orders that come back."
4. **Per order**: average revenue and contribution per delivered order, cost of one failed delivery, how many delivered orders lost money, the worst orders.
5. **Per channel**: sales channel (Shopify `Source`) profit, and per ad platform: spend, platform purchases, estimated cost per delivered order vs break-even cost per order (label estimates).
6. **3-5 actions** that follow from the numbers (price, ad cut, stop a product, fix a cost, reduce RTO with the cod-rto-analysis skill). Each states the number it rests on.
7. **Assumptions** (verbatim from the JSON, including the ad allocation method and any exchange rate) and data gaps.

### Output formats

- **dashboard** (default): `python3 scripts/render_dashboard.py profit.json replai-reports/true-profit.html`. One HTML file, works offline and at 390px. Scenario inputs: price change %, product cost change %, shipping and RTO change %, ad spend change %, fixed monthly costs. Profit, margins, break-even ROAS and the losers list update live.
- **spreadsheet**: `--out-dir` writes `products.csv`, `orders.csv`, `channels.csv`, `ad_platforms.csv`. Add a `summary.csv` with totals if asked.
- **report**: Markdown (or DOCX/PDF if the agent can make them; in chat-only apps, write it in the chat). Order: answer, losers and fixes, product table (top 15 by revenue plus every loser), channels, actions, assumptions. Under two pages.

Footer on every report and dashboard: `Made with the free ReplAi skills pack`.

## Safety

- Read-only. This skill never changes prices, costs, products, ads, budgets or orders.
- Writing costs back to Shopify ("Cost per item"), changing a price or pausing a campaign needs the exact list of changes shown first and an explicit yes for that list. Approval does not carry to later batches.
- Cost and margin data is commercially sensitive: keep it in the merchant's folder or chat, never send it anywhere, never put it in URLs.
- Never invent a cost, fee or exchange rate. Missing costs are reported, missing rates are asked for, estimates are labelled.
- Never delete data. Never touch payments, payouts or credentials.
