# Theme changes: duplicate, edit, preview, publish

Rule: the live theme is never edited. Every theme change goes on a copy, the merchant previews it, and it is published only after an explicit yes. Checked against Shopify docs (Admin GraphQL 2026-10, Shopify CLI theme commands) on Oct 29 2026; if a command or field is rejected, check the current docs (shopify.dev) before trying something else.

## 0. Before you start

- Find the live theme and its ID.
  - CLI: `shopify theme list --store <store>.myshopify.com` (the one with role `live`).
  - GraphQL: `query { themes(first: 20, roles: [MAIN]) { nodes { id name role updatedAt } } }`
  - Manual: Online Store > Themes; the top card is the live theme.
- Write down the live theme ID in the change log (`previous_live_theme_id`). This is the rollback: publish it again.
- Shopify keeps at most 20 themes. If the library is full, ask the merchant which unused theme they want to delete themselves; never delete a theme.

## 1. Duplicate the live theme

Name the copy `ReplAi CRO <date>`.

**Shopify CLI** (merchant or agent with a terminal, logged in with `shopify auth` or a Theme Access password):
```
shopify theme duplicate --store <store>.myshopify.com --theme <live theme id> --name "ReplAi CRO 2026-10-29" --json
```
Add `--force` only in a non-interactive run (it skips the confirmation prompt, it does not touch the live theme). The JSON output gives the new theme `id`. If the CLI is older and has no `duplicate` command, run `shopify upgrade` first, or: `shopify theme pull --theme <live id> --path theme-copy` then `shopify theme push --unpublished --path theme-copy` (creates a new unpublished theme from the files).

**Admin GraphQL** (connector with `write_themes`):
```graphql
mutation Duplicate($id: ID!, $name: String) {
  themeDuplicate(id: $id, name: $name) {
    newTheme { id name role }
    userErrors { code field message }
  }
}
```
Variables: `{"id": "gid://shopify/OnlineStoreTheme/<live id>", "name": "ReplAi CRO 2026-10-29"}`. The copy is created with role `UNPUBLISHED`. A "Maximum number of themes reached" error means the library is full (see step 0).

**Manual** (always works): Online Store > Themes > on the live theme click the three dots (...) > Duplicate. The copy appears in the theme library as "Copy of <name>". Rename it via ... > Rename.

## 2. Make the changes on the copy

Before EVERY write (push, upsert, editor save), re-read the target theme and stop if it is the live one: CLI `shopify theme list` shows role `live`; GraphQL `query { theme(id: "gid://shopify/OnlineStoreTheme/<id>") { id name role } }` must return `UNPUBLISHED`, never `MAIN`. Theme IDs are easy to swap by mistake.

Prefer settings and blocks over code: they are easier to review and survive theme updates.

**Theme editor (manual, or the merchant follows your exact clicks):** Online Store > Themes > the copy > Customize > choose the template (for example Products > Default product) > add or edit a block or setting > Save. Give the merchant numbered clicks and the exact text to paste.

**Shopify CLI (files):**
```
shopify theme pull --store <store>.myshopify.com --theme <copy id> --path work
# edit files in work/ (for example templates/product.json, sections/main-product.liquid, snippets/...)
shopify theme push --store <store>.myshopify.com --theme <copy id> --path work --only templates/product.json --only snippets/replai-cod-note.liquid
```
Always pass `--theme <copy id>`. Never use `--live` or `--allow-live`. Use `--only` so only the changed files are uploaded. `shopify theme check --path work` catches Liquid errors before pushing.

**Admin GraphQL (files):** `themeFilesUpsert` writes up to 50 files per call, but Shopify requires `write_themes` AND a special exemption granted by Shopify to the app. Most connectors do not have it; if the call is refused, use the CLI or the manual route.
```graphql
mutation Upsert($themeId: ID!, $files: [OnlineStoreThemeFilesUpsertFileInput!]!) {
  themeFilesUpsert(themeId: $themeId, files: $files) {
    upsertedThemeFiles { filename }
    job { id }
    userErrors { code field filename message }
  }
}
```
Variables: `{"themeId": "gid://shopify/OnlineStoreTheme/<copy id>", "files": [{"filename": "snippets/replai-cod-note.liquid", "body": {"type": "TEXT", "value": "<p>...</p>"}}]}`

Read a file before changing it (keep the original in the change log):
```graphql
query { theme(id: "gid://shopify/OnlineStoreTheme/<copy id>") { files(filenames: ["templates/product.json"]) { nodes { filename body { ... on OnlineStoreThemeFileBodyText { content } } } } } }
```

**Manual code edit:** Online Store > Themes > the copy > ... > Edit code > open the file > paste > Save.

## 3. Preview and check

- Preview link: `https://<store>.myshopify.com/?preview_theme_id=<copy numeric id>` (CLI: `shopify theme open --theme <copy id>` prints it; admin: ... > Preview, and "Share preview" gives a link that works on the merchant's phone).
- Check each changed page at 390 px and on desktop: no sideways scroll, the new block is where it should be, Arabic version right to left, buttons reachable.
- Send the merchant the preview link with a short list of what changed and where to look.

## 4. Publish (only on an explicit yes)

Ask: "Publish the copy 'ReplAi CRO 2026-10-29' as your live theme? Your current theme stays in the library so we can switch back." Wait for yes.

Before publishing, check the live theme was not edited after the copy was made (compare `updatedAt` from step 0 with now). If it was, the merchant's newer edits would be lost: tell them and redo the duplicate, or copy their edits across.

- CLI: `shopify theme publish --store <store>.myshopify.com --theme <copy id>`
- GraphQL: `mutation { themePublish(id: "gid://shopify/OnlineStoreTheme/<copy id>") { theme { id role } userErrors { code field message } } }`
- Manual: Online Store > Themes > the copy > Publish.

After publishing, load the home page and a product page to confirm, and tell the merchant how to switch back (publish the previous theme from the library). Rerun PageSpeed a day later if speed changes were made.
