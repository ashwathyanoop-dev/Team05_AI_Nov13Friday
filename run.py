#!/usr/bin/env python3
"""Legacy Code Commenter - entry point.

  python run.py                         start the web app on http://localhost:8765
  python run.py serve --port 9000       choose a port; --no-browser to skip opening a tab
  python run.py annotate SRC... [-o DIR] [--level essential|detailed] [--llm]
                                        batch: write <name>.annotated.<ext> (+ .md with --doc)
  python run.py strip FILE [-o OUT]     remove every [AI] comment (restores the original bytes)
  python run.py doc FILE [-o OUT.md]    write the Markdown knowledge-transfer document
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from lcc.commenter import strip
from lcc.engine import analyze, render_file
from lcc.exporters import annotated_name, markdown_doc
from lcc.server import serve


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _library(paths: list[str]) -> dict[str, str]:
    """Copybooks and JCL members (cataloged procedures) that other files can reference by name."""
    lib = {}
    for p in paths:
        if os.path.splitext(p)[1].lower() in (".cpy", ".cpb", ".proc", ".prc", ".jcl", ".cntl", ".prclib"):
            lib[os.path.splitext(os.path.basename(p))[0]] = _read(p)
    return lib


def cmd_annotate(args) -> int:
    paths = [p for pat in args.src for p in (glob.glob(pat) or [pat])]
    lib = _library(paths)
    for p in paths:
        res = analyze(_read(p), os.path.basename(p), args.language, use_llm=args.llm, library=lib)
        if args.level == "essential":
            res["annotations"] = [a for a in res["annotations"] if not a["detail"]]
        text, m = render_file(res, ascii_only=not args.unicode)
        out_dir = args.output or os.path.dirname(p)
        out = os.path.join(out_dir, annotated_name(os.path.basename(p)))
        _write(out, text)
        if args.doc:
            _write(os.path.splitext(out)[0] + ".md", markdown_doc(res))
        print(f"{p}: {res['language_name']}, {len(res['annotations'])} comments, density "
              f"{m['density_before']:.0%} -> {m['density_after']:.0%}, units documented "
              f"{m['units_documented_before']}/{m['units']} -> {m['units_documented_after']}/{m['units']}  => {out}")
    return 0


def cmd_strip(args) -> int:
    text = strip(_read(args.file))
    if args.output:
        _write(args.output, text)
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))   # bytes: no newline translation on Windows
    return 0


def cmd_doc(args) -> int:
    res = analyze(_read(args.file), os.path.basename(args.file), args.language)
    md = markdown_doc(res)
    if args.output:
        _write(args.output, md)
    else:
        sys.stdout.buffer.write(md.encode("utf-8"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Offline inline-comment generator for legacy code.")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the web app (default)")
    s.add_argument("--host", default=os.environ.get("LCC_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("LCC_PORT", "8765")))
    s.add_argument("--no-browser", action="store_true")
    a = sub.add_parser("annotate", help="batch-annotate files")
    a.add_argument("src", nargs="+")
    a.add_argument("-o", "--output", help="output directory (default: next to each source)")
    a.add_argument("--level", choices=["essential", "detailed"], default="essential")
    a.add_argument("--language", choices=["cobol", "plsql", "jcl", "generic"])
    a.add_argument("--llm", action="store_true", help="enrich summaries with the local LLM")
    a.add_argument("--doc", action="store_true", help="also write the Markdown document")
    a.add_argument("--unicode", action="store_true", help="keep non-ASCII characters in comments")
    t = sub.add_parser("strip", help="remove [AI] comments")
    t.add_argument("file")
    t.add_argument("-o", "--output")
    d = sub.add_parser("doc", help="write Markdown documentation")
    d.add_argument("file")
    d.add_argument("-o", "--output")
    d.add_argument("--language", choices=["cobol", "plsql", "jcl", "generic"])
    args = ap.parse_args(argv)
    if args.cmd in (None, "serve"):
        serve(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8765), not getattr(args, "no_browser", False))
        return 0
    return {"annotate": cmd_annotate, "strip": cmd_strip, "doc": cmd_doc}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
