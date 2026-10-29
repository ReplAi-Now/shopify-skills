"""Render the profit.py JSON into one self-contained HTML dashboard with scenario inputs.

Usage:
    python3 profit.py ... > profit.json
    python3 render_dashboard.py profit.json true-profit.html [--title "Store name"]

Scenario inputs (price change %, applied to product revenue only, not shipping charged; product cost change %, shipping and RTO cost change %,
ad spend change %, fixed monthly costs) recompute every product's profit live, assuming the
same units sold. Works offline and on a phone.
"""
import argparse, html, json

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>True profit: __TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f3f5f1;--card:#fff;--ink:#14201a;--mute:#5d6b63;--line:#dde4de;--neg:#b23a2e;--pos:#1f7a4d;--acc:#2a5d8f}
@media (prefers-color-scheme:dark){:root{--bg:#101612;--card:#18211b;--ink:#e9f0eb;--mute:#9aaaa0;--line:#2b372f;--neg:#ec7d6f;--pos:#68c897;--acc:#7fb0e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Source Serif 4",Georgia,serif}
main{max-width:1060px;margin:0 auto;padding:16px}
h1,h2{font-family:"Bricolage Grotesque",Georgia,sans-serif;margin:.2em 0 .4em}h1{font-size:28px}h2{font-size:20px;margin-top:28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.k,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.card{margin:10px 0}
.k b{display:block;font-size:22px;font-family:"Bricolage Grotesque",Georgia,sans-serif}.k span{color:var(--mute);font-size:13px}
.neg{color:var(--neg)}.pos{color:var(--pos)}.tag{font-size:13px;color:var(--mute)}
.scn{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
label{font-size:13px;color:var(--mute)}input{width:100%;padding:10px;font-size:16px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:110px}
ul{padding-left:20px}footer{color:var(--mute);font-size:12px;margin:30px 0 10px;text-align:center}
@media (max-width:480px){.hm{display:none}table{font-size:13px}th,td{padding:7px 3px}th{white-space:normal}th:first-child,td:first-child{min-width:70px}}
</style></head><body><main>
<h1>True profit</h1>
<div class="tag" id="period"></div>
<div class="kpis" id="kpis"></div>
<h2>Bestsellers that lose money</h2><div id="losers"></div>
<h2>Test a scenario</h2>
<div class="card scn">
<div><label>Price change %</label><input id="s_price" type="number" value="0" inputmode="decimal"></div>
<div><label>Product cost change %</label><input id="s_cost" type="number" value="0" inputmode="decimal"></div>
<div><label>Shipping and RTO cost change %</label><input id="s_ship" type="number" value="0" inputmode="decimal"></div>
<div><label>Ad spend change %</label><input id="s_ads" type="number" value="0" inputmode="decimal"></div>
<div><label>Fixed costs per month</label><input id="s_fixed" type="number" inputmode="decimal"></div>
</div>
<div class="tag">Same units sold in every scenario. Price change applies to product prices, not shipping charged. Payment fees move with the order value.</div>
<h2>Profit per product</h2>
<div class="card tw"><table id="prod"></table></div>
<div class="tag">Contribution = net revenue minus product cost, shipping, payment fees, packaging, failed-delivery (RTO) cost and ads. Break-even ROAS (BE ROAS) = the revenue each 1 of ad spend must bring back for the product to make 0.</div>
<h2>Channels</h2><div class="card tw"><table id="chan"></table></div>
<div class="card tw"><table id="plat"></table></div>
<h2>Assumptions and notes</h2><div class="card"><ul id="assume"></ul></div>
<footer>Made with the free ReplAi skills pack</footer>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const cur = D.currency || "";
const money = x => x == null ? "n/a" : (Math.abs(x) < 100 ? (Math.round(x * 10) / 10).toLocaleString() : Math.round(x).toLocaleString()) + " " + cur;
const pct = x => x == null ? "n/a" : (x * 100).toFixed(1) + "%";
const cls = x => x == null ? "" : (x < 0 ? "neg" : "pos");
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const T = D.totals, months = (D.period.days || 30) / 30;
const fixed0 = T.fixed_costs_for_period ? T.fixed_costs_for_period / months : 0;
$("s_fixed").value = Math.round(fixed0);
$("period").textContent = `${D.period.from || "?"} to ${D.period.to || "?"} (${D.period.days} days). delivered orders: ${D.orders.delivered}, failed deliveries: ${D.orders.failed_rto}.`;
function scen(p, s) {
  if (p.contribution == null) return null;
  // Price change moves product revenue only; shipping charged to the customer stays the same.
  const goods = p.net_revenue - (p.shipping_income || 0), dnet = goods * s.price;
  const net = p.net_revenue + dnet, cogs = p.cogs * (1 + s.cost);
  const ship = (p.shipping_cost + p.rto_cost) * (1 + s.ship);
  const fees = p.payment_fees * (p.net_revenue ? net / p.net_revenue : 1);
  const ads = p.ads * (1 + s.ads), cba = net - cogs - ship - fees - p.packaging;
  return {net, ads, cba, contribution: cba - ads, margin: net ? (cba - ads) / net : null, be: cba > 0 ? net / cba : null};
}
function draw() {
  const s = {price: (+$("s_price").value || 0) / 100, cost: (+$("s_cost").value || 0) / 100,
             ship: (+$("s_ship").value || 0) / 100, ads: (+$("s_ads").value || 0) / 100};
  const rows = D.products.map(p => ({p, x: scen(p, s)}));
  const known = rows.filter(r => r.x);
  const net = known.reduce((a, r) => a + r.x.net, 0), con = known.reduce((a, r) => a + r.x.contribution, 0);
  const ads = rows.reduce((a, r) => a + r.p.ads * (1 + s.ads), 0);
  const fixed = (+$("s_fixed").value || 0) * months;
  // No product has a cost: profit is unknown, never a number built from failed-delivery costs alone.
  const known0 = D.profit_known !== false && known.length > 0;
  const unk = "unknown: add product costs";
  $("kpis").innerHTML = [[known0 ? money(net) : money(T.net_revenue), known0 ? "net revenue (products with cost)" : "net revenue"],
    [known0 ? money(con) : unk, "contribution profit", known0 ? cls(con) : ""],
    [known0 ? pct(net ? con / net : null) : "unknown", "contribution margin", known0 ? cls(con) : ""], [money(ads), "ad spend"],
    [fixed && known0 ? money(con - fixed) : "n/a", "after fixed costs", known0 ? cls(con - fixed) : ""],
    [money(D.orders.avg_cost_per_rto_order), "cost of one failed delivery"]]
    .map(k => `<div class="k"><b class="${k[2] || ""}">${k[0]}</b><span>${k[1]}</span></div>`).join("");
  // Bestsellers are fixed (same units); whether they lose money is recomputed for the scenario.
  const best = new Set(D.bestsellers || D.bestsellers_losing_money.map(b => b.product));
  const losers = rows.filter(r => r.x && r.x.contribution < 0 && best.has(r.p.product));
  $("losers").innerHTML = losers.length ? losers.map(r => {
    const why = r.x.cba > 0 ? `Profitable before ads (${money(r.x.cba)}); ads cost ${money(r.x.ads)}. Actual ROAS ${r.x.ads ? (r.x.net / r.x.ads).toFixed(2) : "n/a"} vs break-even ${r.x.be ? r.x.be.toFixed(2) : "never"}.`
      : `Loses money even before ads (${money(r.x.cba)}): price, product cost or shipping needs fixing.`;
    return `<div class="card"><b>${esc(r.p.product)}</b>: ${r.p.units_sold} sold, <span class="neg">${money(r.x.contribution)}</span><br><span class="tag">${why} Break even with +${money(-r.x.contribution / r.p.units_sold)} per unit.</span></div>`;
  }).join("") : (known0 ? `<div class="card">None of the top sellers lose money in this scenario.</div>`
    : `<div class="card">Profit is unknown: no product has a cost yet, so we cannot tell which bestsellers lose money. Add product costs (Cost per item in Shopify, or the cost template) and run it again.</div>`);
  $("prod").innerHTML = `<tr><th>product</th><th>units</th><th>net revenue</th><th class="hm">cost</th><th class="hm">shipping + RTO</th><th class="hm">ads</th><th>profit</th><th class="hm">margin</th><th>BE ROAS</th></tr>` +
    rows.map(({p, x}) => x ? `<tr><td>${esc(p.product)}</td><td>${p.units_sold}</td><td>${money(x.net)}</td><td class="hm">${money(p.cogs * (1 + s.cost))}</td><td class="hm">${money((p.shipping_cost + p.rto_cost) * (1 + s.ship))}</td><td class="hm">${money(x.ads)}</td><td class="${cls(x.contribution)}">${money(x.contribution)}</td><td class="hm">${pct(x.margin)}</td><td>${x.be ? x.be.toFixed(2) : "never"}</td></tr>`
      : `<tr><td>${esc(p.product)}</td><td>${p.units_sold}</td><td>${money(p.net_revenue)}</td><td class="hm" colspan="3">cost missing</td><td>cost missing</td><td class="hm">n/a</td><td>n/a</td></tr>`).join("");
}
$("chan").innerHTML = `<tr><th>sales channel</th><th class="hm">delivered</th><th class="hm">failed</th><th>net revenue</th><th>profit</th></tr>` +
  D.sales_channels.map(c => `<tr><td>${esc(c.channel)}</td><td class="hm">${c.delivered}</td><td class="hm">${c.failed_rto}</td><td>${money(c.net_revenue)}</td><td class="${cls(c.contribution)}">${c.contribution == null ? (c.contribution_known == null ? "n/a (costs missing)" : "n/a (" + c.orders_missing_cost + " orders without cost; known part " + money(c.contribution_known) + ")") : money(c.contribution)}</td></tr>`).join("");
$("plat").innerHTML = D.ad_platforms.length ? `<tr><th>ad platform</th><th>spend</th><th class="hm">platform purchases</th><th>cost per delivered order (estimate)</th><th>break-even</th></tr>` +
  D.ad_platforms.map(p => `<tr><td>${esc(p.platform)}</td><td>${money(p.spend)}</td><td class="hm">${p.platform_purchases}</td><td class="${p.true_cpa_estimate > p.break_even_cpa ? "neg" : "pos"}">${money(p.true_cpa_estimate)}</td><td>${money(p.break_even_cpa)}</td></tr>`).join("") : "<tr><td>No ad files given.</td></tr>";
$("assume").innerHTML = (D.assumptions || []).concat(D.warnings || []).map(a => `<li>${esc(a)}</li>`).join("");
document.querySelectorAll("input").forEach(e => e.addEventListener("input", draw));
draw();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("out")
    ap.add_argument("--title", default="store")
    a = ap.parse_args()
    with open(a.result, encoding="utf-8") as fh:
        data = json.load(fh)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__TITLE__", html.escape(a.title)).replace("__DATA__", blob)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(json.dumps({"written": a.out, "bytes": len(page.encode("utf-8"))}))


if __name__ == "__main__":
    main()
