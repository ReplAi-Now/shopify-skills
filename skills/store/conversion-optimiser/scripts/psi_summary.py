"""Summarise saved Google PageSpeed Insights (API v5) JSON responses.

The agent fetches the API itself (see references/pagespeed.md) and saves each response:
    https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=<page>&strategy=mobile&category=performance
This script never touches the network.

Usage:
    python3 psi_summary.py mobile.json [desktop.json ...]

Pass the home page files first: S1-S5 are suggested from the first mobile file.
Extra pages with the same strategy are kept under "mobile <url>" / "desktop <url>".

Prints JSON: per strategy the performance score (0-100), lab metrics, field metrics
(real Chrome users, when Google has enough data), top opportunities, and suggested
statuses for checklist items S1-S5 that can be pasted into findings.json.

Thresholds (Google's published Core Web Vitals and Lighthouse bands):
    performance score: 90+ pass, 50-89 partial, under 50 fail
    LCP: <= 2.5 s pass, <= 4.0 s partial, else fail
    CLS: <= 0.1 pass, <= 0.25 partial, else fail
    INP (field): <= 200 ms pass, <= 500 ms partial, else fail
    TBT (lab, used when INP field data is missing): <= 200 ms pass, <= 600 ms partial, else fail
    Image savings (S5): 0 pass, under 1000 ms and under 500 KB partial, else fail
"""
import json, sys

IMAGE_AUDITS = ["uses-optimized-images", "modern-image-formats", "uses-responsive-images",
                "offscreen-images", "efficient-animated-content", "image-delivery-insight"]


def band(value, good, poor):
    if value is None:
        return None
    return "pass" if value <= good else ("partial" if value <= poor else "fail")


def savings(audit):
    # Lighthouse 12+ "insight" audits carry time in metricSavings (LCP or FCP) and bytes in
    # details.debugData.wastedBytes or per item, not in overallSavingsMs/Bytes.
    d = audit.get("details") or {}
    m = audit.get("metricSavings") or {}
    ms = d.get("overallSavingsMs") or max(float(m.get("LCP") or 0), float(m.get("FCP") or 0))
    by = d.get("overallSavingsBytes") or (d.get("debugData") or {}).get("wastedBytes") or 0
    if not by and isinstance(d.get("items"), list):
        by = sum(float(i.get("wastedBytes") or 0) for i in d["items"] if isinstance(i, dict))
    return float(ms or 0), float(by or 0)


def summarise(doc):
    lr = doc.get("lighthouseResult")
    if not lr and isinstance(doc.get("error"), dict):
        err = doc["error"]
        hint = (" (the free no-key quota is shared and often used up for the day: use pagespeed.web.dev "
                "or an API key, see references/pagespeed.md)") if err.get("code") == 429 else ""
        raise ValueError(f"PageSpeed API error {err.get('code')}: {err.get('message', '')}{hint}")
    if not lr:
        raise ValueError("no lighthouseResult in file (is this a PageSpeed Insights v5 response?)")
    strategy = (lr.get("configSettings") or {}).get("formFactor") or "unknown"
    url = lr.get("finalDisplayedUrl") or lr.get("finalUrl") or lr.get("requestedUrl") or doc.get("id", "")
    audits = lr.get("audits") or {}

    def nv(key):
        a = audits.get(key) or {}
        return a.get("numericValue")

    perf = ((lr.get("categories") or {}).get("performance") or {}).get("score")
    perf = None if perf is None else int(round(perf * 100))
    lcp_ms, cls, tbt = nv("largest-contentful-paint"), nv("cumulative-layout-shift"), nv("total-blocking-time")
    lab = {"lcp_s": None if lcp_ms is None else round(lcp_ms / 1000, 1),
           "cls": None if cls is None else round(cls, 3),
           "tbt_ms": None if tbt is None else int(round(tbt)),
           "fcp_s": None if nv("first-contentful-paint") is None else round(nv("first-contentful-paint") / 1000, 1),
           "speed_index_s": None if nv("speed-index") is None else round(nv("speed-index") / 1000, 1)}
    fm = (doc.get("loadingExperience") or {}).get("metrics") or {}

    def pct(key):
        m = fm.get(key) or {}
        return m.get("percentile")

    f_lcp, f_inp, f_cls = pct("LARGEST_CONTENTFUL_PAINT_MS"), pct("INTERACTION_TO_NEXT_PAINT"), pct("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    field = {"lcp_s": None if f_lcp is None else round(f_lcp / 1000, 1),
             "inp_ms": f_inp,
             "cls": None if f_cls is None else round(f_cls / 100, 2),  # API reports CLS x100
             "overall": (doc.get("loadingExperience") or {}).get("overall_category")}
    opps = []
    img_ms = img_bytes = 0.0
    for key, a in audits.items():
        ms, by = savings(a)
        if key in IMAGE_AUDITS:
            img_ms += ms
            img_bytes += by
        if (ms > 0 or by > 0) and (a.get("score") is None or a.get("score") < 0.9):
            opps.append({"id": key, "title": a.get("title", key), "savings_ms": int(round(ms)),
                         "savings_kb": int(round(by / 1024))})
    opps.sort(key=lambda o: (-o["savings_ms"], -o["savings_kb"], o["id"]))
    return strategy, {"url": url, "performance_score": perf, "lab": lab, "field": field,
                      "opportunities": opps[:5], "image_savings_ms": int(round(img_ms)),
                      "image_savings_kb": int(round(img_bytes / 1024))}


