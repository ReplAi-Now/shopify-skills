"""Turn an audit findings JSON into a prioritised fix list and an HTML report.

Usage:
    python3 prioritise.py findings.json [--html report.html] [--csv fixes.csv] [--lang en|ar]

findings.json shape (full example: assets/findings.example.json):
    {"store": "...", "store_url": "https://...", "audited_at": "2026-10-29",
     "speed": {...optional output of psi_summary.py...},
     "checks": [{"id": "P5", "area": "product", "title": "...", "status": "fail",
                 "impact": "high", "effort": "low",
                 "evidence": {"url": "https://...", "seen": "..."}, "fix": "...",
                 "change_type": "theme|content|setting|app|manual"}]}

status: pass | fail | partial | na | unknown. fail and partial need impact, effort,
evidence.url, evidence.seen and fix.

Scoring (see references/method.md):
    impact high=3, medium=2, low=1; effort low=1, medium=2, high=3
    priority = impact x (4 - effort)  -> 1..9
    do_first: 6-9, next: 3-4, later: 1-2
    health score = weighted share of checks passed (pass=1, partial=0.5, fail=0),
                   weight = impact (3/2/1, default 2), na/unknown excluded.
Prints JSON. Exit code 1 if the findings file has errors (nothing is written then).
"""
import argparse, html, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IMPACT = {"high": 3, "medium": 2, "med": 2, "low": 1}
EFFORT = {"low": 1, "medium": 2, "med": 2, "high": 3}
STATUSES = {"pass", "fail", "partial", "na", "unknown"}
AREAS = ["speed", "mobile", "product", "trust", "navigation", "checkout", "arabic", "seo"]
AREA_LABEL = {
    "en": {"speed": "Speed", "mobile": "Mobile (390 px)", "product": "Product page", "trust": "Trust",
           "navigation": "Navigation and search", "checkout": "Cart and checkout", "arabic": "Arabic / RTL",
           "seo": "SEO basics"},
    "ar": {"speed": "السرعة", "mobile": "الموبايل (390 بكسل)", "product": "صفحة المنتج", "trust": "الثقة",
           "navigation": "التنقل والبحث", "checkout": "السلة والدفع", "arabic": "العربية واتجاه الصفحة",
           "seo": "أساسيات الظهور في جوجل"},
}
T = {
    "en": {"title": "Store conversion audit", "health": "Health score", "do_first": "Do first",
           "next": "Next", "later": "Later", "impact": "Impact", "effort": "Effort", "evidence": "What we saw",
           "fix": "Fix", "passed": "Passed checks", "unknown": "Not checked", "speed": "Speed (Google PageSpeed)",
           "top": "Top fixes", "high": "high", "medium": "medium", "low": "low", "partial": "partly",
           "explain": "Health score: share of checks your store passes, with high impact checks counting 3 times "
                      "and low impact once. Impact: how much the problem likely costs you in sales. "
                      "Effort: how much work the fix is (low = under 30 minutes, no code).",
           "footer": "Made with the free ReplAi skills pack", "audited": "Audited", "of": "to fix",
           "na": "n/a", "mobile": "mobile", "desktop": "desktop", "score100": "Score /100",
           "speed_explain": "Score: Google's 0-100 speed rating (90+ good, under 50 poor). "
                            "LCP: seconds until the main image or text shows (good: 2.5 or less). CLS: how much the page jumps while "
                            "loading (good: 0.1 or less). TBT: milliseconds the page is frozen and ignores taps (good: 200 or less)."},
    "ar": {"title": "تقرير تحسين مبيعات المتجر", "health": "درجة صحة المتجر", "do_first": "ابدأ بها",
           "next": "بعد ذلك", "later": "لاحقًا", "impact": "الأثر", "effort": "المجهود", "evidence": "ما لاحظناه",
           "fix": "الحل", "passed": "فحوصات ناجحة", "unknown": "لم تُفحص", "speed": "السرعة (Google PageSpeed)",
           "top": "أهم التعديلات", "high": "عالي", "medium": "متوسط", "low": "منخفض", "partial": "جزئي",
           "explain": "درجة الصحة: نسبة الفحوصات التي ينجح فيها متجرك، والفحوصات عالية الأثر تُحسب 3 مرات "
                      "ومنخفضة الأثر مرة واحدة. الأثر: كم تكلفك المشكلة غالبًا من المبيعات. "
                      "المجهود: حجم العمل المطلوب (منخفض = أقل من 30 دقيقة بدون كود).",
           "footer": "Made with the free ReplAi skills pack", "audited": "تاريخ الفحص", "of": "للإصلاح",
           "na": "لا ينطبق", "mobile": "موبايل", "desktop": "كمبيوتر", "score100": "الدرجة /100",
           "speed_explain": "الدرجة: تقييم جوجل للسرعة من 0 إلى 100 (90 فأكثر جيد، أقل من 50 ضعيف). "
                            "LCP: عدد الثواني حتى تظهر الصورة أو النص الرئيسي (الجيد: 2.5 أو أقل). CLS: مقدار تحرك الصفحة أثناء "
                            "التحميل (الجيد: 0.1 أو أقل). TBT: الملّي ثانية التي تتجمد فيها الصفحة ولا تستجيب للمس (الجيد: 200 أو أقل)."},
}


