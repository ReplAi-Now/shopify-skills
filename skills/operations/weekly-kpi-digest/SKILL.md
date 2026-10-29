---
name: weekly-kpi-digest
description: A one-page weekly store snapshot with three things to act on, on a schedule. Use for "weekly report", "how did we do this week" or "التقرير الأسبوعي".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Weekly KPI digest

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** A one-page weekly snapshot of a Shopify store with 3 things to act on. Net sales, orders, average order value, units, new vs returning customers, top and bottom products, discounts, refunds, COD share and COD delivery success, cancelled orders and failed deliveries, stock running out, and sessions and conversion rate when Shopify analytics is available. Compares this week with last week and with the same week 4 weeks ago, with arrows, % changes and flags, respecting the store timezone and week start (Saturday, Sunday or Monday). Runs on a weekly schedule without questions once set up, and delivers a report, dashboard, spreadsheet or email draft. Use when the merchant says "weekly report", "how did we do this week", "weekly KPIs", "sales summary", "store snapshot", "weekly digest", "التقرير الأسبوعي", "ازاي كان الأسبوع", or asks to schedule a weekly business update.

One page, once a week: how the store did, what changed, and the 3 things to act on. Works from the Shopify connector or from a Shopify orders export alone.

Files in this skill:
- `scripts/kpi_digest.py` computes every number and prints JSON. `scripts/render_digest.py` turns that JSON into a report, dashboard, spreadsheet or email draft.
- [references/data-sources.md](references/data-sources.md): connector queries, ShopifyQL for sessions and conversion, exact export paths and columns.
- [references/method.md](references/method.md): every definition and formula, for doing it by hand without code.
- [references/scheduling.md](references/scheduling.md): how to run it weekly in each app, and the rules for unattended runs.

## Setup

1. Look for saved setup: `replai-setup/weekly-kpi-digest.json` in the working folder, else a pasted setup card (fenced JSON with `"skill": "weekly-kpi-digest"`). If found, say "Using your saved weekly digest setup (week starts <day>, <timezone>)" and go to **Run**. If the merchant says "change my setup", re-ask with current answers as defaults.
2. **Scheduled or unattended run with no setup: do not interview.** Write a one-line note that setup is needed (see [references/scheduling.md](references/scheduling.md)) and stop.
3. Otherwise send ONE message with these questions. The merchant can answer "defaults" or only some numbers.

```
To set up your weekly digest, answer any of these (or reply "defaults"):
1. Store name for the report title? [read from Shopify]
2. Currency? [store currency]
3. Timezone? [Africa/Cairo] (Riyadh, Dubai, Kuwait... or a city name)
4. Week starts on? [Saturday] (Saturday / Sunday / Monday)
5. KPIs to show? [all: net sales, orders, AOV, units, new vs returning,
   top/bottom 5 products, discount share, refunds, COD share, COD delivery
   success, cancelled orders, failed deliveries, stock warnings, sessions +
   conversion if available]
6. Weekly targets? [none] (e.g. net sales 150000, orders 400)
7. Flag changes bigger than? [15%, or 3 points for rates]
8. Warn when stock covers fewer than how many days? [14]
9. How do you record a failed COD delivery? [cancel the order after it was
   fulfilled; or tags rto, refused, returned] (or "I'll give a courier file")
10. Output? [report] (report / dashboard / spreadsheet)
11. Delivery? [file] (file / chat message / email draft to <address>)
12. Report language? [the language you write to me in]
13. Run it automatically every week? [yes, Saturday 9:00]
```

4. Save it. With files: write `replai-setup/weekly-kpi-digest.json` using the shape of `assets/setup.example.json` (keys: `kpis`, `targets`, `flag_threshold_pct`, `flag_threshold_pp`, `inventory_cover_days`, `delivered_tags`, `failed_tags`, `output`, `delivery`, `email_to`, `timezone`, `week_start`...). Question 9: extra failed tags go in `failed_tags`; "I never cancel failed orders" sets `count_cancelled_after_fulfillment_as_failed` to false. Save `timezone` as a zone name such as `Africa/Cairo` or `Asia/Riyadh`, and `week_start` as `saturday`, `sunday` or `monday`. Without files: print the setup card as a fenced JSON block and tell the merchant to paste it at the start of future chats (or into the scheduled task).
5. Smoke test: read the store name and the most recent order date from the connector, or the first rows of the export. Report in one line, e.g. "Connected: <store>, last order 24 Oct 2026, 1,240 orders in the export since 1 May."
6. If they said yes to weekly runs, create the schedule now (see [references/scheduling.md](references/scheduling.md)) and run it once to prove it works.

## Run

Fully non-interactive once setup exists. Never ask questions in a scheduled run. Missing data becomes a note in the output, never a question and never a guess.

1. **Load setup** (above). Work out the report week per [references/method.md](references/method.md) section 1, or use the week the merchant named ("last week", "the week of 3 Oct").
2. **Get data** (order in [references/data-sources.md](references/data-sources.md)):
   - Connector: query orders from at least 180 days before the report week start (7 weeks is the minimum for the comparisons; the longer history is what makes new vs returning right), and variant stock. Save as CSV with export column names.
   - Exports: use the files the merchant gave, or in a scheduled run the newest `orders_export*` in `exports_folder`. If the digest JSON has a `STALE DATA` note (latest order, `history_end`, is before the report week), deliver only that note and stop. A file saved before the week ended (check its date) is stale too.
   - Analytics: try the ShopifyQL sessions query for the 3 weeks. If it fails, continue without it. Never invent sessions or conversion.
   - Courier export if the merchant provides one.
