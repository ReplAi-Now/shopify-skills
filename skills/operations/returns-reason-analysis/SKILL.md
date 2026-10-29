---
name: returns-reason-analysis
description: Find why customers return or exchange products (English, Arabic, Franco text) and what to fix. Use for "why are returns so high", "return reasons" or "المرتجعات".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Returns reason analysis

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Find why customers return or exchange products and exactly what to fix. Reads Shopify returns and refunds (connector or orders export), tags and notes, returns app or courier CSVs and support chat exports; classifies free-text reasons in English, Arabic and Franco-Arabic (size too small, too large, fit, quality or defect, not as pictured or colour different, wrong item, damaged in shipping, late delivery, changed mind, refused at door for COD); computes return rates per product, variant, size, colour and supplier on an order cohort, and money lost. Outputs the top products to fix with the specific fix (shift the size chart, reshoot photos, raise with the supplier), trends, and exchanges vs refunds, as a report, dashboard or spreadsheet. Use when the merchant says "why are returns so high", "return reasons", "returns analysis", "which products get returned", "exchange rate", "refund analysis", "المرتجعات", "ليه الناس بترجع", "el morta3 kteer", or shares a returns export.

Turns messy return notes ("el ma2as sghayar", "اللون مختلف عن الصورة", "too big") into a clear list: which products to fix, what the fix is, and how much money returns cost.

Files in this skill:
- `scripts/extract_from_orders.py`: builds a returns file from an orders export (refunds, tags, notes).
- `scripts/classify_reasons.py`: classifies reasons with the keyword lexicon `assets/reason-lexicon.json` and lists the leftovers for you to classify.
- `scripts/analyze_returns.py`: rates, money lost, fixes, trends, exchanges vs refunds (JSON, optional CSVs).
- `scripts/render_returns.py`: report (Markdown) or dashboard (HTML).
- [references/data-sources.md](references/data-sources.md): export paths, columns, returns app and chat exports.
- [references/shopify-queries.md](references/shopify-queries.md): Admin GraphQL for returns, refunds, sold units, costs.
- [references/method.md](references/method.md): taxonomy, classification rules, cohort timing, every formula. Use it to do the work by hand without code.

## Setup

1. Look for saved setup: `replai-setup/returns-reason-analysis.json` in the working folder, else a pasted setup card (fenced JSON with `"skill": "returns-reason-analysis"`). If found, say "Using your saved returns setup (return window <n> days, <currency>)" and go to **Run**. "Change my setup" re-runs the questions with current answers as defaults.
2. Otherwise send ONE message (the merchant can reply "defaults" or answer some numbers):

```
To set up returns analysis, answer any of these (or reply "defaults"):
1. Currency? [store currency]
2. How many days do customers have to return? [14]
3. How do you mark returns, exchanges and refused COD orders in Shopify?
   [returns: tag returned or Shopify returns; exchanges: tag exchange;
   refused: cancel the order after it was fulfilled, or tag refused / rto]
   (or "we use a returns app")
4. What does one return shipment cost you (pickup + back to you)? [unknown: left out]
5. What does reshipping an exchange cost? [same as a return shipment]
6. Anything else per return (inspection, repacking)? [0]
7. Any reasons you want to track differently, or words your customers use
   that we should recognise? [none] (e.g. "مش مريح" = fit)
8. Minimum units sold before we judge a product's return rate? [20]
9. Output? [report] (report / dashboard / spreadsheet)
10. Report language? [the language you write to me in]
```

3. Save it: with files, write `replai-setup/returns-reason-analysis.json` in the shape of `assets/setup.example.json` (question 4 is `default_return_shipping_cost`, 5 `exchange_reship_cost`, 6 `handling_cost_per_return`, 7 `taxonomy_overrides` as `{"fit_other": ["مش مريح"]}`, 8 `min_units_sold`). Without files, print the setup card as a fenced JSON block and ask the merchant to paste it next time.
4. Smoke test: read the store name and count returned or refunded orders in the last 30 days from the connector, or parse the first rows of the export. One line: "Found 64 refunded or returned orders since 1 Sep in your export."

Per run (not saved): the date window, if the merchant wants something other than the default (the 90 days of orders that have had time to come back).

## Run

1. **Load setup.** Note today's date (store timezone).
2. **Gather returns** (combine what exists, see [references/data-sources.md](references/data-sources.md)):
   - Connector: run the queries in [references/shopify-queries.md](references/shopify-queries.md) and write the returns CSV.
   - Returns app / courier / chat exports: map columns by meaning, confirm the mapping in one line if unsure.
   - Nothing else: `python3 scripts/extract_from_orders.py --orders orders_export.csv --setup <setup> --out returns_from_orders.csv`.
