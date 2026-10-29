# Maintaining this repo

Skills live at `skills/<bucket>/<skill-name>/SKILL.md`. Buckets: `support/` (talking to customers), `store/` (the storefront and catalog) and `operations/` (profit, deliveries, returns, stock).

When you add, rename or remove a skill, update all four in the same change:

1. The top-level `README.md`: the download link in the Claude install block, and the entry under Reference, with the skill name linked to its `SKILL.md`.
2. The bucket's `README.md`.
3. The `skills` array in `.claude-plugin/plugin.json`.
4. Remove it from "Coming Soon" in `README.md` if it was listed there.

Then run `claude plugin validate .` (skip `--strict`: it fails on this file sitting at the plugin root, which is meant for maintainers, not plugin users).

The frontmatter `name` must match the folder name. Keep `description` under 200 characters, because older Claude.ai builds reject longer ones.

The readers are shop owners, not developers. Use plain words in skills and in what they tell the model to write. No em dashes in any prose: rewrite the sentence with a comma, colon, full stop or parentheses instead.

To release, bump `version` in `.claude-plugin/plugin.json`, commit, then push a tag `vX.Y.Z`. The Release workflow attaches one zip per skill, which is what the README's download links point at.

## The skills pack (store and operations skills with scripts)

The ten skills listed in `pdf/content.json` are the free skills pack: each has a first-run setup, a Safety section, Python scripts and tests. Read `CONVENTIONS.md` (pack rules) and `SPECS.md` (locked scope) before changing one.

- `python3 tools/lint.py` checks every skill (spec, description length, dashes, private leftovers, file references; pack rules for the pack skills).
- `python3 -m unittest discover tests` runs the tests. Scripts are Python 3.9+ standard library only. `shared/tabular.py` is copied verbatim into each pack skill's `scripts/`; edit the shared copy and re-copy.
- `python3 pdf/build.py` rebuilds the lead magnet PDFs into `pdf/out/` (git ignored). The install line reads each skill's bucket folder from the repo, so rebuild after moving a skill.

## Invariants (rules learned from bugs)

- Read both spellings of renamed Shopify export headers: `Cancelled at`/`Canceled at`, `Handle`/`URL handle`, `Variant SKU`/`SKU`, `Option1 Value`/`Option1 value`/`Option 1 Value`. Shopify renamed them in 2026 exports and the skills silently misread orders.
- A missing unit cost is unknown, never 0. Showing "EGP 0" or a profit number without costs misleads the merchant.
- On COD stores a failed delivery is usually "fulfilled + cancelled + voided", not a tag. Every skill must use the same failed/delivered rules as `cod-rto-analysis`.
- Status words must be matched as negation-aware phrases: "لم يتم التسليم" contains "تم التسليم", "Out for delivery" contains "deliver".
- `Publication.name` is deprecated (API 2026-10) and connectors refuse deprecated fields: use `catalog { title }`.
- Magnific Seedream 5 Pro has no 4:5 ratio; house-model candidate prompts must force the full head in frame.
- Never put real merchant data in tests or fixtures.
