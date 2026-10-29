# Conversion checklist (50 checks)

Use the ID, area and title exactly as below in `findings.json`. For each check record `status` (pass, fail, partial, na, unknown). For fail and partial also record `impact`, `effort`, `evidence` (`url` + what you saw) and `fix` (the exact change). Default impact and effort are given; change them when the evidence says so (for example a missing size chart is high impact for a clothing store, na for a perfume store).

Effort scale: **low** = under 30 minutes, settings or text, no code. **medium** = theme editor blocks, an app setting, or a batch of content edits. **high** = theme code, a new app, photography, or a process change.

`change_type` tells Phase 2 how the fix is made: `theme` (duplicate theme only), `content` (connector, confirmed batch), `setting` (merchant clicks in admin), `app`, `manual` (merchant work like photos).

Pages to look at: home, one top collection, 3 top product pages, cart, and checkout up to the first step (never type personal data or submit anything).

## Speed (area: speed)

Measured with PageSpeed Insights, see [pagespeed.md](pagespeed.md). `scripts/psi_summary.py` pre-fills S1-S5.

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| S1 | Mobile speed score | PSI mobile performance: 90+ pass, 50-89 partial, under 50 fail | high | medium | Work through the top PSI opportunities |
| S2 | Main content shows fast (LCP) | Field p75 if present, else lab: 2.5 s or less pass, up to 4 s partial | high | medium | Compress and size the hero/main product image, do not lazy-load it, no autoplay slider above the fold |
| S3 | Page does not jump while loading (CLS) | 0.1 or less pass, up to 0.25 partial | medium | medium | Fixed image dimensions, reserve space for bars and app widgets |
| S4 | Taps respond quickly (INP, or TBT in the lab) | INP 200 ms or less pass; TBT 200 ms or less pass | medium | high | Remove unused apps, delay chat widgets and trackers |
| S5 | Images compressed and sized for phones | PSI image savings: 0 pass; under 1 s and 500 KB partial | medium | low | Re-upload images under about 300 KB, use theme image width filters |
| S6 | Few third-party scripts | Count app scripts in page source / PSI third-party list; more than 10 third-party domains is a fail | medium | medium | Uninstall unused apps (and remove their leftover code on the duplicate theme) |

## Mobile at 390 px (area: mobile)

Open each page at 390 px wide in the browser tool, or ask the merchant for phone screenshots.

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| M1 | No sideways scrolling | `document.documentElement.scrollWidth` greater than 390 is a fail; note the element | high | medium | Fix the overflowing element (wide tables, fixed-width images, long words) |
| M2 | Buttons and links easy to tap | Main buttons at least 44 px tall, links not crowded | medium | low | Theme settings: button size; spacing in header and footer |
| M3 | Text readable without zoom | Body text at least 16 px, good contrast | medium | low | Theme typography settings |
| M4 | No pop-up covering the page on arrival | A newsletter/discount pop-up within 5 seconds that fills the screen is a fail | medium | low | Delay to exit intent or 30 seconds, make it a small bar on mobile |
| M5 | Add to cart visible without scrolling far | On product pages the button is within the first 1.5 screens | high | medium | Move price, variants and the button above long descriptions |

## Product page (area: product)

Check all 3 top product pages; one bad page out of 3 is a partial.

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| P1 | At least 4 photos, including one on a person or in use | Count images (`/products/<handle>.js` lists them) | high | high | Add on-model and detail photos |
| P2 | Photos can be zoomed or opened full screen | Tap the main image on mobile | medium | low | Theme product section setting: image zoom / lightbox |
| P3 | Price clear and honest | Price near the title, currency shown, compare-at price only when it is a real previous price | high | low | Fix currency format; remove fake compare-at prices |
| P4 | Size chart (clothing and shoes) | A readable chart on the product page at 390 px, not a blurry image | high | low | Use the size-chart-builder skill |
| P5 | Delivery time near Add to cart | "Delivered in 2-4 days" style line within one screen of the button | high | low | Text block under the button (theme copy) |
| P6 | Cash on delivery shown near Add to cart | COD availability stated near the button (Egypt/GCC shoppers look for it first) | high | low | Text or icon block under the button |
| P7 | Shipping cost stated before checkout | Cost or free-shipping threshold visible on product or cart page | high | low | Announcement bar or block with the real rates |
| P8 | Returns or exchange summary near Add to cart | One line plus link to the policy | medium | low | Text block with link |
| P9 | Reviews visible with a count | Stars and number near the title; real reviews only | high | medium | Reviews app; ask past buyers for reviews |
| P10 | Description easy to scan | Bullets for material, fit, care, dimensions; not one long paragraph | medium | medium | Rewrite in brand voice via connector |
| P11 | Variant choice clear | Swatches or buttons, sold-out variants marked, chosen option visible | medium | medium | Theme variant picker setting: buttons/swatches |
| P12 | Stock and urgency messages are honest | No fake countdowns, "only 2 left" that never changes, or fake "X people viewing" | medium | low | Remove fake urgency apps; show real stock only |
| P13 | Sticky Add to cart on mobile | A bar with the button stays visible while scrolling on a phone | medium | medium | Theme setting if available, else a small section on the duplicate theme |

