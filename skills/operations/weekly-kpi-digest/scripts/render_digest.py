"""Render a digest JSON (from kpi_digest.py) into the merchant's chosen output.

Usage:
    python3 render_digest.py --digest digest.json --format report|dashboard|spreadsheet|email --out PATH

report       Markdown one-pager (PATH is a .md file). Also what you paste into a chat.
dashboard    One self-contained HTML file (PATH is a .html file), works offline and at 390px wide,
             with inputs to change the flag thresholds and weekly targets.
spreadsheet  PATH is a folder; writes kpis.csv, top_products.csv, bottom_products.csv,
             inventory_warnings.csv.
email        Plain-text email DRAFT (PATH is a .txt file, first line "Subject: ..."). It is never
             sent by this script.

Prints a JSON line with the files written. Python 3 standard library only, no network.
"""
import argparse, html, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import write_csv  # noqa: E402

FOOTER = "Made with the free ReplAi skills pack"

DEFS = {
    "net_sales": "Net sales: what customers paid for products (after discounts, before shipping and tax) minus refunds on those orders. Cancelled orders are left out.",
    "aov": "Average order value: product sales before refunds divided by the number of orders.",
    "new_customers": "New customers: people (by email, else phone) whose first ever order was this week. Returning: they had ordered before.",
    "discount_share": "Discount share: discounts as a percentage of sales before discounts.",
    "refund_rate": "Orders with a refund: share of this week's orders that have any refund so far.",
    "cod_share": "COD share: share of orders paid cash on delivery.",
    "cod_delivery_success": "COD delivery success: delivered COD orders divided by COD orders with a final result (delivered or failed). Orders still in transit are left out. A COD order paid after fulfilment counts as delivered; one cancelled or voided after fulfilment (a refused parcel) counts as failed.",
    "cancelled_orders": "Cancelled before shipping: orders cancelled before they were handed to the courier. Failed deliveries recorded as cancellations are not in this count.",
    "failed_deliveries": "Failed deliveries: orders that were shipped and came back (refused, unreachable, returned to origin), from failed tags, a courier export, or a cancellation or void after fulfilment. Like cancelled orders, they are left out of orders and net sales when Shopify shows them cancelled.",
    "returned_units": "Returned units (restocked): items customers sent back and you restocked, from the Shopify connector. Counts returns with no refund too (Try & Buy, exchanges).",
    "conversion_rate": "Conversion rate: share of store visits (sessions) that ended in an order, from Shopify analytics.",
    "pp": "pp means percentage points: 5.0% to 1.8% is a change of -3.2 pp.",
}


def money(v, cur):
    if v is None:
        return "n/a"
    s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.2f}"
    return f"{s} {cur}".strip()


def value(k, v, cur):
    if v is None:
        return "n/a"
    if k["kind"] == "money":
        return money(v, cur)
    if k["kind"] == "rate":
        return f"{v}%"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


def change(c):
    if not c:
        return "n/a"
    part = " (partial)" if c.get("partial") else ""
    if c["change"] is None:
        return "new" + part          # previous week was 0, this week is not
    if c["change"] == 0:
        return "no change" + part
    sign = "+" if c["change"] > 0 else ""
    flag = " (!)" if c["flag"] else ""
    return f"{c['arrow']} {sign}{c['change']}{' pp' if c['unit'] == 'pp' else '%'}{flag}{part}"


def title(d):
    name = d.get("store_name") or "Your store"
    w = d["weeks"]["this"]
    return f"{name}: weekly digest {w['start']} to {w['end']}"


