"""Analysis pipeline: detect -> analyze -> (optional LLM enrichment) -> metrics."""
from __future__ import annotations

import os
import re
import time

from . import cobol, jcl, plsql
from .commenter import GENERIC_PREFIX, extract, render
from .detect import LANG_NAMES, analyze_generic, detect
from .llm import EXPLAIN_PROMPT, SUMMARY_PROMPT, LLMConfigError, LocalLLM, mask_literals
from .models import KINDS, Annotation, Collector
from .vocab import shorten

MAX_LLM_UNITS = 30
LLM_BUDGET_S = 180


def split_source(content: str) -> tuple[list[str], str, bool]:
    newline = "\r\n" if "\r\n" in content else "\n"
    text = content.replace("\r\n", "\n")
    lines = text.split("\n")
    trailing = text.endswith("\n")
    if trailing:
        lines.pop()
    return lines, newline, trailing


def join_source(lines: list[str], newline: str, trailing: bool) -> str:
    out = newline.join(lines)
    return out + newline if trailing and lines else out


def comment_line_set(lines: list[str], language: str, dialect: str, ext: str) -> set[int]:
    out = set()
    in_block = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s:
            continue
        if language == "cobol":
            if (dialect == "fixed" and len(ln) > 6 and ln[6] in "*/") or s.startswith("*>"):
                out.add(i)
        elif language == "plsql":
            if in_block:
                out.add(i)
                if "*/" in s:
                    in_block = False
            elif s.startswith("--"):
                out.add(i)
            elif s.startswith("/*"):
                out.add(i)
                in_block = "*/" not in s
        elif language == "jcl":
            if ln.startswith("//*"):
                out.add(i)
        else:
            p = GENERIC_PREFIX.get(ext, "# ").strip()
            if s.startswith(p) or s.startswith(("*", "//", "#", "!")):
                out.add(i)
    return out


def flat_outline(nodes: list[dict]) -> list[dict]:
    out = []
    for n in nodes:
        out.append(n)
        out.extend(flat_outline(n.get("children", [])))
    return out


def compute_metrics(lines: list[str], annotations: list[Annotation], language: str, dialect: str, ext: str,
                    units: list[dict], protected: set[int], dep_count: int) -> dict:
    comments = comment_line_set(lines, language, dialect, ext)
    blank = sum(1 for l in lines if not l.strip())
    code = max(1, len(lines) - blank - len(comments))
    rendered = render(lines, annotations, language, dialect, ext, protected=protected, trailing_newline=False)
    ai_lines = (rendered.count("\n") + 1 if rendered else 0) - len(lines)
    live = [a for a in annotations if a.status != "rejected"]

    def documented_before(line: int) -> bool:
        j = line - 1
        while j >= 1 and not lines[j - 1].strip():
            j -= 1
        return j in comments

    summary_lines = {a.line for a in live if a.kind == "summary"}
    unit_lines = [u["line"] for u in units]
    by_kind = {k: sum(1 for a in live if a.kind == k) for k in KINDS}
    by_status = {s: sum(1 for a in annotations if a.status == s) for s in ("suggested", "accepted", "edited", "rejected")}
    reviewed = by_status["accepted"] + by_status["edited"] + by_status["rejected"]
    return {
        "total_lines": len(lines),
        "code_lines": code,
        "blank_lines": blank,
        "comment_lines_before": len(comments),
        "ai_comment_lines": max(0, ai_lines),
        "density_before": round(len(comments) / code, 3),
        "density_after": round((len(comments) + max(0, ai_lines)) / code, 3),
        "units": len(unit_lines),
        "units_documented_before": sum(1 for l in unit_lines if documented_before(l)),
        "units_documented_after": sum(1 for l in unit_lines if l in summary_lines or documented_before(l)),
        "business_rules": by_kind["business-rule"],
        "risks": by_kind["warning"],
        "dependencies": dep_count,
        "by_kind": by_kind,
        "by_status": by_status,
        "annotations": len(annotations),
        "review_progress": round(reviewed / len(annotations), 3) if annotations else 1.0,
    }


def _run_analyzer(lines: list[str], language: str, ext: str,
                  library: dict[str, str] | None = None) -> tuple[Collector, str]:
    if language == "cobol":
        return cobol.analyze(lines, library)
    if language == "plsql":
        return plsql.analyze("\n".join(lines)), ""
    if language == "jcl":
        return jcl.analyze(lines, library), ""
    return analyze_generic(lines, ext), ""


def analyze(content: str, filename: str, language: str | None = None, use_llm: bool = False,
            mask: bool = True, llm: LocalLLM | None = None, library: dict[str, str] | None = None) -> dict:
    ext = os.path.splitext(filename.lower())[1]
    raw_lines, newline, trailing = split_source(content)
    lines, imported = extract(raw_lines)
    language = language if language in LANG_NAMES else detect(filename, "\n".join(lines))
    t0 = time.time()
    col, dialect = _run_analyzer(lines, language, ext, library)
    protected = set(col.facts.get("protected_lines", []))

    anns = [a for a in col.annotations if a.line not in protected]
    # Imported (previously reviewed) comments win over fresh suggestions of the same kind and line.
    taken = {(a.line, a.kind) for a in imported}
    anns = [a for a in anns if (a.line, a.kind) not in taken] + imported
    anns.sort(key=lambda a: (a.line, KINDS.index(a.kind) if a.kind in KINDS else 99))
    for i, a in enumerate(anns, 1):
        a.id = f"a{i}"

    outline = [n.to_dict() for n in col.outline]
    units = col.facts.get("units", [])
    llm_info = {"requested": use_llm, "used": False}
    if use_llm:
        llm_info.update(_enrich(anns, lines, outline, language, mask, llm))

    deps = [d.to_dict() for d in col.dependencies]
    return {
        "filename": filename,
        "language": language,
        "language_name": LANG_NAMES[language],
        "dialect": dialect,
        "ext": ext,
        "program_id": col.facts.get("program_id", ""),
        "copybooks_resolved": col.facts.get("copybooks_resolved", []),
        "procs_resolved": col.facts.get("procs_resolved", []),
        "programs": col.facts.get("programs", []),
        "newline": newline,
        "trailing_newline": trailing,
        "content": join_source(lines, newline, trailing),
        "line_count": len(lines),
        "imported": len(imported),
        "summary": col.summary,
        "outline": outline,
        "dependencies": deps,
        "call_graph": [list(e) for e in col.call_graph],
        "annotations": [a.to_dict() for a in anns],
        "units": units,
        "protected_lines": sorted(protected),
        "metrics": compute_metrics(lines, anns, language, dialect, ext, units, protected, len(deps)),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "llm": llm_info,
    }


