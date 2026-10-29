---
name: size-chart-builder
description: Build accurate size charts (English or Arabic) from supplier sheets or measurements, and add them to Shopify. Use for "make a size chart", "size guide" or "جدول مقاسات".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Size chart builder

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Build accurate, mobile-friendly size charts for clothing and shoes from a supplier spec sheet (Excel, PDF or photo), measurements typed in chat, photos of flat-measured garments, or a typical base standard. Checks the numbers (sizes that do not increase, uneven grading, gaps), converts cm and inches, turns flat garment measurements into body size guidance, and renders an HTML size chart in English and/or Arabic (right to left) with a how-to-measure guide and fit note. Can place it in Shopify (product description, a page, or a product metafield) only after the merchant confirms. Use when the merchant says "make a size chart", "size guide", "جدول مقاسات", "convert cm to inches", "check my supplier sizes", "my customers keep ordering the wrong size", or "add a size chart to my products".

Wrong sizes are one of the biggest reasons for refused COD orders and returns. This skill turns whatever size data the merchant has into a clean, checked chart that works on a phone, in English, Arabic or both.

## Setup

1. Look for saved setup: `replai-setup/size-chart-builder.json` in the working folder, or a pasted setup card (a JSON block starting with `"skill": "size-chart-builder"`). If found, say "Using your saved size chart setup (<languages>, <placement>)." and go to Run. "Change my setup" or "redo setup" reruns the questions with current answers pre-filled.
2. If not found, send ONE message with these numbered questions. The merchant can reply "defaults" or answer some numbers only.

```
1. Main unit on the chart? [cm, with inches under a "Show in inches" toggle]
2. Language(s) for the chart? [en] (en / ar / both)
3. Arabic digits, if Arabic? [western 0-9] (western / eastern ٠-٩)
4. Size labels you use? [letters XS-XXL] (letters / EU numbers / waist inches / shoe EU / your own)
5. Garment categories you sell? [women tops, bottoms, dresses] (also men tops, men bottoms, shoes, abayas, kids)
6. How does your brand fit? [true to size] (runs small / true to size / runs large)
7. Your numbers usually describe? [the garment, measured flat] (garment / body)
8. Where should charts live in the store? [product metafield custom.size_chart] (product description / one shared page / metafield / a size chart app / I will paste it myself)
9. If metafield: type? [multi_line_text_field] (multi_line_text_field / json)
```

3. Save the answers in the shape of `assets/setup.example.json`: write `replai-setup/size-chart-builder.json` when there is a file system, otherwise print the setup card as a fenced JSON block and tell the merchant to paste it at the start of the next chat.
4. Smoke test: if a Shopify connector is connected, read the shop name and, for metafield placement, check whether the definition `namespace.key` exists and its type. Otherwise run `python3 scripts/sizechart.py validate assets/base-typical-women-tops.csv`. Report the result in one line.

Per run (not at setup): which product(s), which input, the fit of this item (stretch, fitted, regular, relaxed, oversized), and any one-off note (for example "this abaya is one size").

## Inputs and what to do with each

All inputs end as one standard CSV (`chart.csv`). See [references/csv-format.md](references/csv-format.md) for the shape and [references/extraction.md](references/extraction.md) for how to read each source.

| Input | Do this |
|---|---|
| Supplier spec sheet (XLSX/CSV) | `python3 scripts/tabular.py sheet.xlsx` to preview, map supplier terms ("1/2 chest", "pit to pit", "HPS length") to standard names, build `chart.csv` |
| PDF or photo of a spec sheet | Read the table, mark unreadable cells blank, repeat the table back and ask the merchant to confirm |
| Measurements typed in chat | Build `chart.csv` from the message, repeat it as a table, confirm |
| Photos of flat-measured garments | Read size label + tape reading per photo, confirm unclear readings, keep flat numbers, then run `body` |
| No data, "use a standard" | Copy the matching `assets/base-typical-*.csv` (see [references/base-tables.md](references/base-tables.md)) and say clearly it is a typical starting point, not this brand's real sizing |

Never invent a measurement. A blank stays blank until the merchant gives it.

## Run

1. **Build the CSV** from the input. Show it to the merchant as a small table and ask "Is this right?" before going on.
2. **Validate**:
   `python3 scripts/sizechart.py validate chart.csv`
   Read the JSON. Report errors first (a size that gets smaller, duplicate sizes, text in a number cell), then warnings (missing sizes like "M missing", blank cells, uneven grading steps, a measurement that does not change), then notes. Give each one in plain words with the sizes and numbers, and ask the merchant to fix or confirm. Do not render a chart that still has errors unless the merchant says to.