def norm_level(v):
    return str(v or "").strip().lower()


def canon(v):
    v = norm_level(v)
    return "medium" if v == "med" else v


def validate(data):
    errs = []
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        return ["'checks' must be a non-empty list"]
    seen = set()
    for i, c in enumerate(checks):
        if not isinstance(c, dict):
            errs.append(f"checks[{i}]: must be an object")
            continue
        tag = f"checks[{i}] ({c.get('id', '?')})"
        if not c.get("id"):
            errs.append(f"{tag}: missing id")
        elif c["id"] in seen:
            errs.append(f"{tag}: duplicate id")
        seen.add(c.get("id"))
        if c.get("area") not in AREAS:
            errs.append(f"{tag}: area must be one of {', '.join(AREAS)}")
        st = norm_level(c.get("status"))
        if st not in STATUSES:
            errs.append(f"{tag}: status must be one of {', '.join(sorted(STATUSES))}")
        if st in ("fail", "partial"):
            if norm_level(c.get("impact")) not in IMPACT:
                errs.append(f"{tag}: impact must be high, medium or low")
            if norm_level(c.get("effort")) not in EFFORT:
                errs.append(f"{tag}: effort must be low, medium or high")
            ev = c.get("evidence") or {}
            if not isinstance(ev, dict):
                errs.append(f"{tag}: evidence must be an object with url and seen")
                ev = {}
            if not ev.get("url"):
                errs.append(f"{tag}: evidence.url missing (which page showed the problem)")
            if not ev.get("seen"):
                errs.append(f"{tag}: evidence.seen missing (what exactly was seen)")
            if not c.get("fix"):
                errs.append(f"{tag}: fix missing (the exact change to make)")
    return errs


def priority(c):
    return IMPACT[norm_level(c["impact"])] * (4 - EFFORT[norm_level(c["effort"])])


def bucket(score):
    return "do_first" if score >= 6 else ("next" if score >= 3 else "later")


def analyse(data):
    checks = data["checks"]
    fixes = []
    for c in checks:
        st = norm_level(c.get("status"))
        if st in ("fail", "partial"):
            s = priority(c)
            fixes.append(dict(c, status=st, impact=canon(c["impact"]), effort=canon(c["effort"]),
                              priority=s, bucket=bucket(s)))
    fixes.sort(key=lambda f: (-f["priority"], -IMPACT[f["impact"]], EFFORT[f["effort"]],
                              0 if f["status"] == "fail" else 1, AREAS.index(f["area"]), str(f["id"])))
    for n, f in enumerate(fixes, 1):
        f["rank"] = n

    def score(items):
        num = den = 0.0
        for c in items:
            st = norm_level(c.get("status"))
            if st not in ("pass", "fail", "partial"):
                continue
            w = IMPACT.get(norm_level(c.get("impact")), 2)
            den += w
            num += w * {"pass": 1.0, "partial": 0.5, "fail": 0.0}[st]
        return None if den == 0 else int(round(100 * num / den))

    by_area = {}
    for a in AREAS:
        items = [c for c in checks if c.get("area") == a]
        if items:
            by_area[a] = {"score": score(items),
                          "fail": sum(1 for c in items if norm_level(c.get("status")) == "fail"),
                          "partial": sum(1 for c in items if norm_level(c.get("status")) == "partial"),
                          "pass": sum(1 for c in items if norm_level(c.get("status")) == "pass")}
    counts = {s: sum(1 for c in checks if norm_level(c.get("status")) == s) for s in sorted(STATUSES)}
    return {
        "store": data.get("store", ""), "store_url": data.get("store_url", ""),
        "audited_at": data.get("audited_at", ""), "health_score": score(checks), "areas": by_area,
        "counts": counts,
        "buckets": {b: [f["id"] for f in fixes if f["bucket"] == b] for b in ("do_first", "next", "later")},
        "fixes": fixes,
        "passed": [{"id": c["id"], "title": c.get("title", "")} for c in checks if norm_level(c.get("status")) == "pass"],
        "not_checked": [{"id": c["id"], "title": c.get("title", ""), "why": c.get("note", "")}
                        for c in checks if norm_level(c.get("status")) == "unknown"],
    }


