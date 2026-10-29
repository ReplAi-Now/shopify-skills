# Skill conventions (read before writing or editing any skill)

This pack is a free lead magnet from ReplAi for e-commerce owners and operators (Egypt and GCC first, Shopify stores, many cash-on-delivery orders). Merchants receive a PDF with a one-line install prompt; their agent installs the skill from this repo. The merchant may be using any agent: Claude Code, Claude Cowork, Claude.ai, ChatGPT, Gemini, Codex, Cursor. Write for all of them.

## Format

- Open Agent Skills format: `skills/<bucket>/<name>/SKILL.md` (buckets: `support/`, `store/`, `operations/`) plus optional `scripts/`, `references/`, `assets/`.
- Frontmatter: `name` (matches folder, lowercase, single hyphens), `description` (max 1024 chars, says what it does AND when to use it, with trigger phrases a merchant would actually type), `license: MIT`, and
  ```yaml
  metadata:
    author: ReplAi
    version: "1.0.0"
  ```
- SKILL.md under 500 lines and roughly 5000 tokens. Long tables, formulas, edge cases and API recipes go in `references/*.md`, one level deep, linked with relative paths.
- First body line after the title: `*by ReplAi (replai.now). Free e-commerce skills pack.*` Reports and dashboards the skill produces end with a small footer `Made with the free ReplAi skills pack`. No sales pitch, no "book a demo", no product claims anywhere.
- Run `python3 tools/lint.py` before you finish. It checks the spec, dashes, private leftovers, broken file references and the shared helper.

## Writing rules

- Never use em dashes or en dashes anywhere (SKILL.md, references, scripts, generated reports). Use periods, commas, colons, parentheses. Ranges use a plain hyphen (10-20).
- Talk to the merchant in the language they write in. Generated store content (titles, descriptions, size charts) uses the language chosen at setup.
- Plain words for non-technical owners. Explain any metric the first time it appears in a report.
- Never invent numbers. If data is missing, say what is missing and what the result would need. Label every estimate as an estimate and state the assumption.
- No personal data in URLs, no data sent anywhere except the merchant's own store and the tools they connected.

## Setup on first run (every skill has a `## Setup` section)

1. Look for saved setup, in this order:
   a. a file `replai-setup/<skill-name>.json` in the current working folder (each brand folder keeps its own setup);
   b. a "setup card" the merchant pasted in the chat (a fenced JSON block starting with `"skill": "<skill-name>"`).
2. If found, read it, say in one line which setup you are using, and continue. If the merchant says "change my setup" or "redo setup", run the interview again, pre-filling current answers.
3. If not found, run the interview: ONE message with numbered questions, each showing its default in brackets. The merchant can reply "defaults" or answer only some numbers. Ask only what changes the output; anything that varies per run (per shoot, per report) is asked per run, not at setup.
4. Save it. With a file system: write `replai-setup/<skill-name>.json` (copy the shape of `assets/setup.example.json`). Without one (chat apps): print the setup card as a fenced JSON block and tell the merchant to paste it at the start of the next chat.
5. Smoke test: one cheap read that proves the setup works (for example read the store name from the Shopify connector, or parse the first rows of the export they gave). Report the result in one line.

`assets/setup.example.json` holds every key with its default and a `"skill"` and `"version"` key. Keep keys flat and readable.

## Data access (in this order)

1. **Shopify connector (MCP)** if the agent has one connected (the official Shopify connector or Shopify AI Toolkit). Prefer read-only queries. Paginate. Never guess IDs.
2. **CSV/XLSX exports** the merchant downloads from Shopify admin or other tools. Every skill that reads store data must work with exports alone. Tell the merchant the exact admin path, e.g. `Shopify admin > Orders > Export > All orders > CSV for Excel`. List the exact columns you rely on in `references/data-sources.md`.
3. Other files the merchant has: courier exports (Bosta, Aramex, J&T, SMSA, Mylerz, R2S, any), Meta/TikTok/Google Ads exports, supplier invoices (PDF, image or sheet). Map columns by meaning, not by exact header, and confirm the mapping with the merchant in one line when unsure.

If the agent cannot connect to anything, the merchant can upload files directly; that path must always work.

## Scripts

- Python 3 standard library only (no pandas, no openpyxl, no pip install). Merchants' machines and chat sandboxes may have nothing else.
- Copy `shared/tabular.py` verbatim into `scripts/` when you need to read CSV/XLSX; import from it (`read_rows`, `pick`, `num`, `write_csv`).
- Scripts do the deterministic math and print JSON (and optionally write CSV). The agent reads the JSON and builds the output the merchant chose. Scripts take file paths as arguments and never touch the network.
- Every script has a docstring with usage, handles missing columns with a clear message naming the column it wanted, and treats blank numbers as 0 only when that is correct (otherwise reports them).
- If the agent cannot run code (some chat apps), SKILL.md must still let it do the work by hand: `references/method.md` explains the method and formulas step by step.
- Tests live outside the skill folder in `tests/<skill-name>/` (`test_*.py`, runnable with `python3 -m unittest discover tests`; each test folder needs an empty `__init__.py`), with small synthetic fixtures whose correct answers were worked out by hand.

## Outputs

Analysis skills ask at setup which output the merchant wants by default, and accept a different choice per run:
- `dashboard`: one self-contained HTML file (no external JS except a pinned CDN chart library if needed), works offline and on a phone (390px wide), with input fields to test scenarios where the skill has assumptions (costs, lead times, targets).
- `spreadsheet`: CSV (or XLSX if the agent can write it) with one tab or file per table.
- `report`: a short written report (Markdown, or PDF/DOCX if the agent can make them) leading with the 3-5 decisions the numbers support.
In chat-only apps, render the report in the chat.

Every output starts with the answer (what to do), then the evidence. Money in the store currency, rounded sensibly. Dates in the merchant's timezone.

## Safety (every skill has a `## Safety` section)

- Read-only by default. Any change to the store, ads or customers (create, edit, delete, publish, price change, discount, message) requires showing the exact list of changes and getting an explicit yes for that list. Approval does not carry to later batches.
- Theme changes are made on a duplicate theme, previewed, and published only on the merchant's yes.
- Never delete data. Never touch payments, payouts or credentials.
- Spend (image credits, paid APIs): quote the estimate before spending and ask when it is above the limit set in setup.

## Market knowledge to build in

- Egypt has 27 governorates; addresses arrive in English, Arabic or Franco-Arabic with many spellings (Cairo, al qahira, القاهرة, Giza, gizeh, الجيزة, 6th of October counted under Giza). GCC uses emirates (UAE), regions (KSA), governorates (Kuwait, Oman, Bahrain). Normalise before grouping.
- COD: orders can be refused at the door, unreachable, or returned to origin (RTO). Couriers charge shipping both ways and a COD fee. Cash arrives later (remittance cycles).
- Currencies: EGP, SAR, AED, KWD, QAR, BHD, OMR, USD. Use the store's currency.
- Seasonality: Ramadan, Eid al Fitr, Eid al Adha, back to school, White Friday / Black Friday, 11.11, payday at month end.
