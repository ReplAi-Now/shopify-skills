# ROADMAP

## Done (Oct 29 2026)
- [x] Locked scope for 10 skills (SPECS.md) and pack conventions (CONVENTIONS.md): Agent Skills format, per-skill setup on first run, Shopify connector or CSV exports, stdlib scripts, read-only by default.
- [x] Built all 10 skills: catalog-photoshoot, shopify-catalog-upload, cod-rto-analysis, true-profit, weekly-kpi-digest, size-chart-builder, returns-reason-analysis, demand-planner, conversion-optimiser, dead-stock-clearance.
- [x] Adversarial QA of every skill by independent reviewers (about 80 bugs fixed, each with a regression test).
- [x] Real-export QA (read-only, live COD store, data kept out of the repo): Shopify 2026 header renames, unknown-not-zero costs, failed-delivery rules aligned across skills.
- [x] Live photoshoot test on Magnific: house model creation, generation, QA loop with one redo (hem length).
- [x] Shared money parser handles GCC/Arabic formats and UTF-16 files.
- [x] Branded PDFs (pdf/build.py): one 2-page PDF per skill plus the full pack, ReplAi brand system.
- [x] 257 tests passing, lint clean on all 10 skills.
- [x] Merged into ReplAi-Now/shopify-skills (Adam's repo) in the bucket layout: 4 skills in `store/`, 6 in new `operations/`; descriptions cut to 200 chars (full trigger text kept in each body); PDFs point at the real repo.

## Next
- [ ] Tag a release (bump done to 1.1.0 in plugin.json; push tag `v1.1.0`) so the README zip download links work for the 10 new skills.
- [ ] README "Why these skills exist" section only covers the first two skills; add entries for the new ones if wanted (real quotes only).
- [ ] Arabic versions of the PDFs (being curated by the ReplAi team).
- [ ] Live write-path test of shopify-catalog-upload on a dev store (only tested read-only so far).
- [ ] Higgsfield generation test (workspace was out of credits; upload, element creation and cost check verified).
- [ ] Product decision: dead-stock default sell-through assumptions per tactic (markdown 60, bundle 40, gift 50, clearance 25, liquidate 100) are estimates.
- [ ] Validate seasonal calendar windows (Ramadan, Eid, White Friday) with someone in-market.

## Known issues
- Demand dashboard cash differs from the script by about 0.15% (demand rounded to 3 decimals in the browser).
- Courier from tags takes the first matching tag when an order carries two couriers.
- cod-rto treats a "returned" tag as failed delivery by default while returns-reason-analysis treats it as a return.
- WEBP files in simple VP8/VP8L format are not measured by the photoshoot batch planner (tiny ones treated as swatches).
- The Shopify product description editor may strip some size-chart HTML (`details`, sticky column); page and metafield placements are unaffected.
