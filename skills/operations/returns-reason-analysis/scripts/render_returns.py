"""Render the analysis JSON (from analyze_returns.py) as a report or a dashboard.

Usage:
    python3 render_returns.py --analysis analysis.json --format report|dashboard --out PATH

report     Markdown report (PATH .md), leading with the products to fix.
dashboard  One self-contained HTML file (PATH .html), works offline and at 390px wide, with
           scenario inputs: return shipping cost per return, and the share of returns a fix would
           prevent (to estimate the money saved).
For a spreadsheet, run analyze_returns.py with --csv-dir instead.
Python 3 standard library only, no network.
"""
import argparse, html, json

FOOTER = "Made with the free ReplAi skills pack"
LABELS = {
    "size_too_small": "Size too small", "size_too_large": "Size too large", "fit_other": "Fit (other)",
    "quality_defect": "Quality or defect", "not_as_pictured": "Not as pictured or colour different",
    "wrong_item": "Wrong item sent", "damaged_in_shipping": "Damaged in shipping",
    "late_delivery": "Late delivery", "changed_mind": "Changed mind",
    "refused_at_door": "Refused at door (COD)", "other": "Other",
    "size_inconsistent": "Inconsistent sizing between batches",
}


def m(v, cur):
    if v is None:
        return "n/a"
    return f"{v:,.0f} {cur}".strip()


def r(v):
    return "n/a" if v is None else f"{v}%"


def period(w):
    """The order dates the numbers rest on: the covered part of the window when the orders file is shorter."""
    c = w.get("covered")
    if c and c["days"] < c["window_days"]:
        if not c["days"]:
            return f"{w['start']} to {w['end']}, not covered by the orders file"
        return f"{c['start']} to {c['end']}, {c['days']} of the {c['window_days']} days asked for"
    return f"{w['start']} to {w['end']}"


def report(d):
    cur, t = d["currency"], d["totals"]
    w = d["window"]
    out = [f"# Returns: why customers send things back ({period(w)})", ""]
    out += ["## Fix these first", ""]
    if d["top_fixes"]:
        for i, f in enumerate(d["top_fixes"], 1):
            rate = f" ({r(f['return_rate'])} of {f['sold_units']:g} sold)" if f["return_rate"] is not None else ""
            out.append(f"{i}. **{f['product']}**: {f['returned_units']:g} returned{rate}, {m(f['money_lost'], cur)} lost. "
                       f"Main reason: {f['top_reason_label']} ({r(f['top_reason_share'])}). Fix: {f['fix']}")
            if f["by_size"]:
                out.append("   Sizes: " + ", ".join(f"{s['size']} {r(s['return_rate'])}" for s in f["by_size"]))
    else:
        out.append("No product has enough sales and returns to rank yet (see the minimum sample in setup).")
    out += ["", "## The numbers", ""]
    if t.get("return_rate") is not None:
        out.append(f"- Return rate: {r(t['return_rate'])} ({t['returned_units']:g} of {t['sold_units']:g} units sold in orders placed in the window). Return rate means units sent back out of units sold in the same orders.")
    else:
        out.append(f"- Units returned: {t['returned_units']:g} (no orders export, so no return rate).")
    ex = d["exchanges_vs_refunds"]
    out.append(f"- Refunds vs exchanges: {ex['refund_units']:g} refunded units, {ex['exchange_units']:g} exchanged ({r(ex['exchange_share'])} exchanges).")
    mb = d["money_breakdown"]
    out.append(f"- Money lost: {m(t['money_lost'], cur)} = refunds {m(mb['refunded'], cur)} + return shipping {m(mb['return_shipping'], cur)} "
               f"+ exchange reshipping {m(mb['exchange_reship'], cur)} + stock that cannot be resold {m(mb['restock_loss'], cur)} + handling {m(mb['handling'], cur)}.")
    if d["refused_at_door"]["units"]:
        out.append(f"- Refused at the door (COD, not counted as returns): {d['refused_at_door']['units']:g} units.")
    out += ["", "## Reasons", "", "| Reason | Units | Share | Refund | Exchange | Money lost |", "|---|---|---|---|---|---|"]
    out += [f"| {x['label']} | {x['units']:g} | {r(x['share'])} | {x['refund_units']:g} | {x['exchange_units']:g} | {m(x['money_lost'], cur)} |" for x in d["reasons"]]
    for key, head in (("by_size", "size"), ("by_colour", "colour"), ("by_vendor", "vendor")):
        rows = [x for x in d[key] if x.get("sold_units")]
        if rows:
            out += ["", f"## By {head}", "", f"| {head.title()} | Sold | Returned | Rate |", "|---|---|---|---|"]
            out += [f"| {x[head]} | {x['sold_units']:g} | {x['returned_units']:g} | {r(x['return_rate'])}{' (small sample)' if x['low_sample'] else ''} |" for x in rows]
    if d["trend"]:
        out += ["", "## Trend by order month", "", "| Month | Returned | Rate | Main reason |", "|---|---|---|---|"]
        for x in d["trend"]:
            note = "" if x.get("mature", True) else " (still coming in)"
            out.append(f"| {x['month']} | {x['returned_units']:g} | {r(x.get('return_rate'))}{note} | {LABELS.get(x['top_reason'], '')} |")
    if d["notes"]:
        out += ["", "## Data notes", ""] + [f"- {n}" for n in d["notes"]]
    out += ["", f"*{FOOTER}*", ""]
    return "\n".join(out)


