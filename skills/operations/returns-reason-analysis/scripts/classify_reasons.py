"""Classify return reasons (English, Arabic, Franco-Arabic) into the returns taxonomy.

Usage:
    python3 classify_reasons.py --returns returns.csv --out classified.csv
        [--lexicon ../assets/reason-lexicon.json] [--setup setup.json] [--overrides overrides.csv]

--returns    One row per returned line: from extract_from_orders.py, from the connector (see
             references/shopify-queries.md), a returns app CSV or a courier returns CSV. Columns are
             matched by meaning: order, order_date, return_date, product, variant, sku, vendor,
             quantity, type (refund / exchange / refused), reason_code, reason_text, customer_note,
             refund_amount, return_shipping_cost.
--overrides  CSV with columns row,category: your (the agent's) classification of the rows the
             lexicon could not classify, or the merchant's corrections. Applied last.
--setup      Optional: "taxonomy_overrides" {"category": ["extra keyword", ...]} adds keywords.

Order of decisions per row: type "refused" > Shopify reason code (when specific) > lexicon match on
the free text > overrides. Writes the classified CSV and prints a JSON summary including
"unclassified" (rows with text but no match) for the agent to classify. No network access.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabular import read_rows, pick, num, norm, write_csv  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEXICON = os.path.join(HERE, "..", "assets", "reason-lexicon.json")
COLUMNS = ["row", "return_id", "order", "order_date", "return_date", "product", "variant", "sku", "vendor",
           "quantity", "type", "reason_code", "reason_text", "refund_amount", "return_shipping_cost",
           "source", "category", "category_source", "matched", "secondary"]

NO_RETURNS = ("The returns file has no rows, so there is nothing to classify. If it came from extract_from_orders.py, "
              "the orders export showed no refunds, no return or exchange tags and no refused orders. Stores that keep "
              "returns as Shopify return records, or take items back without refunding (Try & Buy, exchanges, store "
              "credit), do not show them in the orders export: use the Shopify connector (references/shopify-queries.md) "
              "or a returns app export.")

_DIAC = re.compile("[ً-ْـٰ]")


def normalise(text):
    """Lowercase, strip Arabic diacritics and tatweel, unify letter forms, collapse repeats."""
    t = str(text or "").lower()
    t = _DIAC.sub("", t)
    t = re.sub("[أإآٱ]", "ا", t)  # alef forms to bare alef
    t = t.replace("ة", "ه").replace("ى", "ي")  # taa marbuta, alef maqsura
    t = re.sub("[’'`]", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"(.)\1+", r"\1", t)  # kbeeer -> kber, واااسع -> واسع
    return re.sub(r"\s+", " ", t).strip()


def load_lexicon(path, setup=None):
    with open(path or DEFAULT_LEXICON, encoding="utf-8") as fh:
        lex = json.load(fh)
    for cat, words in ((setup or {}).get("taxonomy_overrides") or {}).items():
        if cat in lex["categories"]:
            lex["categories"][cat]["keywords"].setdefault("custom", []).extend(words)
    patterns = []
    for cat, spec in lex["categories"].items():
        for group, words in spec["keywords"].items():
            for w in words:
                n = normalise(w)
                if not n:
                    continue
                if group.endswith("_word"):
                    # Whole word only, any script: "بدل" (instead of) but not "استبدل" (exchange) or "بدله" (suit).
                    rx = re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)")
                elif re.search(r"[a-z0-9]", n):
                    rx = re.compile(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])")
                else:
                    rx = re.compile(re.escape(n))
                patterns.append((len(n), cat, w, rx))
    patterns.sort(key=lambda p: -p[0])
    lex["_patterns"] = patterns
    lex["_rank"] = {c: i for i, c in enumerate(lex["priority"])}
    lex["_exchange"] = [normalise(w) for w in lex.get("exchange_keywords", [])]
    return lex


# A negator right before a size keyword cancels it: "not small enough", "مش صغير", "mesh soghayar"
# are not "too small". Only size categories: in "does not fit" the negation is the complaint itself.
NEGATORS = {"not", "isnt", "wasnt", "arent", "never", "مش", "مو", "ما", "مب", "mesh", "msh", "mish", "mush",
            "mosh", "ma", "mo", "mu", "mb"}
NEGATABLE = {"size_too_small", "size_too_large"}


def negated(t, start):
    """True when the word just before position `start` of normalised text t is a negator."""
    before = t[:start]
    if before and not before.endswith(" "):
        return False  # keyword matched inside a word (Arabic substring match)
    words = before.split()
    return bool(words) and words[-1] in NEGATORS


def match_text(text, lex):
    """Return (best_category or None, matched keywords, other categories hit)."""
    t = normalise(text)
    if not t:
        return None, [], []
    taken = []
    hits = {}
    for _, cat, word, rx in lex["_patterns"]:
        for m in rx.finditer(t):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))  # a negated keyword still blocks shorter keywords inside it
            if cat in NEGATABLE and negated(t, s):
                continue
            hits.setdefault(cat, []).append(word)
    if not hits:
        return None, [], []
    rank = lex["_rank"]
    order = sorted(hits, key=lambda c: (-len(hits[c]), rank.get(c, 99)))
    return order[0], hits[order[0]], order[1:]


def code_category(code, lex):
    c = norm(code)
    if c in lex["reason_codes"]:
        return True, lex["reason_codes"][c]
    return False, None


def detect_type(raw_type, text, lex):
    t = normalise(raw_type)
    if re.search(r"refus|rto|reject|return(ed)? to (origin|sender|shipper)|رفض|مرفوض", t):
        return "refused"
    if re.search(r"exchang|swap|replac|استبدال|تبديل", t):
        return "exchange"
    if t:
        return "refund"
    nt = normalise(text)
    for w in lex["_exchange"]:
        if re.search(r"[a-z]", w):
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", nt):
                return "exchange"
        elif w in nt:
            return "exchange"
    return "refund"


def to_record(i, r):
    product = pick(r, "product", "product_title", "product_name", "item", "item_name", "lineitem_name")
    variant = pick(r, "variant", "variant_title", "option", "options")
    if not variant and " - " in product and not pick(r, "product", "product_title"):
        product, variant = product.rsplit(" - ", 1)
    code_raw = pick(r, "reason_code", "return_reason", "return_reason_handle", "reason_handle")
    texts = [pick(r, "reason_text", "return_reason_note", "reason_note"),
             pick(r, "customer_note", "customer_comment"), pick(r, "note", "notes", "comment", "message")]
    reason = pick(r, "reason", "return_reason_name")
    qty_raw = pick(r, "quantity", "qty", "return_quantity", "units", default="")
    return {
        "row": i,
        "return_id": pick(r, "return_id", "return_name", "rma", "return_number"),
        "order": pick(r, "order", "order_name", "order_number", "order_id"),
        "order_date": pick(r, "order_date", "order_created_at", "ordered_at")[:10],
        "return_date": pick(r, "return_date", "requested_at", "created_at", "date")[:10],
        "product": product.strip(),
        "variant": variant.strip(),
        "sku": pick(r, "sku", "variant_sku", "lineitem_sku"),
        "vendor": pick(r, "vendor", "supplier"),
        "quantity": qty_raw,
        "type_raw": pick(r, "type", "resolution", "return_type", "action", "outcome"),
        "code_raw": code_raw,
        "reason": reason,
        "texts": [t for t in texts if t],
        "refund_amount": pick(r, "refund_amount", "refund", "refunded", "amount_refunded", "refunded_amount"),
        "return_shipping_cost": pick(r, "return_shipping_cost", "return_shipping", "shipping_cost"),
        "source": pick(r, "source", default="returns_file"),
    }


def classify_rows(rows, lex, overrides=None):
    out, unclassified, conflicts = [], [], []
    for i, r in enumerate(rows, 1):
        rec = to_record(i, r)
        texts = list(rec["texts"])
        code_raw = rec["code_raw"]
        known, code_cat = code_category(code_raw, lex) if code_raw else (False, None)
        if rec["reason"]:
            k2, c2 = code_category(rec["reason"], lex)
            if k2 and not code_raw:
                known, code_cat, code_raw = k2, c2, rec["reason"]
            elif not k2:
                texts.insert(0, rec["reason"])
        if code_raw and not known:
            texts.insert(0, code_raw)
        text = " | ".join(texts)
        rtype = detect_type(rec["type_raw"], text, lex)
        text_cat, matched, secondary = match_text(text, lex)
        if rtype == "refused":
            cat, src = "refused_at_door", "type"
        elif code_cat:
            cat, src = code_cat, "code"
            if text_cat and text_cat != code_cat:
                conflicts.append({"row": i, "code_category": code_cat, "text_category": text_cat, "text": text})
        elif text_cat:
            cat, src = text_cat, "lexicon"
        else:
            cat, src = "other", "none"
        if text_cat == "refused_at_door" and rtype != "refused":
            rtype = "refused"
            cat, src = "refused_at_door", "lexicon"
        out.append({
            "row": i, "return_id": rec["return_id"], "order": rec["order"], "order_date": rec["order_date"],
            "return_date": rec["return_date"], "product": rec["product"], "variant": rec["variant"],
            "sku": rec["sku"], "vendor": rec["vendor"], "quantity": rec["quantity"], "type": rtype,
            "reason_code": code_raw if known else "", "reason_text": text,
            "refund_amount": rec["refund_amount"], "return_shipping_cost": rec["return_shipping_cost"],
            "source": rec["source"], "category": cat, "category_source": src,
            "matched": "; ".join(matched), "secondary": "; ".join(secondary),
        })
    overrides = overrides or {}
    for rec in out:
        if rec["row"] in overrides:
            rec["category"], rec["category_source"] = overrides[rec["row"]], "agent"
            if rec["category"] == "refused_at_door":
                rec["type"] = "refused"
    for rec in out:
        if rec["category_source"] == "none" and rec["reason_text"].strip():
            unclassified.append({"row": rec["row"], "product": rec["product"], "text": rec["reason_text"]})
    return out, unclassified, conflicts


def load_overrides(path, lex):
    out = {}
    for r in read_rows(path):
        row, cat = pick(r, "row"), pick(r, "category")
        if not row or not cat:
            continue
        if cat not in lex["categories"]:
            raise SystemExit(json.dumps({"error": f"Override row {row}: unknown category '{cat}'. Use one of {list(lex['categories'])}."}))
        out[int(num(row))] = cat
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--returns", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lexicon")
    ap.add_argument("--setup")
    ap.add_argument("--overrides")
    a = ap.parse_args()
    setup = {}
    if a.setup:
        with open(a.setup, encoding="utf-8") as fh:
            setup = json.load(fh)
    lex = load_lexicon(a.lexicon, setup)
    rows = read_rows(a.returns)
    if not rows:
        # Not an error to stop on: say why there is nothing and what would fill it.
        write_csv(a.out, [], COLUMNS)
        print(json.dumps({"rows": 0, "written": a.out, "no_returns_found": NO_RETURNS}, ensure_ascii=False, indent=1))
        return
    overrides = load_overrides(a.overrides, lex) if a.overrides else {}
    out, unclassified, conflicts = classify_rows(rows, lex, overrides)
    write_csv(a.out, out, COLUMNS)
    by_cat, by_src = {}, {}
    for r in out:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        by_src[r["category_source"]] = by_src.get(r["category_source"], 0) + 1
    print(json.dumps({"rows": len(out), "written": a.out, "by_category_rows": by_cat, "by_source": by_src,
                      "no_reason_given": sum(1 for r in out if not r["reason_text"].strip() and r["category_source"] == "none"),
                      "unclassified": unclassified, "code_text_conflicts": conflicts,
                      "categories": list(lex["categories"])}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
