# Method: returns, reasons, rates and money

Use this when you cannot run the scripts. It gives the same results as `classify_reasons.py` and `analyze_returns.py`.

## 1. Taxonomy

| Key | Label | Typical words (EN / AR / Franco) |
|---|---|---|
| `size_too_small` | Size too small | too small, tight / صغير، ضيق، محزق / sghayar, dayya2, ma7zo2 |
| `size_too_large` | Size too large | too big, loose / كبير، واسع / kbeer, wasi3 |
| `fit_other` | Fit (other) | doesn't fit, too long, wrong size / مقاس غلط، طويل، قصير / ma2as, mesh ma2asy |
| `quality_defect` | Quality or defect | defective, torn, stain, bad quality / عيب، مقطوع، بقعة / 3eib, ma2to3, bayez |
| `not_as_pictured` | Not as pictured or colour different | not as pictured, colour different / مش زي الصورة، اللون مختلف / el lon mokhtalef, mesh zay el sora |
| `wrong_item` | Wrong item sent | wrong item, wrong size sent / منتج غلط، بعتولي غلط / ghalat, mesh elly talabto |
| `damaged_in_shipping` | Damaged in shipping | arrived damaged, crushed / وصل مكسور، الكرتونة / maksoor, et7atam |
| `late_delivery` | Late delivery | late, delayed / تأخير، اتأخر / et2a5ar |
| `changed_mind` | Changed mind | changed my mind, don't want / مش عايز، معجبنيش / mesh 3ayez, ma3gabnish |
| `refused_at_door` | Refused at door (COD) | refused, RTO / رفض الاستلام / rafad, mestalamsh |
| `other` | Other | anything else, or no reason given |

The full lexicon is `assets/reason-lexicon.json`. The merchant can add words per category with `taxonomy_overrides` in setup.

`refused_at_door` is not a return: the customer never accepted the parcel. It is counted separately and never enters return rates.

## 2. Classifying a row

In this order, first hit wins:
1. Type says refused (or RTO): `refused_at_door`.
2. Shopify reason code, when specific: `SIZE_TOO_SMALL` and `SIZE_TOO_LARGE` map to the same keys, `COLOR` and `NOT_AS_DESCRIBED` to `not_as_pictured`, `DEFECTIVE` to `quality_defect`, `WRONG_ITEM` to `wrong_item`, `UNWANTED` and `STYLE` to `changed_mind`. `OTHER` and `UNKNOWN` fall through to the text. If the text clearly says something else, keep the code but list the row as a conflict for the merchant.
3. Lexicon on the free text (reason, notes, customer note):
   - Normalise: lowercase; remove Arabic diacritics and tatweel; أ إ آ become ا; ة becomes ه; ى becomes ي; drop apostrophes; collapse any repeated letter to one (kbeeer = kbeer, واااسع = واسع). Apply the same to the keywords.
   - Latin keywords match whole words or phrases; Arabic keywords match anywhere in the text (to allow prefixes like ال، و، ب).
   - Longest keyword first. A shorter keyword that overlaps a longer match is ignored ("مقاس غلط" is fit, its "غلط" does not also count as wrong item; "too small" counts once, not also "small").
   - Negation: a size keyword right after a negator does not count ("not small enough", "isn't small", "مش صغير", "مو ضيق", "mesh soghayar", "ma soghayar" are not "too small"). Negators: not, isn't, wasn't, aren't, never, مش, مو, ما, مب, mesh / msh / mish, ma / mo. Only for too small and too large: in "does not fit" the negation is the complaint itself.
   - The category with the most matches wins. Ties go by priority: refused, wrong item, damaged, quality, too small, too large, not as pictured, late, fit, changed mind.
   - A refused match on the text also makes the row a refusal.
4. Still nothing: `other`. If the row has text, it is a leftover.

**Leftovers: you (the agent) classify them.** Read each leftover text, pick one category, and write `row,category` lines to an overrides CSV. Show the merchant a short table (text, your category) and ask them to confirm or correct before the final run. In a scheduled or unattended run, apply your classification and mark it "classified by the assistant, not confirmed".

## 3. The cohort window (timing matters)

Return rate compares returns with the sales they came from, so both sides use the ORDER date:

- Maturity date = analysis date - (return window days + transit buffer days). Default 14 + 7 = 21 days. Orders after it may still be returned.
- Window: the `analysis_days` (default 90) ending on the maturity date, or the dates the merchant asks for.
- Units sold = units in non-cancelled orders placed in the window, minus units refused at the door (a refused parcel was never delivered).
- Units returned = units of return rows (refund or exchange) whose order was placed in the window, whatever the return date.

Rows whose order is outside the window are dropped (and counted in a note). Rows whose order cannot be found and have no order date are dropped from rates (and counted in a note). If the merchant insists on a window that ends after the maturity date, say the rate is understated.

