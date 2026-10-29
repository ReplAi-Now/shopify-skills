---
name: cod-rto-analysis
description: Find where cash on delivery orders fail (governorate, courier, product) and what it costs. Use for "RTO", "refused orders", "delivery success rate" or "مرتجعات".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# COD failed-delivery (RTO) analysis

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Find where cash-on-delivery orders fail and what it costs. Reads Shopify orders (connector or export) and optional courier files from any courier, normalises addresses to the 27 Egyptian governorates and GCC emirates/regions/governorates, and computes delivery success rate, RTO (return to origin) rate, refusal reasons and money lost to failed deliveries (shipping both ways, COD fee, packaging) by governorate, city, courier, product, order value, new vs repeat customer, weekday and payment method. Small areas are not ranked, every rate shows its confidence. Ends with concrete actions (deposit or prepayment in an area, confirm orders above a value, switch courier in a region) and an estimate of money saved. Use when the merchant says "RTO", "returned orders", "refused orders", "COD failures", "where do my orders fail", "delivery success rate", "which governorate refuses", "is COD worth it", "courier comparison", "مرتجعات", "الطلبات المرفوضة", "نسبة التسليم", or uploads a courier export.

Answers three questions for a cash-on-delivery store: where do orders fail, how much does it cost, and what should change. Works from a Shopify orders export alone; a courier export makes it sharper (real fees, real statuses, refusal reasons).

Files in this skill:
Paths starting with `scripts/` or `assets/` are inside this skill's folder; `replai-setup/` and the merchant's files are in the working folder.
- `scripts/rto_analysis.py` does all the math and prints JSON. It uses `scripts/orders.py` (export parsing, courier join, outcome rules), `scripts/regions.py` (address normalisation) and `scripts/tabular.py` (CSV/XLSX reader).
- `scripts/render_dashboard.py` turns the JSON into a one-file HTML dashboard with scenario inputs.
- `assets/regions.json`: the region table (Egypt 27 governorates with Arabic, Franco and city names; UAE, KSA, Kuwait, Qatar, Bahrain, Oman). Data, not code: add a spelling and rerun.
- `assets/setup.example.json`: every setup key with its default.
- [references/data-sources.md](references/data-sources.md): exact export paths, columns relied on, connector query, courier column mapping.
- [references/method.md](references/method.md): every definition and formula, for doing it by hand without code.

## Setup

1. Look for saved setup: `replai-setup/cod-rto-analysis.json` in the working folder, else a pasted setup card (fenced JSON with `"skill": "cod-rto-analysis"`). If found, say in one line "Using your saved RTO setup (<currency>, failed = <short definition>)" and go to **Run**. If the merchant says "change my setup" or "redo setup", ask again with the current answers as defaults.
2. Otherwise send ONE message with these questions. The merchant can reply "defaults" or answer only some numbers.

```
To set up the COD failure analysis, answer any of these (or reply "defaults"):
1. Store currency? [read from Shopify, else EGP]
2. Which couriers do you use? [none listed] (names only, e.g. "two couriers: A for Cairo, B for the rest")
3. How do you mark a failed (refused / returned) order in Shopify?
   a. tags [rto, returned, refused, undelivered, مرتجع]
   b. cancel the order after it was fulfilled [yes]
   c. financial status [voided]
   d. or "I'll send a courier file", the courier status decides
4. Cost of ONE failed delivery, if no courier file has it:
   outbound shipping [ask], return shipping [ask], COD fee charged on a
   failed delivery [0], packaging [ask]  (or one total, e.g. "120 all in")
5. Analyse COD orders only, or all orders? [COD only]
6. Minimum orders before an area or product is ranked? [30]
7. Order value bands for "confirm above X"? [500 / 1000 / 2000]
8. Output? [report] (report / dashboard / spreadsheet)
```

