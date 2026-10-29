---
name: demand-planner
description: Forecast demand per variant and say what to reorder, when and how much, keeping cash in stock low. Use for "what should I reorder", "when will I run out" or "Ramadan stock".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Demand planner

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Predicts demand per variant (SKU) from Shopify orders and current stock, then says what to reorder, when, and how much, with safety stock, reorder points, stockout dates and the cash each order needs. Handles supplier lead times, MOQ and case packs, stockout days, new products, and Ramadan, Eid and White Friday peaks. Use when a merchant asks "what should I reorder", "when will I run out", "how much stock to buy for Ramadan or White Friday", "reorder list", "safety stock", "reorder point", "how much cash do I need for stock", "plan my purchase order", "inventory forecast", or "demand planning".

Tells the merchant, per variant: order now, this week, or later; how many units; the cash needed; and when it runs out. Goal: fewest stockouts for the least cash tied in stock.

All formulas are in [references/method.md](references/method.md). Data paths and exact columns are in [references/data-sources.md](references/data-sources.md).

## Setup

1. Look for saved setup: `replai-setup/demand-planner.json` in the working folder, else a pasted setup card (a fenced JSON block with `"skill": "demand-planner"`). If found, say "Using your saved demand planner setup (95% service level, 14 day lead time)" with the real values, and continue. If the merchant says "change my setup" or "redo setup", ask again with current answers pre-filled.
2. If not found, send ONE message with these numbered questions (defaults in brackets). The merchant may reply "defaults" or answer only some numbers.
   1. Store currency? [EGP]
   2. Usual supplier lead time, from placing an order to stock being sellable, in days? [14]
   3. How many days early or late do deliveries usually arrive (variability)? [0, always on time]
   4. How often do you check stock and place orders (review period, days)? [7, weekly]
   5. Service level target: how often you want to have stock when a customer orders? [95%] (higher = fewer stockouts but more cash tied in stock)
   6. Minimum order quantity (MOQ) and case pack for most products? [no MOQ, packs of 1]
   7. Do you have a sheet with lead time, MOQ, case pack or cost per supplier or product? [no] (template: `assets/suppliers.example.csv`)
   8. Unit cost source: Shopify "Cost per item", or a cost sheet? [Shopify Cost per item]
   9. Default output: dashboard (interactive HTML), spreadsheet (CSV), or short report? [dashboard]
   10. Timezone? [Africa/Cairo]
3. Save it. With a file system, write `replai-setup/demand-planner.json` using the shape of `assets/setup.example.json`. Without one, print the setup card as a fenced JSON block and tell the merchant to paste it at the start of their next chat.
4. Smoke test: read the first rows of the orders and inventory data (connector or files) and report in one line, for example "Read 1,240 order lines from 2026-07-01 to 2026-10-28 and 186 variants in stock."

Advanced keys (keep defaults unless asked): `history_days` 90, `half_life_days` 30 (a sale 30 days ago weighs half of one today), `min_history_days` 28 (younger SKUs count as new when the export proves it; a shorter export is low confidence), `seasonality` "auto" or "off", `include_drafts` false (draft and archived products are left out of the plan; set true to plan them too).

## Get the data

Follow the order in [references/data-sources.md](references/data-sources.md):
1. Shopify connector if connected (read-only queries, paginate, save as CSV with export headers).
2. Otherwise ask for exports:
   - `Shopify admin > Orders > Export > All orders > CSV for Excel` (at least 90 days; 13 months or more if they want Ramadan, Eid or White Friday measured from last year)
   - `Shopify admin > Products > Inventory > Export > All products` (all locations)
   - `Shopify admin > Products > Export > All products > CSV for Excel` (for Cost per item, Type, Vendor)
   Both the 2026 export headers (`URL handle`, `SKU`, `Price`, `Inventory quantity`, `Canceled at`) and the older ones (`Handle`, `Variant SKU`, `Variant Price`, `Variant Inventory Qty`, `Cancelled at`) work.
3. Optional: the suppliers sheet and a stock history file (date, sku, end-of-day stock). Ask once; do not block on them.

Building `suppliers.csv` from the merchant's answers (when they give costs or lead times in chat instead of a sheet): one row per SKU, or one row per supplier using the Shopify `Vendor` name. Columns: `sku`, `vendor`, `lead_time_days`, `lead_time_sd_days`, `moq`, `case_pack`, `unit_cost`. Fill `sku` OR `vendor` (a SKU row beats a vendor row, which beats the setup defaults) and leave any column blank that the merchant did not give, so the default or Shopify `Cost per item` is used. "Delta Mills delivers in 10 days, sometimes 2 days late, minimum 24 pieces in packs of 6" becomes:

```
sku,vendor,lead_time_days,lead_time_sd_days,moq,case_pack,unit_cost
,Delta Mills,10,2,24,6,
```

"The linen shirt LS-M costs me 180 now" adds `LS-M,,,,,,180`. Show the merchant the rows in one line before running.

Per run, ask only: anything coming up that is not in the calendar (a launch, a sale, a campaign) with an expected uplift %, and estimates for new products if the script asks for them.

## Run

With code execution:

