"""Build a rollback plan from the before/after change log.

Usage:
    python3 rollback.py change-log.json [--batch N]

Log shape (see references/content-edits.md):
    {"store": "example.myshopify.com", "previous_live_theme_id": "gid://shopify/OnlineStoreTheme/1",
     "batches": [{"batch": 1, "approved_at": "2026-10-29T14:05", "approved_text": "yes",
                  "changes": [{"resource": "product", "id": "gid://shopify/Product/1",
                               "title": "Linen shirt", "field": "descriptionHtml",
                               "before": "<p>old</p>", "after": "<p>new</p>", "status": "applied"}]}]}

Prints JSON: the changes to revert, newest first, each with the value to restore
(`restore`) and the value the field must still hold before reverting (`expect_current`).
Only changes with status "applied" are included. The agent must read the current value
first: if it no longer equals expect_current, someone edited it since, so ask the merchant.
A rollback is itself a store change and needs the merchant's yes for the exact list.
"""
import argparse, json, sys

REQUIRED = ["resource", "id", "field", "before", "after"]


def plan(log, batch=None):
    errors, steps = [], []
    batches = log.get("batches") or []
    if batch is not None:
        batches = [b for b in batches if str(b.get("batch")) == str(batch)]  # logs may store "1"
        if not batches:
            errors.append(f"batch {batch} not found")
    for b in sorted(batches, key=lambda x: int(x.get("batch") or 0), reverse=True):
        for i, c in enumerate(reversed(b.get("changes") or [])):
            missing = [k for k in REQUIRED if k not in c]
            if missing:
                errors.append(f"batch {b.get('batch')} change {c.get('id', i)}: missing {', '.join(missing)}")
                continue
            if c.get("status", "applied") != "applied":
                continue
            steps.append({"batch": b.get("batch"), "resource": c["resource"], "id": c["id"],
                          "title": c.get("title", ""), "field": c["field"],
                          "expect_current": c["after"], "restore": c["before"]})
    res = {"store": log.get("store", ""), "steps": steps, "count": len(steps), "errors": errors}
    if log.get("previous_live_theme_id") and batch is None:
        res["theme"] = {"republish_theme_id": log["previous_live_theme_id"],
                        "note": "to undo a theme publish, publish this theme again (it was kept in the theme library)"}
    return res


def main(argv=None):
    p = argparse.ArgumentParser(description="Rollback plan from a change log.")
    p.add_argument("log"); p.add_argument("--batch", type=int)
    a = p.parse_args(argv)
    with open(a.log, encoding="utf-8") as fh:
        res = plan(json.load(fh), a.batch)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
