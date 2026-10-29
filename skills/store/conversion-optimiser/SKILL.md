---
name: conversion-optimiser
description: Audit a Shopify store for conversion problems, then fix them on a theme copy with your OK. Use for "audit my store", "why is my conversion low" or "visits but no orders".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Conversion optimiser

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Audit a Shopify store for conversion problems and then fix them safely with the merchant's OK. Phase 1 (read only) checks speed with Google PageSpeed, the mobile layout at 390 px, product pages (photos, price, size chart, delivery time and cash on delivery info near Add to cart, returns, reviews, sticky Add to cart, honest urgency), trust (contact, WhatsApp, policies, payment icons), navigation and search, cart and checkout friction, Arabic/RTL quality and SEO basics, then gives a prioritised fix list (impact x effort) as an HTML report. Phase 2 makes the fixes on a duplicate theme with a preview link, and content edits through the Shopify connector in confirmed batches with a rollback log. Use when the merchant says "why is my conversion low", "audit my store", "my store gets visits but no orders", "CRO", "speed up my store", "improve my product page", "راجع متجري", or "fix my Shopify theme".

Two phases. **Phase 1 audit** is read only and ends with a ranked fix list. **Phase 2 act** changes the store only on a duplicate theme or in small confirmed content batches. Never edit the live theme.

## Setup

1. Look for saved setup: `replai-setup/conversion-optimiser.json` in the working folder, or a pasted setup card (a JSON block starting with `"skill": "conversion-optimiser"`). If found, say "Using your saved audit setup for <store>." and continue. "Change my setup" or "redo setup" reruns the questions with current answers pre-filled.
2. If not found, send ONE message with these numbered questions. The merchant can reply "defaults" or answer some numbers only.

```
1. Store URL? [read from the Shopify connector if connected]
2. How can I make theme changes? [connector if connected, otherwise manual steps for you] (Shopify CLI / connector / manual)
3. Store languages? [en] (en / ar / both, and which is the default)
4. Main market and currency? [Egypt, EGP] (EG, SA, AE, KW, QA, BH, OM)
5. Anything to focus on first? [everything] (speed / product page / checkout / Arabic / SEO)
6. What may I change in Phase 2? [product descriptions, alt text, SEO titles] (add: theme copy, policies, pages, navigation; or "audit only")
7. Brand voice for any text I write? [friendly, short sentences, no hype]
8. Arabic style, if Arabic? [simple Egyptian Arabic] (Gulf Arabic / Modern Standard Arabic)
9. Report format? [dashboard: one HTML page] (dashboard / spreadsheet / report)
```

3. Save the answers in the shape of `assets/setup.example.json`: write `replai-setup/conversion-optimiser.json` when there is a file system, otherwise print the setup card as a fenced JSON block and tell the merchant to paste it at the start of the next chat.
4. Smoke test: fetch the store home page and report its title in one line (no fetch tool: say the audit will use screenshots and exports instead). If a connector is connected, also read the shop name and the live theme name (`themes(first: 20, roles: [MAIN])`). If the store is password protected, say the audit needs the password page off or screenshots.

Per run (not at setup): which pages to treat as top products (default: best sellers from the connector, else the first 3 on `/collections/all?sort_by=best-selling`), and any page the merchant is worried about.

## Phase 1: audit (read only)

1. **Collect pages**: home, one top collection, 3 top product pages, cart. Use the agent's browser or fetch tool. With neither (chat apps with uploads only), ask for the phone screenshots and exports listed in [references/data-sources.md](references/data-sources.md), which also has the export fallbacks.
2. **Speed**: call PageSpeed Insights for the home page and one product page, mobile and desktop (no key needed for light use). Save each response and run:
   `python3 scripts/psi_summary.py psi-home-mobile.json psi-home-desktop.json psi-product-mobile.json psi-product-desktop.json` (home first: S1-S5 use the first mobile file)
   It returns scores, Core Web Vitals and ready-made S1-S5 checks. Request format, limits and fallbacks: [references/pagespeed.md](references/pagespeed.md).
3. **Walk the checklist** in [references/checklist.md](references/checklist.md) (50 checks: speed, mobile at 390 px, product page, trust, navigation and search, cart and checkout, Arabic/RTL, SEO). For each check, look at the real page:
   - Mobile: open pages at 390 px wide; measure `document.documentElement.scrollWidth`; look for pop-ups, button size, Add to cart position, sticky bar.
   - Product: count photos (`/products/<handle>.js`), find delivery time, COD, returns line, size chart, reviews near the button.
   - Checkout: add one item, open cart and the first checkout step, read what is required, leave. Never type personal data, never submit anything.
   - Arabic: switch language, check direction, leftovers in English, font.
   - SEO: read `<title>`, meta description, `alt` attributes, H1 count; fetch internal links on audited pages and note 404s.
   If something cannot be checked, mark it `unknown` with the reason. Never mark pass without looking.