CSS = """
:root{--bg:#f6f3ef;--card:#fff;--ink:#22201c;--muted:#6f685e;--line:#e3dcd2;--accent:#a4452c;--soft:#fbeee8}
@media (prefers-color-scheme:dark){:root{--bg:#171513;--card:#211e1b;--ink:#f0ebe4;--muted:#a69e93;--line:#38332d;--accent:#e58a6e;--soft:#3a2721}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans Arabic","IBM Plex Sans",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 40px}h1{font:600 24px/1.25 "Fraunces",serif;margin:0 0 4px}
h2{font:600 17px/1.3 "Fraunces",serif;margin:28px 0 10px}.sub{color:var(--muted);font-size:13px}
.fix{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:12px 14px;margin:8px 0}
.fix b{font-size:16px}.fix .k{color:var(--muted);font-size:13px}.save{background:var(--soft);border-radius:6px;padding:2px 6px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.card .l{color:var(--muted);font-size:12px}.card .v{font-size:22px;font-weight:600}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;background:var(--card);font-size:14px}
th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--muted);font-weight:500}
.ctl{display:flex;flex-wrap:wrap;gap:10px}.ctl label{display:flex;flex-direction:column;font-size:12px;color:var(--muted)}
.ctl input{font:inherit;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);width:170px;min-height:44px}
footer{margin-top:30px;color:var(--muted);font-size:12px}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent),C=D.currency;
const f=v=>Math.round(v).toLocaleString()+' '+C;
function render(){
 const el=document.getElementById('ship'),ship=parseFloat(el.value),def=parseFloat(el.defaultValue);
 const mb=D.money_breakdown,cut=(+document.getElementById('cut').value||0)/100;
 // Shipping as in the data until the merchant changes the input; then shipping per return x shipments.
 const changed=!isNaN(ship)&&ship!==def;
 const shipping=changed?ship*mb.return_shipments:mb.return_shipping;
 const lost=mb.refunded+shipping+mb.exchange_reship+mb.restock_loss+mb.handling;
 document.getElementById('lost').textContent=f(lost);
 let saved=0;document.querySelectorAll('[data-lost]').forEach(e=>{
  const pl=changed?+e.dataset.lost-(+e.dataset.ship)+ship*(+e.dataset.shipments):+e.dataset.lost;
  const s=Math.max(pl,0)*cut;saved+=s;e.textContent='Estimated saving: '+f(s);});
 document.getElementById('saved').textContent=f(saved);
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('input',render));render();
"""


def table(rows, cols):
    e = html.escape
    head = "".join(f"<th>{e(c[0])}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{e(str(c[1](x)))}</td>" for c in cols) + "</tr>" for x in rows)
    return f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>'


