# Maintaining this repo

Skills live at `skills/<bucket>/<skill-name>/SKILL.md`. Buckets: `support/` (talking to customers) and `store/` (the storefront).

When you add, rename or remove a skill, update all four in the same change:

1. The top-level `README.md`: the download link in the Claude install block, and the entry under Reference, with the skill name linked to its `SKILL.md`.
2. The bucket's `README.md`.
3. The `skills` array in `.claude-plugin/plugin.json`.
4. Remove it from "Coming Soon" in `README.md` if it was listed there.

Then run `claude plugin validate .` (skip `--strict`: it fails on this file sitting at the plugin root, which is meant for maintainers, not plugin users).

The frontmatter `name` must match the folder name. Keep `description` under 200 characters, because older Claude.ai builds reject longer ones.

The readers are shop owners, not developers. Use plain words in skills and in what they tell the model to write. No em dashes in any prose: rewrite the sentence with a comma, colon, full stop or parentheses instead.

To release, bump `version` in `.claude-plugin/plugin.json`, commit, then push a tag `vX.Y.Z`. The Release workflow attaches one zip per skill, which is what the README's download links point at.