## Trust (area: trust)

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| T1 | Contact details easy to find | Phone or email in footer or a contact page | medium | low | Add to footer menu and contact page |
| T2 | WhatsApp contact works | A WhatsApp button or link that opens `wa.me/<country code + number>` with the right number | high | low | Fix the link; add a floating button on the duplicate theme |
| T3 | Policy pages exist and are linked | Refund, shipping, privacy, terms pages filled and linked in the footer | medium | low | Settings > Policies; footer menu |
| T4 | Payment and COD badges | Payment icons (cards, wallets, COD) in footer or near the button | low | low | Theme footer setting: show payment icons |
| T5 | No leftover placeholder content | No lorem ipsum, demo images, empty pages, "Your headline here", default social links | medium | low | Remove or fill in |

## Navigation and search (area: navigation)

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| N1 | Menu matches how shoppers think | Up to about 7 top items, real categories, no dead links | medium | medium | Rebuild the main menu (connector or Online Store > Navigation) |
| N2 | Search works, including Arabic and typos | Search a product name in English, in Arabic, and with a typo | medium | medium | Add Arabic tags or synonyms to products; a search app if needed |
| N3 | Collection filters and sorting | Filters for size, colour, price on big collections; sort works | medium | low | Search & Discovery app filters; theme setting |
| N4 | Collections are not empty or broken | No empty collections in the menu; prices and sold-out labels clear on cards | medium | low | Hide empty collections; theme card settings |

## Cart and checkout (area: checkout)

Look only. Add one item to the cart, open cart and the first checkout step, read what is asked, then leave. Never type personal data or press pay.

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| C1 | Guest checkout allowed | No forced account creation before checkout | high | low | Settings > Checkout > Customer accounts: optional or not required |
| C2 | No extra required fields | Company, address line 2 not required; postcode not required where shoppers do not use one | high | low | Settings > Checkout > form options |
| C3 | No shipping cost surprise | Shipping cost at checkout matches what was stated earlier | high | low | State rates on product/cart; fix shipping zones |
| C4 | Cash on delivery offered and labelled clearly | COD present in payment methods with a clear name in the store languages | high | low | Settings > Payments > manual payment method named clearly |
| C5 | Cart page clear | Line totals, editable quantity, visible checkout button, delivery estimate | medium | low | Theme cart settings; text block |
| C6 | Phone number collected for delivery | Phone field shown (couriers need it for COD) | medium | low | Settings > Checkout > shipping address phone: required |

## Arabic and RTL (area: arabic). Mark all na if the store is single-language and the market does not need Arabic.

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| A1 | Arabic version and visible language switch | Switch in header; Arabic URLs work (`/ar`) | high | medium | Settings > Languages; Translate & Adapt; theme switch setting |
| A2 | Layout mirrors correctly in Arabic | Text right-aligned, icons and arrows flipped, sliders work, no overlapping | medium | high | Theme RTL fixes on the duplicate theme |
| A3 | Translation quality | No English leftovers, no machine-translation errors, consistent tone | medium | medium | Rewrite in the chosen Arabic style via connector |
| A4 | Arabic font and numbers readable | A real Arabic font (not a fallback), prices and numbers formatted consistently | low | low | Theme typography: Arabic-friendly font |

## SEO basics (area: seo)

| ID | Check | How to see it | Impact | Effort | Typical fix |
|---|---|---|---|---|---|
| E1 | Page titles unique and descriptive | `<title>` under about 60 characters, not "Home" or the default | medium | low | Edit SEO title per page/product |
| E2 | Meta descriptions written | `<meta name="description">` present and specific | low | low | Edit SEO description |
| E3 | Product images have alt text | `alt` on product images not empty or a file name | low | low | Write alt text (connector batch) |
| E4 | No broken links | Internal links on audited pages return 200 (fetch each, note 404s) | medium | low | Fix the link or add a URL redirect |
| E5 | One clear H1 per page | Exactly one `<h1>` with the page or product name | low | medium | Theme heading tags on the duplicate theme |
| E6 | Product structured data | Page source has Product JSON-LD with price and availability | low | medium | Most current themes include it; fix on the duplicate theme if missing |
| E7 | Sitemap and robots fine | `/sitemap.xml` loads; `robots.txt` does not block products or collections | low | low | Remove custom robots rules blocking pages |
