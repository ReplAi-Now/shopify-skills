---
name: dead-stock-clearance
description: Find slow and dead stock, the cash stuck in it, and a clearance plan you approve before anything changes. Use for "dead stock", "slow movers" or "what should I put on sale".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Dead stock clearance

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Finds slow-moving and dead stock in a Shopify store, shows the cash stuck in it, and plans how to clear it per variant (markdown with a safe price, bundle with a product customers already buy together, free gift above an order threshold, clearance collection, or liquidation), with cash recovered and margin impact for each. Produces a change list (price, compare-at price, tags, collection) and a rollback file; nothing changes in the store without the merchant's yes to that exact list. Use when a merchant asks "what stock is not selling", "dead stock", "slow movers", "old inventory", "how much cash is stuck in stock", "what should I put on sale", "clearance sale plan", "markdown plan", "how to get rid of old stock", or "inventory ageing".

Finds what is not selling, how much cash is stuck in it, and the best way to turn it back into cash without selling below the merchant's floor. Read-only until the merchant approves an exact change list.

Formulas and rules: [references/method.md](references/method.md). Data paths and columns: [references/data-sources.md](references/data-sources.md). Store changes and rollback: [references/shopify-apply.md](references/shopify-apply.md).

## Setup

1. Look for saved setup: `replai-setup/dead-stock-clearance.json` in the working folder, else a pasted setup card (a fenced JSON block with `"skill": "dead-stock-clearance"`). If found, say in one line which setup you are using (for example "Using your setup: slow after 60 days, dead after 120, floor cost + 10%") and continue. If the merchant says "change my setup" or "redo setup", ask again with current answers pre-filled.
2. If not found, send ONE message with these numbered questions (defaults in brackets). The merchant may reply "defaults" or answer only some numbers.
   1. Store currency? [EGP]
   2. An item is SLOW after how many days without a sale? [60]
   3. An item is DEAD after how many days without a sale? [120]
   4. Lowest price you accept on a markdown, as margin above unit cost? [10%, never below cost + 10%]
   5. May the clearance sell below cost for truly dead items? [no]
   6. Markdown steps? [10%, 20%, 30%]
   7. Round new prices to? [5] (for example 179 becomes 175)
   8. Tactics you allow: markdown, bundle, free gift, clearance collection, liquidate/donate? [all]
   9. Tag and collection names for clearance items? [tag "clearance", collection "Clearance"]
   10. Default output: spreadsheet (CSV change list), dashboard (interactive HTML), or short report? [spreadsheet]
   11. Timezone? [Africa/Cairo]
3. Save it. With a file system, write `replai-setup/dead-stock-clearance.json` using the shape of `assets/setup.example.json`. Without one, print the setup card as a fenced JSON block and tell the merchant to paste it at the start of their next chat.
4. Smoke test: read the first rows of the orders and products data and report in one line, for example "Read 3,410 order lines from 2026-01-02 to 2026-10-28 and 412 variants with stock."

Advanced keys (defaults are fine): `slow_cover_days` 180, `slow_sell_through_pct` 10, `cover_window_days` 30, `sell_through_window_days` 90, `min_age_days` 30, `bundle_discount_pct` 15, `min_co_orders` 2, `gift_threshold_multiplier` 1.3, `gift_max_cost_pct_of_aov` 15, `liquidation_recovery_pct` 30, `min_evidence_days` 60 (with less order history, items that look slow from a few sales are "too early to judge"), and the assumed sell-through per tactic used for expected cash: `assumed_sell_through_markdown_pct` 60, `_bundle_pct` 40, `_gift_pct` 50, `_clearance_collection_pct` 25, `_liquidate_pct` 100 (estimates; tell the merchant they can change them).

## Get the data

Follow [references/data-sources.md](references/data-sources.md):
1. Shopify connector if connected (read-only, paginate, save as CSV with export headers).
2. Otherwise ask for:
   - `Shopify admin > Orders > Export > All orders > CSV for Excel`, covering at least 240 days (twice the dead threshold) so "never sold" means something
   - `Shopify admin > Products > Export > All products > CSV for Excel` (price, compare-at, Cost per item, tags, stock)
   - optional: `Shopify admin > Products > Inventory > Export` for multi-location stock, and a `sku, first_stocked` sheet (`assets/first-stocked.example.csv`)
   Both the 2026 export headers (`URL handle`, `SKU`, `Price`, `Inventory quantity`, `Canceled at`) and the older ones (`Handle`, `Variant SKU`, `Variant Price`, `Variant Inventory Qty`, `Cancelled at`) work.

## Run

With code execution:

```
python3 scripts/dead_stock.py --orders orders.csv --products products.csv \
  --setup replai-setup/dead-stock-clearance.json [--inventory inventory.csv] \
  [--first-stocked first_stocked.csv] --out-dir clearance > clearance.json
```

