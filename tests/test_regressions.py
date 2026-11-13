"""Regression tests for the COBOL fixes, REPLACE/COPY REPLACING, nested programs, JCL procedure
expansion and symbols, and the anonymisation/validation tooling."""
from __future__ import annotations

import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lcc import commenter, engine, exporters  # noqa: E402
from lcc.detect import detect  # noqa: E402
from lcc.jcl import substitute  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "cobol")
SAMPLES = os.path.join(ROOT, "samples")


def read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def run_fixture(name: str, library: dict | None = None) -> dict:
    return engine.analyze(read(os.path.join(FIX, name)), name, library=library)


def texts(res: dict, kind: str | None = None) -> list[str]:
    return [a["text"] for a in res["annotations"] if kind is None or a["kind"] == kind]


def summary_of(res: dict, unit: str) -> str:
    return next(a["text"] for a in res["annotations"] if a["kind"] == "summary" and a["anchor"] == unit)


class CobolBugFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = run_fixture("OLDSTYLE.cbl")
        cls.low = run_fixture("lowcase.cob")

    def test_computed_goto_targets(self):
        risk = next(t for t in texts(self.old, "warning") if "Computed GO TO" in t)
        self.assertIn("C100-ONE if WS-CODE = 1; C200-TWO if WS-CODE = 2", risk)
        self.assertIn("falls through", risk)
        self.assertNotIn("TO, C100-ONE", risk)
        self.assertIn("jumps (GO TO) to C100-ONE and C200-TWO", summary_of(self.old, "A000-START"))

    def test_goto_without_target_is_alter_target(self):
        self.assertTrue(any("set at run time by an ALTER" in t for t in texts(self.old, "warning")))
        self.assertIn("ALTER", summary_of(self.old, "D000-SWITCH"))

    def test_display_only_paragraphs_are_not_placeholders(self):
        self.assertIn("Writes 1 message", summary_of(self.old, "C100-ONE"))
        self.assertIn("Writes 2 messages", summary_of(self.old, "C200-TWO"))
        self.assertNotIn("placeholder", summary_of(self.old, "C200-TWO"))
        self.assertIn("placeholder", summary_of(self.old, "B999-EXIT"))   # a real EXIT-only paragraph

    def test_section_describes_its_paragraphs(self):
        self.assertIn("Groups paragraphs START-HERE", summary_of(self.low, "MAIN-SECTION"))

    def test_lowercase_source_normalised(self):
        all_text = " ".join(texts(self.low))
        self.assertIn("WS-TOTAL", all_text)
        self.assertNotIn("ws-total", all_text)
        self.assertNotIn("ws-amt", all_text)
        self.assertEqual(self.low["program_id"], "LOWCASE")

    def test_literals_keep_their_case(self):
        self.assertIn("'Total='", read(os.path.join(FIX, "lowcase.cob")))
        text, _ = engine.render_file(self.low)
        self.assertEqual(commenter.strip(text), read(os.path.join(FIX, "lowcase.cob")))


class CobolReplace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = {"CUSTREC": read(os.path.join(FIX, "CUSTREC.cpy"))}
        cls.res = run_fixture("REPLDEMO.cbl", cls.lib)

    def test_replace_statement_applied(self):
        t = " ".join(texts(self.res))
        self.assertIn("substitutes ':PFX:' -> 'WS'", t)
        self.assertIn("REPLACE OFF", t)
        self.assertIn("WS-BALANCE is greater than WS-LIMIT", t)

    def test_copy_replacing_resolves_copybook_names(self):
        self.assertIn("CUSTREC", self.res["copybooks_resolved"])
        self.assertTrue(any("IN-PREMIUM [IN-TIER = 'P']" in t for t in texts(self.res, "business-rule")))
        self.assertTrue(any("REPLACING ':TAG:' -> 'IN'" in t for t in texts(self.res, "dependency")))

    def test_line_numbers_unchanged(self):
        lines = read(os.path.join(FIX, "REPLDEMO.cbl")).split("\n")
        for a in self.res["annotations"]:
            if "REPLACE:" in a["text"]:
                self.assertIn("REPLACE ==:PFX:==", lines[a["line"] - 1])
        text, _ = engine.render_file(self.res)
        self.assertEqual(commenter.strip(text), read(os.path.join(FIX, "REPLDEMO.cbl")))


class NestedPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run_fixture("NESTED.cbl")

    def test_programs_and_outline(self):
        self.assertEqual([p["name"] for p in self.res["programs"]], ["ORDERS", "PRICING"])
        self.assertEqual(self.res["programs"][1]["parent"], "ORDERS")
        outer = self.res["outline"][0]
        self.assertEqual((outer["kind"], outer["name"]), ("program", "ORDERS"))
        inner = [c for c in outer["children"] if c["kind"] == "program"][0]
        self.assertEqual(inner["name"], "PRICING")
        self.assertGreaterEqual(outer["end_line"], inner["end_line"])

    def test_nested_call_recognised(self):
        deps = {d["name"]: d for d in self.res["dependencies"] if d["kind"] == "program"}
        self.assertIn("nested", deps["PRICING"]["ops"])
        self.assertNotIn("nested", deps["AUDITLOG"]["ops"])
        self.assertTrue(any(t.startswith("Calls nested program PRICING") for t in texts(self.res, "dependency")))
        self.assertTrue(any(t.startswith("Calls external program AUDITLOG") for t in texts(self.res, "dependency")))

    def test_global_conditions_inherited(self):
        self.assertTrue(any("ORDER-SHIPPED [WS-ORDER-STATUS = 'S']" in t for t in texts(self.res, "business-rule")))

    def test_summaries_and_roundtrip(self):
        s = " ".join(texts(self.res, "summary"))
        self.assertIn("Nested program PRICING (contained in ORDERS", s)
        self.assertIn("Contains nested program: PRICING", s)
        text, _ = engine.render_file(self.res)
        self.assertEqual(commenter.strip(text), read(os.path.join(FIX, "NESTED.cbl")))

    def test_system_map_does_not_report_nested_program_missing(self):
        sm = exporters.system_map([self.res])
        self.assertNotIn("PRICING", {u["name"] for u in sm["unresolved"]})
        self.assertIn("AUDITLOG", {u["name"] for u in sm["unresolved"]})


class JclProcedures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = {"PAYPROC": read(os.path.join(SAMPLES, "PAYPROC.proc"))}
        cls.res = engine.analyze(read(os.path.join(SAMPLES, "MONTHEND.jcl")), "MONTHEND.jcl", library=cls.lib)
        cls.proc = engine.analyze(read(os.path.join(SAMPLES, "PAYPROC.proc")), "PAYPROC.proc")

    def test_symbol_substitution_rules(self):
        self.assertEqual(substitute("DSN=&HLQ..EMP.&ENV", {"HLQ": "PROD", "ENV": "QA"})[0], "DSN=PROD.EMP.QA")
        self.assertEqual(substitute("DSN=&&TEMP,X=&SYSUID", {"TEMP": "NO"})[0], "DSN=&&TEMP,X=&SYSUID")
        self.assertEqual(substitute("DSN=&MISSING..X", {})[2], ["MISSING"])

    def test_instream_procedure_expanded_with_set_symbol(self):
        s = summary_of(self.res, "STEP005")
        self.assertIn("runs procedure CLEANUP (in-stream definition at line 5)", s)
        self.assertIn("&DSNAME=QA.PAYROLL.WORK", s)
        self.assertIn("CL010 runs IEFBR14", s)

    def test_library_procedure_expanded_with_overrides(self):
        s = summary_of(self.res, "STEP010")
        self.assertIn("library member PAYPROC", s)
        self.assertIn("EMPIN ← TEST.EMP.SNAPSHOT (overridden here)", s)
        self.assertIn("PAYOUT → TEST.PAYROLL.EOM.PAYFILE(+1)", s)
        self.assertIn("GLOUT = DUMMY (overridden here)", s)
        self.assertEqual(self.res["procs_resolved"], ["CLEANUP", "PAYPROC"])
        progs = {d["name"] for d in self.res["dependencies"] if d["kind"] == "program"}
        self.assertTrue({"PAYROLL", "GLPOST", "IEFBR14"} <= progs)

    def test_missing_procedure_reported(self):
        self.assertIn("not in this upload", summary_of(self.res, "STEP020"))

    def test_outline_nests_proc_steps(self):
        job = self.res["outline"][0]
        step010 = next(c for c in job["children"] if c["name"] == "STEP010")
        self.assertEqual([c["name"] for c in step010["children"]], ["PS010", "PS020"])
        top_steps = [c["name"] for c in job["children"] if c["kind"] == "step"]
        self.assertEqual(top_steps, ["STEP005", "STEP010", "STEP020"])     # CL010 belongs to the PROC, not the job
        self.assertIn("3 steps", texts(self.res, "summary")[0])

    def test_cataloged_procedure_documented(self):
        s = self.proc["summary"]
        self.assertIn("Cataloged procedure PAYPROC: 2 steps", s)
        self.assertIn("&ENV", s)     # no default: caller must supply it
        self.assertTrue(any("coded as &HLQ..EMP.MASTER" in t for t in texts(self.proc, "io")))

    def test_prc_extension_with_jcl_content(self):
        self.assertEqual(detect("PAYPROC.prc", read(os.path.join(SAMPLES, "PAYPROC.proc"))), "jcl")
        self.assertEqual(detect("x.prc", "CREATE OR REPLACE PROCEDURE x IS BEGIN NULL; END;"), "plsql")

    def test_system_map_links_job_to_proc_and_program(self):
        files = [engine.analyze(read(os.path.join(SAMPLES, n)), n, library=self.lib)
                 for n in ("MONTHEND.jcl", "PAYPROC.proc", "PAYROLL.cbl")]
        rels = {(l["from"], l["kind"], l["to"]) for l in exporters.system_map(files)["links"]}
        self.assertIn(("MONTHEND.jcl", "invokes procedure", "PAYPROC.proc"), rels)
        self.assertIn(("MONTHEND.jcl", "executes", "PAYROLL.cbl"), rels)

    def test_roundtrip(self):
        text, _ = engine.render_file(self.res)
        self.assertEqual(commenter.strip(text), read(os.path.join(SAMPLES, "MONTHEND.jcl")))


