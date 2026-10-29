#!/usr/bin/env python3
"""Build the self-contained demand planner dashboard (one HTML file, works offline and at 390px).

Usage:
  python3 demand_plan.py ... > plan.json
  python3 build_dashboard.py --plan plan.json --out demand-plan.html [--store "Store name"]

The page embeds the plan and recomputes safety stock, reorder point, order quantity and cash
in the browser when the merchant changes service level, lead time, lead time variability or
review period. Formulas match demand_plan.py (references/method.md).

To stay light on cheap phones with big catalogs (target under 500 KB), the page lists only the
actionable rows (order now, this week, at risk, oversold) and summarises the "later" rows; every
variant is written to <out>-all-items.csv next to the HTML. Items without demand are counted, not listed.
"""
import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import write_csv  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demand plan</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f6f3ec;--card:#fffdf8;--ink:#1f2a24;--muted:#5d6b63;--line:#e2dccf;--now:#b3361e;--week:#c27c0e;--later:#2f6b4f;--accent:#1f5c4a}
@media (prefers-color-scheme: dark){:root{--bg:#141a17;--card:#1c2420;--ink:#ece8de;--muted:#a3ada6;--line:#2e3a34;--now:#ff7a5c;--week:#f0b44c;--later:#6fc79c;--accent:#7fd1b2}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Source Serif 4",Georgia,serif}
h1,h2,.kpi b,th,label,button{font-family:"Bricolage Grotesque","Trebuchet MS",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:26px;margin:4px 0 2px}h2{font-size:18px;margin:24px 0 8px}
.sub{color:var(--muted);margin:0 0 12px}
.answer{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:10px;padding:12px 14px;margin:12px 0}
.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
label{display:block;font-size:13px;color:var(--muted)}
input{width:100%;font-size:17px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);min-height:44px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi span{display:block;font-size:13px;color:var(--muted)}.kpi b{font-size:22px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:720px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:160px}
th{font-size:12px;color:var(--muted);font-weight:500;position:sticky;top:0;background:var(--card)}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-family:"Bricolage Grotesque",sans-serif;color:#fff}
.order_now{background:var(--now)}.this_week{background:var(--week)}.later{background:var(--later)}.no_demand,.needs_estimate{background:var(--muted)}
.risk{color:var(--now)}
ul{padding-left:20px}
footer{color:var(--muted);font-size:12px;margin:28px 0 8px;text-align:center}
</style></head><body><div class="wrap">
<h1>Demand plan</h1>
<p class="sub" id="meta"></p>
<div class="answer" id="answer"></div>
<div class="controls">
 <div><label for="sl">Service level target (%)</label><input id="sl" type="number" min="50" max="99.9" step="0.5"></div>
 <div><label for="lt">Lead time for all items (days, blank = per supplier)</label><input id="lt" type="number" min="0" step="1" placeholder="per supplier"></div>
 <div><label for="ltsd">Lead time variability (days, blank = per supplier)</label><input id="ltsd" type="number" min="0" step="0.5" placeholder="per supplier"></div>
 <div><label for="rp">Review period (days between orders)</label><input id="rp" type="number" min="1" step="1"></div>
</div>
<div class="kpis">
 <div class="kpi"><span>Cash to order now</span><b id="k_now"></b><span id="k_now_s"></span></div>
 <div class="kpi"><span>Cash for this week's orders</span><b id="k_week"></b><span id="k_week_s"></span></div>
 <div class="kpi"><span>Cash in stock today</span><b id="k_tied"></b><span id="k_tied_s"></span></div>
 <div class="kpi"><span>Cash held as safety stock</span><b id="k_ss"></b><span id="k_ss_s"></span></div>
</div>
<p class="sub" id="tradeoff"></p>
<h2>Reorder list</h2>
<p class="sub">Order now, this week, at risk and oversold items. <span id="later"></span></p>
<div class="tablewrap"><table><thead><tr><th>Item</th><th>When</th><th>Order qty</th><th>Cash</th><th>Stock</th><th>Sells/day</th><th>Reorder point</th><th>Runs out</th></tr></thead><tbody id="rows"></tbody></table></div>
<h2>At risk</h2><ul id="risk"></ul>
<h2>Notes</h2><ul id="notes"></ul>
<p class="sub"><b>Reorder point</b>: when stock you have plus stock on the way falls to this number, order. <b>Safety stock</b>: the extra units kept for slow suppliers and busy days. <b>Service level</b>: the chance you do not run out before the next delivery. <b>Oversold</b>: units already sold to customers that are not in stock.</p>
<footer>Made with the free ReplAi skills pack</footer>
</div>
<script>
const PLAN = __PLAN__;
const CUR = PLAN.currency || "";
const DAY = 86400000;
// Items are packed as arrays to keep the file small on cheap phones: unpack once.
const ITEMS = PLAN.rows.map(r=>{const o={};PLAN.fields.forEach((f,i)=>o[f]=r[i]);o.title=PLAN.titles[o.t];return o});
function d0(s){const p=s.split("-");return Date.UTC(+p[0],+p[1]-1,+p[2])/DAY}
function iso(n){return new Date(n*DAY).toISOString().slice(0,10)}
function money(v){return v==null?"unknown":CUR+" "+Math.round(v).toLocaleString()}
function invNorm(p){const a=[-39.69683028665376,220.9460984245205,-275.9285104469687,138.357751867269,-30.66479806614716,2.506628277459239],b=[-54.47609879822406,161.5858368580409,-155.6989798598866,66.80131188771972,-13.28068155288572],c=[-0.007784894002430293,-0.3223964580411365,-2.400758277161838,-2.549732539343734,4.374664141464968,2.938163982698783],d=[0.007784695709041462,0.3224671290700398,2.445134137142996,3.754408661907416];
 if(p>0.97575){const q=Math.sqrt(-2*Math.log(1-p));return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)}
 const q=p-0.5,r=q*q;return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)}