def _enrich(anns: list[Annotation], lines: list[str], outline: list[dict], language: str, mask: bool,
            llm: LocalLLM | None) -> dict:
    try:
        llm = llm or LocalLLM()
    except LLMConfigError as e:
        return {"error": str(e)}
    st = llm.status()
    if not st.get("available"):
        return {"error": st.get("reason", "Local LLM not available")}
    nodes = {n["line"]: n for n in flat_outline(outline)}
    done, masked, start = 0, 0, time.time()
    for a in anns:
        if a.kind != "summary" or a.source != "rule" or a.line not in nodes:
            continue
        if done >= MAX_LLM_UNITS or time.time() - start > LLM_BUDGET_S:
            break
        n = nodes[a.line]
        end = min(n.get("end_line") or a.line, a.line + 120)
        code = "\n".join(lines[a.line - 1:end])
        if mask:
            code, k = mask_literals(code)
            masked += k
        try:
            text = llm.complete(SUMMARY_PROMPT.format(language=language.upper(), kind=n["kind"], name=n["name"],
                                                      facts=a.text, code=code))
        except Exception as e:  # network errors, timeouts, bad JSON
            return {"used": done > 0, "model": llm.model, "enriched": done, "error": f"{type(e).__name__}: {e}"}
        if text and len(text) > 20:
            a.alt_text, a.text = a.text, shorten(text, 600)
            a.source, a.confidence = "llm", 0.7
            done += 1
    return {"used": done > 0, "model": llm.model, "enriched": done, "masked_literals": masked}


def explain(content: str, filename: str, language: str | None, start: int, end: int,
            use_llm: bool = False, mask: bool = True, llm: LocalLLM | None = None) -> dict:
    res = analyze(content, filename, language)
    lines = res["content"].replace("\r\n", "\n").split("\n")
    start, end = max(1, start), min(len(lines), max(start, end))
    facts = [a for a in res["annotations"] if start <= a["line"] <= end and a["kind"] != "summary"]
    unit = None
    for n in flat_outline(res["outline"]):
        if n["line"] <= start <= (n.get("end_line") or n["line"]) and n["kind"] not in ("division", "job", "package body", "package"):
            unit = n
    unit_summary = next((a["text"] for a in res["annotations"] if unit and a["line"] == unit["line"] and a["kind"] == "summary"), "")
    parts = []
    if unit:
        parts.append(f"Lines {start}–{end} are inside {unit['kind']} {unit['name']}." + (f" {unit_summary}" if unit_summary else ""))
    for a in facts:
        parts.append(f"• Line {a['line']} ({a['kind']}): {a['text']}")
    if not facts:
        parts.append("No rule-based findings in this range: it holds declarations, data moves or plain statements.")
    text, source, err = "\n".join(parts), "rule", ""
    if use_llm:
        try:
            llm = llm or LocalLLM()
            if llm.status().get("available"):
                code = "\n".join(lines[start - 1:end])
                if mask:
                    code, _ = mask_literals(code)
                out = llm.complete(EXPLAIN_PROMPT.format(language=res["language_name"], start=start, end=end,
                                                         facts=" | ".join(a["text"] for a in facts[:12]) or unit_summary,
                                                         code=code), max_tokens=320)
                if out:
                    text, source = out + "\n\n" + text, "llm"
            else:
                err = llm.status().get("reason", "")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    return {"text": text, "source": source, "start": start, "end": end,
            "unit": unit["name"] if unit else "", "error": err}


def annotations_from(dicts: list[dict]) -> list[Annotation]:
    out = []
    fields = Annotation.__dataclass_fields__
    for d in dicts or []:
        kw = {k: v for k, v in d.items() if k in fields}
        try:
            kw["line"] = int(kw.get("line", 1))
        except (TypeError, ValueError):
            continue
        if kw.get("kind") not in KINDS:
            kw["kind"] = "note"
        kw["text"] = re.sub(r"[\r\n]+", " ", str(kw.get("text", "")))
        out.append(Annotation(**kw))
    return out


def render_file(f: dict, tag: str = "AI", ascii_only: bool = True) -> tuple[str, dict]:
    lines, newline, trailing = split_source(f["content"])
    anns = annotations_from(f.get("annotations", []))
    protected = set(f.get("protected_lines", []))
    text = render(lines, anns, f.get("language", "generic"), f.get("dialect", ""), f.get("ext", ""), tag=tag,
                  protected=protected, newline=newline, trailing_newline=trailing, ascii_only=ascii_only)
    metrics = compute_metrics(lines, anns, f.get("language", "generic"), f.get("dialect", ""), f.get("ext", ""),
                              f.get("units", []), protected, len(f.get("dependencies", [])))
    return text, metrics