3. Map the answers to `assets/setup.example.json` keys: question 3 fills `failed_tags`, `count_cancelled_after_fulfillment_as_failed`, `failed_financial_statuses` (add the merchant's own words, Arabic or English); question 4 fills `default_outbound_shipping`, `default_return_shipping`, `default_cod_fee_failed`, `packaging_cost` (a single total goes in `default_outbound_shipping`, the rest 0); then `cod_only`, `min_orders`, `value_bands`, `output`, `couriers`, `currency`. Courier status words (`failed_courier_statuses`, `delivered_courier_statuses`) have sensible defaults; add any status text the merchant's courier uses.
4. Save it. With files: write `replai-setup/cod-rto-analysis.json` in the shape of `assets/setup.example.json`. Without files: print the setup card as a fenced JSON block and tell the merchant to paste it at the start of the next chat.
5. Smoke test: parse the first rows of the orders export (`python3 scripts/orders.py <file>`) or read the store name and latest order from the connector. Report in one line, e.g. "Read 1,840 orders from 1 Jul to 27 Oct; 1,610 are COD."

## Run

1. **Load setup** (above). Ask per run only for the date range if not obvious from the files ("last 90 days" is a good default; under 60 days most areas will be too small to rank).
2. **Get orders** (details and exact columns in [references/data-sources.md](references/data-sources.md)):
   - Connector: page through orders in the range with the read-only query in data-sources.md and save them as a CSV with the export column names. Never guess IDs.
   - Export: `Shopify admin > Orders > (filter by date) > Export > Current page / All orders / Selected > CSV for Excel`. One row per line item is expected.
3. **Get courier files** if the merchant has them (any courier, CSV or XLSX). Map columns by meaning: order number or tracking number, status, COD amount, shipping fee, return fee, COD fee, reason. If unsure about a column, confirm in one line ("I read 'State' as the delivery status, ok?").
4. **Compute**:
   ```
   python3 scripts/rto_analysis.py --orders orders.csv --setup replai-setup/cod-rto-analysis.json \
     [--courier courierA.csv::CourierA] [--courier courierB.xlsx::CourierB] \
     [--courier-map status="Shipment State"] [--products products_export.csv] [--out-dir replai-reports/rto-<date>/]
   ```
   Without a courier file the courier segment comes from order tags ("Sent to ShipBlu", "bosta_synced") via setup `courier_tags` (tag text -> courier name; add the merchant's own tags). The product segment groups variants under their product (setup `product_group: "variant"` splits them); `--products` gives exact titles when product names contain " - ".
   Two courier files with different headers: repeat `--courier-map` for the same meaning (`--courier-map status="State" --courier-map status="الحالة"`); each file uses the header it has.
   No code execution: follow [references/method.md](references/method.md) by hand with the same definitions.
5. **Check before presenting**:
   - `outcomes`: if `open` is large (shipped but not marked paid or failed), say so: the store may not update COD orders after delivery, and a courier file would fix it.
   - `unknown_regions`: list them. If they are many orders, add the spellings to setup `region_aliases` (for example `{"Giza": ["el haram el gedid"]}`, region names as in `assets/regions.json`), save the setup and rerun. Never drop them silently.
   - `courier.unmatched`: courier rows that did not match an order (other date range or other store). Mention the count.
   - `warnings`: missing costs mean money lost is understated. Show the warning next to the number. With no cost at all, `money_lost` is null: say money lost is unknown and ask for the cost of one failed delivery; never show 0.
6. **Present** in the setup output (or the one asked for this run). Every output leads with the answer.

### What to show (all outputs)

1. **Headline**: delivery success rate, failure (RTO) rate, failed orders, money lost in the period and per month, and the average cost of one failed order. Explain once: "RTO = the parcel went out and came back without being paid for."
2. **Top 3-5 actions** from `actions`, each with its target, the estimated saving per month and the assumption in plain words (from `basis`). Write "estimate" next to each saving and say the savings overlap, so they must not be added together.
3. **Worst segments** from `worst`: regions first, then couriers, value bands, products, customer history, weekdays. For each: orders, failure rate, money lost, confidence. Show the 95% range (`ci95_low`-`ci95_high`) as "between X% and Y%" for medium confidence.
4. **Not ranked**: say how many areas had fewer than `min_orders` orders, so the merchant does not over-read a 2-of-3 failure.
5. **Refusal reasons** from `failure_reasons` (courier file only).
6. **Unknown regions** with order counts.
7. **Assumptions** list, verbatim from the JSON, in plain words.

### Output formats

- **report**: Markdown (or DOCX/PDF if the agent can make them; in chat-only apps, write it in the chat). Order: headline, actions, worst areas table, other segments, reasons, unknowns, assumptions. Under one page where possible. End with the footer.
- **dashboard**: run `python3 scripts/render_dashboard.py result.json replai-reports/rto-dashboard.html` (save the analysis JSON first with `> result.json`). One self-contained HTML file, works offline and at 390px wide. Scenario inputs: outbound, return, COD fee and packaging cost per failed order, prepayment and confirmation effect %. Money lost and savings update live. No code execution: build the same layout by hand.
- **spreadsheet**: `--out-dir` writes `orders_classified.csv` (one row per order with outcome, region, money lost) and `segments.csv` (every segment). Add a `summary.csv` with the headline and actions if asked.

Footer on every report and dashboard: `Made with the free ReplAi skills pack`.

### How to word actions

- Prepay area: "Ask for the shipping fee upfront (or full prepayment) for COD orders to Giza. Estimated saving: 4,500 EGP per month (estimate: assumes half of today's failures there are avoided)."
- Confirm by value: "Confirm orders of 1,000-1,999 EGP by WhatsApp or phone before shipping."
- Switch courier: only when both couriers have at least `min_orders` orders in that region.
- Product check: a product that fails far more than the store usually means the listing promises something the parcel does not deliver (size, colour, price shown).
- Never claim the saving is certain. Never suggest stopping COD for the whole store from one segment.

## Safety

- Read-only. This skill never edits orders, tags, settings, payment methods or customers.
- If the merchant asks to act on a finding (tag orders, add a deposit rule, message customers), list the exact changes and wait for an explicit yes for that list. Approval does not carry to later batches.
- Customer emails and phones are used only to tell first from repeat orders inside the script. Never print them in outputs, never put them in URLs, never send data anywhere except the merchant's own store and connected tools.
- Never invent numbers. If costs are missing, show the warning; if a segment is small, say it is not ranked.
- Never delete data. Never touch payments, payouts or credentials.