- Setup from a pasted setup card (chat apps): write the card's JSON to a file in the sandbox and pass that path to `--setup`.
- Prints JSON: `summary` (cash stuck by category, plan cash recovered and profit, per tactic, average order value, gift threshold), `items` (each with category, reason, metrics, `options` with numbers per tactic, `recommended`), `changes`, `rollback`, `data_notes`.
- Writes `clearance/dead-stock-classification.csv`, `clearance/dead-stock-changes.csv`, `clearance/dead-stock-rollback.csv`.
- On bad input it prints `{"error": ...}` naming the missing column; tell the merchant exactly which export or column to fix.
- Missing costs: `cash_stuck` (per item and in `summary`) is `null` when unknown, never 0. If `summary.cash_stuck_items` shows fewer items with a cost than items, say "X for N of M items with a cost". With missing costs, ask the merchant for them: Shopify `Cost per item` (Products > open a product > variant > Cost per item, then export again) or a cost sheet. Without a cost no markdown can be checked against the floor.
- `too_early` items: the order history is shorter than `min_evidence_days`, so a few sales cannot prove an item is slow. Say how many, and ask for a longer export instead of marking them down.
- `summary.oversold` lists variants with negative stock: they count as 0 units; tell the merchant to check their open orders.

Without code execution, follow [references/method.md](references/method.md) for every variant with stock, starting with the biggest cash stuck, and say how many you covered.

## Present the results

Start with the answer, then the evidence. Money in the store currency. Explain each metric the first time it appears (days of cover, sell-through, cash stuck, margin floor).

Lead with:
1. Cash stuck: X in dead stock, Y in slow stock (at cost), across N variants.
2. The plan: per tactic, how many items and the expected cash it brings in (`expected_cash_recovered`, using the assumed sell-through, stated in plain words), the ceiling if every unit sells, and the expected profit or loss versus cost.
3. Top 10 items by cash stuck: category and why, recommended tactic, new price, expected cash recovered (and if all sell), expected profit, and the other options' numbers when they are close. Compare options on expected cash, not on "if all sell".
4. Items where no markdown is possible (floor at or above price, or missing cost) and what you suggest instead.
5. Data notes: history length (and items too early to judge), unknown ages, missing costs, oversold items, the sell-through assumptions.

By output type:
- **spreadsheet**: the three CSVs from `--out-dir`. If the agent can write XLSX, one workbook with tabs Summary, Plan, Change list, Rollback, All variants.
- **dashboard**: `python3 scripts/build_dashboard.py --plan clearance.json --out dead-stock.html`. Offline HTML that works at 390px, with inputs for margin floor, markdown depth for slow, dead and very old dead items, bundle discount, liquidation recovery, below-cost permission and the expected sell-through per tactic. Changing an input re-chooses each item's tactic with the same rules as the script (for example allowing below cost can turn a free gift into a markdown) and recomputes prices and cash; with the default inputs it shows exactly the script's plan. Tactics that differ from the change list are marked "changed". It explores scenarios; the approved list is still the CSV. If the merchant settles on different numbers, update the setup and rerun the script to regenerate the change list.
- **report**: Markdown (or PDF/DOCX) led by the 3-5 decisions, then the top items table, then notes. In chat-only apps, write it in the chat.

Reports and dashboards end with the footer `Made with the free ReplAi skills pack`.

## Apply changes (only after an explicit yes)

1. Show the merchant `dead-stock-changes.csv` as a table: product, variant, field, old value, new value, reason. Say how many price changes, tags and collection additions it holds, and that liquidation items need no store change.
2. Ask: "Apply exactly these N changes to <store name>? Reply yes to apply this list." Anything other than a clear yes means do not apply. If they edit the list, show the edited list and ask again.
3. Follow [references/shopify-apply.md](references/shopify-apply.md): confirm the store, re-read live values, stop on rows whose live value changed, write the rollback file from live values BEFORE the first write, then apply with `productVariantsBulkUpdate` (price, compare-at) and `tagsAdd` (tags), and add to the collection.
4. Bundle and free gift discounts are a separate change list with their own yes.
5. Report what was applied, what was skipped and why, and where the rollback file is. Offer to roll back.

Without a connector, give the CSV and the manual import steps from the apply reference.

## Rules of judgement

- Never suggest a price below cost x (1 + margin floor) unless the merchant allowed below-cost clearance in setup.
- Never invent demand: "cash recovered" means "if every unit sells at that price" (the ceiling); "expected cash recovered" uses the sell-through assumptions from setup. Both, and liquidation recovery, are estimates; say so.
- Do not put healthy bestsellers on sale. Bundles use fast movers only as the paid item.
- A product with no sale and unknown age may be new: when the order history is short, say so instead of calling it dead.
- Suggest re-running in 2-4 weeks to see whether the first markdown step worked before going deeper.

## Safety

- Read-only by default. The script never changes the store.
- Any store change (price, compare-at price, tags, collections, discounts, unpublishing) requires showing the exact list and an explicit yes for that list. Approval does not carry to later batches or edited lists.
- A rollback file with the live old values is written before the first change.
- Never delete products, variants, collections or data. Never touch payments, payouts or credentials.
- Data stays on the merchant's machine or in their connected tools. No personal data in URLs.
