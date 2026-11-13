/* Legacy Code Commenter - single-page UI (no frameworks, no external requests). */
(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const KINDS = ['summary', 'business-rule', 'logic', 'data', 'io', 'dependency', 'warning', 'note'];
  const KIND_LABEL = { summary: 'Summary', 'business-rule': 'Business rule', logic: 'Logic', data: 'Data', io: 'I/O',
    dependency: 'Dependency', warning: 'Risk', note: 'Note' };
  const SHORT = { summary: 'SUMMARY', 'business-rule': 'RULE', logic: 'LOGIC', data: 'DATA', io: 'I/O',
    dependency: 'DEPENDENCY', warning: 'RISK', note: 'NOTE' };
  const STORE = 'lcc.session.v1';
  const MAX_FILE = 10 * 1024 * 1024;

  const state = {
    files: [], active: null, kinds: new Set(KINDS), level: 'essential', tab: 'outline',
    hits: [], hitIdx: -1, sel: null, focus: null, preview: false, editing: null,
    config: null, llm: false, mask: true,
  };
  let seq = 0;
  const uid = () => `n${Date.now().toString(36)}${(++seq).toString(36)}`;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cur = () => state.files.find((f) => f.id === state.active) || null;
  const kindOrder = (k) => { const i = KINDS.indexOf(k); return i < 0 ? 99 : i; };
  const isCopybook = (n) => /\.(cpy|cpb)$/i.test(n);
  const isProcLike = (n) => /\.(proc|prc|jcl|cntl|prclib)$/i.test(n);
  const isLibrary = (n) => isCopybook(n) || /\.(proc|prclib)$/i.test(n);
  const stem = (n) => n.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '').toUpperCase();

  // ------------------------------------------------------------------ API
  async function api(path, body) {
    const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`;
      try { msg = (await r.json()).error || msg; } catch { /* not JSON */ }
      throw new Error(msg);
    }
    return (r.headers.get('Content-Type') || '').includes('application/json') ? r.json() : r.blob();
  }

  function toast(msg, ms = 3200) {
    const t = $('#toast');
    t.innerHTML = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    if (ms) toast._t = setTimeout(() => { t.hidden = true; }, ms);
  }

  // ------------------------------------------------------------------ persistence (per-browser convenience only)
  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try {
        const data = JSON.stringify({ files: state.files, active: state.active, level: state.level });
        if (data.length < 4.5e6) localStorage.setItem(STORE, data); else localStorage.removeItem(STORE);
      } catch { /* storage unavailable or full: the app still works */ }
    }, 300);
  }
  function load() {
    try {
      const d = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (d && Array.isArray(d.files)) {
        state.files = d.files;
        state.active = d.active;
        state.level = d.level || 'essential';
      }
    } catch { /* ignore corrupt session */ }
    try {
      const th = localStorage.getItem('lcc.theme');
      if (th) document.documentElement.dataset.theme = th;
    } catch { /* ignore */ }
  }

  // ------------------------------------------------------------------ analysis
  function library(extra) {
    const lib = {};
    // Copybooks (COPY members) and JCL members (cataloged procedures) that other files may reference.
    for (const f of state.files) if (isCopybook(f.filename) || f.language === 'jcl') lib[stem(f.filename)] = f.content;
    if (extra && (isCopybook(extra.name) || isProcLike(extra.name))) lib[stem(extra.name)] = extra.content;
    return lib;
  }

  function withIds(anns) {
    return anns.map((a) => ({ ...a, id: uid() }));
  }

  async function analyzeNew(name, content) {
    const res = await api('/api/analyze', { filename: name, content, use_llm: state.llm, mask: state.mask, library: library({ name, content }) });
    const existing = state.files.find((f) => f.filename === name);
    const rec = { ...res, id: existing ? existing.id : uid(), annotations: withIds(res.annotations) };
    if (existing) state.files[state.files.indexOf(existing)] = rec; else state.files.push(rec);
    if (res.imported) toast(`${esc(name)}: imported ${res.imported} existing [AI] comments for editing.`);
    if (res.llm && res.llm.requested && res.llm.error) toast(`Local LLM not used: ${esc(res.llm.error)}`, 6000);
    return rec;
  }

  async function reanalyze(f, quiet) {
    const res = await api('/api/analyze', { filename: f.filename, content: f.content, language: f.language, use_llm: state.llm, mask: state.mask, library: library() });
    const kept = f.annotations.filter((a) => a.status !== 'suggested' || a.source === 'user');
    const keys = new Set(kept.map((a) => `${a.line}|${a.kind}`));
    const fresh = withIds(res.annotations.filter((a) => !keys.has(`${a.line}|${a.kind}`)));
    Object.assign(f, res, { id: f.id, annotations: [...kept, ...fresh].sort((a, b) => a.line - b.line || kindOrder(a.kind) - kindOrder(b.kind)) });
    if (!quiet) {
      const llm = res.llm && res.llm.used ? ` · ${res.llm.enriched} summaries rewritten by ${esc(res.llm.model)}` : '';
      toast(`Re-analyzed ${esc(f.filename)}: kept ${kept.length} reviewed comments${llm}.`);
      if (res.llm && res.llm.requested && res.llm.error) toast(`Local LLM not used: ${esc(res.llm.error)}`, 6000);
    }
  }

  async function addFiles(list) {
    const items = [];
    for (const f of list) {
      if (f.size > MAX_FILE) { toast(`${esc(f.name)} is larger than 10 MB and was skipped.`); continue; }
      items.push({ name: f.name, content: await f.text() });
    }
    await ingest(items);
  }

  async function ingest(items) {
    if (!items.length) return;
    items.sort((a, b) => isLibrary(b.name) - isLibrary(a.name));   // copybooks/procs first so callers resolve them
    let last = null;
    for (let i = 0; i < items.length; i++) {
      toast(`<span class="spinner"></span>Analyzing ${esc(items[i].name)} (${i + 1}/${items.length})${state.llm ? ' with local LLM' : ''}…`, 0);
      try {
        last = await analyzeNew(items[i].name, items[i].content);
        // A copybook or procedure arriving later: re-analyze the files that reference it (reviews are kept).
        const s = stem(items[i].name);
        for (const f of state.files) {
          const resolved = [...(f.copybooks_resolved || []), ...(f.procs_resolved || [])];
          if (f.id !== last.id && (f.dependencies || []).some((d) => (d.kind === 'copybook' || d.kind === 'proc') && d.name.toUpperCase() === s)
              && !resolved.includes(s)) await reanalyze(f, true);
        }
      } catch (e) {
        toast(`Could not analyze ${esc(items[i].name)}: ${esc(e.message)}`, 6000);
      }
    }
    const t = $('#toast');
    if (t.innerHTML.includes('spinner')) t.hidden = true;
    if (last) select(last.id);
    save();
  }

  // ------------------------------------------------------------------ visibility & review
  function visible(a) {
    if (!state.kinds.has(a.kind)) return false;
    if (state.level === 'essential' && a.detail && a.status === 'suggested' && a.source !== 'user') return false;
    return true;
  }
  const exportable = (f) => f.annotations.filter((a) => visible(a) && a.status !== 'rejected');
  const payload = (f) => ({ ...f, annotations: exportable(f) });
  function progress(f) {
    const v = f.annotations.filter(visible);
    const done = v.filter((a) => a.status !== 'suggested').length;
    return { done, total: v.length, pct: v.length ? Math.round((100 * done) / v.length) : 100 };
  }

  // ------------------------------------------------------------------ syntax highlighting
  const KW = {
    cobol: new Set(('ACCEPT ADD ALTER AND ASSIGN AT BY CALL CLOSE COMPUTE CONTINUE COPY DATA DELETE DISPLAY DIVIDE DIVISION ELSE END END-EVALUATE ' +
      'END-IF END-PERFORM END-READ END-SEARCH END-EXEC EVALUATE EXEC EXIT FD SD FILE FILE-CONTROL FROM GIVING GO GOBACK IF INITIALIZE INPUT INSPECT ' +
      'INTO IS MOVE MULTIPLY NOT OCCURS OF OPEN OR OTHER OUTPUT PERFORM PIC PICTURE PROCEDURE PROGRAM-ID READ REDEFINES RETURN REWRITE ROUNDED SEARCH ' +
      'SECTION SELECT SET SORT STOP STRING SUBTRACT THEN THRU TIMES TO TRUE UNTIL USING VALUE VALUES VARYING WHEN WORKING-STORAGE LINKAGE WRITE ZERO ' +
      'ZEROS SPACES SPACE COMP COMP-3 BINARY IDENTIFICATION ENVIRONMENT INPUT-OUTPUT ORGANIZATION SEQUENTIAL INDEXED RUN SQL CURSOR FETCH DECLARE ' +
      'INCLUDE COMMIT UPDATE WHERE AUTHOR RECORDING MODE ADVANCING AFTER BEFORE LINE INDEXED NUMERIC CICS ALL').split(' ')),
    plsql: new Set(('SELECT FROM WHERE INSERT INTO UPDATE DELETE MERGE SET VALUES BEGIN END IF THEN ELSE ELSIF LOOP FOR WHILE IN OUT RETURN IS AS ' +
      'DECLARE EXCEPTION WHEN OTHERS RAISE NULL COMMIT ROLLBACK CURSOR OPEN FETCH CLOSE PROCEDURE FUNCTION PACKAGE BODY CREATE OR REPLACE TRIGGER ' +
      'BEFORE AFTER EACH ROW ON AND NOT CASE EXECUTE IMMEDIATE PRAGMA TYPE TABLE OF RECORD CONSTANT DEFAULT NUMBER VARCHAR2 DATE BOOLEAN INTEGER ' +
      'BULK COLLECT LIMIT FORALL EXIT JOIN GROUP BY ORDER HAVING DISTINCT UNION ALL LIKE BETWEEN EXISTS AUTONOMOUS_TRANSACTION SYSDATE ' +
      'SYSTIMESTAMP RAISE_APPLICATION_ERROR NVL ROUND TRUNC GREATEST REVERSE').split(' ')),
    jcl: new Set('JOB EXEC DD PROC PEND IF THEN ELSE ENDIF SET INCLUDE JCLLIB OUTPUT'.split(' ')),
  };
  function tokens(text, kw, dash) {
    const rx = dash
      ? /('(?:[^']|'')*'?|"[^"]*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z0-9_$#@][\w$#@-]*)|(\s+)|([\s\S])/g
      : /('(?:[^']|'')*'?|"[^"]*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$#@][\w$#@]*)|(\s+)|([\s\S])/g;
    let out = '';
    let m;
    while ((m = rx.exec(text))) {
      if (m[1]) out += `<span class="t-str">${esc(m[1])}</span>`;
      else if (m[2]) out += `<span class="t-num">${m[2]}</span>`;
      else if (m[3]) out += kw.has(m[3].toUpperCase()) ? `<span class="t-kw">${esc(m[3])}</span>` : esc(m[3]);
      else out += esc(m[0]);
    }
    return out;
  }
  // Comment span; [TAG]-marked lines (generated or imported comments) get a distinct style.
  const com = (s) => `<span class="t-com${/^\s*(?:\*>|\*|--|\/\/\*)\s?\[[\w-]+\]/.test(s) ? ' t-ai' : ''}">${esc(s)}</span>`;
  function splitInline(line, marker) {   // split code / trailing comment outside quotes
    let q = '';
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) { if (c === q) q = ''; } else if (c === "'" || c === '"') q = c; else if (line.startsWith(marker, i)) return [line.slice(0, i), line.slice(i)];
    }
    return [line, ''];
  }
  function highlighter(lang, dialect) {
    let inBlock = false;
    if (lang === 'cobol') {
      return (line) => {
        if (dialect === 'fixed') {
          const ind = line.slice(6, 7);
          if (ind === '*' || ind === '/') return `<span class="t-seq">${esc(line.slice(0, 6))}</span>${com(line.slice(6))}`;
          const [code, c] = splitInline(line.slice(7, 72), '*>');
          return `<span class="t-seq">${esc(line.slice(0, 6))}</span>${esc(ind)}${tokens(code, KW.cobol, true)}${c ? com(c) : ''}<span class="t-seq">${esc(line.slice(72))}</span>`;
        }
        if (/^\s*\*>/.test(line)) return com(line);
        const [code, c] = splitInline(line, '*>');
        return tokens(code, KW.cobol, true) + (c ? com(c) : '');
      };
    }
    if (lang === 'plsql') {
      return (line) => {
        let out = '';
        let rest = line;
        while (rest) {
          if (inBlock) {
            const j = rest.indexOf('*/');
            if (j < 0) { out += com(rest); rest = ''; } else { out += com(rest.slice(0, j + 2)); rest = rest.slice(j + 2); inBlock = false; }
            continue;
          }
          const [code, c] = splitInline(rest, '--');
          const b = splitInline(code, '/*');
          if (b[1]) { out += tokens(b[0], KW.plsql, false); rest = b[1] + c; inBlock = true; continue; }
          out += tokens(code, KW.plsql, false) + (c ? com(c) : '');
          rest = '';
        }
        return out;
      };
    }
    if (lang === 'jcl') {
      return (line) => {
        if (line.startsWith('//*')) return com(line);
        if (line.startsWith('/*')) return `<span class="t-kw">${esc(line)}</span>`;
        if (!line.startsWith('//')) return esc(line);
        const m = /^(\/\/)(\S*)(\s+)(\S+)?(.*)$/.exec(line);
        if (!m) return esc(line);
        const ops = esc(m[5] || '').replace(/\b([A-Z][A-Z0-9]*)=/g, '<span class="t-kw">$1</span>=');
        return `${m[1]}<span class="t-name">${esc(m[2])}</span>${m[3]}${m[4] ? (KW.jcl.has(m[4]) ? `<span class="t-kw">${esc(m[4])}</span>` : esc(m[4])) : ''}${ops}`;
      };
    }
    return (line) => (/^\s*(#|\/\/|!|\*|'|REM\b|C\s)/i.test(line) ? com(line) : tokens(line, new Set(), false));
  }

  // ------------------------------------------------------------------ rendering: code view
  function srcLines(f) {
    const lines = f.content.replace(/\r\n/g, '\n').split('\n');
    if (f.trailing_newline) lines.pop();
    return lines;
  }

  function annHtml(a) {
    if (state.editing === a.id) return editorHtml(a);
    const st = a.status;
    const status = { suggested: 'suggested', accepted: '✓ accepted', edited: '✎ edited', rejected: 'rejected' }[st] || st;
    const src = { llm: 'local LLM', user: 'you', import: 'imported' }[a.source] || 'rule engine';
    const conf = a.source === 'rule' || a.source === 'llm' ? ` · ${Math.round((a.confidence || 0) * 100)}%` : '';
    const acts = st === 'rejected'
      ? '<button data-act="undo" title="Restore this comment">↺ Undo</button>'
      : '<button data-act="accept" title="Accept (a)">✓</button><button data-act="edit" title="Edit (e)">✎</button><button data-act="reject" title="Reject (r)">✕</button>';
    const alt = a.alt_text && st !== 'rejected' ? `<details class="alt"><summary>Rule-engine version</summary>${esc(a.alt_text)}</details>` : '';
    return `<div class="ann k-${a.kind} s-${st}${state.focus === a.id ? ' focused' : ''}" data-id="${a.id}" id="ann-${a.id}">` +
      `<div class="ann-head"><span class="ann-kind">${SHORT[a.kind] || 'NOTE'}</span><span>${src}${conf}</span><span class="ann-status">${status}</span>` +
      `<span class="ann-actions">${acts}</span></div><div class="ann-text">${esc(a.text)}</div>${alt}</div>`;
  }

  function editorHtml(a) {
    const opts = KINDS.map((k) => `<option value="${k}"${k === a.kind ? ' selected' : ''}>${KIND_LABEL[k]}</option>`).join('');
    return `<div class="ann k-${a.kind} focused" data-id="${a.id}" id="ann-${a.id}">` +
      `<div class="ann-head"><span class="ann-kind">${a._new ? 'NEW COMMENT' : 'EDIT COMMENT'} · above line ${a.line}</span></div>` +
      `<div class="edit-wrap"><textarea id="editBox" aria-label="Comment text">${esc(a.text)}</textarea></div>` +
      `<div class="edit-row"><select id="editKind" aria-label="Comment type">${opts}</select>` +
      `<span class="muted" style="font-size:12px">Ctrl+Enter save · Esc cancel</span><span style="flex:1"></span>` +
      `<button class="btn btn-sm" data-act="cancel">Cancel</button><button class="btn btn-sm btn-primary" data-act="save">Save</button></div></div>`;
  }

  function renderCode() {
    const f = cur();
    const code = $('#code');
    if (!f) { code.hidden = true; return; }
    const lines = srcLines(f);
    const byLine = new Map();
    for (const a of f.annotations) {
      if (!visible(a) && state.editing !== a.id) continue;
      if (!byLine.has(a.line)) byLine.set(a.line, []);
      byLine.get(a.line).push(a);
    }
    const prot = new Set(f.protected_lines || []);
    const hl = highlighter(f.language, f.dialect);
    const out = [];
    for (let i = 1; i <= lines.length + 1; i++) {
      const anns = byLine.get(i);
      if (anns) anns.sort((a, b) => kindOrder(a.kind) - kindOrder(b.kind)).forEach((a) => out.push(annHtml(a)));
      if (i > lines.length) break;
      const p = prot.has(i);
      out.push(`<div class="ln${p ? ' protected' : ''}" id="L${i}" data-line="${i}"><span class="gutter">` +
        (p ? '' : `<button class="add" data-add="${i}" title="Add a comment above line ${i}">+</button>`) +
        `<span class="num" data-num="${i}" title="Click to select, shift-click for a range">${i}</span></span><code>${hl(lines[i - 1]) || ' '}</code></div>`);
    }
    code.innerHTML = out.join('');
    code.hidden = state.preview;
    applySelection();
    applyHits();
    const box = $('#editBox');
    if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
  }

  function refreshCard(a) {
    const el = document.getElementById(`ann-${a.id}`);
    if (el) el.outerHTML = visible(a) || state.editing === a.id ? annHtml(a) : '';
    renderToolbar();
    renderFiles();
    if (state.tab === 'risks' || state.tab === 'insights') renderTab();
    save();
  }

  // ------------------------------------------------------------------ toolbar, files, tabs
  function renderToolbar() {
    const f = cur();
    $('#toolbar').hidden = !f;
    $('#exportBtn').disabled = !state.files.length;
    if (!f) return;
    $('#langBadge').className = `lang-badge lang-${f.language}`;
    $('#langBadge').textContent = f.language_name;
    $('#fileTitle').textContent = f.filename;
    const extras = [];
    if (f.dialect) extras.push(`${f.dialect} format`);
    extras.push(`${f.line_count} lines`);
    if (f.program_id) extras.push(`PROGRAM-ID ${f.program_id}`);
    if ((f.copybooks_resolved || []).length) extras.push(`copybooks resolved: ${f.copybooks_resolved.join(', ')}`);
    if ((f.procs_resolved || []).length) extras.push(`procedures expanded: ${f.procs_resolved.join(', ')}`);
    if ((f.programs || []).length > 1) extras.push(`${f.programs.length} programs (nested)`);
    if (f.llm && f.llm.used) extras.push(`LLM: ${f.llm.model}`);
    $('#fileMeta').textContent = '· ' + extras.join(' · ');
    const counts = {};
    for (const a of f.annotations) {
      if (state.level === 'essential' && a.detail && a.status === 'suggested' && a.source !== 'user') continue;
      counts[a.kind] = (counts[a.kind] || 0) + 1;
    }
    $('#kindChips').innerHTML = KINDS.filter((k) => counts[k]).map((k) =>
      `<span class="chip${state.kinds.has(k) ? '' : ' off'}" data-kind="${k}" title="Show/hide ${KIND_LABEL[k]} comments (double-click: only this)">` +
      `<span class="dot" style="background:var(--k-${k})"></span>${KIND_LABEL[k]}<span class="n">${counts[k]}</span></span>`).join('');
    $('#levelSel').value = state.level;
    const p = progress(f);
    $('#reviewBar').style.width = `${p.pct}%`;
    $('#reviewText').textContent = `${p.done}/${p.total} visible comments reviewed (${p.pct}%) · export includes what is shown, minus rejected`;
    $('#previewBtn').classList.toggle('on', state.preview);
  }

  function renderFiles() {
    $('#fileCount').textContent = state.files.length;
    $('#fileList').innerHTML = state.files.map((f) => {
      const p = progress(f);
      return `<li class="${f.id === state.active ? 'active' : ''}" data-file="${f.id}" title="${esc(f.filename)}">` +
        `<span class="lang-badge lang-${f.language}">${esc(f.language === 'generic' ? 'TXT' : f.language_name)}</span>` +
        `<span class="fname">${esc(f.filename)}</span><span class="fprog">${p.pct}%</span>` +
        `<button class="x" data-remove="${f.id}" title="Remove from session" aria-label="Remove">✕</button></li>`;
    }).join('') || '<li class="muted" style="cursor:default">No files yet</li>';
  }

  function outlineHtml(nodes, f, depth = 0) {
    return nodes.map((n) => {
      const s = f.annotations.find((a) => a.line === n.line && a.kind === 'summary' && a.status !== 'rejected');
      const pad = 6 + depth * 14;
      return `<button class="outline-node" style="padding-left:${pad}px" data-line="${n.line}" title="${esc(s ? s.text : n.name)}">` +
        `<span class="outline-kind">${esc(n.kind)}</span>${esc(n.name)}<span class="ok">${n.line}–${n.end_line || n.line}${s ? ' ✓' : ''}</span></button>` +
        (n.children && n.children.length ? outlineHtml(n.children, f, depth + 1) : '');
    }).join('');
  }

  async function renderTab() {
    $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === state.tab));
    const body = $('#tabBody');
    const f = cur();
    if (state.tab === 'map') return renderMap(body);
    if (!f) { body.innerHTML = '<p class="muted">Upload a file to see its structure.</p>'; return; }
    if (state.tab === 'outline') {
      body.innerHTML = (f.outline && f.outline.length ? outlineHtml(f.outline, f) : '<p class="muted">No structure detected.</p>');
    } else if (state.tab === 'deps') {
      const groups = {};
      for (const d of f.dependencies || []) (groups[d.kind] = groups[d.kind] || []).push(d);
      const names = { table: 'Database tables', file: 'Files', dataset: 'Datasets', program: 'Programs', copybook: 'Copybooks', package: 'Packages',
        procedure: 'Procedures', proc: 'JCL procedures', library: 'Load libraries', cics: 'CICS commands', external: 'External systems', include: 'Includes', scheduler: 'Scheduler' };
      body.innerHTML = Object.keys(groups).sort().map((k) => `<h4>${esc(names[k] || k)} (${groups[k].length})</h4>` + groups[k].map((d) =>
        `<div class="dep"><div class="dep-name">${esc(d.name)}</div><div class="muted" style="font-size:11.5px">${esc([d.ops.join(', '), d.detail].filter(Boolean).join(' · '))}</div>` +
        `<div>${d.lines.slice(0, 16).map((l) => `<button class="linechip" data-line="${l}">L${l}</button>`).join('')}</div></div>`).join('')).join('')
        || '<p class="muted">No external dependencies detected.</p>';
    } else if (state.tab === 'risks') {
      const risks = f.annotations.filter((a) => a.kind === 'warning' && a.status !== 'rejected');
      body.innerHTML = risks.length
        ? `<p class="muted" style="margin-top:0">${risks.length} construct${risks.length > 1 ? 's' : ''} need special care during migration.</p>` +
          risks.map((a) => `<div class="risk" data-line="${a.line}" data-ann="${a.id}"><b>L${a.line}</b>${a.anchor ? ` <span class="muted">${esc(a.anchor)}</span>` : ''}<div>${esc(a.text)}</div></div>`).join('')
        : '<p class="muted">No migration risks detected in this file.</p>';
    } else if (state.tab === 'insights') {
      body.innerHTML = `<div class="summary-box">${esc(f.summary || 'No summary.')}</div><p class="muted"><span class="spinner"></span>Computing coverage…</p>`;
      try {
        const { metrics: m } = await api('/api/render', { file: payload(f), tag: tag(), ascii: ascii() });
        if (state.tab !== 'insights' || cur() !== f) return;
        const max = Math.max(m.density_after, m.density_before, 0.01);
        const bar = (label, v, frac, after) => `<span>${label}</span><div class="bar${after ? ' after' : ''}"><i style="width:${Math.min(100, frac * 100)}%"></i></div><span>${v}</span>`;
        const units = Math.max(1, m.units);
        const p = progress(f);
        body.innerHTML = `<div class="summary-box">${esc(f.summary || 'No summary.')}</div>` +
          `<h4>Comprehension coverage</h4>` +
          `<div class="metric"><div class="metric-label"><span>Comment density</span><span class="muted">comment ÷ code lines</span></div><div class="bars">` +
          bar('Before', `${Math.round(m.density_before * 100)}%`, m.density_before / max, false) +
          bar('After', `${Math.round(m.density_after * 100)}%`, m.density_after / max, true) + `</div></div>` +
          (m.units ? `<div class="metric"><div class="metric-label"><span>Units with an explanatory header</span><span class="muted">${esc((f.units[0] || {}).kind || 'unit')}s</span></div><div class="bars">` +
          bar('Before', `${m.units_documented_before}/${m.units}`, m.units_documented_before / units, false) +
          bar('After', `${m.units_documented_after}/${m.units}`, m.units_documented_after / units, true) + `</div></div>` : '') +
          `<div class="metric"><div class="metric-label"><span>Review progress</span><span>${p.pct}%</span></div><div class="bars">` +
          bar('Reviewed', `${p.done}/${p.total}`, p.pct / 100, true) + `</div></div>` +
          `<h4>Findings exported</h4><div class="kind-grid">` + KINDS.filter((k) => m.by_kind[k]).map((k) =>
            `<span><span class="dot" style="background:var(--k-${k})"></span>${KIND_LABEL[k]}</span><span>${m.by_kind[k]}</span>`).join('') + `</div>` +
          `<h4>Size</h4><div class="kind-grid"><span>Code lines</span><span>${m.code_lines}</span><span>Original comment lines</span><span>${m.comment_lines_before}</span>` +
          `<span>[AI] comment lines</span><span>${m.ai_comment_lines}</span><span>Dependencies</span><span>${m.dependencies}</span></div>` +
          (f.llm && f.llm.used ? `<h4>Local LLM</h4><p>${f.llm.enriched} unit summaries rewritten by <code>${esc(f.llm.model)}</code>${f.llm.masked_literals ? `; ${f.llm.masked_literals} literals masked before sending` : ''}.</p>` : '') +
          `<p class="fine">Analysis took ${f.elapsed_ms} ms on this machine.</p>`;
      } catch (e) {
        body.insertAdjacentHTML('beforeend', `<p class="muted">Could not compute metrics: ${esc(e.message)}</p>`);
      }
    }
  }

  async function renderMap(body) {
    if (!state.files.length) { body.innerHTML = '<p class="muted">Upload several related files (JCL, programs, copybooks, packages) to see how they connect.</p>'; return; }
    body.innerHTML = '<p class="muted"><span class="spinner"></span>Linking files…</p>';
    const light = state.files.map((f) => ({ filename: f.filename, language: f.language, ext: f.ext, program_id: f.program_id, dependencies: f.dependencies, outline: f.outline }));
    try {
      const m = await api('/api/system-map', { files: light });
      if (state.tab !== 'map') return;
      const fileBtn = (n) => { const f = state.files.find((x) => x.filename === n); return f ? `<a href="#" data-goto="${f.id}">${esc(n)}</a>` : esc(n); };
      let h = '';
      h += `<h4>Relationships (${m.links.length})</h4>` + (m.links.length
        ? `<table class="map-table">${m.links.map((l) => `<tr><td>${fileBtn(l.from)}</td><td class="muted">${esc(l.kind)}</td><td>${fileBtn(l.to)}</td></tr>`).join('')}</table>`
        : '<p class="muted">No links between the uploaded files yet.</p>');
      if (m.dd_bindings.length) h += `<h4>JCL ↔ program files</h4>` + m.dd_bindings.map((b) =>
        `<div class="binding"><b>${esc(b.step)}</b> → ${fileBtn(b.program)}: <code>${esc(b.file)}</code> ` +
        `<span class="muted">via DD ${esc(b.dd)} =</span> <code>${esc(b.dataset)}</code></div>`).join('');
      if (m.utilities && m.utilities.length) h += `<h4>System utilities used</h4><p class="muted" style="margin-top:0">${m.utilities.map(esc).join(', ')} — vendor-supplied, not part of the application inventory.</p>`;
      if (m.shared_tables.length) h += `<h4>Shared tables</h4>` + m.shared_tables.map((t) => `<div class="dep"><span class="dep-name">${esc(t.table)}</span><div class="muted">${t.files.map(esc).join(', ')}</div></div>`).join('');
      if (m.unresolved.length) h += `<h4>Not in this upload (${m.unresolved.length})</h4><p class="muted" style="margin-top:0">Referenced but missing: collect these for the migration inventory.</p>` +
        m.unresolved.map((u) => `<div class="dep"><span class="dep-name">${esc(u.name)}</span> <span class="muted">${esc(u.kind)} · from ${esc(u.file)}</span></div>`).join('');
      body.innerHTML = h;
    } catch (e) {
      body.innerHTML = `<p class="muted">System map failed: ${esc(e.message)}</p>`;
    }
  }

  function renderAll() {
    const has = state.files.length > 0;
    $('#emptyState').hidden = has;
    if (!cur() && has) state.active = state.files[0].id;
    renderFiles();
    renderToolbar();
    if (state.preview && cur()) renderPreview(); else { $('#preview').hidden = true; renderCode(); }
    renderTab();
  }

  function select(id) {
    state.active = id;
    state.sel = null;
    state.focus = null;
    state.editing = null;
    state.hits = [];
    $('#searchBox').value = '';
    $('#searchCount').textContent = '';
    $('#viewer').scrollTop = 0;
    renderAll();
    save();
  }

  // ------------------------------------------------------------------ navigation helpers
  function gotoLine(line, annId) {
    const target = (annId && document.getElementById(`ann-${annId}`)) || document.getElementById(`L${line}`);
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const ln = document.getElementById(`L${line}`);
    if (ln) { ln.classList.remove('flash'); void ln.offsetWidth; ln.classList.add('flash'); }
    if (annId) setFocus(annId);
  }
  function setFocus(id) {
    const prev = state.focus && document.getElementById(`ann-${state.focus}`);
    if (prev) prev.classList.remove('focused');
    state.focus = id;
    const el = id && document.getElementById(`ann-${id}`);
    if (el) el.classList.add('focused');
  }
  function stepUnreviewed(dir) {
    const f = cur();
    if (!f) return;
    const list = f.annotations.filter((a) => visible(a) && a.status === 'suggested').sort((a, b) => a.line - b.line || kindOrder(a.kind) - kindOrder(b.kind));
    if (!list.length) { toast('Every visible comment has been reviewed.'); return; }
    let i = list.findIndex((a) => a.id === state.focus);
    if (i < 0) {
      const focusLine = (f.annotations.find((a) => a.id === state.focus) || {}).line || 0;
      i = dir > 0 ? list.findIndex((a) => a.line > focusLine) : list.length - 1 - [...list].reverse().findIndex((a) => a.line < focusLine);
      if (i < 0 || i >= list.length) i = dir > 0 ? 0 : list.length - 1;
    } else i = (i + dir + list.length) % list.length;
    gotoLine(list[i].line, list[i].id);
  }

  // ------------------------------------------------------------------ selection & explain
  function applySelection() {
    $$('.ln.sel').forEach((el) => el.classList.remove('sel'));
    const bar = $('#selBar');
    if (!state.sel) { bar.hidden = true; return; }
    const { start, end } = state.sel;
    for (let i = start; i <= end; i++) { const el = document.getElementById(`L${i}`); if (el) el.classList.add('sel'); }
    $('#selText').textContent = start === end ? `Line ${start} selected` : `Lines ${start}–${end} selected`;
    bar.hidden = state.preview;
  }

  async function explainSelection() {
    const f = cur();
    if (!f || !state.sel) return;
    const { start, end } = state.sel;
    openDrawer(`Lines ${start}–${end}`, '<span class="spinner"></span>Explaining…', '');
    try {
      const r = await api('/api/explain', { filename: f.filename, content: f.content, language: f.language, start, end, use_llm: state.llm, mask: state.mask });
      const note = r.source === 'llm' ? 'Explained by the local LLM, checked against the rule engine findings below.' : 'Explained by the offline rule engine.';
      openDrawer(`Lines ${r.start}–${r.end}${r.unit ? ' · ' + esc(r.unit) : ''}`,
        `<p class="muted" style="margin-top:0">${note}${r.error ? ` (LLM: ${esc(r.error)})` : ''}</p>${esc(r.text)}`,
        '<button class="btn btn-sm btn-primary" id="insertExplain">Insert as comment</button><button class="btn btn-sm" id="copyExplain">Copy</button>');
      $('#insertExplain').onclick = () => {
        const text = r.text.split('\n').map((s) => s.replace(/^•\s*/, '')).filter(Boolean).join(' ');
        const a = { id: uid(), line: r.start, kind: 'note', text, confidence: 1, source: r.source === 'llm' ? 'llm' : 'user', status: 'accepted', anchor: r.unit || '', detail: false, alt_text: '' };
        f.annotations.push(a);
        state.kinds.add('note');
        closeDrawer();
        renderAll();
        gotoLine(a.line, a.id);
        save();
      };
      $('#copyExplain').onclick = async () => { try { await navigator.clipboard.writeText(r.text); toast('Copied.'); } catch { toast('Clipboard not available.'); } };
    } catch (e) {
      openDrawer('Explain failed', esc(e.message), '');
    }
  }

  function openDrawer(title, html, foot) {
    $('#drawerTitle').innerHTML = title;
    $('#drawerBody').innerHTML = html;
    $('#drawerFoot').innerHTML = foot;
    $('#drawer').hidden = false;
  }
  function closeDrawer() { $('#drawer').hidden = true; }

  function addComment(line) {
    const f = cur();
    if (!f) return;
    const prot = new Set(f.protected_lines || []);
    while (prot.has(line) && line > 1) line--;
    const a = { id: uid(), line, kind: 'note', text: '', confidence: 1, source: 'user', status: 'accepted', anchor: '', detail: false, alt_text: '', _new: true };
    f.annotations.push(a);
    state.editing = a.id;
    state.kinds.add('note');
    renderCode();
    gotoLine(line, a.id);
  }

  function saveEdit(a) {
    const f = cur();
    const text = ($('#editBox').value || '').replace(/\s+/g, ' ').trim();
    const kind = $('#editKind').value;
    if (!text) {
      if (a._new || a.source === 'user') f.annotations.splice(f.annotations.indexOf(a), 1);
      else a.status = 'rejected';
    } else {
      if (text !== a.text && !a._new && a.status !== 'edited') a.status = 'edited';
      if (a._new) a.status = 'accepted';
      else if (text === a.text && kind === a.kind && a.status === 'suggested') a.status = 'accepted';
      a.text = text;
      a.kind = kind;
      state.kinds.add(kind);
    }
    delete a._new;
    state.editing = null;
    renderCode();
    renderToolbar();
    renderFiles();
    if (f.annotations.includes(a)) setFocus(a.id);
    save();
  }
  function cancelEdit(a) {
    const f = cur();
    if (a._new) f.annotations.splice(f.annotations.indexOf(a), 1);
    state.editing = null;
    renderCode();
  }

  // ------------------------------------------------------------------ search
  function runSearch(q) {
    const f = cur();
    state.hits = [];
    state.hitIdx = -1;
    if (f && q) {
      const needle = q.toLowerCase();
      srcLines(f).forEach((l, i) => { if (l.toLowerCase().includes(needle)) state.hits.push(i + 1); });
    }
    $('#searchCount').textContent = q ? `${state.hits.length} hit${state.hits.length === 1 ? '' : 's'}` : '';
    applyHits();
  }
  function applyHits() {
    $$('.ln.hit').forEach((el) => el.classList.remove('hit'));
    for (const n of state.hits) { const el = document.getElementById(`L${n}`); if (el) el.classList.add('hit'); }
  }
  function nextHit(dir = 1) {
    if (!state.hits.length) return;
    state.hitIdx = (state.hitIdx + dir + state.hits.length) % state.hits.length;
    $('#searchCount').textContent = `${state.hitIdx + 1}/${state.hits.length}`;
    gotoLine(state.hits[state.hitIdx]);
  }

  // ------------------------------------------------------------------ preview & export
  const tag = () => (($('#tagOpt').value || 'AI').replace(/[^\w-]/g, '') || 'AI');
  const ascii = () => $('#asciiOpt').checked;

  async function renderPreview() {
    const f = cur();
    if (!f) return;
    $('#code').hidden = true;
    $('#selBar').hidden = true;
    const pre = $('#preview');
    pre.hidden = false;
    pre.textContent = 'Rendering…';
    try {
      const r = await api('/api/render', { file: payload(f), tag: tag(), ascii: ascii() });
      const marker = `[${tag()}]`;
      pre.innerHTML = r.text.split(/\r?\n/).map((l) => (l.includes(marker) ? `<span class="ai">${esc(l)}</span>` : esc(l))).join('\n');
      toast(`Export preview: ${r.metrics.ai_comment_lines} comment lines added; comment density ${Math.round(r.metrics.density_before * 100)}% → ${Math.round(r.metrics.density_after * 100)}%. Original lines are unchanged.`, 5000);
    } catch (e) {
      pre.textContent = `Preview failed: ${e.message}`;
    }
  }

  function download(name, data, mime) {
    const blob = data instanceof Blob ? data : new Blob([data], { type: `${mime || 'text/plain'};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async function doExport(kind) {
    $('#exportMenu').hidden = true;
    const f = cur();
    try {
      if (kind === 'zip') {
        toast('<span class="spinner"></span>Building ZIP…', 0);
        const blob = await api('/api/export-zip', { files: state.files.map(payload), tag: tag() });
        download('legacy-docs.zip', blob);
        toast(`ZIP ready: ${state.files.length} annotated files, Markdown docs, JSON and a system map.`);
        return;
      }
      if (!f) return;
      const r = await api('/api/export', { file: payload(f), format: kind, tag: tag(), ascii: ascii() });
      download(r.filename, r.content, r.mime);
      toast(`Downloaded ${esc(r.filename)}.`);
    } catch (e) {
      toast(`Export failed: ${esc(e.message)}`, 6000);
    }
  }

  // ------------------------------------------------------------------ samples & config
  async function loadSamples() {
    try {
      const { samples } = await api('/api/samples');
      const items = [];
      for (const s of samples) {
        const r = await api(`/api/samples/${encodeURIComponent(s)}`);
        items.push({ name: r.filename, content: r.content });
      }
      await ingest(items);
      const pay = state.files.find((f) => f.filename === 'PAYROLL.cbl');
      if (pay) select(pay.id);
    } catch (e) {
      toast(`Could not load samples: ${esc(e.message)}`, 6000);
    }
  }

  async function loadConfig() {
    try {
      state.config = await api('/api/config');
      const llm = state.config.llm || {};
      const sw = $('#llmSwitch');
      if (llm.available) {
        sw.classList.remove('disabled');
        $('#llmToggle').disabled = false;
        $('#llmLabel').textContent = `Local LLM (${llm.model})`;
        sw.title = `Rewrite unit summaries and explanations with ${llm.model} running at ${llm.url}. Literals are masked before sending.`;
      } else {
        sw.classList.add('disabled');
        $('#llmToggle').disabled = true;
        $('#llmToggle').checked = false;
        sw.title = `Local LLM unavailable: ${llm.reason || 'not configured'}. The offline rule engine is always used.`;
      }
    } catch (e) {
      toast(`Server not reachable: ${esc(e.message)}`, 8000);
    }
  }

  // ------------------------------------------------------------------ user guide
  // The guide lives in web/guide.html (also printable on its own) and is loaded into an in-app overlay.
  const guide = { ready: null, sections: [], marks: [], markIdx: -1 };
  const guideOpen = () => !$('#guide').hidden;

  function loadGuide() {
    if (!guide.ready) {
      guide.ready = fetch('guide.html', { cache: 'no-store' })
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text(); })
        .then((html) => {
          const art = new DOMParser().parseFromString(html, 'text/html').querySelector('#guideContent');
          if (!art) throw new Error('guide content missing');
          const scroll = $('#guideScroll');
          scroll.replaceChildren(document.adoptNode(art));
          guide.sections = $$('section[id]', scroll);
          $('#guideToc').innerHTML = guide.sections.map((sec) =>
            `<a href="#guide/${esc(sec.id)}" data-goto="${esc(sec.id)}">${esc(sec.dataset.title || $('h2', sec).textContent)}</a>`).join('');
          spyGuide();
        })
        .catch((e) => {
          guide.ready = null;
          $('#guideScroll').innerHTML = `<p class="guide-loading">Could not load the guide: ${esc(e.message)}</p>`;
        });
    }
    return guide.ready;
  }

  async function openGuide(id) {
    const g = $('#guide');
    if (g.hidden) {
      g.hidden = false;
      for (const el of document.body.children) if (el !== g && el.id !== 'toast') el.inert = true;
    }
    await loadGuide();
    if (id) gotoGuide(id);
    $('#guideScroll').focus({ preventScroll: true });
  }

  function closeGuide() {
    $('#guide').hidden = true;
    for (const el of document.body.children) el.inert = false;
    if (location.hash.startsWith('#guide')) history.replaceState(null, '', location.pathname + location.search);
  }

  function gotoGuide(id) {
    const sec = document.getElementById(id);
    if (!sec || !$('#guideScroll').contains(sec)) return;
    if (sec.hidden) { $('#guideSearch').value = ''; searchGuide(''); }
    $('#guideScroll').scrollTo({ top: sec.offsetTop - 8, behavior: 'auto' });
    history.replaceState(null, '', `#guide/${id}`);
    markToc(id);
  }

  function markToc(id) {
    $$('#guideToc a').forEach((a) => a.classList.toggle('on', a.dataset.goto === id));
  }

  function spyGuide() {
    const scroll = $('#guideScroll');
    scroll.addEventListener('scroll', () => {
      const y = scroll.scrollTop + 40;
      let current = '';
      for (const sec of guide.sections) if (!sec.hidden && sec.offsetTop <= y) current = sec.id;
      if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 4) {
        const visible = guide.sections.filter((sec) => !sec.hidden);
        if (visible.length) current = visible[visible.length - 1].id;
      }
      markToc(current);
    }, { passive: true });
  }

  function searchGuide(q) {
    const root = $('#guideContent');
    if (!root) return;
    for (const m of $$('mark.gq', root)) m.replaceWith(document.createTextNode(m.textContent));
    root.normalize();
    guide.marks = [];
    guide.markIdx = -1;
    const query = q.trim().toLowerCase();
    for (const sec of guide.sections) {
      sec.hidden = !!query && !sec.textContent.toLowerCase().includes(query);
      const link = $(`#guideToc a[data-goto="${sec.id}"]`);
      if (link) link.hidden = sec.hidden;
    }
    $('.guide-intro', root).hidden = !!query;
    if (!query) { $('#guideCount').textContent = ''; return; }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest('[hidden]') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    while (walker.nextNode()) if (walker.currentNode.nodeValue.toLowerCase().includes(query)) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      const lower = text.toLowerCase();
      const frag = document.createDocumentFragment();
      let at = 0;
      for (let i = lower.indexOf(query); i >= 0; i = lower.indexOf(query, i + query.length)) {
        frag.append(text.slice(at, i));
        const m = document.createElement('mark');
        m.className = 'gq';
        m.textContent = text.slice(i, i + query.length);
        frag.append(m);
        guide.marks.push(m);
        at = i + query.length;
      }
      frag.append(text.slice(at));
      node.replaceWith(frag);
    }
    $('#guideCount').textContent = guide.marks.length ? `${guide.marks.length} match${guide.marks.length === 1 ? '' : 'es'}` : 'no matches';
    $('#guideScroll').scrollTop = 0;
  }

  function nextGuideMatch(dir) {
    if (!guide.marks.length) return;
    guide.marks[guide.markIdx]?.classList.remove('cur');
    guide.markIdx = (guide.markIdx + dir + guide.marks.length) % guide.marks.length;
    const m = guide.marks[guide.markIdx];
    m.classList.add('cur');
    m.scrollIntoView({ block: 'center', behavior: 'smooth' });
    $('#guideCount').textContent = `${guide.markIdx + 1} of ${guide.marks.length}`;
  }

  function bindGuide() {
    $('#helpBtn').onclick = () => openGuide();
    $('#emptyGuide').onclick = (e) => { e.preventDefault(); openGuide(); };
    $('#guideClose').onclick = closeGuide;
    $('#guidePrint').onclick = () => { $('#guideSearch').value = ''; searchGuide(''); window.print(); };
    $('#guide').addEventListener('click', (e) => {
      const go = e.target.closest('[data-goto]');
      if (go) { e.preventDefault(); gotoGuide(go.dataset.goto); return; }
      const act = e.target.closest('[data-guide-action]');
      if (act) {
        closeGuide();
        if (act.dataset.guideAction === 'samples') loadSamples();
        else if (act.dataset.guideAction === 'upload') $('#fileInput').click();
      }
    });
    let timer = 0;
    $('#guideSearch').addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => searchGuide(e.target.value), 120); });
    $('#guideSearch').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timer); if (!guide.marks.length) searchGuide(e.target.value); nextGuideMatch(e.shiftKey ? -1 : 1); }
      else if (e.key === 'Escape') {
        e.preventDefault();
        if (e.target.value) { e.target.value = ''; searchGuide(''); } else closeGuide();
      }
    });
    const fromHash = () => {
      if (location.hash.startsWith('#guide')) openGuide(location.hash.split('/')[1] || '');
    };
    window.addEventListener('hashchange', fromHash);
    fromHash();
  }

  // ------------------------------------------------------------------ events
  function bind() {
    const input = $('#fileInput');
    const pick = () => input.click();
    $('#uploadBtn').onclick = pick;
    $('#emptyUpload').onclick = pick;
    input.onchange = () => { addFiles([...input.files]); input.value = ''; };
    $('#samplesBtn').onclick = loadSamples;
    $('#emptySamples').onclick = loadSamples;

    const dz = $('#dropZone');
    window.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
    window.addEventListener('dragleave', (e) => { if (!e.relatedTarget) dz.classList.remove('over'); });
    window.addEventListener('drop', (e) => { e.preventDefault(); dz.classList.remove('over'); if (e.dataTransfer.files.length) addFiles([...e.dataTransfer.files]); });

    $('#exportBtn').onclick = (e) => { e.stopPropagation(); $('#exportMenu').hidden = !$('#exportMenu').hidden; };
    $('#exportMenu').addEventListener('click', (e) => { const b = e.target.closest('[data-export]'); if (b) doExport(b.dataset.export); e.stopPropagation(); });
    document.addEventListener('click', () => { $('#exportMenu').hidden = true; });

    $('#themeBtn').onclick = () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === 'dark'
        : window.matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('lcc.theme', document.documentElement.dataset.theme); } catch { /* ignore */ }
    };
    bindGuide();

    $('#llmToggle').onchange = (e) => {
      state.llm = e.target.checked;
      if (state.llm) toast(`Local LLM on: new uploads, Re-analyze and Explain will use ${esc(state.config.llm.model)}. Code stays on this machine.`, 5000);
    };

    $('#fileList').addEventListener('click', (e) => {
      const rm = e.target.closest('[data-remove]');
      if (rm) {
        const f = state.files.find((x) => x.id === rm.dataset.remove);
        if (f && confirm(`Remove ${f.filename} and its review state from this session?`)) {
          state.files.splice(state.files.indexOf(f), 1);
          if (state.active === f.id) state.active = state.files[0] ? state.files[0].id : null;
          renderAll();
          save();
        }
        return;
      }
      const li = e.target.closest('[data-file]');
      if (li) select(li.dataset.file);
    });

    $$('.tab').forEach((t) => { t.onclick = () => { state.tab = t.dataset.tab; renderTab(); }; });
    $('#tabBody').addEventListener('click', (e) => {
      const g = e.target.closest('[data-goto]');
      if (g) { e.preventDefault(); select(g.dataset.goto); return; }
      const el = e.target.closest('[data-line]');
      if (el) {
        if (state.preview) { state.preview = false; renderAll(); }
        gotoLine(+el.dataset.line, el.dataset.ann);
      }
    });

    $('#kindChips').addEventListener('click', (e) => {
      const c = e.target.closest('[data-kind]');
      if (!c) return;
      const k = c.dataset.kind;
      if (state.kinds.has(k)) state.kinds.delete(k); else state.kinds.add(k);
      renderToolbar();
      state.preview ? renderPreview() : renderCode();
    });
    $('#kindChips').addEventListener('dblclick', (e) => {
      const c = e.target.closest('[data-kind]');
      if (!c) return;
      state.kinds = new Set([c.dataset.kind]);
      renderToolbar();
      state.preview ? renderPreview() : renderCode();
    });
    $('#levelSel').onchange = (e) => { state.level = e.target.value; renderAll(); save(); };

    let st = null;
    $('#searchBox').addEventListener('input', (e) => { clearTimeout(st); st = setTimeout(() => runSearch(e.target.value), 150); });
    $('#searchBox').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runSearch(e.target.value); nextHit(e.shiftKey ? -1 : 1); }
      if (e.key === 'Escape') { e.target.value = ''; runSearch(''); e.target.blur(); }
    });

    $('#acceptAllBtn').onclick = () => {
      const f = cur();
      if (!f) return;
      let n = 0;
      for (const a of f.annotations) if (visible(a) && a.status === 'suggested') { a.status = 'accepted'; n++; }
      toast(`Accepted ${n} comments.`);
      renderAll();
      save();
    };
    $('#reanalyzeBtn').onclick = async () => {
      const f = cur();
      if (!f) return;
      toast(`<span class="spinner"></span>Re-analyzing${state.llm ? ' with local LLM (this can take a while)' : ''}…`, 0);
      try { await reanalyze(f); renderAll(); save(); } catch (e) { toast(`Re-analysis failed: ${esc(e.message)}`, 6000); }
    };
    $('#previewBtn').onclick = () => togglePreview();

    $('#code').addEventListener('click', (e) => {
      const f = cur();
      const add = e.target.closest('[data-add]');
      if (add) { addComment(+add.dataset.add); return; }
      const num = e.target.closest('[data-num]');
      if (num) {
        const n = +num.dataset.num;
        if (e.shiftKey && state.sel) state.sel = { start: Math.min(state.sel.anchor, n), end: Math.max(state.sel.anchor, n), anchor: state.sel.anchor };
        else if (state.sel && state.sel.start === n && state.sel.end === n) state.sel = null;
        else state.sel = { start: n, end: n, anchor: n };
        applySelection();
        return;
      }
      const card = e.target.closest('.ann');
      if (!card || !f) return;
      const a = f.annotations.find((x) => x.id === card.dataset.id);
      if (!a) return;
      const act = e.target.closest('[data-act]');
      if (!act) { if (state.editing !== a.id && e.target.tagName !== 'SUMMARY') setFocus(a.id); return; }
      act.blur();
      const op = act.dataset.act;
      if (op === 'accept') { a.status = 'accepted'; state.focus = a.id; refreshCard(a); }
      else if (op === 'reject') { a.status = 'rejected'; state.focus = a.id; refreshCard(a); }
      else if (op === 'undo') { a.status = 'suggested'; state.focus = a.id; refreshCard(a); }
      else if (op === 'edit') { state.editing = a.id; state.focus = a.id; renderCode(); }
      else if (op === 'save') saveEdit(a);
      else if (op === 'cancel') cancelEdit(a);
    });
    $('#code').addEventListener('keydown', (e) => {
      if (e.target.id !== 'editBox' && e.target.id !== 'editKind') return;
      const f = cur();
      const a = f && f.annotations.find((x) => x.id === state.editing);
      if (!a) return;
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveEdit(a); }
      if (e.key === 'Escape') { e.preventDefault(); cancelEdit(a); }
    });

    $('#explainBtn').onclick = explainSelection;
    $('#addCommentBtn').onclick = () => { if (state.sel) addComment(state.sel.start); };
    $('#clearSelBtn').onclick = () => { state.sel = null; applySelection(); };
    $('#drawerClose').onclick = closeDrawer;

    document.addEventListener('keydown', (e) => {
      const tagName = (e.target.tagName || '').toLowerCase();
      if (['input', 'textarea', 'select'].includes(tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (guideOpen()) { if (e.key === 'Escape') closeGuide(); return; }
      const f = cur();
      if (e.key === 'Escape') { closeDrawer(); state.sel = null; applySelection(); return; }
      if (e.key === '?') { openGuide('g-keys'); return; }
      if (!f) return;
      if (e.key === '/') { e.preventDefault(); $('#searchBox').focus(); return; }
      if (e.key === 'p') { togglePreview(); return; }
      if (e.key === ']') { e.preventDefault(); stepUnreviewed(1); return; }
      if (e.key === '[') { e.preventDefault(); stepUnreviewed(-1); return; }
      const a = f.annotations.find((x) => x.id === state.focus);
      if (!a || state.preview) return;
      if (e.key === 'a') { a.status = 'accepted'; refreshCard(a); stepUnreviewed(1); }
      else if (e.key === 'r') { a.status = 'rejected'; refreshCard(a); stepUnreviewed(1); }
      else if (e.key === 'e') { e.preventDefault(); state.editing = a.id; renderCode(); }
    });
  }

  function togglePreview() {
    if (!cur()) return;
    state.preview = !state.preview;
    renderToolbar();
    if (state.preview) renderPreview();
    else { $('#preview').hidden = true; renderCode(); }
  }

  // ------------------------------------------------------------------ boot
  // Keep comment cards sized to the visible code area (drawer open, narrow screens).
  const viewer = $('#viewer');
  const setW = () => document.documentElement.style.setProperty('--viewer-w', `${viewer.clientWidth}px`);
  if (window.ResizeObserver) new ResizeObserver(setW).observe(viewer); else window.addEventListener('resize', setW);
  setW();
  load();
  bind();
  renderAll();
  loadConfig();
})();
