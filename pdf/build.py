"""Build the ReplAi skills pack PDFs (one per skill plus the full pack) with headless Chrome.

Usage:
    python3 pdf/build.py [--repo OWNER/REPO (default ReplAi-Now/shopify-skills)] [--only <slug>] [--html-only]

With --repo "" the install prompt shows a visible placeholder and every page is marked DRAFT.
Output: pdf/out/<nn>-<slug>.pdf and pdf/out/replai-ecommerce-skills-pack.pdf (HTML kept in pdf/out/html/).
"""
import argparse, glob, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
LOGOS = os.path.join(os.path.dirname(os.path.dirname(ROOT)), "Brand Assets", "brand-logos")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
AGENTS = "Claude, ChatGPT, Gemini, Codex, Cursor or Copilot"

CSS = """
@page { size: A4; margin: 0; }
:root { --brand:#5B4FE5; --page:#FAFAF8; --surface:#FFFFFF; --dark:#111110; --dark2:#1A1A19;
  --border:#E8E8E4; --text:#1A1A1A; --muted:#6B6B6B; --success:#2BA06A; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--page); color: var(--text); font-family: 'General Sans', sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; position: relative; overflow: hidden; page-break-after: always;
  background: var(--page); }
.page:last-child { page-break-after: auto; }
h1, h2, h3 { font-family: 'Sentient', serif; font-weight: 500; letter-spacing: -0.015em; }
em { font-style: italic; }
.eyebrow { font-family: 'JetBrains Mono', monospace; font-size: 8pt; text-transform: uppercase;
  letter-spacing: 0.18em; color: var(--muted); }
.mono { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
.band { background: var(--dark); color: #fff; padding: 16mm 18mm 13mm; position: relative; }
.band .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 11mm; }
.band .logo { height: 8mm; }
.band .eyebrow { color: rgba(255,255,255,0.6); }
.band h1 { font-size: 34pt; line-height: 1.08; max-width: 165mm; }
.band h1 em { color: var(--brand); }
.band .tag { margin-top: 6mm; font-size: 12pt; line-height: 1.5; color: rgba(255,255,255,0.78); max-width: 160mm; }
.body { padding: 9mm 18mm 0; }
.grid { display: grid; grid-template-columns: 1.35fr 1fr; gap: 9mm; }
.section h3 { font-size: 15pt; margin: 2.5mm 0 4mm; }
ol.list { list-style: none; }
ol.list li { display: grid; grid-template-columns: 9mm 1fr; font-size: 10pt; line-height: 1.5; margin-bottom: 3.2mm; }
ol.list li .n { font-family: 'JetBrains Mono', monospace; font-size: 8.5pt; color: var(--brand); padding-top: 0.6mm; }
.chips { display: flex; flex-wrap: wrap; gap: 2.2mm; }
.chip { border: 1px solid var(--border); background: var(--surface); padding: 2mm 3mm;
  font-family: 'JetBrains Mono', monospace; font-size: 8pt; line-height: 1.35; }
.agents { margin-top: 5mm; font-size: 9pt; line-height: 1.5; color: var(--muted); }
.install { margin: 6mm 18mm 0; background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--brand); padding: 6mm 8mm; }
.install h3 { font-size: 15pt; margin: 2mm 0 4mm; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6mm; margin-top: 5mm; }
.step .n { font-family: 'JetBrains Mono', monospace; color: var(--brand); font-size: 8.5pt; }
.step p { font-size: 9pt; line-height: 1.5; margin-top: 1.5mm; }
.prompt { background: var(--dark); color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 9pt;
  line-height: 1.6; padding: 4.5mm 5mm; word-break: break-word; }
.prompt .ph { background: #F4D35E; color: var(--dark); padding: 0 1mm; }
.prompt .lbl { display: block; color: rgba(255,255,255,0.5); font-size: 7pt; letter-spacing: 0.18em;
  text-transform: uppercase; margin-bottom: 1.5mm; }
.p2 { padding: 16mm 18mm 0; }
.p2 .head { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border);
  padding-bottom: 5mm; margin-bottom: 9mm; }
.p2 .head .logo { height: 6mm; }
.p2 h2 { font-size: 24pt; line-height: 1.1; margin: 2.5mm 0 6mm; }
.p2 h2 em { color: var(--brand); }
.setup { background: var(--surface); border: 1px solid var(--border); padding: 6mm 7mm; }
.setup p.lead { font-size: 9.5pt; line-height: 1.55; color: var(--muted); margin-bottom: 4mm; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; margin-top: 7mm; }
.quote { border: 1px solid var(--border); background: var(--surface); padding: 3.5mm 4.5mm; margin-bottom: 3mm;
  font-size: 9.5pt; line-height: 1.5; }
.quote::before { content: "\\201C"; font-family: 'Sentient', serif; color: var(--brand); font-size: 15pt;
  line-height: 0; margin-right: 1mm; vertical-align: -4pt; }
ul.check { list-style: none; }
ul.check li { font-size: 9.5pt; line-height: 1.5; padding-left: 6mm; position: relative; margin-bottom: 3mm; }
ul.check li::before { content: ""; position: absolute; left: 0; top: 1.6mm; width: 2.4mm; height: 2.4mm; background: var(--brand); }
.safe { margin-top: 7mm; background: var(--dark); color: #fff; padding: 6mm 7mm; display: grid;
  grid-template-columns: 38mm 1fr; gap: 6mm; align-items: start; }
.safe .eyebrow { color: rgba(255,255,255,0.6); padding-top: 1mm; }
.safe p { font-size: 9.5pt; line-height: 1.55; color: rgba(255,255,255,0.85); }
.more { margin-top: 8mm; }
.more .g { display: flex; flex-wrap: wrap; gap: 2mm; margin-top: 3mm; }
.more .g span { border: 1px solid var(--border); background: var(--surface); padding: 1.6mm 2.6mm;
  font-family: 'JetBrains Mono', monospace; font-size: 7.4pt; color: var(--text); }
.foot { position: absolute; left: 18mm; right: 18mm; bottom: 10mm; display: flex; justify-content: space-between;
  align-items: center; border-top: 1px solid var(--border); padding-top: 3.5mm; }
.foot span { font-family: 'JetBrains Mono', monospace; font-size: 7pt; color: var(--muted); letter-spacing: 0.08em; }
.draft { color: #B4232A !important; }
/* cover */
.cover { background: var(--dark); color: #fff; padding: 20mm 18mm; }
.nw { white-space: nowrap; }
.cover .logo { height: 11mm; }
.cover h1 { font-size: 44pt; line-height: 1.04; margin-top: 30mm; max-width: 165mm; }
.cover h1 em { color: var(--brand); }
.cover .tag { margin-top: 8mm; font-size: 12.5pt; line-height: 1.55; color: rgba(255,255,255,0.78); max-width: 155mm; }
.index { margin-top: 16mm; display: grid; grid-template-columns: 1fr 1fr; gap: 0 10mm;
  border-top: 1px solid rgba(255,255,255,0.12); }
.index div { display: grid; grid-template-columns: 10mm 1fr auto; padding: 3.4mm 0;
  border-bottom: 1px solid rgba(255,255,255,0.12); font-size: 10pt; align-items: baseline; }
.index .n { font-family: 'JetBrains Mono', monospace; color: var(--brand); font-size: 8.5pt; }
.index .c { font-family: 'JetBrains Mono', monospace; font-size: 7pt; color: rgba(255,255,255,0.5);
  text-transform: uppercase; letter-spacing: 0.14em; }
.cover .foot { border-top-color: rgba(255,255,255,0.12); }
.cover .foot span { color: rgba(255,255,255,0.5); }
.how { padding: 18mm; }
.how h2 { font-size: 28pt; line-height: 1.1; margin: 3mm 0 8mm; }
.how h2 em { color: var(--brand); }
.how .card { background: var(--surface); border: 1px solid var(--border); padding: 6mm 7mm; margin-bottom: 6mm; }
.how .card h3 { font-size: 13.5pt; margin-bottom: 3mm; }
.how .card p { font-size: 9.5pt; line-height: 1.55; color: var(--text); margin-bottom: 3mm; }
"""

