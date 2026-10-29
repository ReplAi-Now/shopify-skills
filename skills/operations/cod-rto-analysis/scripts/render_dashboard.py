"""Render the rto_analysis.py JSON into one self-contained HTML dashboard.

Usage:
    python3 rto_analysis.py --orders orders.csv --setup setup.json > result.json
    python3 render_dashboard.py result.json rto-dashboard.html [--title "Store name"]

The page works offline and on a phone. Scenario inputs (cost per failed order and the
assumed effect of prepayment and confirmation) recompute money lost and savings live.
"""
import argparse, html, json

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>COD failures: __TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f6f3ee;--card:#fff;--ink:#1d1b18;--mute:#6b645a;--line:#e4ddd2;--bad:#b4442c;--ok:#2f6f4f;--acc:#c98a2b}
@media (prefers-color-scheme:dark){:root{--bg:#171512;--card:#211e1a;--ink:#f1ece4;--mute:#a59d90;--line:#36312a;--bad:#e2775e;--ok:#6fbf93;--acc:#e0a94f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",Georgia,serif}
main{max-width:1000px;margin:0 auto;padding:16px}
h1,h2{font-family:Fraunces,Georgia,serif;margin:.2em 0 .4em}h1{font-size:26px}h2{font-size:19px;margin-top:28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.k{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.k b{display:block;font-size:22px;font-family:Fraunces,Georgia,serif}.k span{color:var(--mute);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.act b{color:var(--ok)}.tag{font-size:12px;color:var(--mute)}
.scn{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
label{font-size:13px;color:var(--mute)}input,select{width:100%;padding:10px;font-size:16px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
.bar{height:6px;background:var(--line);border-radius:3px;min-width:60px}.bar i{display:block;height:6px;border-radius:3px;background:var(--bad)}
.dim{color:var(--mute)}footer{color:var(--mute);font-size:12px;margin:30px 0 10px;text-align:center}
ul{padding-left:20px}
@media (max-width:480px){.hb{display:none}table{font-size:13px}th,td{padding:7px 3px}}
</style></head><body><main>
<h1>Where COD orders fail</h1>
<div class="tag" id="period"></div>
<div class="kpis" id="kpis"></div>
<h2>What to do</h2><div id="actions"></div>
<h2>Test your numbers</h2>
<div class="card scn">
<div><label>Outbound shipping per failed order</label><input id="c_o" type="number" inputmode="decimal"></div>
<div><label>Return shipping</label><input id="c_r" type="number" inputmode="decimal"></div>
<div><label>COD fee on a failed order</label><input id="c_c" type="number" inputmode="decimal"></div>
<div><label>Packaging</label><input id="c_p" type="number" inputmode="decimal"></div>
<div><label>Failures avoided by prepayment %</label><input id="r_p" type="number" inputmode="decimal"></div>
<div><label>Failures avoided by confirmation %</label><input id="r_c" type="number" inputmode="decimal"></div>
</div>
<h2>Segments</h2>
<div class="card"><label>View by</label><select id="dim"></select>
<div class="tw"><table id="seg"></table></div>
<div class="tag" id="segnote"></div></div>
<div id="reasons"></div>
<div id="unknown"></div>
<h2>Assumptions</h2><div class="card"><ul id="assume"></ul></div>
<footer>Made with the free ReplAi skills pack</footer>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const cur = D.currency || "";
const fmt = x => x == null ? "n/a" : Math.round(x).toLocaleString() + " " + cur;
const pct = x => x == null ? "n/a" : (x * 100).toFixed(1) + "%";
const O = D.overall, F = O.failed || 0, perMonth = D.period.days ? 30 / D.period.days : 0;
const bd = O.loss_breakdown || {};
const avg = k => F ? (bd[k] || 0) / F : 0;
const base = {o: avg("outbound"), r: avg("return"), c: avg("cod_fee"), p: avg("packaging")};
const baseCost = base.o + base.r + base.c + base.p;
const r2 = x => Math.round(x * 100) / 100;
$("c_o").value = r2(base.o); $("c_r").value = r2(base.r);
$("c_c").value = r2(base.c); $("c_p").value = r2(base.p);
$("r_p").value = 50; $("r_c").value = 30;
let bp = 0.5, bc = 0.3;
(D.assumptions || []).forEach(a => {
  const m = a.match(/prepayment assumed to avoid (\d+)%.*confirmation (\d+)%/);
  if (m) { $("r_p").value = m[1]; $("r_c").value = m[2]; bp = m[1] / 100; bc = m[2] / 100; }
});
$("period").textContent = `${D.period.from || "?"} to ${D.period.to || "?"} (${D.period.days} days), ${D.scope}. Failure (RTO) rate = parcels that went out and came back unpaid.`;
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function cost() { return ["c_o","c_r","c_c","c_p"].reduce((s, id) => s + (+$(id).value || 0), 0); }
function draw() {
  const c = cost(), rp = (+$("r_p").value || 0) / 100, rc = (+$("r_c").value || 0) / 100;
  // Scale the measured money by the new cost per failed order (keeps courier-specific fees).
  const k = baseCost ? c / baseCost : 0;
  // No measured cost and none typed: money lost is unknown (n/a), never 0.
  const money = (m, failed) => baseCost ? (m || 0) * k : (c ? failed * c : null);
  const lost = money(O.money_lost, F);
  $("kpis").innerHTML = [
    [pct(O.delivery_success_rate), "delivered"], [pct(O.failure_rate), "failed (RTO)"],
    [(F).toLocaleString(), "failed orders"], [fmt(lost), "lost in period"],
    [fmt(lost == null ? null : lost * perMonth), "lost per month"], [fmt(c), "per failed order"]
  ].map(k => `<div class="k"><b>${k[0]}</b><span>${k[1]}</span></div>`).join("");
  $("actions").innerHTML = (D.actions || []).slice(0, 6).map(a => {
    const isPre = a.type === "prepay_area" || (a.type === "customer_rule" && /failed before/.test(a.target));
    // No measured cost (setup had none): failures avoided x the cost typed above.
    let s = baseCost ? (a.estimated_saving || 0) * k : (a.failures_avoided_estimate || 0) * c;
    if (a.type !== "switch_courier") s = s * (isPre ? (bp ? rp / bp : 0) : (bc ? rc / bc : 0));
    return `<div class="card act">${esc(a.action)}<br><b>${c ? "about " + fmt(s * perMonth) + " per month" : "type your cost per failed order above to see the saving"}</b>
      <span class="tag">(estimate, ${esc(a.basis)}; ${a.segment_orders} orders, ${pct(a.segment_failure_rate)} failed, confidence ${esc(a.confidence)})</span></div>`;
  }).join("") + (D.actions && D.actions.length ? `<div class="tag">Savings overlap. Do not add them up.</div>` : `<div class="card">No segment fails clearly more than the store average with enough orders to be sure.</div>`);
  const dim = $("dim").value, rows = D.segments[dim] || [];
  const ranked = rows.filter(r => r.ranked).sort((a, b) => b.failure_rate - a.failure_rate);
  const small = rows.filter(r => !r.ranked);
  $("seg").innerHTML = `<tr><th>${esc(dim.replace(/_/g, " "))}</th><th>orders</th><th>failed</th><th>rate</th><th class="hb"></th><th>95% range</th><th>lost</th></tr>` +
    ranked.map(r => `<tr><td>${esc(r.value)}</td><td>${r.resolved}</td><td>${r.failed}</td><td>${pct(r.failure_rate)}</td>
      <td class="hb"><div class="bar"><i style="width:${Math.round(r.failure_rate * 100)}%"></i></div></td>
      <td class="dim">${pct(r.ci95_low)}-${pct(r.ci95_high)}</td><td>${fmt(money(r.money_lost, r.failed))}</td></tr>`).join("");
  $("segnote").textContent = small.length ? `${small.length} more with fewer than ${D.min_orders} orders are not ranked: ${small.slice(0, 12).map(r => r.value + " (" + r.failed + "/" + r.resolved + ")").join(", ")}${small.length > 12 ? "..." : ""}` : "";
}
Object.keys(D.segments).forEach(k => { const o = document.createElement("option"); o.value = k; o.textContent = k.replace(/_/g, " "); $("dim").appendChild(o); });
if (D.failure_reasons && D.failure_reasons.length) $("reasons").innerHTML = `<h2>Why they failed (courier)</h2><div class="card tw"><table>${D.failure_reasons.map(r => `<tr><td>${esc(r.reason)}</td><td>${r.orders}</td></tr>`).join("")}</table></div>`;
if (D.unknown_regions && D.unknown_regions.length) $("unknown").innerHTML = `<h2>Addresses we could not place</h2><div class="card tw"><table><tr><th>province</th><th>city</th><th>country</th><th>orders</th></tr>${D.unknown_regions.slice(0, 30).map(r => `<tr><td>${esc(r.province || "-")}</td><td>${esc(r.city || "-")}</td><td>${esc(r.country || "-")}</td><td>${r.orders}</td></tr>`).join("")}</table></div>`;
$("assume").innerHTML = (D.assumptions || []).concat(D.warnings || []).map(a => `<li>${esc(a)}</li>`).join("");
document.querySelectorAll("input,select").forEach(e => e.addEventListener("input", draw));
draw();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("out")
    ap.add_argument("--title", default="COD orders")
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