# ------------------------------------------------------------------ html

def nodash(s):
    # Store text quoted as evidence often carries em/en dashes ("Studio Bag \u2013 Store"); the pack's
    # reports never show them, so they become plain hyphens.
    return str(s if s is not None else "").replace("\u2014", "-").replace("\u2013", "-")


def e(s):
    return html.escape(nodash(s))


def safe_url(u):
    u = str(u or "")
    return u if re.match(r"^https?://", u) else ""


def fix_card(f, t, lang):
    url = safe_url(f.get("evidence", {}).get("url"))
    link = f'<a href="{e(url)}" rel="noopener" target="_blank">{e(url)}</a>' if url else e(f.get("evidence", {}).get("url"))
    part = f' <span class="tag warn">{t["partial"]}</span>' if f["status"] == "partial" else ""
    return (f'<article class="fix"><div class="fix-head"><span class="rank">{f["rank"]}</span>'
            f'<h3>{e(f.get("title") or f["id"])}{part}</h3></div>'
            f'<div class="meta"><span class="tag i-{f["impact"]}">{t["impact"]}: {t[f["impact"]]}</span>'
            f'<span class="tag">{t["effort"]}: {t[f["effort"]]}</span>'
            f'<span class="tag area">{e(AREA_LABEL[lang][f["area"]])}</span><span class="id">{e(f["id"])}</span></div>'
            f'<p><strong>{t["evidence"]}:</strong> {e(f["evidence"].get("seen"))}<br><span class="url" dir="ltr">{link}</span></p>'
            f'<p class="fixtext"><strong>{t["fix"]}:</strong> {e(f.get("fix"))}</p></article>')


def speed_block(speed, t):
    if not speed or not speed.get("strategies"):
        return ""
    rows = []
    for name, s in speed["strategies"].items():
        lab = s.get("lab", {})
        label = t.get(name.split(" ")[0], name) + (name[len(name.split(" ")[0]):] if " " in name else "")
        rows.append(f'<tr><th scope="row">{e(label)}</th><td>{e(s.get("performance_score"))}</td>'
                    f'<td>{e(lab.get("lcp_s"))}</td><td>{e(lab.get("cls"))}</td><td>{e(lab.get("tbt_ms"))}</td></tr>')
    return (f'<section><h2>{t["speed"]}</h2><div class="scroll"><table><thead><tr><th></th><th>{t["score100"]}</th>'
            '<th>LCP (s)</th><th>CLS</th><th>TBT (ms)</th></tr></thead><tbody>' + "".join(rows) +
            f'</tbody></table></div><p class="small">{e(t["speed_explain"])}</p></section>')


CSS = """
:root{--bg:#f7f5f0;--card:#fff;--ink:#1d1b18;--mute:#6b665d;--line:#e4dfd4;--hi:#b3261e;--med:#a15c00;--low:#3b6e3b;--acc:#1f4e5f}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#f1ede4;--mute:#a59f93;--line:#34312b;--hi:#ff8a80;--med:#ffb74d;--low:#9ccc9c;--acc:#7fb8c9}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "IBM Plex Sans","IBM Plex Sans Arabic","Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}h1,h2{font-family:"Fraunces",Georgia,serif;font-weight:600;margin:24px 0 8px}
h1{font-size:28px;margin-top:8px}h2{font-size:21px}h3{font-size:17px;margin:0}
.hero{display:flex;flex-wrap:wrap;gap:16px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.score{font:600 44px/1 "Fraunces",Georgia,serif;color:var(--acc)}.small{font-size:13px;color:var(--mute)}
.areas{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:12px}
.area-c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}.area-c b{display:block;font-size:22px}
.fix{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0}
.fix-head{display:flex;gap:10px;align-items:flex-start}.rank{flex:none;width:28px;height:28px;border-radius:50%;background:var(--acc);color:var(--card);display:grid;place-items:center;font-weight:600;font-size:14px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.tag{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:2px 8px}
.i-high{color:var(--hi);border-color:var(--hi)}.i-medium{color:var(--med);border-color:var(--med)}.i-low{color:var(--low);border-color:var(--low)}
.warn{color:var(--med)}.id{font-size:12px;color:var(--mute);align-self:center}.url{font-size:13px;word-break:break-all}
.fix p{margin:6px 0}.scroll{max-width:100%;overflow-x:auto}table{border-collapse:collapse;min-width:100%}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:center;white-space:nowrap}a{color:var(--acc)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}summary{cursor:pointer;font-weight:600}
footer{margin:32px 0 16px;font-size:12px;color:var(--mute);text-align:center}
"""