```
python3 scripts/demand_plan.py --orders orders.csv --inventory inventory.csv --products products.csv \
  --setup replai-setup/demand-planner.json [--suppliers suppliers.csv] [--stock-history stock.csv] \
  [--event "Summer sale,2026-07-01,2026-07-07,30"] [--estimate SKU123=1.5] > plan.json
```

- Setup from a pasted setup card (chat apps): write the card's JSON to a file in the sandbox and pass that path to `--setup`.
- The script prints JSON (`items`, `reorder_list`, `at_risk`, `cash`, `service_level_tradeoff`, `seasonality`, `data_notes`, `needs_estimate`, `unmatched_order_skus`). On bad input it prints `{"error": ...}` naming the missing column: tell the merchant exactly which export or column to fix.
- If `seasonality.needs_merchant_uplift` lists an event (for example White Friday with less than a year of history), ask the merchant for an uplift % for it and rerun with `--event`.
- Items without sales (`needs_estimate`, often hundreds) are never asked about one by one. Use `estimate_groups_to_ask` (the 10 biggest groups, by product type or by product when the type is blank): ask ONE message, one line per group, "about how many units per day (or week, divided by 7) does one variant of X sell?". Rerun with `--estimate "TYPE:Dresses=0.3"` or `--estimate "PRODUCT:<handle>=0.2"` (the `estimate_key` of the group; it applies to every variant in it that has no sales). Single SKUs still work: `--estimate SKU123=1.5`. Say how many variants are left without an estimate (`needs_estimate_count`) and that they are not reordered.
- `new_products` lists SKUs planned from their own sales since launch ("new product, estimate", capped at their category average). Offer the merchant to give their own estimate instead.
- `low_confidence: true` means the export covers less than 28 days: show the plan, say clearly it is low confidence, and ask for a longer export.
- `moq_warnings` lists items where the MOQ or case pack forces more than 180 days of stock: mention each one.
- `oversold` lists variants with negative stock (units already sold but not in stock). They are planned from 0 stock and the owed units are added to the order. Show the top ones and tell the merchant to check their open orders: an old negative count may only be out of date.
- Missing costs: a cash figure is `null` when no item in it has a unit cost (never say "EGP 0"). When `cash.<bucket>_items_with_cost` is below `cash.<bucket>_items`, the total covers only those items: say "EGP X for N of M items with a cost". If costs are missing, ask the merchant for them: Shopify `Cost per item` (Products > open a product > variant > Cost per item, then export again) or a sheet with `sku,unit_cost` passed as `--suppliers`.

Without code execution, follow [references/method.md](references/method.md) step by step for the top sellers and every item close to running out, and say how many SKUs you covered.

## Present the results

Every output starts with the answer, then the evidence. Money in the store currency, rounded to whole units. Dates in the merchant's timezone. Explain each metric the first time it appears (reorder point, safety stock, service level, lead time).

Lead with:
1. Order now: N items, total cash X. The list (item, quantity, cash, runs out on).
2. This week: N items, cash Y.
3. At risk: items that run out before a new order can arrive, with the date and the lost sales estimate (labelled as an estimate).
4. Cash: in stock today, needed now, needed this week.
5. The trade-off, in plain words, from `service_level_tradeoff`: "At 95% you keep X as safety stock. At 99% it is Y: more cash on shelves, fewer stockouts. At 90% it is Z."
6. Data notes: history length (and low confidence if under 28 days), whether stock history was used (if not: demand for items that sold out is understated), events included and where each uplift came from (an event running today is not uplifted again), refunded orders left out, new products planned from their own sales, MOQ warnings, missing costs, unmatched SKUs.

By output type:
- **dashboard**: `python3 scripts/build_dashboard.py --plan plan.json --out demand-plan.html`. One offline HTML file, works at 390px wide and stays light for big catalogs: it lists the order now, this week, at risk and oversold rows, summarises the "later" rows, and writes every variant to `demand-plan-all-items.csv` next to it (send both files). Inputs for service level, lead time, lead time variability and review period recompute the reorder list and cash in the browser. Tell the merchant to open it and try 90% vs 99%.
- **spreadsheet**: add `--csv-out demand-plan.csv` to the run (one row per variant, sorted by urgency). If the agent can write XLSX, make tabs: Reorder now, This week, At risk, All variants, Cash summary.
- **report**: Markdown (or PDF/DOCX if available) led by the 3-5 decisions above, then a table of order-now items, then notes. In chat-only apps, write it in the chat.

Reports and dashboards end with the footer `Made with the free ReplAi skills pack`.

## Rules of judgement

- Never invent numbers. Missing cost, missing stock, or no history: say what is missing and what the result would need.
- Label every estimate: new product rates, merchant uplifts, lost sales.
- A product that never sold is not a reorder candidate unless the merchant gives an estimate; it may be dead stock (point them to the dead-stock-clearance skill).
- If one SKU dominates the cash needed, say so and suggest splitting the order if the supplier allows.
- If the review period is longer than the lead time, mention that checking more often would cut the cash needed.

## Safety

- Read-only. This skill never changes the store, never creates purchase orders, transfers or inventory adjustments, and never contacts suppliers.
- If the merchant asks to act on the plan (for example draft a purchase order or adjust inventory), show the exact list of changes and wait for an explicit yes for that list. Approval does not carry to later batches.
- Never delete data. Never touch payments, payouts or credentials.
- Data stays on the merchant's machine or in their connected tools. No personal data in URLs.