def report(d):
    cur = d["currency"]
    out = [f"# {title(d)}", ""]
    out += ["## Act on this", ""] + [f"{i}. {a['text']}" for i, a in enumerate(d["act_on"], 1)] + [""]
    out += ["## Key numbers", "",
            "| KPI | This week | Last week | vs last week | 4 weeks ago | vs 4 weeks ago |",
            "|---|---|---|---|---|---|"]
    for k in d["kpis"]:
        out.append(f"| {k['label']} | {value(k, k['this'], cur)} | {value(k, k['last'], cur)} | "
                   f"{change(k['vs_last'])} | {value(k, k['four_weeks_ago'], cur)} | {change(k['vs_four_weeks_ago'])} |")
    out += ["", f"(!) marks a change of at least {d['thresholds']['pct']}% (or {d['thresholds']['pp']} percentage points for rates)."
            + (" (partial) marks a comparison with a week the data only partly covers." if d.get("partial_weeks") else ""), ""]
    for key, head in (("top_products", "Top 5 products"), ("bottom_products", "Bottom 5 products")):
        if d.get(key):
            out += [f"## {head}", "", "| Product | Units | Revenue | Last week |", "|---|---|---|---|"]
            out += [f"| {p['product']} | {p['units']:g} | {money(p['revenue'], cur)} | {money(p['last_week_revenue'], cur)} |" for p in d[key]]
            out.append("")
    if d.get("inventory_warnings"):
        out += [f"## Stock running out (under {d['inventory_cover_days']} days)", "",
                "| Variant | SKU | Available | Sold per day | Days left |", "|---|---|---|---|---|"]
        out += [f"| {i['name']} | {i['sku']} | {i['available']:g} | {i['per_day']} | {i['days_of_cover']} |" for i in d["inventory_warnings"]]
        out.append("")
    if d.get("notes"):
        out += ["## Data notes", ""] + [f"- {n}" for n in d["notes"]] + [""]
    shown = {k["key"] for k in d["kpis"]}
    out += ["## What the numbers mean", ""] + [f"- {DEFS[k]}" for k in DEFS if k in shown or k == "pp"] + [""]
    out += [f"Weeks start on {d['week_start'].title()}, timezone {d['timezone']}.", "", f"*{FOOTER}*", ""]
    return "\n".join(out)


def email(d):
    cur = d["currency"]
    lines = [f"Subject: {title(d)}", "", "Act on this:"]
    lines += [f"{i}. {a['text']}" for i, a in enumerate(d["act_on"], 1)]
    lines += ["", "Key numbers (this week, change vs last week):"]
    lines += [f"- {k['label']}: {value(k, k['this'], cur)} ({change(k['vs_last'])})" for k in d["kpis"]]
    if d.get("notes"):
        lines += ["", "Notes:"] + [f"- {n}" for n in d["notes"]]
    lines += ["", FOOTER, ""]
    return "\n".join(lines)


CSS = """
:root{--bg:#f7f4ee;--card:#fff;--ink:#1d1b18;--muted:#6b665d;--line:#e4ded3;--up:#1f7a4d;--down:#b3362b;--flag:#fff2d6;--accent:#2b4c7e}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#f1ede6;--muted:#a59f94;--line:#35332e;--up:#5fc28f;--down:#ef7d71;--flag:#3a3020;--accent:#8fb0e3}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans Arabic","IBM Plex Sans",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 40px}h1{font:600 24px/1.25 "Fraunces",serif;margin:0 0 4px}
h2{font:600 17px/1.3 "Fraunces",serif;margin:28px 0 10px}.sub{color:var(--muted);font-size:13px}
.act{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:12px 14px;margin:8px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.card.flag{background:var(--flag)}
.card .l{color:var(--muted);font-size:12px}.card .v{font-size:22px;font-weight:600;margin:2px 0}.good{color:var(--up)}.bad{color:var(--down)}
.card .c{font-size:13px}.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;background:var(--card);font-size:14px}
th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--muted);font-weight:500}
.ctl{display:flex;flex-wrap:wrap;gap:10px}.ctl label{display:flex;flex-direction:column;font-size:12px;color:var(--muted)}
.ctl input{font:inherit;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);width:150px;min-height:44px}
footer{margin-top:30px;color:var(--muted);font-size:12px}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const fmt=(k,v)=>v==null?'n/a':k.kind==='money'?Math.round(v).toLocaleString()+' '+D.currency:k.kind==='rate'?v+'%':Number(v).toLocaleString();
function render(){
 const tpct=+document.getElementById('tpct').value||D.thresholds.pct, tpp=+document.getElementById('tpp').value||D.thresholds.pp;
 const g=document.getElementById('cards');g.innerHTML='';
 D.kpis.forEach(k=>{const c=k.vs_last;let cls='',txt='n/a',flag=false;
  if(c&&c.change===null){txt='new vs last week';}
  else if(c&&c.change===0){txt='no change vs last week';}
  else if(c){flag=Math.abs(c.change)>=(c.unit==='pp'?tpp:tpct);const good=k.polarity*Math.sign(c.change);
   cls=good>0?'good':good<0?'bad':'';txt=c.arrow+' '+(c.change>0?'+':'')+c.change+(c.unit==='pp'?' pp':'%')+' vs last week';}
  if(c&&c.partial){txt+=' (partial)';}
  const t=document.getElementById('t_'+k.key);let tg='';
  if(t&&+t.value&&k.this!=null){tg='<div class="c">'+Math.round(k.this/ +t.value*100)+'% of target</div>';}
  const el=document.createElement('div');el.className='card'+(flag?' flag':'');
  el.innerHTML='<div class="l">'+k.label+'</div><div class="v">'+fmt(k,k.this)+'</div><div class="c '+cls+'">'+txt+'</div><div class="c">4 weeks ago: '+fmt(k,k.four_weeks_ago)+'</div>'+tg;
  g.appendChild(el);});
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('input',render));render();
"""


