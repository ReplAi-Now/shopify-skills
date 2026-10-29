#!/usr/bin/env python3
"""Build the self-contained dead stock dashboard (one HTML file, works offline and at 390px).

Usage:
  python3 dead_stock.py ... > clearance.json
  python3 build_dashboard.py --plan clearance.json --out dead-stock.html [--store "Store name"]

Scenario inputs (margin floor, markdown depth for slow, dead and very old dead items, bundle
discount, liquidation recovery, below cost) and the expected sell-through per tactic re-choose each item's tactic and recompute prices,
cash recovered and profit in the browser with the same rules as dead_stock.py
(references/method.md). With the default inputs the numbers equal the script's. The dashboard is for exploring only:
the change list the merchant approves is the CSV written by dead_stock.py.
"""
import argparse
import html
import json
import sys

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dead stock plan</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800&family=Public+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f1f8;--card:#fff;--ink:#231b2e;--muted:#675d73;--line:#e3dcea;--dead:#a3292f;--slow:#b5770d;--ok:#2d6a4f;--accent:#5a2d82}
@media (prefers-color-scheme: dark){:root{--bg:#17131c;--card:#211b28;--ink:#eee8f4;--muted:#a99fb4;--line:#352c40;--dead:#ff7b7f;--slow:#f2b84b;--ok:#73c69c;--accent:#c39bea}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Public Sans","Helvetica Neue",sans-serif}
h1,h2,.kpi b{font-family:Fraunces,Georgia,serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:28px;margin:4px 0 2px}h2{font-size:19px;margin:24px 0 8px}
.sub{color:var(--muted);margin:0 0 12px}
.answer{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:10px;padding:12px 14px;margin:12px 0}
.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
label{display:block;font-size:13px;color:var(--muted)}
input{width:100%;font-size:17px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);min-height:44px}
input[type=checkbox]{width:26px;min-height:26px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi span{display:block;font-size:13px;color:var(--muted)}.kpi b{font-size:23px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:170px}
th{font-size:12px;color:var(--muted);font-weight:600}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;color:#fff}
.dead{background:var(--dead)}.slow{background:var(--slow)}
.neg{color:var(--dead)}
ul{padding-left:20px}
footer{color:var(--muted);font-size:12px;margin:28px 0 8px;text-align:center}
</style></head><body><div class="wrap">
<h1>Dead stock plan</h1>
<p class="sub" id="meta"></p>
<div class="answer" id="answer"></div>
<div class="controls">
 <div><label for="floor">Minimum margin above cost (%)</label><input id="floor" type="number" min="0" step="1"></div>
 <div><label for="slowstep">Markdown for slow items (%)</label><input id="slowstep" type="number" min="0" max="90" step="5"></div>
 <div><label for="deadstep">Markdown for dead items (%)</label><input id="deadstep" type="number" min="0" max="90" step="5"></div>
 <div><label for="xstep">Markdown for very old dead items (%)</label><input id="xstep" type="number" min="0" max="90" step="5"></div>
 <div><label for="bundle">Bundle discount on the slow item (%)</label><input id="bundle" type="number" min="0" max="90" step="5"></div>
 <div><label for="liq">Liquidation: % of cost a stock buyer pays</label><input id="liq" type="number" min="0" max="100" step="5"></div>
 <div><label for="below">Allow selling below cost</label><input id="below" type="checkbox"></div>
</div>
<p class="sub">Expected sell-through: the share of units you expect to sell with each tactic (an estimate, change it to test scenarios).</p>
<div class="controls">
 <div><label for="st_markdown">Markdown sells (%)</label><input id="st_markdown" type="number" min="0" max="100" step="5"></div>
 <div><label for="st_bundle">Bundle sells (%)</label><input id="st_bundle" type="number" min="0" max="100" step="5"></div>
 <div><label for="st_gift">Free gift given away (%)</label><input id="st_gift" type="number" min="0" max="100" step="5"></div>
 <div><label for="st_clearance_collection">Clearance collection, price unchanged, sells (%)</label><input id="st_clearance_collection" type="number" min="0" max="100" step="5"></div>
 <div><label for="st_liquidate">Stock buyer takes (%)</label><input id="st_liquidate" type="number" min="0" max="100" step="5"></div>
</div>
<div class="kpis">
 <div class="kpi"><span>Cash stuck in dead stock</span><b id="k_dead"></b><span id="k_dead_s"></span></div>
 <div class="kpi"><span>Cash stuck in slow stock</span><b id="k_slow"></b><span id="k_slow_s"></span></div>
 <div class="kpi"><span>Expected cash recovered</span><b id="k_rec"></b><span id="k_rec_s"></span></div>
 <div class="kpi"><span>Expected profit</span><b id="k_profit"></b><span id="k_profit_s"></span></div>
</div>
<h2>Clearance plan</h2>
<div class="tablewrap"><table><thead><tr><th>Item</th><th>Status</th><th>Units</th><th>Cash stuck</th><th>Tactic</th><th>Price now</th><th>New price</th><th>Sells (%)</th><th>Expected cash</th><th>If all sell</th><th>Expected profit</th></tr></thead><tbody id="rows"></tbody></table></div>
<h2>Notes</h2><ul id="notes"></ul>
<p class="sub"><b>Cash stuck</b>: units in stock x unit cost, money already paid that is sitting on shelves. <b>Days of cover</b>: how many days current stock lasts at the last 30 days' sales rate. <b>Sell-through</b>: share of stock sold over the window. <b>Expected cash</b>: cash from the share of units expected to sell with that tactic (an estimate). <b>If all sell</b>: the ceiling, every unit sold at that price.</p>
<footer>Made with the free ReplAi skills pack</footer>
</div>
<script>
const P = __PLAN__;
const CUR = P.currency || "", S = P.settings, EPS = 1e-9;
const $ = id => document.getElementById(id);
const steps = S.markdown_steps_pct.slice().sort((a,b)=>a-b);
const ALLOWED = new Set(S.allowed_tactics||[]);
$("floor").value = S.margin_floor_pct; $("slowstep").value = steps[0]; $("deadstep").value = steps.length>1?steps[1]:steps[steps.length-1]; $("xstep").value = steps[steps.length-1];
$("bundle").value = S.bundle_discount_pct; $("liq").value = S.liquidation_recovery_pct; $("below").checked = !!S.allow_below_cost;
function money(v){return v==null?"unknown":CUR+" "+Math.round(v).toLocaleString()}
const TACTICS=["markdown","bundle","gift","clearance_collection","liquidate"];
for(const t of TACTICS) $("st_"+t).value=S["assumed_sell_through_"+t+"_pct"];
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function val(id,d){const v=parseFloat($(id).value);return isNaN(v)?d:v}
const R = S.price_rounding || 1;
const floorTo = x => Math.floor(x/R+EPS)*R, ceilTo = x => Math.ceil(x/R-EPS)*R;
const LABEL = {markdown:"Markdown",markdown_clearance:"Markdown + clearance collection",bundle:"Bundle",gift:"Free gift",clearance_collection:"Clearance collection",liquidate:"Liquidate"};
const LAST = {};
// Same decision rules as dead_stock.py: rebuild the options with the current inputs, then pick.
function plan(it,inp){
 const p=it.price, c=it.unit_cost, u=it.stock, has=t=>(it.options||[]).some(o=>o.tactic===t);
 const floorP = c==null?null:(inp.below?0:ceilTo(c*(1+inp.fl/100)));
 const step = it.category==="slow"?inp.slow:(it.extreme?inp.xdead:inp.dead);
 let md=null, bd=null;
 if(ALLOWED.has("markdown")&&c!=null&&p){let np=floorTo(p*(1-step/100)),cl=false;if(np<floorP-EPS){np=floorP;cl=true}if(np<p-EPS)md={np,cl}}
 const bp=it.bundle_partner;
 if(ALLOWED.has("bundle")&&bp&&c!=null&&p){const x=Math.max(floorTo(p*(1-inp.bundle/100)),floorP);if(x<p-EPS||inp.bundle===0)bd={np:x,basis:bp.basis}}
 const gift=has("gift"), cc=has("clearance_collection"), liq=has("liquidate");
 let t=null;
 if(it.category==="slow"){t=bd&&bd.basis==="co_purchase"?"bundle":md?"markdown":gift?"gift":cc?"clearance_collection":null}
 else if(it.extreme){t=md&&!md.cl?"markdown":liq?"liquidate":md?"markdown":null}
 else{t=md?"markdown":gift?"gift":liq?"liquidate":null}
 if(t==="markdown"&&it.category==="dead"&&ALLOWED.has("clearance_collection"))t="markdown_clearance";
 if((it.duplicate_handles||[]).length)t=null;
 let np=p, cash=null, pr=null;
 if(t==="markdown"||t==="markdown_clearance"){np=md.np;cash=np*u;pr=(np-c)*u}
 else if(t==="bundle"){np=bd.np;cash=np*u;pr=(np-c)*u}
 else if(t==="gift"){np=0;cash=0;pr=-c*u}
 else if(t==="liquidate"){np=c*inp.liq/100;cash=np*u;pr=(np-c)*u}
 else if(t==="clearance_collection"){cash=p*u;pr=c==null?null:(p-c)*u}
  const pct=t?inp.st[t==="markdown_clearance"?"markdown":t]:null;
  return {t,np,cash,pr,step,pct,exp:cash==null?null:cash*pct/100,expPr:pr==null?null:pr*pct/100};
}
function render(){
 const inp={fl:val("floor",S.margin_floor_pct), below:$("below").checked, liq:val("liq",S.liquidation_recovery_pct),
  slow:val("slowstep",steps[0]), dead:val("deadstep",steps.length>1?steps[1]:steps[steps.length-1]), xdead:val("xstep",steps[steps.length-1]),
  bundle:val("bundle",S.bundle_discount_pct), st:{}};
 for(const t of TACTICS) inp.st[t]=val("st_"+t,S["assumed_sell_through_"+t+"_pct"]);
 let rec=0, prof=0, exp=0, expPr=0, n=0; const rows=[], out=[];
 for(const it of P.items){
  if(it.category!=="slow"&&it.category!=="dead") continue;
  const r=plan(it,inp), t=r.t, p=it.price, u=it.stock, np=r.np, cash=r.cash, pr=r.pr;
  if(cash!=null){rec+=cash;exp+=r.exp;n++} if(pr!=null){prof+=pr;expPr+=r.expPr}
  out.push({sku:it.sku,tactic:t,new_price:t?np:null,cash:cash,profit:pr,expected:r.exp});
  rows.push("<tr><td>"+esc(it.title)+(it.variant_title?" <span class=sub>"+esc(it.variant_title)+"</span>":"")+"<br><span class=sub>"+esc(it.sku)+" · "+esc(it.reason)+"</span></td><td><span class='pill "+it.category+"'>"+it.category+"</span></td><td>"+u+"</td><td>"+money(it.cash_stuck)+"</td><td>"+(t?LABEL[t]+(t!==it.recommended?" <span class=sub>(changed)</span>":""):"<span class=sub>none possible</span>")+"</td><td>"+money(p)+"</td><td>"+(t==="gift"?"free":money(np))+"</td><td>"+(t?r.pct:"")+"</td><td>"+money(r.exp)+"</td><td>"+money(cash)+"</td><td class='"+(r.expPr<0?"neg":"")+"'>"+money(r.expPr)+"</td></tr>");
 }
 LAST.rec=rec; LAST.profit=prof; LAST.exp=exp; LAST.expProfit=expPr; LAST.items=out;
 $("rows").innerHTML = rows.join("") || "<tr><td colspan=11>No slow or dead stock at these thresholds.</td></tr>";
 const SM=P.summary, CI=SM.cash_stuck_items||{};
 // A missing unit cost is unknown, never 0: say how many items the cash figure covers.
 const part=(n,c)=>n&&!c?"no unit costs: add them to see this":(c<n?"for "+c+" of "+n+" items with a cost":"");
 $("k_dead").textContent=money(SM.cash_stuck_dead); $("k_dead_s").textContent=part(CI.dead,CI.dead_with_cost);
 $("k_slow").textContent=money(SM.cash_stuck_slow); $("k_slow_s").textContent=part(CI.slow,CI.slow_with_cost);
 $("k_rec").textContent=money(exp); $("k_rec_s").textContent="if every unit sells: "+money(rec);
 $("k_profit").textContent=money(expPr); $("k_profit_s").textContent="if every unit sells: "+money(prof);
 const both=SM.cash_stuck_dead==null&&SM.cash_stuck_slow==null?null:(SM.cash_stuck_dead||0)+(SM.cash_stuck_slow||0);
 const nItems=(SM.categories.dead||{count:0}).count+(SM.categories.slow||{count:0}).count;
 const head=!nItems?"No slow or dead stock at these thresholds.":both==null?nItems+" slow or dead items found; the cash stuck in them is unknown until you add unit costs.":money(both)+" is stuck in slow and dead stock (at cost"+((CI.slow_with_cost+CI.dead_with_cost)<(CI.slow+CI.dead)?", items with a cost only":"")+").";
 LAST.head=head;
 $("answer").innerHTML="<b>"+esc(head)+"</b> Clearing "+n+" items this way should bring in about "+money(exp)+" (at the expected sell-through below), and at most "+money(rec)+" if every unit sells. Floor: never below cost + "+inp.fl+"%"+(inp.below?" (below cost allowed)":"")+". Tactics marked (changed) differ from the approved change list; rerun the script with these settings to get a new list.";
}
$("meta").textContent = "As of "+P.as_of+" · order history "+P.history.days_of_history+" days · slow after "+S.slow_days+" days without a sale, dead after "+S.dead_days;
const notes=(P.data_notes||[]).slice();
if(P.summary.items_missing_cost.length) notes.push("Missing unit cost (no markdown proposed): "+P.summary.items_missing_cost.join(", "));
if(P.summary.gift_threshold) notes.push("Free gift threshold: orders above "+money(P.summary.gift_threshold)+" (average order "+money(P.summary.aov)+" x "+S.gift_threshold_multiplier+").");
notes.push("Nothing changes in your store until you approve the exact change list (dead-stock-changes.csv).");
$("notes").innerHTML=notes.map(x=>"<li>"+esc(x)+"</li>").join("");
for(const id of ["floor","slowstep","deadstep","xstep","bundle","liq","below"].concat(TACTICS.map(t=>"st_"+t))) $(id).addEventListener("input",render);
render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--store", default="")
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    if "error" in plan:
        sys.exit("plan file contains an error: " + plan["error"])
    # Only slow and dead items are shown: leave the rest out to keep the file light on phones.
    keep = ("sku", "title", "variant_title", "reason", "category", "stock", "cash_stuck", "price", "unit_cost",
            "extreme", "recommended", "duplicate_handles")
    plan["items"] = [dict({k: i.get(k) for k in keep}, options=[{"tactic": o["tactic"]} for o in i.get("options", [])],
                          bundle_partner={"basis": i["bundle_partner"]["basis"]} if i.get("bundle_partner") else None)
                     for i in plan["items"] if i.get("category") in ("slow", "dead")]
    plan.pop("changes", None)
    plan.pop("rollback", None)
    page = PAGE.replace("__PLAN__", json.dumps(plan, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    if a.store:
        page = page.replace("<h1>Dead stock plan</h1>", "<h1>Dead stock plan: " + html.escape(a.store) + "</h1>")
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(json.dumps({"written": a.out}))


if __name__ == "__main__":
    main()