def render_html(res, speed, lang):
    t = T[lang]
    d = 'dir="rtl" lang="ar"' if lang == "ar" else 'dir="ltr" lang="en"'
    areas = "".join(f'<div class="area-c"><span class="small">{e(AREA_LABEL[lang][a])}</span><b>{e(v["score"]) if v["score"] is not None else t["na"]}</b>'
                    f'<span class="small">{v["fail"] + v["partial"]} {t["of"]}</span></div>' for a, v in res["areas"].items())
    parts = [f'<!doctype html><html {d}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>{e(t["title"])}</title>'
             '<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Sans+Arabic:wght@400;600&display=swap" rel="stylesheet">'
             f'<style>{CSS}</style></head><body><main>',
             f'<h1>{e(t["title"])}</h1><p class="small">{e(res["store_url"] or res["store"])} . {t["audited"]}: {e(res["audited_at"])}</p>',
             f'<div class="hero"><div><div class="small">{t["health"]}</div><div class="score">{e(res["health_score"])}<span class="small">/100</span></div></div>'
             f'<p class="small" style="flex:1;min-width:220px;margin:0">{t["explain"]}</p></div><div class="areas">{areas}</div>']
    top = [f for f in res["fixes"] if f["bucket"] == "do_first"][:5]
    if top:
        parts.append(f'<h2>{t["top"]}</h2>' + "".join(fix_card(f, t, lang) for f in top))
    for b in ("do_first", "next", "later"):
        items = [f for f in res["fixes"] if f["bucket"] == b]
        if b == "do_first":
            items = items[5:]
        if items:
            parts.append(f'<h2>{t[b]}</h2>' + "".join(fix_card(f, t, lang) for f in items))
    parts.append(speed_block(speed, t))
    if res["passed"]:
        parts.append(f'<details><summary>{t["passed"]} ({len(res["passed"])})</summary><ul>' +
                     "".join(f'<li>{e(p["id"])}: {e(p["title"])}</li>' for p in res["passed"]) + "</ul></details>")
    if res["not_checked"]:
        parts.append(f'<details><summary>{t["unknown"]} ({len(res["not_checked"])})</summary><ul>' +
                     "".join(f'<li>{e(p["id"])}: {e(p["title"])} {("(" + e(p["why"]) + ")") if p["why"] else ""}</li>'
                             for p in res["not_checked"]) + "</ul></details>")
    parts.append(f'<footer>{t["footer"]}</footer></main></body></html>')
    return "".join(parts)


def main(argv=None):
    p = argparse.ArgumentParser(description="Prioritise conversion audit findings.")
    p.add_argument("findings"); p.add_argument("--html"); p.add_argument("--csv")
    p.add_argument("--lang", choices=["en", "ar"], default="en")
    a = p.parse_args(argv)
    with open(a.findings, encoding="utf-8") as fh:
        data = json.load(fh)
    errs = validate(data)
    if errs:
        print(json.dumps({"ok": False, "errors": errs}, ensure_ascii=False, indent=1))
        return 1
    res = analyse(data)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(res, data.get("speed"), a.lang))
    if a.csv:
        from tabular import write_csv
        rows = [{"rank": f["rank"], "bucket": f["bucket"], "priority": f["priority"], "id": f["id"],
                 "area": f["area"], "title": f.get("title", ""), "status": f["status"], "impact": f["impact"],
                 "effort": f["effort"], "url": f["evidence"].get("url", ""), "seen": f["evidence"].get("seen", ""),
                 "fix": f.get("fix", ""), "change_type": f.get("change_type", "")} for f in res["fixes"]]
        rows = [{k: nodash(v) for k, v in r.items()} for r in rows]
        write_csv(a.csv, rows, ["rank", "bucket", "priority", "id", "area", "title", "status", "impact",
                                "effort", "url", "seen", "fix", "change_type"])
    res["ok"] = True
    res["html"] = a.html
    res["csv"] = a.csv
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