def table(rows, cols):
    head = "".join(f"<th>{html.escape(c[0])}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c[1](r)))}</td>" for c in cols) + "</tr>" for r in rows)
    return f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>'


def dashboard(d):
    cur = d["currency"]
    e = html.escape
    acts = "".join(f'<div class="act"><b>{i}.</b> {e(a["text"])}</div>' for i, a in enumerate(d["act_on"], 1))
    targets = "".join(
        f'<label>Target: {e(k["label"])}<input id="t_{k["key"]}" type="number" inputmode="decimal" value="{k.get("target") or ""}"></label>'
        for k in d["kpis"] if k["key"] in ("net_sales", "orders", "aov", "conversion_rate"))
    parts = [f"<h1>{e(title(d))}</h1>",
             f'<div class="sub">Weeks start {e(d["week_start"].title())}, timezone {e(d["timezone"])}. Compared with last week and with the same week 4 weeks ago.</div>',
             "<h2>Act on this</h2>", acts, "<h2>Key numbers</h2>",
             '<div class="ctl"><label>Flag changes above (%%)<input id="tpct" type="number" inputmode="decimal" value="%s"></label>'
             '<label>Flag rate changes above (pp)<input id="tpp" type="number" inputmode="decimal" value="%s"></label>%s</div>'
             % (d["thresholds"]["pct"], d["thresholds"]["pp"], targets),
             '<div class="grid" id="cards" style="margin-top:12px"></div>']
    pcols = [("Product", lambda r: r["product"]), ("Units", lambda r: f"{r['units']:g}"),
             ("Revenue", lambda r: money(r["revenue"], cur)), ("Last week", lambda r: money(r["last_week_revenue"], cur))]
    if d.get("top_products"):
        parts += ["<h2>Top 5 products</h2>", table(d["top_products"], pcols)]
    if d.get("bottom_products"):
        parts += ["<h2>Bottom 5 products</h2>", table(d["bottom_products"], pcols)]
    if d.get("inventory_warnings"):
        parts += [f"<h2>Stock running out (under {d['inventory_cover_days']} days)</h2>",
                  table(d["inventory_warnings"], [("Variant", lambda r: r["name"]), ("SKU", lambda r: r["sku"]),
                                                  ("Available", lambda r: f"{r['available']:g}"),
                                                  ("Per day", lambda r: r["per_day"]), ("Days left", lambda r: r["days_of_cover"])])]
    if d.get("notes"):
        parts += ["<h2>Data notes</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in d["notes"]) + "</ul>"]
    parts.append(f"<footer>{FOOTER}</footer>")
    data = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Weekly digest</title>"
            "<link href=\"https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=IBM+Plex+Sans+Arabic:wght@400;600&display=swap\" rel=\"stylesheet\">"
            f"<style>{CSS}</style></head><body><main>{''.join(parts)}</main>"
            f"<script type=\"application/json\" id=\"data\">{data}</script><script>{JS}</script></body></html>")


def spreadsheet(d, folder):
    os.makedirs(folder, exist_ok=True)
    cur = d["currency"]
    rows = [{"kpi": k["label"], "this_week": k["this"], "last_week": k["last"], "vs_last_week": change(k["vs_last"]),
             "four_weeks_ago": k["four_weeks_ago"], "vs_four_weeks_ago": change(k["vs_four_weeks_ago"]),
             "target": k.get("target", ""), "unit": cur if k["kind"] == "money" else ("%" if k["kind"] == "rate" else "")}
            for k in d["kpis"]]
    files = {"kpis.csv": rows, "top_products.csv": d.get("top_products") or [],
             "bottom_products.csv": d.get("bottom_products") or [],
             "inventory_warnings.csv": d.get("inventory_warnings") or []}
    written = []
    for name, data in files.items():
        if data:
            p = os.path.join(folder, name)
            write_csv(p, data)
            written.append(p)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digest", required=True)
    ap.add_argument("--format", required=True, choices=["report", "dashboard", "spreadsheet", "email"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.digest, encoding="utf-8") as fh:
        d = json.load(fh)
    if a.format == "spreadsheet":
        written = spreadsheet(d, a.out)
    else:
        text = {"report": report, "dashboard": dashboard, "email": email}[a.format](d)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        written = [a.out]
    print(json.dumps({"written": written}, ensure_ascii=False))


if __name__ == "__main__":
    main()
