# Technical documentation

## Architecture

```
 Browser (web/)                      Python server (lcc/, stdlib only)
 ┌──────────────────────────┐  JSON  ┌───────────────────────────────────────────────┐
 │ index.html / app.js      │ ─────► │ server.py   HTTP API, CSP, same-origin check   │
 │  upload, code view,      │        │ engine.py   detect → analyze → enrich → metrics│
 │  review state, filters,  │ ◄───── │   detect.py   language detection + generic     │
 │  explain, export menu    │        │   cobol.py    COBOL analyzer                   │
 │ guide.html (user guide)  │        │   plsql.py    PL/SQL analyzer                  │
 │ localStorage (session)   │        │                                                │
 └──────────────────────────┘        │   jcl.py      JCL analyzer                     │
                                     │   vocab.py    identifiers/conditions → English │
                                     │ commenter.py  render / strip / re-import       │
                                     │ exporters.py  Markdown, JSON, ZIP, system map  │
                                     │ llm.py        optional local LLM (Ollama)      │
                                     └───────────────────────────────────────────────┘
```

- **Stateless server.** Each request carries the file content and its annotations. Review state lives in the browser and in exported files, so nothing is stored server-side except a metadata-only audit log.
- **Built-in user guide.** `web/guide.html` is a complete HTML page (printable on its own). `app.js` fetches it on first use, takes its `<article>`, and shows it in a full-screen overlay with a section list, search with highlighting, and deep links (`#guide/<section-id>`, for example `#guide/g-export`). Screenshots live in `web/img/`. To change the guide, edit `web/guide.html`; every `<section>` with an `id` and `data-title` becomes an entry in the contents list.
- **No dependencies.** Python 3.10+ standard library, and vanilla JS/CSS with no build step. This removes package-approval friction in client environments and keeps the attack surface small.

## Pipeline

1. **Split** the source and detect the newline style (`\n` or `\r\n`) and trailing newline, so export can reproduce them exactly.
2. **Re-import.** Existing `[AI]` lines are removed and turned back into annotations (`commenter.extract`), which lets a reviewed file round-trip.
3. **Detect** the language from the extension, falling back to content heuristics.
4. **Analyze** with the language analyzer. Its output is a `Collector` holding annotations, an outline tree, dependencies, a call graph, a summary and facts.
5. **Enrich** (optional). Each unit summary is sent with its code (literals masked) to the local LLM. The rule text is kept in `alt_text`.
6. **Metrics.** Comment density, header coverage before and after, and counts by kind and status.

### Annotation model (`models.py`)

| Field | Meaning |
|---|---|
| `line` | 1-based line the comment is inserted **above** |
| `kind` | `summary`, `business-rule`, `logic`, `data`, `io`, `dependency`, `warning`, `note` |
| `text` | the explanation |
| `confidence` | analyzer confidence (0–1) |
| `source` | `rule`, `llm`, `user`, `import` |
| `status` | `suggested`, `accepted`, `edited`, `rejected` |
| `detail` | shown only at the *Detailed* level |
| `anchor` | owning unit (paragraph, procedure, step) |
| `alt_text` | rule-engine text kept when an LLM rewrote the comment |

## Analyzers

### COBOL (`cobol.py`)
- **Compile-time text manipulation (`prepare`).** Before analysis, code outside literals is upper-cased (COBOL is case-insensitive). `REPLACE ==a== BY ==b==` applies to the following source until `REPLACE OFF`, including multi-line REPLACE statements. `COPY member REPLACING …` (pseudo-text, identifiers, `LEADING`, `TRAILING`) is applied to the copybook when it is resolved. Replacement only rewrites the analysis view; line numbers and the file itself are untouched.
- **Nested and multiple programs.** A source holding several `IDENTIFICATION DIVISION`s is split per program. Each program is analyzed on a copy of the file in which the other programs' lines are blanked, so line numbers stay exact. Nesting comes from `END PROGRAM`. Contained programs inherit the container's condition-names and PICs (GLOBAL data). Calls to a program defined in the same file are reported as *nested*, not external. The outline shows program → divisions → paragraphs.
- **Format detection.** Fixed format is used when ≥80% of non-blank lines have a valid indicator in column 7; otherwise free format (or a `>>SOURCE FORMAT FREE` directive). In fixed format only columns 8–72 are analyzed.
- **Divisions, sections and paragraphs.** Paragraph names must start in Area A (fixed format) and be a lone `NAME.`.
- **Environment.** `SELECT … ASSIGN` binds a logical file to its DD name, with organisation, key and file status.
- **Data division.** Entries are joined up to the terminating period, then a level hierarchy is built. Byte sizes are computed from PIC and USAGE (display, COMP-3, binary, COMP-1/2, OCCURS; REDEFINES excluded), and a target type is suggested (`DECIMAL(p,s)/BigDecimal`, `int`/`long`, `CHAR(n)`). 88-levels are stored so conditions like `IF EMP-HOURLY` can be explained as `EMP-TYPE in 'H','P'`.
- **Copybook resolution.** Copybooks supplied in the `library` request field are pre-analyzed, and their 88-levels and PICs are merged in.
- **Procedure division.** A tokenizer handles literals; `EXEC … END-EXEC` text is kept verbatim. Tokens are split into statements at verbs and scope terminators. A recursive-descent parser builds a tree of IF/ELSE, EVALUATE/WHEN, SEARCH and inline PERFORM nodes, honouring both `END-IF` and pre-85 period termination. Walking the tree produces rules (condition plus the actions of each branch), formulas (with a ROUNDED/truncation note), loops, I/O, CALLs, embedded SQL (tables and operations), CICS commands, and GO TO/ALTER risks.
- **Summaries.** Per paragraph: loops, performs, reads, writes, calculations, SQL, calls, rule count, and who invokes it (from the call graph). Per program: inputs and outputs by OPEN mode, tables, calls, copybooks, and the main flow.