4. **Write findings.json** (shape in `assets/findings.example.json`). Every fail or partial needs `evidence.url`, `evidence.seen` (what exactly you saw, with numbers), `impact`, `effort`, `fix` (the exact change: which setting, which text, which block) and `change_type` (theme, content, setting, app, manual). Paste the psi_summary output under `"speed"` and its `suggested_checks` into `checks`.
5. **Prioritise and report**:
   `python3 scripts/prioritise.py findings.json --html conversion-report.html --csv fixes.csv --lang en`
   Priority = impact x (4 - effort), from 9 (high impact, low effort) down to 1. Buckets: Do first (6-9), Next (3-4), Later (1-2). The health score is the weighted share of checks passed. If the script lists errors, fix findings.json and rerun. Without code, follow [references/method.md](references/method.md).
6. **Tell the merchant** in their language: the health score in one line, the top 5 fixes (what, evidence, fix), what needs them (photos, settings), and what could not be checked. Then attach or show the report. Use `--lang ar` for an Arabic report frame.
7. Ask: "Do you want me to start on the Do first list?" Phase 2 starts only on a yes and only within what setup allows (question 6).

## Phase 2: act (with confirmation)

Group the approved fixes by `change_type` and handle one group at a time.

**Theme changes** (blocks, settings, snippets, code). Full commands and fallbacks in [references/theme-workflow.md](references/theme-workflow.md).
1. Record the live theme ID in the change log (it is the rollback).
2. Duplicate the live theme: `shopify theme duplicate --theme <live id> --name "ReplAi CRO <date>"`, or GraphQL `themeDuplicate(id:, name:)`, or manual: Online Store > Themes > ... > Duplicate.
3. Make the changes on the copy only: theme editor clicks, or `shopify theme push --theme <copy id> --only <file>`, or GraphQL `themeFilesUpsert` (needs a Shopify exemption most connectors lack). Never `--live`, never `--allow-live`.
4. Check the copy at 390 px and desktop, then send the preview link `https://<store>.myshopify.com/?preview_theme_id=<id>` with a list of what changed.
5. Publish only after an explicit yes for publishing this copy, after checking the live theme was not edited in the meantime. Tell the merchant how to switch back.

**Content changes** (descriptions, SEO titles, alt text, policies, pages, navigation) through the connector. Queries, mutations and the log format in [references/content-edits.md](references/content-edits.md).
1. One area per batch, up to 25 changes. Read the before values.
2. Show the exact list (item, field, before, after) and wait for a yes for that list.
3. Apply, read back, report errors, and append the batch to `replai-cro-change-log.json` (or print it in chat apps).
4. To undo: `python3 scripts/rollback.py replai-cro-change-log.json --batch N` lists what to restore; that is a new batch with its own yes.

**Settings, apps and manual work**: give exact admin clicks (for example Settings > Checkout > Company name: Don't include) or the brief (for example "2 on-model photos for the denim jacket"). Do not install apps or change settings yourself unless the merchant asks and confirms.

After the fixes: rerun PageSpeed and the failed checks, update findings.json and regenerate the report so the merchant sees before and after. Suggest comparing conversion rate in Shopify Analytics over the next 2-4 weeks. Never promise a number.

## Outputs

- `conversion-report.html` (dashboard, default): health score, top fixes, Next and Later lists, speed table with plain explanations, passed and unchecked items. Works offline and at 390 px. Ends with `Made with the free ReplAi skills pack`.
- `fixes.csv` (spreadsheet): ranked fixes with evidence and fix text.
- report: a short message leading with the 3-5 decisions, built from the script's JSON.
- `findings.json` and `replai-cro-change-log.json`: the audit record and the rollback log.

## Safety

- Phase 1 is read only. No store writes, no form submissions, no personal data typed anywhere (checkout is looked at, not filled in).
- The live theme is never edited. Theme work happens on a duplicate, is previewed, and is published only on the merchant's explicit yes for that publish. The previous theme stays in the library for rollback. Never delete a theme.
- Content changes go in small batches; each batch needs its own explicit yes for the exact list shown. Approval never carries to the next batch.
- Before every write, read and log the current value. Never delete products, pages, policies or menu items; `menuUpdate` replaces the whole menu, so always send every existing item back.
- Change only the areas allowed in setup question 6. Ask before touching anything else.
- Never touch payments, payouts, staff accounts, apps' billing or credentials. Do not install or uninstall apps without the merchant's yes.
- Never invent facts in store content (delivery times, materials, guarantees, review counts) and never add fake urgency. Estimates are labelled with their assumption.
- Only fetch the merchant's own public storefront, Google PageSpeed and the tools they connected. No personal data in URLs.