class ValidationTooling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        cls.tmp = tempfile.mkdtemp()
        cls.src = os.path.join(cls.tmp, "src")
        os.makedirs(cls.src)
        for d in (SAMPLES, FIX):
            for n in os.listdir(d):
                if os.path.isfile(os.path.join(d, n)) and not n.endswith(".py"):
                    shutil.copy(os.path.join(d, n), cls.src)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_anonymiser_preserves_structure_and_hides_names(self):
        import anonymize
        out, key = os.path.join(self.tmp, "anon"), os.path.join(self.tmp, "key.json")
        with redirect_stdout(io.StringIO()):
            anonymize.main([self.src, out, "--key", key])
        names = sorted(os.listdir(out))
        self.assertEqual(len(names), len(os.listdir(self.src)))
        blob = " ".join(read(os.path.join(out, n)) for n in names)
        for secret in ("PAYROLL", "TAXCALC", "loan_servicing", "HEALTH", "Daily payment limit", "PROD.EMP.MASTER"):
            self.assertNotIn(secret, blob)
        before = {n: engine.analyze(read(os.path.join(self.src, n)), n) for n in os.listdir(self.src)}
        for n, res in before.items():
            stem, ext = os.path.splitext(n)
            match = [m for m in names if m.endswith(ext) and len(m) == len(n)
                     and [len(x) for x in read(os.path.join(out, m)).split("\n")] == [len(x) for x in read(os.path.join(self.src, n)).split("\n")]]
            self.assertTrue(match, f"no length-preserving counterpart for {n}")
            after = engine.analyze(read(os.path.join(out, match[0])), match[0])
            self.assertEqual(len(after["units"]), len(res["units"]), n)
            self.assertEqual(len(after["annotations"]), len(res["annotations"]), n)

    def test_validate_gates_and_scoring(self):
        import validate
        out = os.path.join(self.tmp, "validation")
        with redirect_stdout(io.StringIO()):
            rc = validate.main([self.src, "--out", out, "--sample", "30"])
        self.assertEqual(rc, 0)
        report = read(os.path.join(out, "VALIDATION_REPORT.md"))
        self.assertIn("| byte-exact round trip |", report)
        self.assertNotIn("FAIL", report)
        sheet = os.path.join(out, "review_sheet.csv")
        with open(sheet, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 20)
        for i, r in enumerate(rows):                       # simulated SME verdicts, only to test the maths
            r["verdict"] = "wrong" if i % 10 == 0 else ("partly" if i % 10 == 1 else "correct")
        with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        with redirect_stdout(io.StringIO()) as buf:
            validate.main(["--score", sheet])
        correct = sum(1 for i in range(len(rows)) if i % 10 not in (0, 1))
        self.assertIn(f"strict accuracy {correct / len(rows):.0%}", buf.getvalue())
        self.assertIn("## Comments judged wrong", read(os.path.join(out, "ACCURACY.md")))


if __name__ == "__main__":
    unittest.main()