const EPS=1e-9, ASOF=d0(PLAN.as_of);
const EVENTS=(PLAN.seasonality.events||[]).filter(e=>!e.in_progress).map(e=>({s:d0(e.start),e:d0(e.end),f:e.factor,name:e.name}));
function roundOrder(q,moq,cp){if(q<=EPS)return 0;let x=Math.max(Math.ceil(q-EPS),moq||0);cp=Math.max(cp||1,1);return Math.ceil(x/cp)*cp}
// Same rules as demand_plan.py. Position = available (never below 0) + incoming - units owed (oversold).
function calc(it,z,ltO,ltsdO,R){
 const d=it.d, pos=it.av+it.inc-it.owed;
 const lt=ltO!=null?ltO:it.lt, ltsd=ltsdO!=null?ltsdO:it.ltsd, H=lt+R;
 let dE=d; if(H>0&&d){const hd=Math.ceil(H-EPS);let ex=0;for(const ev of EVENTS){const s=Math.max(ev.s,ASOF+1),e=Math.min(ev.e,ASOF+hd);if(e>=s)ex+=(ev.f-1)*(e-s+1)}dE=d*(H+ex)/H}
 const cash=q=>it.cost==null?null:q*it.cost;
 if(dE<=EPS){if(pos<-EPS){const q=roundOrder(-pos,it.moq,it.cp);return {urgency:"order_now",qty:q,cash:cash(q),ss:0,rop:0,dE:0}}return {urgency:"no_demand",qty:0,cash:0,ss:0,rop:0,dE:0}}
 const sE=d?it.sd*dE/d:0, ss=z*Math.sqrt(lt*sE*sE+dE*dE*ltsd*ltsd), rop=dE*lt+ss, S=rop+dE*R;
 const qty=roundOrder(S-Math.min(pos,rop),it.moq,it.cp), until=(pos-rop)/dE;
 const urgency=pos<=rop+EPS?"order_now":(until<=7+EPS?"this_week":"later");
 const dts=Math.max(it.av,0)/dE;
 return {urgency,qty,cash:cash(qty),ss,rop,dE,lt,
  reorder:iso(ASOF+Math.floor(Math.max(until,0)+EPS)),stockout:iso(ASOF+Math.floor(dts+EPS)),
  risk:it.av<=0?"out of stock now":(dts<lt-EPS?"runs out before an order placed today can arrive":"")};
}
const ORDER=["order_now","this_week","later","no_demand","needs_estimate"];
const LABEL={order_now:"Order now",this_week:"This week",later:"Later",no_demand:"No demand",needs_estimate:"Needs estimate"};
const $=id=>document.getElementById(id);
$("sl").value=PLAN.settings.service_level_pct; $("rp").value=PLAN.settings.review_period_days;
function num(id){const v=String($(id).value).trim();return v===""?null:parseFloat(v)}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
// A missing unit cost is unknown, never 0: totals carry how many items had a cost.
function tot(){return {v:0,n:0,c:0}}
function add(t,v){t.n++;if(v!=null){t.v+=v;t.c++}}
function shown(t){return t.n&&!t.c?null:t.v}
function partial(t){return t.n&&!t.c?"no unit costs: add them for a total":(t.c<t.n?"for "+t.c+" of "+t.n+" items with a cost":"")}
function cashText(t){if(t.n&&!t.c)return "cash unknown: add unit costs";const p=partial(t);return money(shown(t))+(p?", "+p:"")}
function ssTotal(z,ltO,ltsdO,R){const t=tot();for(const it of ITEMS){const r=calc(it,z,ltO,ltsdO,R);add(t,it.cost==null?null:(r.ss||0)*it.cost)}return t}
const LAST={};
function render(){
 let sl=num("sl");if(sl==null||sl<50||sl>99.9)sl=PLAN.settings.service_level_pct;
 const z=invNorm(sl/100), ltO=num("lt"), ltsdO=num("ltsd"); let R=num("rp"); if(R==null||R<1)R=1;
 const rows=ITEMS.map(it=>({it,r:calc(it,z,ltO,ltsdO,R)}));
 rows.sort((a,b)=>ORDER.indexOf(a.r.urgency)-ORDER.indexOf(b.r.urgency)||((a.r.reorder||"9")<(b.r.reorder||"9")?-1:1));
 const now=tot(),week=tot(),ss=ssTotal(z,ltO,ltsdO,R); let nLater=0,nextLater=null;
 for(const {r} of rows){if(r.urgency==="order_now"&&r.qty>0)add(now,r.cash);if(r.urgency==="this_week"&&r.qty>0)add(week,r.cash);if(r.urgency==="later"){nLater++;if(!nextLater||r.reorder<nextLater)nextLater=r.reorder}}
 LAST.now=shown(now);LAST.week=shown(week);LAST.nNow=now.n;LAST.nWeek=week.n;LAST.ss=shown(ss);
 const C=PLAN.cash, tied={v:C.capital_tied_now||0,n:C.capital_tied_items||0,c:C.capital_tied_items_with_cost||0};
 $("k_now").textContent=money(shown(now));$("k_now_s").textContent=partial(now);
 $("k_week").textContent=money(shown(week));$("k_week_s").textContent=partial(week);
 $("k_tied").textContent=money(shown(tied));$("k_tied_s").textContent=partial(tied);
 $("k_ss").textContent=money(shown(ss));$("k_ss_s").textContent=partial(ss);
 $("answer").innerHTML="<b>Order "+now.n+" item"+(now.n==1?"":"s")+" now ("+esc(cashText(now))+")</b> and "+week.n+" more this week ("+esc(cashText(week))+"). Plan assumes "+sl+"% service level"+(ltO!=null?" and "+ltO+" day lead time for every item":"")+".";
 const lo=ssTotal(invNorm(0.90),ltO,ltsdO,R), hi=ssTotal(invNorm(0.99),ltO,ltsdO,R);
 $("tradeoff").textContent=ss.n&&!ss.c?"Trade-off: a higher service level means fewer stockouts but more cash sitting in safety stock. Add unit costs to see how much.":"Trade-off: a higher service level means fewer stockouts but more cash sitting in safety stock. At 90% you hold "+money(shown(lo))+" of safety stock"+(sl!=90&&sl!=99?", at your "+sl+"% "+money(shown(ss)):"")+", at 99% "+money(shown(hi))+(ss.c<ss.n?" (items with a cost only)":"")+".";
 const act=rows.filter(({it,r})=>((r.urgency==="order_now"||r.urgency==="this_week")&&r.qty>0)||r.risk||it.owed>0);
 LAST.rows=act.length;
 $("later").textContent=nLater?nLater+" more item"+(nLater==1?"":"s")+" to reorder later (next on "+nextLater+") are left out here: the full list is in "+PLAN.csv_name+".":"";
 $("rows").innerHTML=act.map(({it,r})=>"<tr><td>"+esc(it.title)+(it.v?" <span class=sub>"+esc(it.v)+"</span>":"")+"<br><span class=sub>"+esc(it.sku)+(it.owed?" · oversold: "+it.owed+" owed to customers":"")+"</span></td><td><span class='pill "+r.urgency+"'>"+LABEL[r.urgency]+"</span>"+(r.urgency==="later"?"<br><span class=sub>"+r.reorder+"</span>":"")+"</td><td>"+r.qty+"</td><td>"+money(r.cash)+"</td><td>"+it.av+(it.inc?" +"+it.inc:"")+"</td><td>"+(r.dE==null?"?":r.dE.toFixed(2))+"</td><td>"+(r.rop==null?"":r.rop.toFixed(1))+"</td><td class='"+(r.risk?"risk":"")+"'>"+(r.stockout||"")+"</td></tr>").join("")||"<tr><td colspan=8>Nothing to order at these settings.</td></tr>";
 const risky=act.filter(x=>x.r.risk);
 $("risk").innerHTML=risky.length?risky.slice(0,50).map(({it,r})=>"<li class=risk>"+esc(it.title)+" "+esc(it.v||"")+": "+r.risk+" (runs out "+r.stockout+")</li>").join("")+(risky.length>50?"<li>and "+(risky.length-50)+" more in the reorder list above.</li>":""):"<li>None at these settings.</li>";
}
$("meta").textContent="As of "+PLAN.as_of+" · "+PLAN.counts.variants+" variants · history from "+PLAN.history.first_order+(PLAN.stockout_aware?" · stockout aware":"");
const notes=(PLAN.data_notes||[]).slice();
for(const e of PLAN.seasonality.events||[])notes.push(e.name+" ("+e.start+" to "+e.end+"): "+(e.in_progress?"in progress today, recent sales already include it, so no extra uplift is added":"demand x"+e.factor+(e.source==="merchant"?" (your estimate)":" (measured from last year)")));
for(const m of PLAN.moq_warnings||[])notes.push(m.sku+": the MOQ or case pack forces "+m.order_qty+" units, about "+m.days_of_demand+" days of demand. Ask for a smaller minimum or skip it.");
for(const e of PLAN.seasonality.needs_merchant_uplift||[])notes.push(e.name+" ("+e.start+" to "+e.end+") is coming but "+e.reason+". Give an uplift % to include it.");
if(PLAN.counts.needs_estimate)notes.push(PLAN.counts.needs_estimate+" variants have no usable sales and need your estimate. Biggest groups: "+PLAN.estimate_groups.map(g=>g.group+" ("+g.variants+")").join(", ")+".");
if(PLAN.counts.no_demand)notes.push(PLAN.counts.no_demand+" variants had no sales in the window and need nothing now.");
if(PLAN.missing_cost.count)notes.push(PLAN.missing_cost.count+" items have no unit cost (cash totals leave them out): "+PLAN.missing_cost.sample.join(", ")+(PLAN.missing_cost.count>PLAN.missing_cost.sample.length?" and more (see "+PLAN.csv_name+")":""));
$("notes").innerHTML=notes.length?notes.map(n=>"<li>"+esc(n)+"</li>").join(""):"<li>None.</li>";
for(const id of ["sl","lt","ltsd","rp"])$(id).addEventListener("input",render);
render();
</script></body></html>
"""


FIELDS = ["t", "v", "sku", "d", "sd", "lt", "ltsd", "moq", "cp", "av", "inc", "owed", "cost"]
CSV_COLS = ["sku", "title", "variant_title", "urgency", "order_qty", "cash_needed", "unit_cost", "available",
            "oversold_units", "incoming", "daily_demand", "horizon_daily_demand", "lead_time_days", "safety_stock",
            "reorder_point", "reorder_date", "stockout_date", "at_risk", "risk_reason", "capital_tied",
            "demand_source", "status", "flags"]
SAMPLE = 10


def slim(plan, csv_name):
    """Only what the page needs: planned items packed as arrays with titles listed once, and counts
    (not rows) for items without demand. Keeps the file light for big catalogs on cheap phones."""
    titles, tidx, rows = [], {}, []
    for i in plan["items"]:
        if i.get("daily_demand") is None:
            continue
        t = i.get("title") or ""
        if t not in tidx:
            tidx[t] = len(titles)
            titles.append(t)
        rows.append([tidx[t], i.get("variant_title") or "", i.get("sku") or i["key"], i["daily_demand"],
                     i.get("daily_demand_sd") or 0, i["lead_time_days"], i["lead_time_sd_days"], i.get("moq", 0),
                     i.get("case_pack", 1), i.get("available", 0), i.get("incoming", 0), i.get("oversold_units", 0),
                     i.get("unit_cost")])
    cash = plan["cash"]
    missing = cash.get("items_missing_cost", [])
    keep = ("as_of", "currency", "settings", "history", "stockout_aware", "seasonality", "data_notes", "moq_warnings")
    out = {k: plan.get(k) for k in keep}
    out.update(fields=FIELDS, rows=rows, titles=titles, csv_name=csv_name,
               cash={k: v for k, v in cash.items() if not isinstance(v, list)},
               missing_cost={"count": len(missing), "sample": missing[:SAMPLE]},
               estimate_groups=[{"group": g["group"], "variants": g["variants"]}
                                for g in plan.get("estimate_groups", [])[:SAMPLE]],
               counts={"variants": len(plan["items"]),
                       "needs_estimate": sum(1 for i in plan["items"] if i["urgency"] == "needs_estimate"),
                       "no_demand": sum(1 for i in plan["items"] if i["urgency"] == "no_demand")})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--store", default="")
    a = ap.parse_args()
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    if "error" in plan:
        sys.exit("plan.json contains an error: " + plan["error"])
    csv_path = os.path.splitext(a.out)[0] + "-all-items.csv"
    rows = [dict(i, flags="; ".join(i.get("flags", []))) for i in plan["items"]]
    write_csv(csv_path, rows, CSV_COLS)
    data = json.dumps(slim(plan, os.path.basename(csv_path)), ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    page = PAGE.replace("__PLAN__", data)
    if a.store:
        page = page.replace("<h1>Demand plan</h1>", "<h1>Demand plan: " + html.escape(a.store) + "</h1>")
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(json.dumps({"written": a.out, "all_items_csv": csv_path, "bytes": len(page.encode("utf-8"))}))


if __name__ == "__main__":
    main()