FONTS = ('<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=sentient@400,401,500,501'
         '&f[]=general-sans@400,500,600&display=swap">'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap">')

DASH = re.compile("[\u2013\u2014]")


def e(s):
    return html.escape(s, quote=True)


def em(title):
    """'Find where COD *goes wrong*' -> escaped HTML with one <em>."""
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", e(title))


def skill_folder(slug):
    """skills/<bucket>/<slug>, read from the repo so the PDF matches where the skill lives."""
    hits = glob.glob(os.path.join(ROOT, "skills", "*", slug, "SKILL.md"))
    if len(hits) != 1:
        sys.exit(f"expected one skills/<bucket>/{slug}/SKILL.md, found {len(hits)}")
    return os.path.relpath(os.path.dirname(hits[0]), ROOT)


def prompt_html(slug, repo):
    if repo:
        url = f'<span class="nw">https://github.com/{e(repo)}</span>'
    else:
        url = '<span class="ph">github.com/REPO-LINK-PENDING</span>'
    return (f'<div class="prompt"><span class="lbl">Paste this into your AI agent</span>'
            f'Install the "{e(slug)}" skill from {url} (folder {e(skill_folder(slug))}), then run it.</div>')


def foot(left, right, repo):
    draft = '' if repo else ' <span class="draft">DRAFT: repo link pending</span>'
    return f'<div class="foot"><span>{left}{draft}</span><span>{right}</span></div>'


def skill_pages(i, n, s, repo, logo_white, logo_color, others=()):
    num = f"{i:02d}"
    does = "".join(f'<li><span class="n">{k:02d}</span><span>{e(x)}</span></li>' for k, x in enumerate(s["does"], 1))
    chips = "".join(f'<span class="chip">{e(x)}</span>' for x in s["needs"])
    setup = "".join(f'<li><span class="n">{k:02d}</span><span>{e(x)}</span></li>' for k, x in enumerate(s["setup"], 1))
    tries = "".join(f'<div class="quote">{e(x)}</div>' for x in s["try"])
    gets = "".join(f"<li>{e(x)}</li>" for x in s["get"])
    more = "".join(f'<span>{e(o["slug"])}</span>' for o in others)
    p1 = f"""
<section class="page">
  <div class="band">
    <div class="top"><img class="logo" src="{logo_white}" alt="ReplAi"><span class="eyebrow">Free skill {num} / {n:02d} &middot; {e(s['category'])}</span></div>
    <h1>{em(s['title'])}</h1>
    <p class="tag">{e(s['tagline'])}</p>
  </div>
  <div class="body grid">
    <div class="section"><span class="eyebrow">What it does</span><h3>Work it takes off your plate</h3><ol class="list">{does}</ol></div>
    <div class="section"><span class="eyebrow">What you need</span><h3>Before you start</h3><div class="chips">{chips}</div>
      <p class="agents">Works in {AGENTS}, and any agent that reads skills. Skill name: <span class="mono">{e(s['slug'])}</span></p></div>
  </div>
  <div class="install">
    <span class="eyebrow">Install in one minute</span>
    <h3>Three steps, once</h3>
    {prompt_html(s['slug'], repo)}
    <div class="steps">
      <div class="step"><span class="n">01</span><p>Paste the line above into your AI agent. It installs the skill for you.</p></div>
      <div class="step"><span class="n">02</span><p>Answer a few setup questions once. Reply "defaults" to skip any of them.</p></div>
      <div class="step"><span class="n">03</span><p>Use it whenever you need it, with prompts like the ones on the next page.</p></div>
    </div>
  </div>
  {foot('replai.now', f'{num} &middot; {e(s["slug"])} &middot; 1/2', repo)}
</section>"""
    p2 = f"""
<section class="page">
  <div class="p2">
    <div class="head"><img class="logo" src="{logo_color}" alt="ReplAi"><span class="eyebrow">Free skill {num} &middot; {e(s['slug'])}</span></div>
    <span class="eyebrow">First run</span>
    <h2>It asks once, <em>then remembers</em>.</h2>
    <div class="setup"><p class="lead">The first time you run it, the skill asks a short set of questions in one message and saves your answers for every run after. Change them any time by saying "change my setup".</p><ol class="list">{setup}</ol></div>
    <div class="cols">
      <div><span class="eyebrow">Try saying</span><h3 style="font-size:15pt;margin:2.5mm 0 4mm">Prompts that work</h3>{tries}</div>
      <div><span class="eyebrow">What you get</span><h3 style="font-size:15pt;margin:2.5mm 0 4mm">The output</h3><ul class="check">{gets}</ul></div>
    </div>
    <div class="safe"><span class="eyebrow">Your store, your call</span><p>{e(s['safety'])} Your data stays between you, your agent and the tools you connected.</p></div>
    <div class="more"><span class="eyebrow">Also in the free pack</span><div class="g">{more}</div></div>
  </div>
  {foot('Made with the free ReplAi skills pack', f'{num} &middot; {e(s["slug"])} &middot; 2/2', repo)}
</section>"""
    return p1 + p2


def cover_pages(data, repo, logo_white, logo_color):
    rows = "".join(f'<div><span class="n">{i:02d}</span><span>{e(s["slug"])}</span><span class="c">{e(s["category"])}</span></div>'
                   for i, s in enumerate(data["skills"], 1))
    cover = f"""
<section class="page cover">
  <img class="logo" src="{logo_white}" alt="ReplAi">
  <h1>The free e-commerce <em>skills</em> pack</h1>
  <p class="tag">{e(data['pack_tagline'])}</p>
  <div class="index">{rows}</div>
  {foot('replai.now', 'Works in Claude, ChatGPT, Gemini, Codex, Cursor', repo)}
</section>"""
    repo_txt = f'<span class="nw">github.com/{e(repo)}</span>' if repo else '<span class="mono draft">github.com/REPO-LINK-PENDING</span>'
    how = f"""
<section class="page">
  <div class="how">
    <img class="logo" src="{logo_color}" alt="ReplAi" style="height:6mm">
    <div style="margin-top:12mm"><span class="eyebrow">How it works</span></div>
    <h2>Install once, <em>reuse every week</em>.</h2>
    <div class="card"><h3>1. Install a skill</h3><p>Each skill has its own page in this pack with a one-line prompt. Paste it into your AI agent ({AGENTS}) and it installs the skill from {repo_txt}.</p><p>Using the Claude app? Download the skill's zip from the repo's Releases page and upload it in Customize &gt; Skills. Comfortable with a terminal? <span class="mono nw">npx skills@latest add {e(repo) if repo else 'REPO-LINK-PENDING'} --skill &lt;name&gt;</span></p></div>
    <div class="card"><h3>2. Answer the setup questions once</h3><p>The first run asks a few questions in one message: your currency, how you mark failed orders, your costs, your style. The answers are saved in a <span class="mono">replai-setup</span> folder next to your files. In chat apps without files, the skill gives you a short setup card to paste next time.</p></div>
    <div class="card"><h3>3. Connect your store, or just upload files</h3><p>Skills read your Shopify data through the Shopify connector if your agent has one. No connector? Every skill also works with the CSV exports from your Shopify admin, plus files from your couriers, ad accounts and suppliers.</p></div>
    <div class="card"><h3>4. You stay in control</h3><p>Skills are read only by default. Before anything changes in your store, the skill shows you the exact list of changes and waits for your yes. Nothing is ever deleted, and changes can be rolled back.</p></div>
  </div>
  {foot('replai.now', 'Made with the free ReplAi skills pack', repo)}
</section>"""
    return cover + how


def doc(body, title):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>{FONTS}'
            f'<style>{CSS}</style></head><body>{body}</body></html>')