3. **Gather sales** for rates: the orders export (Orders > Export, at least the window plus 3 weeks), or the sold-units query. Unit costs: products export (`Cost per item`) or the costs query.
4. **Classify, lexicon first:**
   ```
   python3 scripts/classify_reasons.py --returns returns.csv --setup <setup> --out classified.csv
   ```
   The JSON lists `unclassified` rows (text the lexicon did not recognise) and `code_text_conflicts`.
5. **Classify the leftovers yourself.** Read each leftover's text (any language or dialect), pick one category from the taxonomy in [references/method.md](references/method.md), and write `overrides.csv` (`row,category`). Then **confirm with the merchant**: show a compact table (row, text, your category, plus any conflicts) and ask "Correct? Reply with row numbers to change." Apply their corrections, then re-run step 4 with `--overrides overrides.csv` until `unclassified` is empty. If there are more than 30 leftovers, show the 30 most common phrasings and apply the same category to identical texts. Suggest adding recurring words to `taxonomy_overrides` so next time they are automatic.
6. **Analyse:**
   ```
   python3 scripts/analyze_returns.py --returns classified.csv --orders orders_export.csv \
     --setup <setup> [--products products_export.csv] [--start YYYY-MM-DD --end YYYY-MM-DD] \
     [--csv-dir replai-reports/returns-<date>] > analysis.json
   ```
   No code execution: follow [references/method.md](references/method.md) step by step.
7. **Sanity check** before presenting: the window ends on or before `mature_until` (otherwise say rates are understated); show every item in `notes`; small-sample groups are labelled; refusals are reported separately, never inside return rates.
8. **Present** in the chosen output (below). Translate labels and fixes into the setup language; keep product names as they are in the store.

## How to present each output

Every output leads with the products to fix (product, return rate, units, money lost, main reason with its share, the specific fix), then the evidence. Explain "return rate" the first time: units sent back out of units sold in the same orders.

- **report** (default): `python3 scripts/render_returns.py --analysis analysis.json --format report --out replai-reports/returns-<date>.md`. Sections: Fix these first (with per-size rates for size problems), The numbers (rate, refunds vs exchanges, money lost broken down), Reasons table, By size / colour / vendor, Trend by order month, Data notes, footer. In chat, paste it as the message. Lead with 3-5 decisions in plain words, e.g. "Maxi Dress: raise the defects with Supplier B, 2 of 3 returns are defects".
- **dashboard**: `--format dashboard --out replai-reports/returns-<date>.html`. One self-contained file, works offline and at 390px. Scenario inputs: return shipping cost per return (recomputes money lost, store total and per product, and so each product's saving) and the share of returns a fix would prevent (estimated saving per product and total, labelled as an estimate).
- **spreadsheet**: the `--csv-dir` folder: `top_fixes.csv`, `by_product.csv`, `by_variant.csv`, `by_size.csv`, `by_colour.csv`, `by_vendor.csv`, `reasons.csv`, `trend.csv`. One tab per file if you can write XLSX.

Patterns worth saying in words when the numbers show them:
- Size returns split between too small and too large on one product: inconsistent batches, a supplier issue, not the chart.
- High exchange share on size reasons: the product is wanted; fix the size guide and returns turn into kept sales.
- One colour far above the others: that colour's photos are off.
- One vendor far above the others on quality: raise it with that supplier with the counts.

## Rules that keep the numbers honest

- Rates use the order cohort: returns from orders placed in the window over units sold in that same window, and the window ends return window + 7 days before today.
- Refused at door (COD) is never a return. It is shown on its own; point to the cod-rto-analysis skill for it. From an orders export, an order cancelled or voided after it was fulfilled is a refusal (same rule and setup keys `count_cancelled_after_fulfillment_as_failed`, `failed_cancel_reasons`, `failed_financial_statuses` as cod-rto-analysis, so the two skills agree).
- If the export finds no returns (`no_returns_found` in the script output), say why in plain words (returns kept as Shopify return records, or taken back without a refund) and ask for connector access or a returns app export. Do not report "0% returns".
- Report the dates the orders file covers (`window.covered`), not only the window asked for.
- Never rank a product on a small sample (below `min_units_sold` sold or `min_returns` returned).
- Costs you do not have are left out and named in the notes, never guessed. Estimates (units from a partial refund, savings) are labelled.
- Rows the export cannot tie to a product keep their money but stay out of product rates.

## Safety

- Read-only. This skill never edits products, size charts, photos, orders, refunds or customers. Fixes are recommendations; if the merchant wants one applied (for example a size chart change), hand over to the right skill (size-chart-builder) and make no store change without showing the exact change and getting an explicit yes.
- Never contact customers or suppliers. Draft a supplier message only if asked, and never send it.
- Keep personal data out: reports show products and counts, not customer names, phones, emails or addresses. Chat exports are read for reasons only.
- No data leaves the merchant's store, their connected tools and their own folder.