def suggested(strategies):
    m = strategies.get("mobile") or next(iter(strategies.values()))
    url = m["url"]
    out = []

    def add(cid, title, status, seen, impact, effort, fix):
        if status:
            out.append({"id": cid, "area": "speed", "title": title, "status": status, "impact": impact,
                        "effort": effort, "evidence": {"url": url, "seen": seen}, "fix": fix,
                        "change_type": "theme"})

    ps = m["performance_score"]
    desk = strategies.get("desktop", {}).get("performance_score")
    s1 = None if ps is None else ("pass" if ps >= 90 else ("partial" if ps >= 50 else "fail"))
    add("S1", "Mobile speed score", s1,
        f"PageSpeed mobile performance {ps}/100" + (f", desktop {desk}/100" if desk is not None else "") + " (lab test)",
        "high", "medium", "Work through the top PageSpeed opportunities listed in the speed section, biggest savings first.")
    lcp = m["field"]["lcp_s"] if m["field"]["lcp_s"] is not None else m["lab"]["lcp_s"]
    src = "real users (p75)" if m["field"]["lcp_s"] is not None else "lab test"
    add("S2", "Main content shows fast (LCP)", band(lcp, 2.5, 4.0), f"LCP {lcp} s on mobile, {src}",
        "high", "medium", "Compress and correctly size the first big image (hero or main product photo), do not lazy-load it, and remove slider autoplay above the fold.")
    cls = m["field"]["cls"] if m["field"]["cls"] is not None else m["lab"]["cls"]
    src = "real users (p75)" if m["field"]["cls"] is not None else "lab test"
    add("S3", "Page does not jump while loading (CLS)", band(cls, 0.1, 0.25), f"CLS {cls} on mobile, {src}",
        "medium", "medium", "Give images and banners fixed width and height, and reserve space for announcement bars and app widgets.")
    if m["field"]["inp_ms"] is not None:
        add("S4", "Taps respond quickly (INP)", band(m["field"]["inp_ms"], 200, 500),
            f"INP {m['field']['inp_ms']} ms on mobile, real users (p75)", "medium", "high",
            "Remove or delay heavy apps and third-party scripts (chat widgets, trackers you no longer use).")
    elif m["lab"]["tbt_ms"] is not None:
        add("S4", "Taps respond quickly (TBT as stand-in for INP)", band(m["lab"]["tbt_ms"], 200, 600),
            f"Total blocking time {m['lab']['tbt_ms']} ms on mobile, lab test (no real-user data yet)", "medium", "high",
            "Remove or delay heavy apps and third-party scripts (chat widgets, trackers you no longer use).")
    ims, imk = m["image_savings_ms"], m["image_savings_kb"]
    s5 = "pass" if ims == 0 and imk == 0 else ("partial" if ims < 1000 and imk < 500 else "fail")
    add("S5", "Images compressed and sized for phones", s5,
        f"PageSpeed estimates {ims} ms and {imk} KB could be saved on images", "medium", "low",
        "Re-upload oversized images (aim under 300 KB, about 2000 px wide for product photos) and use the theme's image_url width filters.")
    return out


def main(paths):
    if not paths:
        print(__doc__)
        return 1
    strategies, errors = {}, []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                name, s = summarise(json.load(fh))
            if name in strategies:  # a second page with the same strategy must not overwrite the first
                name = f"{name} {s['url']}"
                if name in strategies:
                    name = f"{name} ({p})"
            strategies[name] = s
        except (ValueError, json.JSONDecodeError, OSError) as ex:
            errors.append(f"{p}: {ex}")
    res = {"strategies": strategies, "errors": errors,
           "suggested_checks": suggested(strategies) if strategies else []}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if errors and not strategies else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