Report the dates the orders file actually covers inside the window, not just the window: if the window is 90 days but the orders file starts 20 days before its end, the report period is those 20 days, with a note "the orders file covers only 20 of the 90 days".

Refused at the door, from an orders export: same rule as the cod-rto-analysis skill. An order tagged with a refused tag, or cancelled (or voided) AFTER it was fulfilled, is a refusal: the parcel went out and came back. An order cancelled before fulfilment is neither a return nor a refusal. A refused COD order has no refund: the uncollected amount is not money lost to refunds.

## 4. Rates

For any group (product, variant, size, colour, vendor):

return rate = units returned / units sold x 100, rounded to 1 decimal.

- Variant key = SKU, or "Product - Variant" when there is no SKU.
- Product = `Lineitem name` up to the last " - ".
- Size and colour come from the variant title split on " / " (slash with spaces, Shopify's separator; a bare "/" belongs to the value, as in the shoe size 36/37): a part that looks like a size (XS-XXXL, 2XL-6XL, numbers like 38 or 42.5, Free size, kids ages like 2-3Y) is the size, the first other part is the colour. Setup `size_option` / `colour_option` (1, 2 or 3) override this. Colours are grouped ignoring case and shown in Title Case ("red" and "RED" are one row, "Red").
- Small sample guard: a group with fewer than `min_units_sold` (default 20) units sold is marked "small sample" and never ranked as a product to fix. A product also needs at least `min_returns` (default 3) returned units to be ranked.
- Exchanges count as returns in the rate (the item came back). Refund units and exchange units are always shown separately.

## 5. Money lost

Per return row (not refusals):

- **Refunded**: the refund amount on the row.
- **Return shipping**: the row's return shipping cost if given; else `default_return_shipping_cost` per return shipment, split across the rows of that shipment by units. A shipment is one return id (or one order and type).
- **Exchange reshipping**: for exchanges, `exchange_reship_cost` per shipment (defaults to the return shipping cost), split the same way.
- **Restocking loss**: units x unit cost x unsellable share for the reason. Default shares: quality or defect 100%, damaged in shipping 100%, wrong item 0%, late delivery 0%, all others 5%. Setup `unsellable_share` overrides per reason. No unit cost: not included, with a note.
- **Handling**: `handling_cost_per_return` per shipment (default 0).

Money lost = refunded + return shipping + exchange reshipping + restocking loss + handling. The refunded part is revenue given back; the rest is cost on top. Show both parts.

## 6. Products to fix

Products that pass the sample guard, sorted by money lost (then units returned). Top `top_n` (default 10). For each:
- top reason = the reason with the most returned units, ignoring `other` when any named reason exists; its share = units with that reason / units returned. If "too small" and "too large" tie for the most units, do not pick one: the top reason is "Inconsistent sizing between batches" (share = too small + too large units / units returned), because shifting the size chart either way would make half the customers worse off.
- the fix = the fix text for that reason in the lexicon:

| Top reason | Fix |
|---|---|
| Size too small | Runs small: shift the size chart one size (tell customers to size up) and recheck the supplier spec sheet. |
| Size too large | Runs large: shift the size chart one size down and recheck the spec sheet. |
| Fit (other) | Add model height and size worn, garment length and sleeve, fit notes. |
| Quality or defect | Raise with the supplier with photos and counts; add a quality check before dispatch. |
| Not as pictured | Reshoot in daylight with true colour, fix colour names, add an unedited photo. |
| Wrong item | Check SKU labels and shelf position; add a scan or second check at packing. |
| Damaged in shipping | Better packaging; claim from the courier with photos. |
| Late delivery | Check courier times for the affected areas; show realistic delivery dates. |
| Changed mind | Check description and photos set the right expectation; offer exchange or store credit first. |
| Inconsistent sizing between batches | Measure units from different batches against the size chart and the supplier spec sheet; fix it with the supplier before shifting the chart. |

For size and fit reasons also show the return rate per size of that product, so the merchant sees which sizes drive it (for example "M 50%, L 33%": the M pattern is off).

A combined pattern is worth saying in words: if a product's returns split between "too small" and "too large", the size chart is fine but the fit is inconsistent between batches (a supplier issue).

## 7. Trends and exchanges

- Trend: for each order month, units sold, units returned from those orders, rate, main reason. Months that end after the maturity date are marked "still coming in".
- Exchanges vs refunds: units of each overall and per reason. A high exchange share on size reasons means customers like the product but the size guide fails them.

## 8. Estimated saving (dashboard scenario)

Estimated saving for a product = its money lost x the share of returns the merchant expects the fix to prevent (default 30%). When the merchant changes "return shipping per return", each product's money lost is recomputed first: money lost - its return shipping in the data + shipping per return x its return shipments (a shipment with several products is split by units), and the store total uses shipping per return x all return shipments. Always labelled as an estimate with the assumption shown.
