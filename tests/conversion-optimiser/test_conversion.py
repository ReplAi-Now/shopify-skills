"""Tests for skills/store/conversion-optimiser/scripts. Expected values worked out by hand."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "store", "conversion-optimiser", "scripts"))
import prioritise, psi_summary, rollback  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EXAMPLE = os.path.join(ROOT, "skills", "store", "conversion-optimiser", "assets", "findings.example.json")


def run(mod, args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(args)
    return code, json.loads(buf.getvalue())


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Prioritise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.html = os.path.join(self.tmp, "r.html")
        self.csv = os.path.join(self.tmp, "f.csv")
        self.code, self.r = run(prioritise, [os.path.join(FX, "findings.json"), "--html", self.html, "--csv", self.csv])

    def test_order_and_buckets(self):
        self.assertEqual(self.code, 0)
        # P5 h/l=9; S1 h/m=6 beats P4 m/l=6 on impact; T2 m/m=4; C2 h/h=3 beats E3 l/l=3 on impact; A3 l/h=1
        self.assertEqual([f["id"] for f in self.r["fixes"]], ["P5", "S1", "P4", "T2", "C2", "E3", "A3"])
        self.assertEqual([f["priority"] for f in self.r["fixes"]], [9, 6, 6, 4, 3, 3, 1])
        self.assertEqual(self.r["buckets"], {"do_first": ["P5", "S1", "P4"], "next": ["T2", "C2", "E3"], "later": ["A3"]})
        self.assertEqual(self.r["fixes"][3]["impact"], "medium")  # "med" normalised

    def test_scores(self):
        # weights: S1 3, P5 3, P4 2 (partial 0.5), T2 2, E3 1, C2 3, A3 1, N2 3 pass, M1 2 pass (default)
        # den 20, num 1 + 3 + 2 = 6 -> 30
        self.assertEqual(self.r["health_score"], 30)
        self.assertEqual(self.r["areas"]["product"]["score"], 20)   # 2*0.5 / 5
        self.assertEqual(self.r["areas"]["trust"]["score"], 0)      # T3 na excluded
        self.assertEqual(self.r["areas"]["navigation"]["score"], 100)
        self.assertEqual(self.r["counts"], {"fail": 6, "na": 1, "partial": 1, "pass": 2, "unknown": 1})
        self.assertEqual(self.r["not_checked"][0]["id"], "C1")

    def test_outputs(self):
        h = read(self.html)
        self.assertIn("Made with the free ReplAi skills pack", h)
        self.assertIn('name="viewport"', h)
        self.assertIn("Delivery time near Add to cart", h)
        self.assertLess(h.index("Delivery time near Add to cart"), h.index("Image alt text"))
        self.assertNotIn("<script", h)
        self.assertTrue(read(self.csv).startswith("rank,bucket,priority,id"))

    def test_arabic_report(self):
        out = os.path.join(self.tmp, "ar.html")
        run(prioritise, [os.path.join(FX, "findings.json"), "--html", out, "--lang", "ar"])
        h = read(out)
        self.assertIn('dir="rtl" lang="ar"', h)
        self.assertIn("أهم التعديلات", h)
        self.assertIn("لاحقًا", h)

    def test_invalid(self):
        code, r = run(prioritise, [os.path.join(FX, "findings_bad.json")])
        self.assertEqual(code, 1)
        joined = " | ".join(r["errors"])
        for needle in ["impact must be", "evidence.url missing", "evidence.seen missing", "duplicate id",
                       "area must be", "status must be"]:
            self.assertIn(needle, joined)

    def test_example_asset_valid(self):
        code, r = run(prioritise, [EXAMPLE])
        self.assertEqual(code, 0, r.get("errors"))

    def test_escaping_and_unsafe_url(self):
        data = {"checks": [{"id": "X1", "area": "seo", "title": "<img src=x onerror=alert(1)>", "status": "fail",
                            "impact": "low", "effort": "low", "fix": "f",
                            "evidence": {"url": "javascript:alert(1)", "seen": "s"}}]}
        p = os.path.join(self.tmp, "x.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        out = os.path.join(self.tmp, "x.html")
        run(prioritise, [p, "--html", out])
        h = read(out)
        self.assertNotIn("<img src=x", h)
        self.assertNotIn('href="javascript', h)


class PSI(unittest.TestCase):
    def test_mobile_desktop(self):
        code, r = run(psi_summary, [os.path.join(FX, "psi_mobile.json"), os.path.join(FX, "psi_desktop.json")])
        self.assertEqual(code, 0)
        m = r["strategies"]["mobile"]
        self.assertEqual(m["performance_score"], 42)
        self.assertEqual(m["lab"], {"lcp_s": 5.2, "cls": 0.05, "tbt_ms": 450, "fcp_s": 2.1, "speed_index_s": 4.8})
        self.assertEqual(m["field"]["cls"], 0.12)  # API percentile 12 means 0.12
        self.assertEqual([o["id"] for o in m["opportunities"]],
                         ["render-blocking-resources", "uses-optimized-images", "offscreen-images"])
        self.assertEqual((m["image_savings_ms"], m["image_savings_kb"]), (900, 500))
        self.assertEqual(r["strategies"]["desktop"]["performance_score"], 91)
        s = {c["id"]: c for c in r["suggested_checks"]}
        # 42 -> fail; field LCP 3.1 -> partial; field CLS 0.12 -> partial; INP 180 -> pass; 500 KB images -> fail
        self.assertEqual({k: v["status"] for k, v in s.items()},
                         {"S1": "fail", "S2": "partial", "S3": "partial", "S4": "pass", "S5": "fail"})
        self.assertIn("desktop 91/100", s["S1"]["evidence"]["seen"])
        self.assertIn("real users", s["S2"]["evidence"]["seen"])

    def test_lab_fallback(self):
        code, r = run(psi_summary, [os.path.join(FX, "psi_no_field.json")])
        s = {c["id"]: c for c in r["suggested_checks"]}
        # 95 pass; lab LCP 2.4 pass; lab CLS 0.3 fail; TBT 700 fail; no image audits -> pass
        self.assertEqual({k: v["status"] for k, v in s.items()},
                         {"S1": "pass", "S2": "pass", "S3": "fail", "S4": "fail", "S5": "pass"})
        self.assertIn("TBT", s["S4"]["title"])

    def test_suggested_checks_feed_prioritise(self):
        _, r = run(psi_summary, [os.path.join(FX, "psi_mobile.json")])
        self.assertEqual(prioritise.validate({"checks": r["suggested_checks"]}), [])

    def test_bad_file(self):
        p = os.path.join(tempfile.mkdtemp(), "x.json")
        with open(p, "w") as fh:
            fh.write("{}")
        code, r = run(psi_summary, [p])
        self.assertEqual(code, 1)
        self.assertIn("lighthouseResult", r["errors"][0])


class Rollback(unittest.TestCase):
    def test_all(self):
        code, r = run(rollback, [os.path.join(FX, "change_log.json")])
        self.assertEqual(code, 0)
        self.assertEqual([(s["batch"], s["id"]) for s in r["steps"]],
                         [(2, "REFUND_POLICY"), (1, "gid://shopify/MediaImage/9"), (1, "gid://shopify/Product/1")])
        self.assertEqual(r["steps"][0]["restore"], "old policy")
        self.assertEqual(r["steps"][0]["expect_current"], "new policy")
        self.assertEqual(r["theme"]["republish_theme_id"], "gid://shopify/OnlineStoreTheme/111")

    def test_one_batch(self):
        _, r = run(rollback, [os.path.join(FX, "change_log.json"), "--batch", "1"])
        self.assertEqual(r["count"], 2)
        self.assertNotIn("theme", r)
        code, r = run(rollback, [os.path.join(FX, "change_log.json"), "--batch", "7"])
        self.assertEqual(code, 1)



class QARegressions(unittest.TestCase):
    """Defects found in adversarial QA, Oct 29 2026."""

    def test_lighthouse13_insight_savings(self):
        # Real PSI response (Lighthouse 13.5, theme-dawn-demo home, trimmed): image-delivery-insight has
        # metricSavings LCP 650 and debugData.wastedBytes 106842 (PSI shows "104 KiB"); render-blocking-insight
        # saves FCP 150 ms. Before the fix bytes read 0 and render-blocking was dropped.
        code, r = run(psi_summary, [os.path.join(FX, "psi_lh13_mobile.json")])
        m = r["strategies"]["mobile"]
        self.assertEqual((m["image_savings_ms"], m["image_savings_kb"]), (650, 104))
        ops = {o["id"]: o for o in m["opportunities"]}
        self.assertEqual(ops["render-blocking-insight"]["savings_ms"], 150)
        s = {c["id"]: c for c in r["suggested_checks"]}
        self.assertEqual(s["S5"]["status"], "partial")
        self.assertIn("104 KB", s["S5"]["evidence"]["seen"])
        self.assertEqual(m["performance_score"], 92)

    def test_two_pages_same_strategy_not_overwritten(self):
        d = json.loads(read(os.path.join(FX, "psi_lh13_mobile.json")))
        d["lighthouseResult"]["finalDisplayedUrl"] = "https://x.test/products/a"
        d["lighthouseResult"]["categories"]["performance"]["score"] = 0.4
        p = os.path.join(tempfile.mkdtemp(), "prod.json")
        with open(p, "w") as fh:
            json.dump(d, fh)
        _, r = run(psi_summary, [os.path.join(FX, "psi_lh13_mobile.json"), p])
        self.assertEqual(r["strategies"]["mobile"]["performance_score"], 92)
        self.assertEqual(r["strategies"]["mobile https://x.test/products/a"]["performance_score"], 40)
        s1 = next(c for c in r["suggested_checks"] if c["id"] == "S1")
        self.assertEqual(s1["status"], "pass")  # from the first (home) mobile file

    def test_api_error_is_explained(self):
        p = os.path.join(tempfile.mkdtemp(), "e.json")
        with open(p, "w") as fh:
            json.dump({"error": {"code": 429, "message": "Quota exceeded for quota metric 'Queries' and limit 'Queries per day'"}}, fh)
        code, r = run(psi_summary, [p])
        self.assertEqual(code, 1)
        self.assertIn("429", r["errors"][0])
        self.assertIn("pagespeed.web.dev", r["errors"][0])

    def _findings(self, checks):
        p = os.path.join(tempfile.mkdtemp(), "f.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"store": "s", "checks": checks}, fh, ensure_ascii=False)
        return p

    def test_no_dashes_in_outputs_and_na_tiles(self):
        p = self._findings([
            {"id": "E1", "area": "seo", "title": "Titles", "status": "fail", "impact": "medium", "effort": "low",
             "evidence": {"url": "https://x.test/", "seen": "Title is 'Studio Bag \u2013 Store \u2014 Home'"},
             "fix": "Edit the title", "change_type": "setting"},
            {"id": "C1", "area": "checkout", "title": "Guest", "status": "unknown", "note": "no access"}])
        out = os.path.dirname(p)
        code, _ = run(prioritise, [p, "--html", os.path.join(out, "r.html"), "--csv", os.path.join(out, "f.csv")])
        self.assertEqual(code, 0)
        for f in ("r.html", "f.csv"):
            s = read(os.path.join(out, f))
            self.assertNotIn("\u2013", s)
            self.assertNotIn("\u2014", s)
        self.assertIn("<b>n/a</b>", read(os.path.join(out, "r.html")))

    def test_arabic_speed_block_localised(self):
        _, psi = run(psi_summary, [os.path.join(FX, "psi_lh13_mobile.json")])
        p = self._findings(psi["suggested_checks"])
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        d["speed"] = psi
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        out = os.path.join(os.path.dirname(p), "ar.html")
        run(prioritise, [p, "--html", out, "--lang", "ar"])
        s = read(out)
        self.assertIn("موبايل", s)
        self.assertNotIn("milliseconds the page is frozen", s)
        self.assertIn('class="url" dir="ltr"', s)

    def test_evidence_not_object(self):
        errs = prioritise.validate({"checks": [{"id": "P1", "area": "product", "status": "fail", "impact": "high",
                                                "effort": "low", "evidence": "a string", "fix": "x"}, "junk"]})
        self.assertTrue(any("evidence must be an object" in e for e in errs))
        self.assertTrue(any("must be an object" in e and "checks[1]" in e for e in errs))

    def test_rollback_batch_number_as_string(self):
        log = json.loads(read(os.path.join(FX, "change_log.json")))
        for b in log["batches"]:
            b["batch"] = str(b["batch"])
        p = os.path.join(tempfile.mkdtemp(), "log.json")
        with open(p, "w") as fh:
            json.dump(log, fh)
        code, r = run(rollback, [p, "--batch", "1"])
        self.assertEqual((code, r["count"]), (0, 2))


if __name__ == "__main__":
    unittest.main()
