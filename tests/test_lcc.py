"""Test-suite: run with `python -m unittest discover -s tests -v` from the project root."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lcc import commenter, engine, exporters  # noqa: E402
from lcc.llm import LLMConfigError, LocalLLM, mask_literals  # noqa: E402
from lcc.models import Annotation  # noqa: E402
from lcc.vocab import humanize, sql_tables, verbalize_cobol  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def read(name: str) -> str:
    with open(os.path.join(SAMPLES, name), encoding="utf-8", newline="") as f:
        return f.read()


def library() -> dict:
    return {os.path.splitext(n)[0]: read(n) for n in os.listdir(SAMPLES) if n.endswith(".cpy")}


def analyze(name: str) -> dict:
    return engine.analyze(read(name), name, library=library())


def texts(res: dict, kind: str | None = None) -> list[str]:
    return [a["text"] for a in res["annotations"] if kind is None or a["kind"] == kind]


class NonIntrusive(unittest.TestCase):
    """The core guarantee: only whole [AI] comment lines are ever added."""

    def test_roundtrip_all_samples_byte_exact(self):
        for name in os.listdir(SAMPLES):
            with self.subTest(name=name):
                src = read(name)
                res = analyze(name)
                text, _ = engine.render_file(res)
                self.assertNotEqual(text, src, "expected comments to be added")
                self.assertEqual(commenter.strip(text), src)

    def test_original_lines_preserved_in_order(self):
        src = read("PAYROLL.cbl")
        text, _ = engine.render_file(analyze("PAYROLL.cbl"))
        kept = [l for l in text.split("\n") if "[AI]" not in l]
        self.assertEqual(kept, src.split("\n"))

    def test_crlf_files_keep_crlf(self):
        src = read("loan_servicing.pkb").replace("\n", "\r\n")
        res = engine.analyze(src, "x.pkb")
        text, _ = engine.render_file(res)
        self.assertNotIn("\r\r", text)
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        self.assertEqual(commenter.strip(text), src)

    def test_cobol_fixed_comments_respect_columns(self):
        for name in ("PAYROLL.cbl", "EMPREC.cpy"):
            text, _ = engine.render_file(analyze(name))
            for line in text.split("\n"):
                if "[AI]" in line:
                    self.assertTrue(line.startswith("      *[AI]"), line)
                    self.assertLessEqual(len(line), 72, line)

    def test_ascii_safe_by_default(self):
        for name in os.listdir(SAMPLES):
            text, _ = engine.render_file(analyze(name))
            self.assertTrue(all(ord(c) < 128 for c in text), name)

    def test_jcl_instream_data_never_split(self):
        res = analyze("NIGHTPAY.jcl")
        lines = read("NIGHTPAY.jcl").split("\n")
        protected = set(res["protected_lines"])
        self.assertIn(lines.index("  SORT FIELDS=(37,4,CH,A,1,6,CH,A)") + 1, protected)
        # Even a user comment placed on in-stream data is moved above the DD statement.
        res["annotations"].append(Annotation(line=min(protected), kind="note", text="user note").to_dict())
        text, _ = engine.render_file(res)
        out = text.split("\n")
        i = out.index("//SYSIN    DD *")
        self.assertEqual(out[i + 1], "  SORT FIELDS=(37,4,CH,A,1,6,CH,A)")

    def test_jcl_comment_width(self):
        text, _ = engine.render_file(analyze("NIGHTPAY.jcl"))
        for line in text.split("\n"):
            if "[AI]" in line:
                self.assertTrue(line.startswith("//*[AI]"))
                self.assertLessEqual(len(line), 71)

    def test_reimport_of_annotated_file(self):
        res = analyze("loan_servicing.pkb")
        res["annotations"][0]["text"] = "Hand-edited summary by an analyst."
        res["annotations"][0]["status"] = "edited"
        text, _ = engine.render_file(res, ascii_only=False)
        again = engine.analyze(text, "loan_servicing.pkb")
        self.assertEqual(again["content"], read("loan_servicing.pkb"))
        self.assertGreater(again["imported"], 10)
        self.assertIn("Hand-edited summary by an analyst.", texts(again))

    def test_rejected_and_empty_comments_not_rendered(self):
        res = analyze("trg_payment_limits.trg")
        for a in res["annotations"]:
            a["status"] = "rejected"
        text, _ = engine.render_file(res)
        self.assertEqual(text, read("trg_payment_limits.trg"))


class Cobol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = analyze("PAYROLL.cbl")

    def test_structure(self):
        paras = [n["name"] for d in self.res["outline"] for n in d["children"] if n["kind"] == "paragraph"]
        self.assertEqual(paras[0], "0000-MAINLINE")
        self.assertIn("2200-CALC-GROSS-PAY", paras)
        self.assertEqual(len(paras), 11)
        self.assertEqual(self.res["program_id"], "PAYROLL")
        self.assertEqual(self.res["dialect"], "fixed")

    def test_every_paragraph_documented(self):
        m = self.res["metrics"]
        self.assertEqual(m["units"], 11)
        self.assertEqual(m["units_documented_after"], 11)
        self.assertLess(m["units_documented_before"], 3)

    def test_copybook_conditions_resolved(self):
        rules = " ".join(texts(self.res, "business-rule"))
        self.assertIn("EMP-HOURLY [EMP-TYPE in 'H', 'P']", rules)
        self.assertIn("EMPREC", self.res["copybooks_resolved"])

    def test_business_rules_and_formulas(self):
        all_text = " ".join(texts(self.res))
        self.assertIn("Decision table", all_text)
        self.assertIn("WS-OT-HRS × EMP-RATE × WS-OT-RATE", all_text)
        self.assertIn("truncated, not rounded", all_text)
        self.assertIn("is not numeric", all_text)
        self.assertNotIn("is not is numeric", all_text)

    def test_dependencies_and_risks(self):
        deps = {(d["kind"], d["name"]) for d in self.res["dependencies"]}
        self.assertIn(("program", "TAXCALC"), deps)
        self.assertIn(("copybook", "EMPREC"), deps)
        risks = " ".join(texts(self.res, "warning"))
        self.assertIn("GO TO", risks)
        self.assertIn("REDEFINES", risks)

    def test_record_sizes(self):
        cpy = analyze("EMPREC.cpy")
        self.assertTrue(any("about 80 bytes" in t for t in texts(cpy, "data")))
        self.assertTrue(any("PAY-REC" in t and "64 bytes" in t for t in texts(self.res, "data")))

    def test_working_storage_not_attributed_to_files(self):
        self.assertFalse(any("WS-COUNTERS" in t and "record of file" in t for t in texts(self.res)))

    def test_free_format_embedded_sql(self):
        res = analyze("CUSTRISK.cob")
        self.assertEqual(res["dialect"], "free")
        tables = {d["name"]: d["ops"] for d in res["dependencies"] if d["kind"] == "table"}
        self.assertEqual(set(tables), {"CUSTOMER", "ACCOUNT"})
        self.assertIn("update", tables["ACCOUNT"])
        self.assertTrue(any("Declares cursor CUST-CUR" in t for t in texts(res)))


class Plsql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = analyze("loan_servicing.pkb")

    def test_units_and_ranges(self):
        body = [n for n in self.res["outline"] if n["kind"] == "package body"][0]
        units = {c["name"]: (c["line"], c["end_line"]) for c in body["children"]}
        self.assertEqual(set(units), {"log_event", "apply_payment", "accrue_monthly_interest", "get_risk_grade"})
        lines = read("loan_servicing.pkb").split("\n")
        start, end = units["apply_payment"]
        self.assertIn("PROCEDURE apply_payment", lines[start - 1])
        self.assertIn("END apply_payment;", lines[end - 1])

    def test_rules_and_risks(self):
        t = " ".join(texts(self.res))
        self.assertIn("ORA-20010", t)
        self.assertIn("WHEN OTHERS THEN NULL", t)
        self.assertIn("COMMIT inside a loop", t)
        self.assertIn("Autonomous transaction", t)
        self.assertIn("Dynamic SQL", t)
        # v_sql is built with || on the previous line, then executed: taint must carry over.
        self.assertIn("SQL-injection", t)

    def test_table_access(self):
        deps = {d["name"]: set(d["ops"]) for d in self.res["dependencies"] if d["kind"] == "table"}
        self.assertEqual(deps["LOANS"], {"read", "update"})
        self.assertEqual(deps["PAYMENTS"], {"insert"})

    def test_trigger(self):
        res = analyze("trg_payment_limits.trg")
        summary = texts(res, "summary")[0]
        self.assertIn("before insert/update on PAYMENTS for each row", summary)
        self.assertNotIn("inputs", summary)
        self.assertTrue(any("ORA-20020" in t for t in texts(res, "business-rule")))


class Jcl(unittest.TestCase):
    def test_steps_cond_and_datasets(self):
        res = analyze("NIGHTPAY.jcl")
        steps = [c["name"] for c in res["outline"][0]["children"]]
        self.assertEqual(steps, ["STEP010", "STEP020", "STEP025", "STEP030"])
        t = " ".join(texts(res))
        self.assertIn("bypassed if any earlier step's return code is greater than 4", t)
        self.assertIn("a NEW generation of GDG PROD.PAYROLL.PAYFILE", t)
        self.assertIn("sorts by bytes 37–40 (text) ascending", t)
        self.assertIn("STEP020 return code = 4", t)


class Vocabulary(unittest.TestCase):
    def test_humanize(self):
        self.assertEqual(humanize("2000-CALC-GROSS-PAY"), "calculate gross pay")
        self.assertEqual(humanize("v_cust_bal"), "customer balance")
        self.assertEqual(humanize("trg_payment_limits"), "payment limits")

    def test_conditions(self):
        self.assertEqual(verbalize_cobol("A NOT = B"), "A is not B")
        self.assertEqual(verbalize_cobol("X > 40 AND Y NOT NUMERIC"), "X is greater than 40 and Y is not numeric")
        self.assertEqual(verbalize_cobol("WS-NAME = 'NOT ='"), "WS-NAME = 'NOT ='")

    def test_sql_tables(self):
        self.assertEqual(sql_tables("SELECT a FROM t1 x, t2 y WHERE 1=1"), [("T1", "read"), ("T2", "read")])
        self.assertEqual(sql_tables("DELETE FROM orders WHERE id = 1"), [("ORDERS", "delete")])
        self.assertIn(("SRC", "read"), sql_tables("MERGE INTO dst d USING src s ON (d.id = s.id)"))


class SystemMap(unittest.TestCase):
    def test_cross_file_links(self):
        files = [analyze(n) for n in os.listdir(SAMPLES)]
        m = exporters.system_map(files)
        rels = {(l["from"], l["kind"], l["to"]) for l in m["links"]}
        self.assertIn(("NIGHTPAY.jcl", "executes", "PAYROLL.cbl"), rels)
        self.assertIn(("PAYROLL.cbl", "includes", "EMPREC.cpy"), rels)
        self.assertTrue(any(b["dd"] == "EMPIN" and b["file"] == "EMP-FILE" for b in m["dd_bindings"]))
        self.assertIn("TAXCALC", {u["name"] for u in m["unresolved"]})
        self.assertIn("PAYMENTS", {t["table"] for t in m["shared_tables"]})

    def test_zip_bundle(self):
        import io
        import zipfile
        files = [analyze(n) for n in ("PAYROLL.cbl", "NIGHTPAY.jcl")]
        z = zipfile.ZipFile(io.BytesIO(exporters.project_zip(files)))
        names = set(z.namelist())
        self.assertIn("README.md", names)
        self.assertIn("docs/SYSTEM_MAP.md", names)
        self.assertIn("annotated/PAYROLL.annotated.cbl", names)
        self.assertIn("## Business rules", z.read("docs/PAYROLL.cbl.md").decode())


class Confidentiality(unittest.TestCase):
    def test_remote_llm_refused(self):
        os.environ.pop("LCC_ALLOW_REMOTE_LLM", None)
        with self.assertRaises(LLMConfigError):
            LocalLLM(url="https://api.example.com")
        LocalLLM(url="http://127.0.0.1:11434")  # loopback is fine

    def test_mask_literals(self):
        out, n = mask_literals("IF X = 'ACME CORP' AND ACCT = 1234567890")
        self.assertNotIn("ACME", out)
        self.assertNotIn("1234567890", out)
        self.assertEqual(n, 2)


class LlmEnrichment(unittest.TestCase):
    """Exercise the Ollama integration against a stub server that records every prompt it receives."""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        cls.prompts = prompts = []

        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"models": [{"name": "stub-model:latest"}]})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompts.append(data["prompt"])
                self._send({"response": "Summary: Computes the employee's pay for the period and applies the overtime policy."})

        cls.stub = HTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=cls.stub.serve_forever, daemon=True).start()
        cls.llm = LocalLLM(url=f"http://127.0.0.1:{cls.stub.server_address[1]}")

    @classmethod
    def tearDownClass(cls):
        cls.stub.shutdown()
        cls.stub.server_close()

    def test_summaries_rewritten_and_literals_masked(self):
        res = engine.analyze(read("PAYROLL.cbl"), "PAYROLL.cbl", use_llm=True, llm=self.llm, library=library())
        self.assertTrue(res["llm"]["used"])
        self.assertEqual(res["llm"]["model"], "stub-model:latest")
        llm_anns = [a for a in res["annotations"] if a["source"] == "llm"]
        self.assertEqual(len(llm_anns), 11)                       # one per paragraph
        self.assertTrue(all(a["alt_text"] for a in llm_anns))     # rule text kept as fallback
        self.assertTrue(llm_anns[0]["text"].startswith("Computes"))  # "Summary:" prefix stripped
        joined = "\n".join(self.prompts)
        self.assertNotIn("'TAXCALC FAILED FOR '", joined)          # string literals never sent
        self.assertIn("<STR", joined)
        text, _ = engine.render_file(res)
        self.assertEqual(commenter.strip(text), read("PAYROLL.cbl"))

    def test_unreachable_llm_falls_back_to_rules(self):
        res = engine.analyze(read("NIGHTPAY.jcl"), "NIGHTPAY.jcl", use_llm=True, llm=LocalLLM(url="http://127.0.0.1:9"))
        self.assertFalse(res["llm"].get("used"))
        self.assertIn("error", res["llm"])
        self.assertTrue(all(a["source"] == "rule" for a in res["annotations"]))


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LCC_AUDIT"] = "0"
        from lcc.server import Handler, Server
        cls.httpd = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=20) as r:
            return r.status, r.headers, r.read()

    def test_index_and_csp(self):
        status, headers, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Legacy Code Commenter", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_analyze_render_export(self):
        _, _, body = self.call("/api/analyze", {"filename": "PAYROLL.cbl", "content": read("PAYROLL.cbl"), "library": library()})
        res = json.loads(body)
        self.assertEqual(res["language"], "cobol")
        _, _, body = self.call("/api/export", {"file": res, "format": "annotated"})
        out = json.loads(body)
        self.assertEqual(out["filename"], "PAYROLL.annotated.cbl")
        self.assertEqual(commenter.strip(out["content"]), read("PAYROLL.cbl"))
        _, _, body = self.call("/api/explain", {"filename": "PAYROLL.cbl", "content": read("PAYROLL.cbl"), "start": 120, "end": 125})
        self.assertIn("2200-CALC-GROSS-PAY", json.loads(body)["text"])

    def test_user_guide_built_in(self):
        status, _, body = self.call("/guide.html")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="guideContent"', html)
        # Self-contained: no resources from other hosts.
        self.assertNotRegex(html, r'(?:src|href)="(?:https?:)?//')
        for img in re.findall(r'<img src="([^"]+)"', html):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "web", img)), img)
        sections = re.findall(r'<section id="([^"]+)" data-title="[^"]+"', html)
        for needed in ("g-start", "g-load", "g-read", "g-review", "g-navigate", "g-export", "g-keys", "g-glossary", "g-faq"):
            self.assertIn(needed, sections)
        for label in ("Summary", "Business rule", "Logic", "Data", "I/O", "Dependency", "Risk", "Note"):
            self.assertIn(f">{label}</span>", html)
        for key in ("]", "[", "a", "r", "e", "/", "p", "?", "Esc"):
            self.assertIn(f"<kbd>{key}</kbd>", html)
        # The app wires the guide to the ? button and keyboard shortcut.
        _, _, js = self.call("/app.js")
        self.assertIn(b"fetch('guide.html'", js)
        _, _, index = self.call("/")
        self.assertIn(b'id="guide"', index)

    def test_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("/../lcc/server.py")
        self.assertEqual(cm.exception.code, 404)

    def test_cross_origin_post_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("/api/analyze", {"filename": "a.sql", "content": "BEGIN NULL; END;"}, {"Origin": "http://evil.example"})
        self.assertEqual(cm.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