def render(html_path, pdf_path):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--run-all-compositor-stages-before-draw", "--virtual-time-budget=15000",
                    f"--print-to-pdf={pdf_path}", "file://" + html_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="ReplAi-Now/shopify-skills")
    ap.add_argument("--only")
    ap.add_argument("--html-only", action="store_true")
    a = ap.parse_args()
    data = json.load(open(os.path.join(HERE, "content.json"), encoding="utf-8"))
    bad = [m.group(0) for m in DASH.finditer(json.dumps(data, ensure_ascii=False))]
    if bad:
        sys.exit("content.json contains em/en dashes; remove them first")
    os.makedirs(os.path.join(OUT, "html"), exist_ok=True)
    logo_white = "file://" + os.path.join(LOGOS, "replai-wordmark-white-1024.png")
    logo_color = "file://" + os.path.join(LOGOS, "replai-wordmark-fullcolor-1024.png")
    n = len(data["skills"])
    made = []
    pack = [cover_pages(data, a.repo, logo_white, logo_color)]
    for i, s in enumerate(data["skills"], 1):
        pages = skill_pages(i, n, s, a.repo, logo_white, logo_color, [o for o in data['skills'] if o is not s])
        pack.append(pages)
        if a.only and s["slug"] != a.only:
            continue
        hp = os.path.join(OUT, "html", f"{i:02d}-{s['slug']}.html")
        open(hp, "w", encoding="utf-8").write(doc(pages, f"ReplAi skill: {s['slug']}"))
        made.append((hp, os.path.join(OUT, f"{i:02d}-{s['slug']}.pdf")))
    if not a.only:
        hp = os.path.join(OUT, "html", "replai-ecommerce-skills-pack.html")
        open(hp, "w", encoding="utf-8").write(doc("".join(pack), "ReplAi e-commerce skills pack"))
        made.append((hp, os.path.join(OUT, "replai-ecommerce-skills-pack.pdf")))
    if not a.html_only:
        for hp, pp in made:
            render(hp, pp)
    print(json.dumps({"files": [p for _, p in made], "repo": a.repo or "PENDING"}, indent=1))


if __name__ == "__main__":
    main()
