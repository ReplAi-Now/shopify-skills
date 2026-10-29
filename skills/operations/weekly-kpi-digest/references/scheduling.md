# Scheduling the weekly digest

The digest should run by itself once a week, the morning after the week ends (for Saturday-start weeks, Saturday morning covers Saturday to Friday). A scheduled run never asks questions: it reads the saved setup, gets the data, writes the output and stops. If something is missing it writes a short note saying exactly what, instead of guessing.

## The prompt to schedule

Use the same prompt everywhere, with the merchant's folder:

> Run the weekly-kpi-digest skill for the last complete week using my saved setup in replai-setup/weekly-kpi-digest.json. Do not ask questions. Deliver it the way the setup says.

In chat apps without files, paste the setup card into the scheduled prompt instead of the file path.

## Claude Code and Claude Cowork

Use the built-in scheduled tasks (the `/schedule` command, or "schedule this weekly" in Cowork's task panel). Give it:
- the prompt above,
- the working folder that holds `replai-setup/` and `replai-exports/`,
- a weekly cron such as `0 9 * * 6` (Saturday 09:00) in the merchant's timezone.

The task needs the Shopify connector available to it, or fresh exports in `replai-exports/`. Run it once by hand right after creating it to prove it works.

Claude Code CLI on the merchant's own computer can also use the system scheduler:
```
0 9 * * 6 cd /path/to/brand-folder && claude -p "Run the weekly-kpi-digest skill ... Do not ask questions."
```

## Claude.ai

If the merchant's plan shows scheduled tasks, use them with the prompt above and the Shopify connector enabled. Otherwise: create a Project, put the setup card in the project instructions, and each week open a new chat in that project and type "run my weekly digest". A weekly calendar reminder makes this a 10-second habit.

## ChatGPT

Use Tasks: in a chat, type "Every Saturday at 9:00, run the weekly-kpi-digest skill with this setup: <paste setup card>. Do not ask questions." ChatGPT keeps the task and runs it on schedule; it needs a connected Shopify app to fetch data. Without a connector, scheduled runs cannot get fresh exports, so use the manual fallback.

## Gemini, Cursor, Codex and others

If the app has scheduled actions, use the prompt above. If not, use the manual fallback.

## Manual fallback (works everywhere)

1. Set a weekly calendar reminder: "Weekly digest".
2. Export orders (and inventory if used) as described in [data-sources.md](data-sources.md).
3. Open the agent in the brand folder (or a chat with the setup card) and type "run my weekly digest".

## Rules for a scheduled (non-interactive) run

- No setup found: do not start the interview. Write `replai-reports/weekly-digest-SETUP-NEEDED.md` (or reply in the chat) saying setup is needed and how to start it, then stop.
- No connector and no export covering the report week: write a short note listing the missing file and the export path, then stop.
- Analytics unavailable: run the digest without sessions and conversion rate, with the note.
- Delivery `email_draft`: create the draft only. Never send. The merchant sends it after reading.
- Never change anything in the store during a scheduled run.
