"""Exports: annotated source, Markdown knowledge-transfer document, JSON, project ZIP, system map."""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile

from .engine import annotations_from, flat_outline, render_file
from .jcl import SORT_PGMS, UTIL

# IBM/vendor utilities: referenced by JCL but never part of the application's own source inventory.
SYSTEM_PROGRAMS = set(UTIL) | SORT_PGMS | {"IEBUPDTE", "IEBPTPCH", "IEHLIST", "IEHMOVE", "DSNTEP2", "DSNTIAUL",
                                           "DSNUTILB", "IDCAMS", "IKJEFT01", "ICEGENER", "SYNCGENR", "DFSRRC00"}


def _md(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def markdown_doc(f: dict) -> str:
    _, m = render_file(f)
    anns = [a for a in annotations_from(f.get("annotations", [])) if a.status != "rejected"]
    by_line = {}
    for a in anns:
        by_line.setdefault((a.line, a.kind), a)
    out = [f"# {f['filename']}", ""]
    out.append(f"*Language:* {f.get('language_name', f.get('language'))}"
               + (f" ({f['dialect']} format)" if f.get("dialect") else "")
               + f" · *Lines:* {m['total_lines']} · *Generated:* {time.strftime('%Y-%m-%d %H:%M')}")
    out += ["", "## Summary", "", f.get("summary") or "_No summary._", ""]

    nodes = [n for n in flat_outline(f.get("outline", [])) if n["kind"] not in ("division",)]
    if nodes:
        out += ["## Structure", "", "| Unit | Kind | Lines | What it does |", "|---|---|---|---|"]
        for n in nodes:
            s = by_line.get((n["line"], "summary"))
            out.append(f"| `{_md(n['name'])}` | {n['kind']} | {n['line']}–{n.get('end_line') or n['line']} | {_md(s.text) if s else ''} |")
        out.append("")

    def section(title, kind, intro=""):
        items = [a for a in anns if a.kind == kind]
        if not items:
            return
        out.extend([f"## {title}", ""])
        if intro:
            out.extend([intro, ""])
        for a in sorted(items, key=lambda x: x.line):
            flag = "" if a.status in ("accepted", "edited") else " _(unreviewed)_"
            out.append(f"- **L{a.line}**{(' `' + a.anchor + '`') if a.anchor else ''}: {a.text}{flag}")
        out.append("")

    section("Business rules", "business-rule", "Conditions and decisions that encode business policy. Verify each with a subject-matter expert before re-implementing.")
    section("Migration risks", "warning", "Constructs that need special care when the code is rewritten or converted.")
    section("Inputs and outputs", "io")
    section("Data structures", "data")
    section("Processing logic", "logic")
    section("External dependencies", "dependency")
    section("Notes", "note")

    deps = f.get("dependencies", [])
    if deps:
        out += ["## Dependency inventory", "", "| Kind | Name | Access | Lines |", "|---|---|---|---|"]
        for d in deps:
            out.append(f"| {d['kind']} | `{_md(d['name'])}` | {', '.join(d.get('ops', []))} | {', '.join(map(str, d.get('lines', [])[:12]))} |")
        out.append("")

    out += ["## Documentation coverage", "",
            "| Metric | Before | After |", "|---|---|---|",
            f"| Comment lines | {m['comment_lines_before']} | {m['comment_lines_before'] + m['ai_comment_lines']} |",
            f"| Comment density (comments ÷ code lines) | {m['density_before']:.0%} | {m['density_after']:.0%} |",
            f"| Units with an explanatory header | {m['units_documented_before']}/{m['units']} | {m['units_documented_after']}/{m['units']} |",
            "", f"Review status: {m['by_status']['accepted']} accepted, {m['by_status']['edited']} edited, "
            f"{m['by_status']['suggested']} unreviewed, {m['by_status']['rejected']} rejected.", ""]
    return "\n".join(out)


def json_export(f: dict) -> str:
    text, metrics = render_file(f)
    data = {k: f.get(k) for k in ("filename", "language", "dialect", "summary", "outline", "dependencies",
                                  "call_graph", "annotations", "units")}
    data["metrics"] = metrics
    return json.dumps(data, indent=2, ensure_ascii=False)


def annotated_name(filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    return f"{stem}.annotated{ext}"


def system_map(files: list[dict]) -> dict:
    """Cross-file relationships: who runs/calls/includes whom, DD bindings, shared tables, gaps."""
    programs, books, units, procs = {}, {}, {}, {}
    for f in files:
        stem = os.path.splitext(os.path.basename(f["filename"]))[0].upper()
        pid = (f.get("program_id") or "").upper()
        if f.get("language") == "cobol":
            if f.get("ext") in (".cpy", ".cpb") or not pid:
                books[stem] = f["filename"]
            programs[pid or stem] = f["filename"]
            for p in f.get("programs") or []:          # nested / multiple programs in one source file
                programs.setdefault(p["name"].upper(), f["filename"])
        if f.get("language") == "jcl":
            for n in flat_outline(f.get("outline", [])):
                if n["kind"] == "proc":
                    procs.setdefault(n["name"].upper(), f["filename"])
            procs.setdefault(stem, f["filename"])
        for n in flat_outline(f.get("outline", [])):
            if n["kind"] in ("procedure", "function", "package", "package body", "trigger"):
                units[n["name"].upper().split(".")[-1]] = f["filename"]
    links, unresolved, utilities = [], [], set()
    for f in files:
        for d in f.get("dependencies", []):
            name = d["name"].upper().split(" ")[0]
            target, rel = None, ""
            if d["kind"] == "program" and name in SYSTEM_PROGRAMS and name not in programs:
                utilities.add(name)     # vendor utility, not an inventory gap
                continue
            if d["kind"] == "program":
                target, rel = programs.get(name), ("executes" if "exec" in d.get("ops", []) else "calls")
            elif d["kind"] == "copybook":
                target, rel = books.get(name), "includes"
            elif d["kind"] in ("package", "procedure"):
                target, rel = units.get(name.split(".")[-1]), "calls"
            elif d["kind"] == "proc":
                target, rel = procs.get(name), "invokes procedure"
            else:
                continue
            if target and target != f["filename"]:
                links.append({"from": f["filename"], "to": target, "kind": rel, "name": d["name"]})
            elif not target:
                unresolved.append({"file": f["filename"], "kind": d["kind"], "name": d["name"]})

    # JCL DD name -> dataset, matched to the COBOL program's ASSIGN names
    bindings = []
    for j in (f for f in files if f.get("language") == "jcl"):
        steps = [n for n in flat_outline(j.get("outline", [])) if n["kind"] in ("step", "proc step")]
        for st in steps:
            prog_file = programs.get((st.get("detail") or "").upper())
            if not prog_file:
                continue
            pf = next(f for f in files if f["filename"] == prog_file)
            assigns = {}
            for d in pf.get("dependencies", []):
                if d["kind"] == "file" and d.get("detail", "").startswith("DD/assign "):
                    assigns[d["detail"].split(" ", 1)[1].upper()] = d["name"]
            for d in j.get("dependencies", []):
                if d["kind"] != "dataset":
                    continue
                dds = [x.replace("DD ", "").upper() for x in d.get("detail", "").split("; ")]
                dd = next((x for x in dds if x in assigns), "")
                if dd and any(st["line"] <= l <= (st.get("end_line") or st["line"]) for l in d.get("lines", [])):
                    bindings.append({"job": j["filename"], "step": st["name"], "program": prog_file,
                                     "file": assigns[dd], "dd": dd, "dataset": d["name"], "disp": ",".join(d.get("ops", []))})
    tables: dict[str, set] = {}
    for f in files:
        for d in f.get("dependencies", []):
            if d["kind"] == "table":
                tables.setdefault(d["name"].upper(), set()).add(f["filename"])
    shared = [{"table": t, "files": sorted(v)} for t, v in sorted(tables.items()) if len(v) > 1]
    return {"files": [{"filename": f["filename"], "language": f.get("language"), "program_id": f.get("program_id", "")} for f in files],
            "links": links, "unresolved": unresolved, "dd_bindings": bindings, "shared_tables": shared,
            "utilities": sorted(utilities)}


def system_map_md(sm: dict) -> str:
    out = ["# System map", "", f"{len(sm['files'])} files analysed.", ""]
    if sm["links"]:
        out += ["## Relationships", "", "| From | Relationship | To |", "|---|---|---|"]
        out += [f"| {l['from']} | {l['kind']} `{l['name']}` | {l['to']} |" for l in sm["links"]]
        out.append("")
    if sm["dd_bindings"]:
        out += ["## JCL ↔ program file bindings", "", "| Job step | Program file | Logical file | DD | Dataset |", "|---|---|---|---|---|"]
        out += [f"| {b['job']} / {b['step']} | {b['program']} | {b['file']} | {b['dd']} | `{b['dataset']}` |" for b in sm["dd_bindings"]]
        out.append("")
    if sm["shared_tables"]:
        out += ["## Tables shared across files", ""]
        out += [f"- `{t['table']}`: {', '.join(t['files'])}" for t in sm["shared_tables"]]
        out.append("")
    if sm.get("utilities"):
        out += ["## System utilities used", "", ", ".join(f"`{u}`" for u in sm["utilities"]) + " (vendor-supplied).", ""]
    if sm["unresolved"]:
        out += ["## Not in this upload (inventory gaps)", "", "Referenced but not provided; collect these before migration scoping.", ""]
        out += [f"- {u['kind']} `{u['name']}` (referenced by {u['file']})" for u in sm["unresolved"]]
        out.append("")
    return "\n".join(out)


def project_zip(files: list[dict], tag: str = "AI") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        index = ["# Legacy code documentation bundle", "", f"Generated {time.strftime('%Y-%m-%d %H:%M')} by Legacy Code Commenter.", "",
                 "| File | Language | Annotated source | Document |", "|---|---|---|---|"]
        for f in files:
            safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(f["filename"])) or "file"
            text, _ = render_file(f, tag)
            z.writestr(f"annotated/{annotated_name(safe)}", text.encode("utf-8"))
            z.writestr(f"docs/{safe}.md", markdown_doc(f).encode("utf-8"))
            z.writestr(f"json/{safe}.json", json_export(f).encode("utf-8"))
            index.append(f"| {f['filename']} | {f.get('language_name', '')} | annotated/{annotated_name(safe)} | docs/{safe}.md |")
        sm = system_map(files)
        z.writestr("docs/SYSTEM_MAP.md", system_map_md(sm).encode("utf-8"))
        index += ["", "See docs/SYSTEM_MAP.md for cross-file relationships.", "",
                  f"AI comments carry the `[{tag}]` marker and can be removed with: `python run.py strip <file>`."]
        z.writestr("README.md", "\n".join(index).encode("utf-8"))
    return buf.getvalue()
