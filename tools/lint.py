"""Lint every skill in skills/<bucket>/ against the Agent Skills spec and this repo's rules.

Pack rules (setup, safety, credit line, metadata, shared helper) apply to the skills listed
in pdf/content.json; the spec, description length, dash and leftover checks apply to all.

    python3 tools/lint.py            # all skills
    python3 tools/lint.py <name>     # one skill
Exit code 1 if any check fails.
"""
import os, re, sys, filecmp, json, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
SHARED = os.path.join(ROOT, "shared", "tabular.py")
DASHES = re.compile("[\\u2013\\u2014]")
# Words that must never ship (real merchant names, personal data), one per line in
# tools/private-words.txt. That file is git ignored so the list itself stays private.
_words_file = os.path.join(ROOT, "tools", "private-words.txt")
_words = [w.strip() for w in open(_words_file, encoding="utf-8")] if os.path.exists(_words_file) else []
_words = [re.escape(w) for w in _words if w and not w.startswith("#")]
BANNED = re.compile(r"\b(" + "|".join(_words) + r")\b", re.I) if _words else re.compile(r"(?!)")
REQUIRED_SECTIONS = ["## Setup", "## Safety"]
# Older Claude.ai builds reject longer descriptions (see CLAUDE.md).
DESC_MAX = 200
PACK = {s["slug"] for s in json.load(open(os.path.join(ROOT, "pdf", "content.json"), encoding="utf-8"))["skills"]}


def find_skills():
    return {os.path.basename(os.path.dirname(p)): os.path.dirname(p)
            for p in sorted(glob.glob(os.path.join(SKILLS, "*", "*", "SKILL.md")))}


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    fm, body = {}, text[m.end():]
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^[a-z\-]+:", line):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"')
        elif key and line.startswith("  "):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, body


def lint(name, d):
    errs = []
    pack = name in PACK
    path = os.path.join(d, "SKILL.md")
    if not os.path.isfile(path):
        return [f"{name}: missing SKILL.md"]
    text = open(path, encoding="utf-8").read()
    fm, body = frontmatter(text)
    if fm is None:
        return [f"{name}: missing YAML frontmatter"]
    n = fm.get("name", "")
    if n != name:
        errs.append(f"name '{n}' must match folder '{name}'")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", n) or len(n) > 64:
        errs.append("name must be lowercase a-z0-9 and single hyphens, max 64")
    desc = fm.get("description", "")
    if not desc or len(desc) > DESC_MAX:
        errs.append(f"description must be 1-{DESC_MAX} chars (is {len(desc)})")
    if pack and "metadata" not in fm:
        errs.append("metadata block missing (author, version)")
    lines = text.count("\n")
    if lines > 500:
        errs.append(f"SKILL.md is {lines} lines (max 500); move detail to references/")
    for sec in REQUIRED_SECTIONS if pack else []:
        if sec not in body:
            errs.append(f"missing section '{sec}'")
    if pack and "by ReplAi" not in body:
        errs.append("missing 'by ReplAi' credit line")
    # Every file in the skill: dashes, banned words, broken relative references.
    for dp, _, files in os.walk(d):
        for f in files:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, d)
            if f.endswith((".png", ".jpg", ".pyc")) or "__pycache__" in p:
                continue
            try:
                t = open(p, encoding="utf-8").read()
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(t.splitlines(), 1):
                if DASHES.search(line):
                    errs.append(f"{rel}:{i} contains an em/en dash")
                if BANNED.search(line):
                    errs.append(f"{rel}:{i} contains private leftover '{BANNED.search(line).group(0)}'")
    for ref in re.findall(r"\]\(((?:references|scripts|assets)/[^)#\s]+)\)", body) + \
               re.findall(r"`((?:references|scripts|assets)/[A-Za-z0-9_.\-/]+)`", body):
        if not os.path.exists(os.path.join(d, ref)):
            errs.append(f"referenced file not found: {ref}")
    tab = os.path.join(d, "scripts", "tabular.py")
    if os.path.exists(tab) and not filecmp.cmp(tab, SHARED, shallow=False):
        errs.append("scripts/tabular.py differs from shared/tabular.py (copy it verbatim)")
    if pack and not os.path.exists(os.path.join(d, "assets", "setup.example.json")):
        errs.append("assets/setup.example.json missing")
    return [f"{name}: {e}" for e in errs]


if __name__ == "__main__":
    found = find_skills()
    names = sys.argv[1:] or sorted(found)
    missing = sorted(PACK - set(found))
    all_errs = [f"{m}: listed in pdf/content.json but no skills/<bucket>/{m}/SKILL.md" for m in missing]
    for n in names:
        e = lint(n, found[n]) if n in found else [f"{n}: not found under skills/<bucket>/"]
        all_errs += e
        print(("FAIL " if e else "ok   ") + n)
    for e in all_errs:
        print("  " + e)
    sys.exit(1 if all_errs else 0)
