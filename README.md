# Skills For Real Shopify Stores

Free AI skills that do the store jobs you keep putting off: calming down angry customers, writing product pages that sell, and more on the way.

They work in Claude (web and desktop app), Claude Code, and most other AI agents. Each skill is one short file you can read in two minutes, so you can see exactly what it does and change it to suit your store.

Made by [ReplAi](https://www.replai.now/?utm_source=github&utm_medium=readme&utm_campaign=shopify-skills), the AI support agent for Shopify stores.

## Installation (2-minute setup)

Pick one route. Installing the same skills twice gives you duplicates.

<details open>
<summary><strong>Claude (web or desktop app)</strong></summary>

1. Download the skills you want:
   - [angry-customer-reply.zip](https://github.com/ReplAi-Now/shopify-skills/releases/latest/download/angry-customer-reply.zip)
   - [product-descriptions.zip](https://github.com/ReplAi-Now/shopify-skills/releases/latest/download/product-descriptions.zip)
2. In Claude, open [Customize > Skills](https://claude.ai/customize/skills) and upload each zip. Don't unzip it first.
3. Check each skill is switched on.

Done. Next time you paste in an angry email or ask for a product description, Claude picks up the skill by itself.

Skills need a paid Claude plan (Pro, Max, Team or Enterprise).

</details>

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude plugin marketplace add ReplAi-Now/shopify-skills
claude plugin install shopify-skills@replai
```

To pick up new skills later, run `claude plugin marketplace update replai`.

</details>

<details>
<summary><strong>Any other agent</strong> (Cursor, Codex, Windsurf and more)</summary>

```bash
npx skills@latest add ReplAi-Now/shopify-skills
```

To update, run `npx skills@latest update`, and re-run `add` to pick up new skills.

</details>

## Why These Skills Exist

Running a store means doing ten jobs at once, with no time to do any of them well. AI can help, but a blank chat box gives you generic answers. A skill gives the AI a proven way to do one job, so you get the same good result every time without writing a long prompt.

### #1: Angry Emails Eat Your Morning

> "Your most unhappy customers are your greatest source of learning."
>
> Bill Gates, Business @ the Speed of Thought

**The Problem**: One furious email can cost you an hour. You draft, delete, redraft, and still worry you sound defensive. Reply badly and it becomes a chargeback or a one-star review.

**The Fix**: [`angry-customer-reply`](./skills/support/angry-customer-reply/SKILL.md). Paste the email, add the order details, and say what you're willing to offer. You get a short, calm reply that fixes the problem, sticks to your policy, and never promises anything you didn't approve.

### #2: Product Pages That Don't Sell

> "On the average, five times as many people read the headline as read the body copy."
>
> David Ogilvy, Confessions of an Advertising Man

**The Problem**: Most product descriptions are a supplier's spec sheet pasted in, or a paragraph of "premium quality" that says nothing. Shoppers skim, don't find their answer, and either leave or email you to ask.

**The Fix**: [`product-descriptions`](./skills/store/product-descriptions/SKILL.md). Give it the product facts and it writes a description shoppers can take in at a glance: an opening line about what they get, benefit-first bullet points, and the details people usually email to ask about. It also writes the SEO title and meta description. It never invents specs.

## Reference

### Support

Skills for talking to customers.

- **[angry-customer-reply](./skills/support/angry-customer-reply/SKILL.md)**: Draft a calm, on-policy reply to an upset customer email, chat message or review.

### Store

Skills for your storefront.

- **[product-descriptions](./skills/store/product-descriptions/SKILL.md)**: Write or rewrite product descriptions that sell, plus the SEO title and meta description.

### Coming Soon

- **returns-policy**: Write a clear returns and refunds page from a few questions.
- **faq-from-tickets**: Turn your past customer emails into an FAQ page.
- **review-replies**: Reply to good and bad reviews in your brand voice.
- **abandoned-cart-emails**: Write an abandoned checkout email sequence.
- **collection-seo-audit**: Check a collection page for the SEO basics and fix what's missing.

To hear when they land, watch this repo (Watch > Custom > Releases).

## Feedback

Skill doing something wrong? [Open an issue](https://github.com/ReplAi-Now/shopify-skills/issues/new) with what you pasted in, what it wrote, and what you expected instead. Ideas for new skills are welcome too.

---

Every question your product page answers is one less support email. For the ones that still arrive, [ReplAi](https://www.replai.now/?utm_source=github&utm_medium=readme&utm_campaign=shopify-skills) answers them for you, using your own store policies.