3. **Garment to body guidance** (when the numbers are flat garment measurements and the merchant wants body sizes):
   `python3 scripts/sizechart.py body chart.csv --category tops --fit regular --out body.csv`
   Categories: tops, dresses, bottoms. Fits: stretch, fitted, regular, relaxed, oversized. Use `--measured full` if widths were measured all the way round. The script doubles flat widths and subtracts typical ease from `assets/ease.json`. Body ranges are estimates: say so, and show the ease used. If the merchant knows their pattern ease, copy `assets/ease.json`, edit it and pass `--ease-file`.
   Then choose what the chart shows: the garment numbers (`--basis garment`; flat widths are doubled on the chart so shoppers see the full measurement around, add `--measured full` if the CSV already holds full measurements) or a body chart built from the body ranges (put the midpoint or a min/max pair in a new `chart.csv` and use `--basis body`).
4. **Convert units** when the source is in inches or the merchant wants an inches file:
   `python3 scripts/sizechart.py convert chart.csv --to in --out chart-in.csv`
   1 in = 2.54 cm, rounded to the nearest 0.5. The render step converts on its own, so this is only needed for a separate file.
5. **Render**:
   `python3 scripts/sizechart.py render chart.csv --out size-chart.html --lang both --units both --basis garment --fit-note true-to-size`
   Options: `--lang en|ar|both`, `--units cm|in|both`, `--basis body|garment`, `--fit-note true-to-size|runs-small|runs-large` or your own words with `--fit-note-text` and `--fit-note-text-ar`, `--title`, `--title-ar`, `--arabic-digits eastern|western` (eastern applies to every number in the Arabic chart: measurements, numeric sizes like 38 or 36/37, and EU/UK/US columns; letter sizes stay), `--measured flat|full` (garment basis only). With `--basis garment` the how-to-measure list uses garment wording (lay the item flat, measure across). With a custom fit note and `--lang both`, always pass both `--fit-note-text` and `--fit-note-text-ar` (translate it yourself): a note given in one language only is left out of the other chart and `warnings` says so; rerun with the missing text.
   The snippet uses inline styles only (no scripts, no external CSS) so it survives the Shopify editor. Only the table scrolls sideways on a phone, never the page; the size column stays pinned (on the right in Arabic). The inches table sits behind a "Show in inches" toggle. Read `warnings` in the output: a measurement with no built-in label needs its header checked, and translated by you in the Arabic table.
6. **Check the result**: open `size-chart.html` in a browser at 390 px wide if you can and confirm the page does not scroll sideways and Arabic reads right to left. Otherwise show the merchant the HTML and a text version of the table.
7. **Place it** in the store using the setup placement. Steps, manual clicks and the exact GraphQL for each option are in [references/shopify-placement.md](references/shopify-placement.md):
   - Product description: `productUpdate` with `descriptionHtml` (replace an existing `replai-size-chart` block instead of adding a second one).
   - One shared page: `pageCreate`, then link it from product pages.
   - Product metafield (namespace and key from setup): `metafieldsSet` with type `multi_line_text_field` (HTML) or `json` (table data, displayed by `assets/size-chart-snippet.liquid`). Rich text cannot hold a table.
   - Size chart app or "I will paste it myself": hand over the HTML or CSV with the exact admin path. No store write.
   Before any write: read the current value, show the exact change list, wait for a yes for that list.

If the agent cannot run code, follow [references/method.md](references/method.md); it gives the same rules and rounding so the result matches the script.

## Outputs

- `chart.csv`: the checked chart in the standard shape (the merchant keeps this as the source of truth).
- `size-chart.html`: the snippet for the product page or page body.
- A short summary in chat: what was checked and fixed, which basis (body or garment), the fit note, any estimate and its assumption, and where it was placed (or the paste steps).
- On request: an image (screenshot the HTML at 1080 px wide), or the JSON `table` from the render output for a json metafield (display headers like "Chest (cm)" and the same values the HTML shows, flat widths doubled; `tables.ar` is the Arabic one). Use it as the metafield value as is.
- If the merchant wants a standalone report page, end it with the footer `Made with the free ReplAi skills pack`. The product page snippet itself carries no footer.

## Safety

- Read-only by default. Building, validating and rendering never touch the store.
- Any Shopify write (product description, page, metafield definition, metafield value) happens only after showing the exact change list (product names, IDs, field, what is added or replaced) and getting an explicit yes for that list. Approval does not carry to later batches.
- Read and keep the current value before every write (log file or chat) so it can be put back. Never delete a description, page or metafield; replace only the size chart block.
- Theme changes (a Custom liquid block, the snippet file) are made on a duplicate theme, previewed, and published only on the merchant's yes. Steps are in [references/shopify-placement.md](references/shopify-placement.md).
- Never invent measurements or fill blanks. Typical base tables and ease-based body ranges are labelled as typical starting points and estimates every time they are shown.
- No customer data is needed or used. Nothing is sent anywhere except the merchant's own store.