### PL/SQL (`plsql.py`)
- **Masking.** Comments and string literals are masked while keeping character positions, so line numbers stay exact. SQL*Plus `/` lines are ignored.
- **Block pass.** A token stack (`PKG`, `UNIT`, `BEGIN`, `CASE`) gives exact start and end lines for packages, procedures, functions, triggers and anonymous blocks. Expression `CASE … END` is told apart from `END CASE`.
- **Segmentation.** Statements are split on `;`, `THEN`, `LOOP`, block keywords and statement-level `WHEN`. Splitting is suppressed inside SQL statements and CASE expressions.
- **Findings.** Cursors, collection types, `PRAGMA AUTONOMOUS_TRANSACTION`, IF/ELSIF/CASE rules with branch actions, exception handlers (with special treatment for `WHEN OTHERS THEN NULL`), FOR/WHILE/FORALL loops, DML (tables, operations, single-row SELECT INTO, FOR UPDATE, UPDATE or DELETE without WHERE), COMMIT inside loops, `RAISE_APPLICATION_ERROR`, and `EXECUTE IMMEDIATE`. Variables built with `||` are tracked so SQL-injection risk is flagged at the execute site. Also UTL_FILE/UTL_HTTP/DBMS_SCHEDULER, and calls to other packages.

### JCL (`jcl.py`)
- **Symbols.** `&NAME` and `&NAME.` are substituted from three scopes: `SET` statements (in order), procedure defaults (`//P PROC A=1`), and EXEC overrides (`EXEC P,A=2`), with later scopes winning. `&&TEMP` datasets and system symbols (`&SYSUID`…) are left alone. Symbols with no value are flagged.
- **Procedure expansion.** `EXEC name` / `EXEC PROC=name` is expanded from an in-stream `PROC … PEND` block or from a library member uploaded with the job (any JCL file whose stem is the proc name; `.proc`, `.prc`, `.jcl`). The caller's `//step.dd DD` overrides replace or add DDs in the named procedure step. The expansion is described on the calling EXEC line, procedure steps appear nested in the outline, and their programs and datasets join the dependency list and system map. A file that *is* a cataloged procedure is documented on its own, including the symbols a caller must supply.
- Statements are assembled with comma continuation. In-stream data (`DD *`, `DD DATA`, `DLM=`) is captured and its lines are **protected**: no comment is ever inserted inside it.
- Findings: job summary and step chain, `COND=` translated into plain English (the condition is inverted correctly: `COND=(4,LT)` means "bypassed if a prior RC > 4"), `IF/THEN/ELSE/ENDIF`, `DISP` semantics including the abnormal disposition, GDG generations, temporary datasets, `SYSOUT`, `DUMMY`, `JOBLIB/STEPLIB`, `INCLUDE/JCLLIB/SET`, DFSORT control cards (`SORT FIELDS`, `INCLUDE/OMIT COND`, `SUM`, `OUTREC`), and known utilities (IEBGENER, IDCAMS, …).

### Generic (`detect.py`)
Routine headers (SUBROUTINE/FUNCTION/PROC/BEGSR/DCL-PROC…), CALL/PERFORM/EXSR targets and GOTO, for RPG, Fortran, PL/I, Natural, BASIC and similar. Pair it with the local LLM for useful prose.

## Rendering comments (`commenter.py`)

| Language | Comment line | Width |
|---|---|---|
| COBOL fixed | `      *[AI] KIND: text` (indicator in column 7; sequence area left blank) | ≤ 72 |
| COBOL free | `<indent>*> [AI] KIND: text` | 100 |
| PL/SQL | `<indent>-- [AI] KIND: text` | 110 |
| JCL | `//*[AI] KIND: text` | ≤ 71 |
| Other | language-appropriate prefix by extension | 100 |