def dashboard(d):
    e, cur, t = html.escape, d["currency"], d["totals"]
    w = d["window"]
    fixes = "".join(
        f'<div class="fix"><b>{e(x["product"])}</b> <span class="k">{x["returned_units"]:g} returned'
        f'{" of " + format(x["sold_units"], "g") + " sold (" + r(x["return_rate"]) + ")" if x["return_rate"] is not None else ""}, '
        f'{e(m(x["money_lost"], cur))} lost</span><div>{e(x["top_reason_label"])} ({r(x["top_reason_share"])}): {e(x["fix"])}</div>'
        + (f'<div class="k">By size: {e(", ".join(s["size"] + " " + r(s["return_rate"]) for s in x["by_size"]))}</div>' if x["by_size"] else "")
        + f'<span class="save" data-lost="{x["money_lost"]}" data-ship="{x.get("return_shipping", 0)}" '
          f'data-shipments="{x.get("return_shipments", 0)}"></span></div>' for x in d["top_fixes"]) or "<p>No product has enough sales and returns to rank yet.</p>"
    mb = d["money_breakdown"]
    # Blank (not 0) when no shipping cost is known, so the input does not claim returns ship free.
    default_ship = round(mb["return_shipping"] / mb["return_shipments"], 2) if mb["return_shipments"] and mb["return_shipping"] else ""
    cards = [("Return rate", r(t.get("return_rate"))), ("Units returned", f"{t['returned_units']:g}"),
             ("Exchanges", r(d["exchanges_vs_refunds"]["exchange_share"])),
             ("Refused at door", f"{d['refused_at_door']['units']:g}")]
    maxu = max([x["units"] for x in d["reasons"]] or [1])
    reasons = "".join(f'<tr><td>{e(x["label"])}</td><td>{x["units"]:g}</td><td style="width:40%"><div class="bar"><i style="width:{x["units"] / maxu * 100:.0f}%"></i></div></td><td>{e(m(x["money_lost"], cur))}</td></tr>' for x in d["reasons"])
    parts = [f"<h1>Returns: what to fix</h1><div class=\"sub\">Orders placed {e(period(w))}. Return rate = units sent back / units sold in the same orders.</div>",
             '<h2>Scenario</h2><div class="ctl">'
             f'<label>Return shipping per return ({e(cur)})<input id="ship" type="number" inputmode="decimal" value="{default_ship}"></label>'
             '<label>Returns a fix would prevent (%)<input id="cut" type="number" inputmode="decimal" value="30"></label></div>',
             '<div class="grid" style="margin-top:12px"><div class="card"><div class="l">Money lost to returns</div><div class="v" id="lost"></div></div>'
             '<div class="card"><div class="l">Estimated saving from the fixes below</div><div class="v" id="saved"></div></div>'
             + "".join(f'<div class="card"><div class="l">{e(a)}</div><div class="v">{e(b)}</div></div>' for a, b in cards) + "</div>",
             "<h2>Fix these first</h2>", fixes,
             f'<h2>Reasons</h2><div class="tw"><table><tr><th>Reason</th><th>Units</th><th></th><th>Money lost</th></tr>{reasons}</table></div>']
    for key, head in (("by_size", "size"), ("by_colour", "colour"), ("by_vendor", "vendor")):
        rows = [x for x in d[key] if x.get("sold_units")]
        if rows:
            parts += [f"<h2>By {head}</h2>", table(rows, [(head.title(), lambda x, h=head: x[h]), ("Sold", lambda x: f"{x['sold_units']:g}"),
                                                          ("Returned", lambda x: f"{x['returned_units']:g}"), ("Rate", lambda x: r(x["return_rate"]) + (" (small sample)" if x["low_sample"] else ""))])]
    if d["trend"]:
        parts += ["<h2>Trend by order month</h2>", table(d["trend"], [("Month", lambda x: x["month"]), ("Returned", lambda x: f"{x['returned_units']:g}"),
                                                                       ("Rate", lambda x: r(x.get("return_rate")) + ("" if x.get("mature", True) else " (still coming in)")),
                                                                       ("Main reason", lambda x: LABELS.get(x["top_reason"], ""))])]
    if d["notes"]:
        parts.append("<h2>Data notes</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in d["notes"]) + "</ul>")
    parts.append("<p class=\"sub\">The saving is an estimate: money lost on each product times the share of returns you expect the fix to prevent.</p>")
    parts.append(f"<footer>{FOOTER}</footer>")
    data = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Returns analysis</title><link href=\"https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=IBM+Plex+Sans+Arabic:wght@400;600&display=swap\" rel=\"stylesheet\">"
            f"<style>{CSS}</style></head><body><main>{''.join(parts)}</main><script type=\"application/json\" id=\"data\">{data}</script><script>{JS}</script></body></html>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--format", required=True, choices=["report", "dashboard"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.analysis, encoding="utf-8") as fh:
        d = json.load(fh)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(report(d) if a.format == "report" else dashboard(d))
    print(json.dumps({"written": [a.out]}))


if __name__ == "__main__":
    main()