3. **Compute**:
   ```
   python3 scripts/kpi_digest.py --orders orders.csv --setup replai-setup/weekly-kpi-digest.json \
     [--inventory inventory.csv] [--courier courier.csv] [--analytics analytics.json] \
     [--as-of YYYY-MM-DD | --week-start YYYY-MM-DD] --out replai-reports/digest.json
   ```
   No code execution: compute by hand with [references/method.md](references/method.md), same definitions.
4. **Check before presenting**: orders this week > 0 (if 0, say so plainly, it may be a stale export); the `notes` list is shown as data notes; act-on items are exactly 3.
5. **Render** the output in setup (or the one asked for this run):
   ```
   python3 scripts/render_digest.py --digest replai-reports/digest.json --format report|dashboard|spreadsheet|email --out <path>
   ```
   File names: `replai-reports/weekly-digest-<week start>.md|.html|/` and `weekly-digest-<week start>-email.txt`.
6. **Deliver** (see below). Translate the rendered text into the setup language if it is not English; keep numbers, arrows and currency as they are.

## How to present each output

Every output opens with the 3 "act on this" items, then the numbers.

- **report** (default): the Markdown one-pager from `render_digest.py`. Sections: Act on this, Key numbers table (this week, last week, change, 4 weeks ago, change; (!) on flagged changes), Top 5 and Bottom 5 products, Stock running out, Data notes, What the numbers mean, footer. In chat, paste it as the message.
- **dashboard**: the single HTML file. Works offline and at 390px wide. KPI cards colour the change green or red by whether it is good or bad for that KPI. Inputs let the merchant change the flag thresholds and weekly targets and see flags and target progress update. Tell the merchant the file path.
- **spreadsheet**: a folder with `kpis.csv`, `top_products.csv`, `bottom_products.csv`, `inventory_warnings.csv`. If you can write XLSX, one tab per CSV.
- **email**: `render_digest.py --format email` writes a plain-text draft (first line is the subject). If a mail connector (Gmail, Outlook) is connected, create a DRAFT to `email_to` with that subject and body. Otherwise save the .txt and tell the merchant where it is. **Never send.**

Language for the merchant: say "Net sales were 152,400 EGP, up 12% on last week" rather than "Δ net_sales +12%". Explain pp the first time ("percentage points: 5% to 8% is +3 pp").

## Delivery

- `file`: save to `output_folder` (default `replai-reports/`) and reply with one line: the path and the 3 act-on items.
- `chat`: post the report in the chat (also save the file if there is a file system).
- `email_draft`: create the draft as above and reply "Draft ready in your mailbox, not sent." Sending needs the merchant's explicit yes in the chat, for that one email.

## Rules that keep the numbers honest

- Week boundaries are in the store timezone and start on the setup day. Orders near midnight UTC often land in a different local day.
- Refunds belong to the week of the order (exports have no refund date). Shopify's Sales report books them on refund day, so totals can differ slightly; say so if asked.
- Cancelled and voided orders are excluded from sales, orders and customer KPIs. They are split into "Cancelled before shipping" and "Failed deliveries" (cancelled after fulfilment, the usual way a refused COD parcel is recorded). Delivery outcomes use the same rules and setup keys (`failed_tags`, `count_cancelled_after_fulfillment_as_failed`, `failed_cancel_reasons`, `failed_financial_statuses`, `failed_courier_statuses`, `delivered_courier_statuses`) as the cod-rto-analysis skill, so both skills report the same numbers.
- Stores that take returns without refunding (Try & Buy, exchanges) show 0 refunds in exports. Only the connector can count those returned units ([references/data-sources.md](references/data-sources.md)).
- A comparison week the export only partly covers (data starting hours into its first day) is marked "(partial)" and not used for "act on this". Test orders (Shopify `bogus` test gateway, tagged `test`, or "test" in the note) are excluded from everything, with a note counting them.
- "Act on this" never ranks a rate that rests on fewer than `min_rate_base` (default 5) orders, nor COD delivery success for a week still settling, and never suggests connecting analytics or courier data that was already given.
- A comparison week with no data is left blank, never treated as zero.
- The most recent week's COD delivery success is often incomplete (orders still in transit). The script notes it when more than 30% are unknown.
- New vs returning needs history: with less than 6 months of orders, say returning customers are undercounted.
- Conversion rate and sessions come only from Shopify analytics. If unavailable, they are absent with a note.

## Safety

- Read-only. This skill never changes products, orders, customers, prices or settings.
- Email: drafts only. Never send, forward or schedule an email without the merchant's explicit yes in this chat for that exact message.
- Scheduled runs never ask questions and never act on the store; they only read, write the output file or draft, and stop.
- Data stays with the merchant: no personal data in URLs, nothing sent anywhere except the merchant's store, their connected tools and their own output folder. Reports show order counts and products, not customer names, emails or phones.
- Never invent numbers. Missing data is reported as missing, with what would fill it.