Continuation lines repeat the marker (`[AI]   …`), so **every** generated line is self-identifying. `strip()` deletes exactly the lines matching `marker_regex`. The property `strip(render(src)) == src` is tested byte-for-byte for every sample and for CRLF input. Comments targeted at protected lines move up to the nearest unprotected line. By default, text is folded to ASCII (`→` becomes `->`, and so on) because mainframe compilers and EBCDIC transfers reject other bytes.

## HTTP API

All endpoints accept and return JSON (except the ZIP). POSTs with a foreign `Origin` are refused (403). The body limit is 12 MB.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/config` | — | version, languages, LLM status |
| GET | `/api/samples`, `/api/samples/<name>` | — | sample list or content |
| POST | `/api/analyze` | `filename, content, language?, use_llm?, mask?, library?` | analysis result (annotations, outline, dependencies, metrics, …) |
| POST | `/api/render` | `file, tag?, ascii?` | `{text, metrics}` for the given annotations |
| POST | `/api/export` | `file, format: annotated\|markdown\|json, tag?, ascii?` | `{filename, content, mime}` |
| POST | `/api/export-zip` | `files[], tag?` | `application/zip` |
| POST | `/api/system-map` | `files[]` (analysis results) | links, DD bindings, shared tables, gaps, utilities |
| POST | `/api/explain` | `filename, content, language?, start, end, use_llm?` | `{text, source, unit}` |

`file` is an analysis result (as returned by `/api/analyze`) whose `annotations` array is the reviewed set.

## Security and confidentiality

- Binds to `127.0.0.1` by default. Binding elsewhere prints a warning.
- `Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self' …`: the page cannot load or send anything off-host. Also `X-Content-Type-Options`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.
- Same-origin check on POSTs, which blocks other open web pages from driving the local API. The static file server is protected against path traversal.
- **LLM guard**: only loopback hosts unless `LCC_ALLOW_REMOTE_LLM=1`. Proxies are bypassed for the local call. String literals and 5+ digit numbers are masked (`<STR1>`, `<NUM2>`). The LLM is used only when the user switches it on, and every LLM failure falls back to the rule engine.
- **Audit log** `logs/audit.jsonl`: timestamp, action, the SHA-256 prefix of the content, language, line and annotation counts, and LLM use. It never contains code or filenames. Disable it with `LCC_AUDIT=0`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LCC_HOST` / `LCC_PORT` | `127.0.0.1` / `8765` | bind address |
| `LCC_LLM_URL` | `http://127.0.0.1:11434` | Ollama-compatible endpoint |
| `LCC_LLM_MODEL` | first installed model | model name |
| `LCC_ALLOW_REMOTE_LLM` | unset | allow a non-loopback LLM host (only if the contract permits) |
| `LCC_AUDIT` | `1` | metadata audit log on/off |
| `LCC_VERBOSE` | unset | log HTTP requests to the console |

## Testing and evaluation

```bash
python -m unittest discover -s tests -v
python tools/evaluate.py
python tools/make_samples.py     # regenerate the synthetic codebase (column rules are checked)
```

The tests cover byte-exact round trip (LF and CRLF), the column-72 and JCL width rules, ASCII safety, protected in-stream data, re-import of edited comments, per-language findings, the cross-file system map, the ZIP bundle, the LLM host guard and literal masking, LLM enrichment against a stub Ollama server (including fallback when it is unreachable), the HTTP API (CSP, path traversal, cross-origin refusal), and the built-in guide (served, self-contained, every image present, every comment kind and shortcut documented).

## Extending

**Add a language:**
1. Write `lcc/<lang>.py` with `analyze(lines) -> Collector`. Call `c.note(line, kind, text, confidence, anchor, detail)`, `c.dep(kind, name, line, op)` and `c.edge(src, dst)`, and set `c.outline`, `c.summary` and `c.facts["units"]`.
2. Register its extensions in `detect.EXT` and add a branch in `engine._run_analyzer`.
3. Add a comment style in `commenter.style` and make sure `marker_regex` matches it.
4. Add a sample and tests. The round-trip test picks it up automatically.

**Improve wording:** the abbreviation dictionary and operator translations are in `vocab.py`.

## Validation tooling

- `tools/anonymize.py` produces a client sample that is safe to share. Pseudonyms keep the same length and are consistent across files, so structure, columns and cross-references survive. Literals and comments are masked, and the reversible key stays with the client.
- `tools/validate.py DIR` runs the automated gates (no crash, byte-exact round trip, column rules, in-stream data intact, unit coverage), reports gaps and suspicious files, and writes a stratified SME review sheet. `--score` turns the filled sheet into accuracy figures with confidence intervals.
- See [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) for the procedure.

**Known limitations:** analysis is pattern-based rather than a full grammar. Heavily macro-generated code and PL/SQL conditional compilation are only partly understood. `REPLACE` pseudo-text that spans several source lines, and procedure code inside copybooks, are not handled. JCL procedures that call other procedures are expanded one level deep, and IF/THEN blocks inside procedures are not evaluated against the caller. Source must be readable text (convert EBCDIC first).
