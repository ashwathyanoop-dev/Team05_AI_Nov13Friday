"""Generate a 16:9 widescreen PowerPoint presentation for Legacy Code Commenter."""
import os
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

# Colors
C_DARK = RGBColor(15, 23, 42)       # Slate 900
C_NAVY = RGBColor(30, 41, 59)      # Slate 800
C_BLUE = RGBColor(37, 99, 235)     # Blue 600
C_CYAN = RGBColor(13, 148, 136)    # Teal 600
C_BG = RGBColor(248, 250, 252)     # Slate 50
C_WHITE = RGBColor(255, 255, 255)
C_MUTED = RGBColor(100, 116, 139)  # Slate 500
C_TEXT = RGBColor(51, 65, 85)      # Slate 700
C_ACCENT = RGBColor(79, 70, 229)   # Indigo 600
C_GREEN = RGBColor(22, 163, 74)    # Green 600
C_CARD_BG = RGBColor(241, 245, 249)# Slate 100
C_BORDER = RGBColor(226, 232, 240) # Slate 200

def create_presentation(output_path="Legacy_Code_Commenter_Presentation.pptx"):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    def add_header(slide, title, category="LEGACY CODE COMMENTER", subtitle=None):
        # Header banner shape
        banner = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.5), Inches(11.733), Inches(1.1))
        banner.fill.background()
        banner.line.color.rgb = C_BORDER
        banner.line.fill.background()
        
        # Category pill text
        tf = banner.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p0 = tf.paragraphs[0]
        p0.text = category.upper()
        p0.font.size = Pt(10)
        p0.font.bold = True
        p0.font.color.rgb = C_BLUE
        
        # Title text
        p1 = tf.add_paragraph()
        p1.text = title
        p1.font.size = Pt(22)
        p1.font.bold = True
        p1.font.color.rgb = C_DARK
        
        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(11)
            p2.font.color.rgb = C_MUTED

    def add_footer(slide, current_idx, total_slides=12):
        footer = slide.shapes.add_textbox(Inches(0.8), Inches(7.0), Inches(11.733), Inches(0.4))
        tf = footer.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = f"Legacy Code Commenter  |  Automated Modernization & Knowledge Transfer  |  Slide {current_idx} of {total_slides}"
        p.font.size = Pt(9)
        p.font.color.rgb = C_MUTED

    def create_card(slide, left, top, width, height, bg_color=C_CARD_BG, border_color=C_BORDER):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        if border_color:
            card.line.color.rgb = border_color
            card.line.width = Pt(1)
        else:
            card.line.fill.background()
        return card

    # ==========================================
    # SLIDE 1: Title Slide
    # ==========================================
    s1 = prs.slides.add_slide(blank_layout)
    bg1 = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    bg1.fill.solid()
    bg1.fill.fore_color.rgb = C_DARK
    bg1.line.fill.background()

    # Title card inner
    t_box = s1.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(10.9), Inches(3.8))
    tf1 = t_box.text_frame
    tf1.word_wrap = True

    p = tf1.paragraphs[0]
    p.text = "AI-POWERED MAINFRAME & LEGACY MODERNIZATION"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = RGBColor(96, 165, 250) # Blue 400

    p = tf1.add_paragraph()
    p.text = "Legacy Code Commenter"
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = C_WHITE

    p = tf1.add_paragraph()
    p.text = "Offline, Zero-Dependency Semantic Analyzer, Comment Generator &\nKnowledge-Transfer Platform for COBOL, PL/SQL, and JCL"
    p.font.size = Pt(18)
    p.font.color.rgb = RGBColor(203, 213, 225) # Slate 300

    p = tf1.add_paragraph()
    p.text = "\nEnd-to-End Architectural Overview, Capabilities, Security & Evaluation"
    p.font.size = Pt(12)
    p.font.color.rgb = C_MUTED

    # Bottom metric pills on title slide
    pills = [
        ("Zero Dependencies", "Python stdlib only"),
        ("Byte-Exact Safety", "Original code untouched"),
        ("100% Offline", "No data egress / strictly air-gapped"),
        ("3 Core Stacks", "COBOL, PL/SQL, JCL + Fallback")
    ]
    for i, (head, sub) in enumerate(pills):
        px = Inches(1.2 + i * 2.8)
        py = Inches(5.6)
        card = create_card(s1, px, py, Inches(2.6), Inches(1.1), bg_color=C_NAVY, border_color=RGBColor(51, 65, 85))
        tf = card.text_frame
        tf.margin_top = Inches(0.15)
        tf.margin_left = Inches(0.2)
        p = tf.paragraphs[0]
        p.text = head
        p.font.size = Pt(12)
        p.font.bold = True
        p.font.color.rgb = C_WHITE
        p2 = tf.add_paragraph()
        p2.text = sub
        p2.font.size = Pt(9.5)
        p2.font.color.rgb = RGBColor(148, 163, 184)

    # ==========================================
    # SLIDE 2: Problem Statement
    # ==========================================
    s2 = prs.slides.add_slide(blank_layout)
    add_header(s2, "The Legacy Code Modernization Dilemma", "BUSINESS CONTEXT & PAIN POINTS",
               "Why enterprise migration initiatives stall and cost millions in manual discovery.")
    add_footer(s2, 2)

    cards_s2 = [
        ("The 'Lost Knowledge' Crisis",
         "Decades of Undocumented Rules",
         [
             "Mission-critical COBOL, PL/SQL, and JCL codebases run core banking and utility operations.",
             "Original authors retired; legacy code has sparse, misleading, or completely absent comments.",
             "Average comment density in legacy code is under 2-5%, forcing manual code reverse-engineering."
         ]),
        ("Costly & Slow Discovery",
         "Weeks Lost Per Module",
         [
             "Modernization teams spend up to 60-70% of project time just figuring out what the code actually does.",
             "Hidden gotchas: 88-level condition names, truncation vs rounding, GO TO spaghetti, COMMIT inside loops.",
             "Missing cross-file maps: how JCL feeds COBOL batch jobs and updates Db2 tables is untracked."
         ]),
        ("Compliance & Air-Gap Barriers",
         "Strict Data Privacy Laws",
         [
             "Financial & utility clients strictly forbid sending proprietary source code or PII to external cloud LLMs.",
             "Standard open-source packages require complex C-compilers or package approvals in locked environments.",
             "Modernization tools must run 100% local, air-gapped, and provide provable safety guarantees."
         ])
    ]

    for i, (title, subtitle, bullets) in enumerate(cards_s2):
        cx = Inches(0.8 + i * 4.0)
        card = create_card(s2, cx, Inches(1.8), Inches(3.733), Inches(4.9))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(15)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.size = Pt(11)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_BLUE

        tf.add_paragraph() # Spacer
        for b in bullets:
            pb = tf.add_paragraph()
            pb.text = "• " + b
            pb.font.size = Pt(11)
            pb.font.color.rgb = C_TEXT
            pb.space_after = Pt(8)

    # ==========================================
    # SLIDE 3: Product Vision & Solution
    # ==========================================
    s3 = prs.slides.add_slide(blank_layout)
    add_header(s3, "Introducing Legacy Code Commenter", "THE SOLUTION",
               "An intelligent, offline platform that converts cryptic legacy syntax into self-documenting code.")
    add_footer(s3, 3)

    # 4 Quadrants
    features_s3 = [
        ("Automated Semantic Commenting",
         "High-Precision Rule Engine",
         "Parses COBOL, PL/SQL, and JCL using native AST-like pattern parsers. Injects plain-English explanatory headers, business rule callouts, data transformations, and migration warnings."),
        ("Non-Intrusive & Byte-Exact",
         "Zero Risk to Source Code",
         "Never modifies or alters existing source lines. Injects only dedicated [AI] comment lines strictly respecting column-72 (COBOL) and JCL limits. Original bytes can be restored instantly via single-command strip."),
        ("Interactive Web Review & Workbench",
         "Human-in-the-Loop Review",
         "Developers review, edit, accept, or reject generated annotations in an intuitive browser UI. Includes interactive selection explanation ('Explain This'), call graph navigation, and live search."),
        ("Comprehensive Knowledge Transfer",
         "Instant Documentation & System Maps",
         "One-click export of annotated source code, comprehensive Markdown KT documentation, JSON AST representations, ZIP bundles, and cross-file System Dependency Maps.")
    ]

    for i, (f_title, f_sub, f_desc) in enumerate(features_s3):
        col = i % 2
        row = i // 2
        cx = Inches(0.8 + col * 5.95)
        cy = Inches(1.8 + row * 2.5)
        card = create_card(s3, cx, cy, Inches(5.75), Inches(2.3))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = f_title
        p.font.size = Pt(15)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = f_sub
        p_sub.font.size = Pt(11)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_CYAN

        p_desc = tf.add_paragraph()
        p_desc.text = f_desc
        p_desc.font.size = Pt(11)
        p_desc.font.color.rgb = C_TEXT
        p_desc.space_before = Pt(6)

    # ==========================================
    # SLIDE 4: End-to-End Architecture
    # ==========================================
    s4 = prs.slides.add_slide(blank_layout)
    add_header(s4, "End-to-End System Architecture", "SYSTEM DESIGN",
               "Stateless, lightweight architecture adhering to zero-trust air-gapped operational standards.")
    add_footer(s4, 4)

    # Three Tier horizontal cards
    tiers = [
        ("Frontend: Browser UI",
         "Vanilla HTML5 / Modern JS / CSS3",
         [
             "Zero-build SPA: No node_modules, no Webpack, no external CDNs.",
             "Interactive Code Viewer with syntax highlight & review badges.",
             "State preserved locally in client browser session (localStorage).",
             "Interactive explain-a-selection modal & full-text outline search.",
             "Built-in searchable User Guide (g-load, g-review, g-export, keys)."
         ]),
        ("Core: Python Server & Rule Engine",
         "Python 3.10+ Standard Library Only",
         [
             "server.py: Pure stdlib ThreadingHTTPServer binding to 127.0.0.1.",
             "engine.py: Orchestrates detection, parsing, metrics, and rendering.",
             "Dedicated Analyzers: cobol.py, plsql.py, jcl.py, detect.py.",
             "vocab.py: Humanizes uppercase abbreviations & operator conditions.",
             "exporters.py: Generates Markdown KT docs, JSON AST, ZIP, & maps."
         ]),
        ("Privacy & Optional Local LLM",
         "Air-Gap Guarded & Literal-Masked",
         [
             "Strict Content-Security-Policy: Blocks all outbound web traffic.",
             "Loopback Guard: Connects only to local Ollama (127.0.0.1:11434).",
             "Automatic Literal Masking: Replaces literals (<STR1>, <NUM1>).",
             "Graceful Fallback: Seamlessly falls back to rule engine if LLM offline.",
             "Audit Logging: Logs SHA-256 prefixes only; source code never stored."
         ])
    ]

    for i, (t_name, t_sub, t_items) in enumerate(tiers):
        cx = Inches(0.8 + i * 4.0)
        card = create_card(s4, cx, Inches(1.8), Inches(3.733), Inches(4.9))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = t_name
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = t_sub
        p_sub.font.size = Pt(10.5)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_BLUE

        tf.add_paragraph()
        for item in t_items:
            pb = tf.add_paragraph()
            pb.text = "• " + item
            pb.font.size = Pt(10.5)
            pb.font.color.rgb = C_TEXT
            pb.space_after = Pt(7)

    # ==========================================
    # SLIDE 5: Deep-Dive: COBOL Analyzer
    # ==========================================
    s5 = prs.slides.add_slide(blank_layout)
    add_header(s5, "Multi-Language Deep Dive: COBOL Engine", "LANGUAGE ANALYZERS",
               "Full compile-time pre-processing, copybook resolution, and hierarchical grammar analysis.")
    add_footer(s5, 5)

    cobol_cards = [
        ("Compile-Time Text Pre-Processing",
         [
             "REPLACE Directive: Handles multi-line REPLACE ==x== BY ==y== until REPLACE OFF.",
             "COPY REPLACING: Expands external copybooks with identifier, pseudo-text, LEADING/TRAILING replacements.",
             "Nested Programs: Splits multi-program sources, preserving line numbering through blanked overlays.",
             "Format Heuristics: Auto-detects Fixed Format (columns 8-72 Area A/B) vs Free Format."
         ]),
        ("Data Division & 88-Levels",
         [
             "PIC & USAGE Parsing: Computes exact byte layouts for COMP, COMP-3 (packed decimal), binary, and OCCURS.",
             "Target Type Suggestions: Maps COBOL fields to Java/C# equivalents (BigDecimal, int, long, CHAR).",
             "Condition Names (88-Levels): Ingests 88-levels to translate 'IF EMP-HOURLY' into 'EMP-TYPE in H, P'.",
             "Library Copybooks: Merges external copybook definitions directly into data dictionary."
         ]),
        ("Procedure Division & Risks",
         [
             "Recursive Descent Parser: Evaluates nested IF/ELSE, EVALUATE/WHEN, SEARCH, and PERFORM statements.",
             "Arithmetic Truncation Detection: Flags COMPUTE/MULTIPLY without ROUNDED as high migration risks.",
             "Control-Flow Spaghetti: Flags ALTER and computed/unconditional GO TO branching.",
             "Embedded Subsystems: Extracts EXEC SQL (tables, operations) and EXEC CICS command semantics."
         ])
    ]

    for i, (title, items) in enumerate(cobol_cards):
        cx = Inches(0.8 + i * 4.0)
        card = create_card(s5, cx, Inches(1.8), Inches(3.733), Inches(4.9))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        tf.add_paragraph()
        for item in items:
            head, body = item.split(": ", 1)
            pb = tf.add_paragraph()
            pb.text = "• " + head + ": "
            pb.font.size = Pt(10.5)
            pb.font.bold = True
            pb.font.color.rgb = C_NAVY
            pb.space_after = Pt(7)
            # Add normal text
            r = pb.add_run()
            r.text = body
            r.font.bold = False
            r.font.color.rgb = C_TEXT

    # ==========================================
    # SLIDE 6: Deep-Dive: PL/SQL and JCL Analyzers
    # ==========================================
    s6 = prs.slides.add_slide(blank_layout)
    add_header(s6, "PL/SQL and JCL Specialized Analyzers", "LANGUAGE ANALYZERS",
               "Understanding database stored procedures and mainframe job control orchestration.")
    add_footer(s6, 6)

    # Two large columns: PL/SQL on left, JCL on right
    plsql_items = [
        ("Block Stack Resolution", "Identifies package specifications, package bodies, procedures, functions, triggers, and nested blocks."),
        ("Database Transaction Boundaries", "Flags PRAGMA AUTONOMOUS_TRANSACTION and dangerous COMMIT / ROLLBACK inside iterative loops."),
        ("Silent Exception Swallowing", "Specifically flags 'WHEN OTHERS THEN NULL' which masks production runtime errors during cloud migration."),
        ("Dynamic SQL & Security", "Tracks string concatenations (||) fed into EXECUTE IMMEDIATE to pinpoint SQL injection vulnerabilities."),
        ("DML & Cursor Analysis", "Maps queries, FOR UPDATE locks, and detects risky bulk UPDATE/DELETE without WHERE clauses.")
    ]

    jcl_items = [
        ("Symbol Substitution Scopes", "Substitutes &NAME across 3 prioritized scopes: SET statements, cataloged PROC defaults, and EXEC overrides."),
        ("Procedure Expansion", "Recursively inlines cataloged procedures (PROCs) from uploaded libraries, resolving step-level DD overrides."),
        ("COND Logic Inversion", "Inverts tricky mainframe logic into plain English (e.g. COND=(4,LT) -> 'Bypassed if a prior step RC > 4')."),
        ("GDG Generation Management", "Explains Generation Data Group semantics: allocates (+1) new generation, binds (0) current, or (-1) prior."),
        ("Protected In-Stream Cards", "Captures DD * and DD DATA (DFSORT SORT/INCLUDE rules); guarantees zero comment insertion inside raw data.")
    ]

    # Left Card: PL/SQL
    card_pl = create_card(s6, Inches(0.8), Inches(1.8), Inches(5.75), Inches(4.9))
    tf_pl = card_pl.text_frame
    tf_pl.word_wrap = True
    tf_pl.margin_top = tf_pl.margin_left = tf_pl.margin_right = Inches(0.25)
    p = tf_pl.paragraphs[0]
    p.text = "PL/SQL Analyzer (Packages, Triggers, Procs)"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = C_DARK

    for head, body in plsql_items:
        pb = tf_pl.add_paragraph()
        pb.text = "• " + head + ": "
        pb.font.size = Pt(10.5)
        pb.font.bold = True
        pb.font.color.rgb = C_BLUE
        pb.space_after = Pt(6)
        r = pb.add_run()
        r.text = body
        r.font.bold = False
        r.font.color.rgb = C_TEXT

    # Right Card: JCL
    card_jcl = create_card(s6, Inches(6.75), Inches(1.8), Inches(5.75), Inches(4.9))
    tf_jcl = card_jcl.text_frame
    tf_jcl.word_wrap = True
    tf_jcl.margin_top = tf_jcl.margin_left = tf_jcl.margin_right = Inches(0.25)
    p = tf_jcl.paragraphs[0]
    p.text = "JCL Analyzer (Job Streams & Cataloged PROCs)"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = C_DARK

    for head, body in jcl_items:
        pb = tf_jcl.add_paragraph()
        pb.text = "• " + head + ": "
        pb.font.size = Pt(10.5)
        pb.font.bold = True
        pb.font.color.rgb = C_CYAN
        pb.space_after = Pt(6)
        r = pb.add_run()
        r.text = body
        r.font.bold = False
        r.font.color.rgb = C_TEXT

    # ==========================================
    # SLIDE 7: Safety & Non-Intrusive Commenting
    # ==========================================
    s7 = prs.slides.add_slide(blank_layout)
    add_header(s7, "Non-Intrusive Commenting & Byte-Exact Round-Trip", "SAFETY & COMPLIANCE",
               "How the tool guarantees zero breakage of legacy compiler pipelines and production builds.")
    add_footer(s7, 7)

    safety_rules = [
        ("Column 7 & 72 Adherence",
         "Strict COBOL Layout",
         "COBOL fixed format comments place '*' strictly in column 7, keeping sequence numbers blank and code width <= 72. Compilers will never choke on comment overflow."),
        ("Self-Identifying Markers",
         "[AI] Line Signatures",
         "Every injected comment and continuation line begins with a dedicated [AI] tag (e.g. '*[AI]', '//*[AI]', '-- [AI]'). Easily grep-able and identifiable across large codebases."),
        ("Byte-Exact Reversibility",
         "strip() Exact Match",
         "Running 'python run.py strip <annotated_file>' strips every injected comment, restoring the original file bit-by-bit. Verified on all samples and both CRLF/LF line endings."),
        ("EBCDIC & ASCII Safety",
         "Character Folding",
         "Replaces Unicode arrows and characters with clean ASCII representations ('->', '<=', '!='). Prevents EBCDIC code page corruption during mainframe file transfers."),
        ("Protected In-Stream Data",
         "DFSORT Card Safety",
         "Guarantees that inline data cards (DD *, SYSIN, DFSORT control statements) are never broken or injected with comments, which would otherwise abend the batch job."),
        ("Preserved Newline Formats",
         "CRLF / LF Fidelity",
         "Detects the file's native line ending and preserves it upon export, preventing noisy diffs in enterprise Git and mainframe version control systems.")
    ]

    for i, (title, sub, desc) in enumerate(safety_rules):
        col = i % 3
        row = i // 3
        cx = Inches(0.8 + col * 4.0)
        cy = Inches(1.8 + row * 2.5)
        card = create_card(s7, cx, cy, Inches(3.733), Inches(2.3))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.2)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = sub
        p_sub.font.size = Pt(10.5)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_GREEN

        p_desc = tf.add_paragraph()
        p_desc.text = desc
        p_desc.font.size = Pt(10)
        p_desc.font.color.rgb = C_TEXT
        p_desc.space_before = Pt(4)

    # ==========================================
    # SLIDE 8: Developer Experience & Web UI
    # ==========================================
    s8 = prs.slides.add_slide(blank_layout)
    add_header(s8, "Interactive Developer UI & Workflow", "DEVELOPER WORKBENCH",
               "Designed for software engineers, migration architects, and domain SMEs.")
    add_footer(s8, 8)

    # Left: UI features list, Right: Step-by-step workflow
    ui_cards = [
        ("Interactive Code Viewer", "Line-by-line syntax view showing original source alongside toggleable inline AI comment boxes with badge indicators (Summary, Business Rule, Risk, IO)."),
        ("Filter by Kind & Level", "Switch between 'Essential' level (high-level summaries & risks) and 'Detailed' level (field-level mappings). Filter by specific tags (Warnings, Business Rules, DB)."),
        ("Explain This Selection", "Highlight any cryptic chunk of legacy code and click 'Explain' to receive an instant contextual breakdown of calculations, branch conditions, and unit dependencies."),
        ("Built-in User Guide", "Integrated searchable offline guide covering mainframe terminology, COBOL PIC layouts, navigation shortcuts, and validation workflows (press '?' anytime).")
    ]

    card_left = create_card(s8, Inches(0.8), Inches(1.8), Inches(5.75), Inches(4.9))
    tf_l = card_left.text_frame
    tf_l.word_wrap = True
    tf_l.margin_top = tf_l.margin_left = tf_l.margin_right = Inches(0.25)
    p = tf_l.paragraphs[0]
    p.text = "Developer Review Features"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = C_DARK

    for head, body in ui_cards:
        pb = tf_l.add_paragraph()
        pb.text = "• " + head + ": "
        pb.font.size = Pt(10.5)
        pb.font.bold = True
        pb.font.color.rgb = C_BLUE
        pb.space_after = Pt(6)
        r = pb.add_run()
        r.text = body
        r.font.bold = False
        r.font.color.rgb = C_TEXT

    # Right: The Review Lifecycle
    card_right = create_card(s8, Inches(6.75), Inches(1.8), Inches(5.75), Inches(4.9))
    tf_r = card_right.text_frame
    tf_r.word_wrap = True
    tf_r.margin_top = tf_r.margin_left = tf_r.margin_right = Inches(0.25)
    p = tf_r.paragraphs[0]
    p.text = "The Human-in-the-Loop Review Cycle"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = C_DARK

    steps = [
        ("1. Ingest", "Drag and drop source files or point the batch CLI at 'src/*.cbl'. Includes copybooks and cataloged procs."),
        ("2. Auto-Analyze", "Rule engine extracts data structures, control paths, formulas, and risks in milliseconds without internet."),
        ("3. SME Review", "Engineers review suggestions: Accept (A), Reject (R), or Edit (E) directly inline. Keyboard shortcuts enabled."),
        ("4. Audit & Export", "Export fully annotated source code, export KT markdown docs, or bundle an entire repository as a clean ZIP package.")
    ]

    for head, body in steps:
        pb = tf_r.add_paragraph()
        pb.text = head + "\n"
        pb.font.size = Pt(11)
        pb.font.bold = True
        pb.font.color.rgb = C_CYAN
        pb.space_before = Pt(6)
        r = pb.add_run()
        r.text = body
        r.font.size = Pt(10)
        r.font.bold = False
        r.font.color.rgb = C_TEXT

    # ==========================================
    # SLIDE 9: Cross-File System Map & Export
    # ==========================================
    s9 = prs.slides.add_slide(blank_layout)
    add_header(s9, "Cross-File System Map & Export Deliverables", "OUTPUT ARTIFACTS",
               "Beyond comments: generating comprehensive system topologies and knowledge transfer documents.")
    add_footer(s9, 9)

    export_artifacts = [
        ("Annotated Source Code",
         "Ready for Compiler & Repo",
         [
             "Generates <name>.annotated.<ext>.",
             "100% compiler-safe with validated column-72 boundaries.",
             "Contains accepted, reviewed, or AI-generated comments.",
             "Seamlessly round-tripped and stripped anytime."
         ]),
        ("Markdown KT Documentation",
         "Knowledge-Transfer Document",
         [
             "Outputs structured documentation (<name>.md).",
             "Includes business rules catalog, formulas, error codes.",
             "Data dictionary mapping COBOL PICs to Java types.",
             "Identifies modernization risks (truncation, GO TO)."
         ]),
        ("Cross-File System Map",
         "Multi-File Ecosystem Topology",
         [
             "Correlates JCL job steps to COBOL program binaries.",
             "Tracks dataset DD bindings and Generation Data Groups.",
             "Identifies shared relational tables across programs.",
             "Flags missing copybooks, PROCs, or orphaned steps."
         ]),
        ("JSON AST & ZIP Packages",
         "Tooling & Pipeline Integration",
         [
             "Export JSON AST containing call graphs, outline, & metrics.",
             "Export entire multi-file project as a structured ZIP.",
             "CLI batch automation: run.py annotate -o out/ --doc.",
             "Easily integrates into existing enterprise CI/CD pipelines."
         ])
    ]

    for i, (title, sub, bullets) in enumerate(export_artifacts):
        cx = Inches(0.8 + i * 2.95)
        card = create_card(s9, cx, Inches(1.8), Inches(2.8), Inches(4.9))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.2)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = sub
        p_sub.font.size = Pt(10)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_BLUE

        tf.add_paragraph()
        for b in bullets:
            pb = tf.add_paragraph()
            pb.text = "• " + b
            pb.font.size = Pt(9.5)
            pb.font.color.rgb = C_TEXT
            pb.space_after = Pt(5)

    # ==========================================
    # SLIDE 10: Validation Tooling & Quality Gates
    # ==========================================
    s10 = prs.slides.add_slide(blank_layout)
    add_header(s10, "Client Validation Tooling & Quality Gates", "ENTERPRISE ASSURANCE",
               "Automated gate checks, safe anonymization, and statistical SME review scoring.")
    add_footer(s10, 10)

    val_cards = [
        ("tools/anonymize.py",
         "Zero IP Leakage for Client Code",
         [
             "Reversible Pseudonymization: Replaces identifiers, literals, and comments with consistent pseudonyms.",
             "Preserves Exact Layout: Maintains character lengths so COBOL column positions and JCL limits never shift.",
             "Client-Retained Key: Secret mapping key stays on-premise with the client; vendors only see anonymized code."
         ]),
        ("Automated Quality Gates",
         "Strict Pre-Deployment Criteria",
         [
             "Gate 1: Zero crashes across all codebase files.",
             "Gate 2: 100% byte-exact reversibility (strip restores original).",
             "Gate 3: Zero column-72 or JCL margin overflow violations.",
             "Gate 4: Zero corruption of protected in-stream data cards.",
             "Gate 5: 100% header coverage across paragraphs & procedures."
         ]),
        ("tools/validate.py & SME Scoring",
         "Quantifiable Accuracy Scoring",
         [
             "SME Review Sheet: Automatically generates stratified CSV review sheets for domain engineers.",
             "Statistical Scoring: python tools/validate.py --score computes precision, recall, and 95% confidence intervals.",
             "Continuous Feedback Loop: Flagged inaccuracies directly feed grammar enhancements in vocab.py and analyzers."
         ])
    ]

    for i, (title, subtitle, bullets) in enumerate(val_cards):
        cx = Inches(0.8 + i * 4.0)
        card = create_card(s10, cx, Inches(1.8), Inches(3.733), Inches(4.9))
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = subtitle
        p_sub.font.size = Pt(10.5)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_ACCENT

        tf.add_paragraph()
        for b in bullets:
            head, body = b.split(": ", 1)
            pb = tf.add_paragraph()
            pb.text = "• " + head + ": "
            pb.font.size = Pt(10)
            pb.font.bold = True
            pb.font.color.rgb = C_NAVY
            pb.space_after = Pt(7)
            r = pb.add_run()
            r.text = body
            r.font.bold = False
            r.font.color.rgb = C_TEXT

    # ==========================================
    # SLIDE 11: Demonstrated Comprehension & Metrics
    # ==========================================
    s11 = prs.slides.add_slide(blank_layout)
    add_header(s11, "Demonstrated Evaluation & Comprehension Results", "EMPIRICAL PROOF",
               "Rigorous before-vs-after evaluation on synthetic enterprise legacy codebase.")
    add_footer(s11, 11)

    # 4 Big Metric Callouts across top
    metrics = [
        ("1/34 -> 34/34", "100% Question Answerability", "From comments alone (0/11 -> 11/11 in COBOL)"),
        ("1/11 -> 11/11", "100% Unit Header Coverage", "Every paragraph & procedure documented"),
        ("61 Tests Passing", "Zero-Regression Suite", "Tested on COBOL, PL/SQL, JCL, API & UI"),
        ("23 Rules & Risks", "Zero Migration Gotchas Missed", "Truncation, 88-levels, COMMIT inside loops")
    ]

    for i, (val, title, sub) in enumerate(metrics):
        cx = Inches(0.8 + i * 2.95)
        card = create_card(s11, cx, Inches(1.8), Inches(2.8), Inches(1.5), bg_color=C_NAVY)
        tf = card.text_frame
        tf.margin_top = Inches(0.15)
        tf.margin_left = Inches(0.15)
        p = tf.paragraphs[0]
        p.text = val
        p.font.size = Pt(18)
        p.font.bold = True
        p.font.color.rgb = RGBColor(96, 165, 250)
        p2 = tf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(10.5)
        p2.font.bold = True
        p2.font.color.rgb = C_WHITE
        p3 = tf.add_paragraph()
        p3.text = sub
        p3.font.size = Pt(8.5)
        p3.font.color.rgb = RGBColor(203, 213, 225)

    # Table of benchmark results
    table_card = create_card(s11, Inches(0.8), Inches(3.6), Inches(11.733), Inches(3.1), bg_color=C_WHITE)
    table_shape = s11.shapes.add_table(6, 6, Inches(1.0), Inches(3.8), Inches(11.333), Inches(2.7))
    t = table_shape.table
    headers = ["Program File", "Language", "Answerable Questions", "Comment Density", "Unit Headers Documented", "Surfaced Rules & Risks"]
    for j, h in enumerate(headers):
        cell = t.cell(0, j)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = C_CARD_BG
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(10)
            p.font.bold = True
            p.font.color.rgb = C_DARK

    rows_data = [
        ["PAYROLL.cbl", "COBOL Fixed", "0/11  ->  11/11 (100%)", "2%  ->  112%", "1/11  ->  11/11 (100%)", "7 Business Rules, 2 Risks"],
        ["loan_servicing.pkb", "PL/SQL Body", "0/10  ->  10/10 (100%)", "1%  ->  54%", "0/4   ->   4/4 (100%)", "7 Rules, 4 Critical Risks"],
        ["NIGHTPAY.jcl", "JCL Batch", "0/6   ->   6/6 (100%)", "9%  ->  128%", "0/4   ->   4/4 (100%)", "Step conds, DFSORT control"],
        ["CUSTRISK.cob", "COBOL Free", "0/3   ->   3/3 (100%)", "2%  ->  64%", "0/2   ->   2/2 (100%)", "3 Credit Rules, Db2 SQL"],
        ["EMPREC.cpy", "COBOL Copybook", "1/2   ->   2/2 (100%)", "5%  ->  119%", "Data layout complete", "4 88-level condition sets"]
    ]
    for r_idx, row in enumerate(rows_data):
        for c_idx, val in enumerate(row):
            cell = t.cell(r_idx + 1, c_idx)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = C_WHITE if r_idx % 2 == 0 else C_BG
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(9.5)
                p.font.color.rgb = C_TEXT

    # ==========================================
    # SLIDE 12: Business Value & Summary
    # ==========================================
    s12 = prs.slides.add_slide(blank_layout)
    add_header(s12, "Business Value & Modernization Impact", "EXECUTIVE SUMMARY",
               "Why Legacy Code Commenter delivers immediate ROI for enterprise modernization programs.")
    add_footer(s12, 12)

    val_pillars = [
        ("Accelerates Migration Timelines",
         "Weeks to Days",
         "Cuts code reverse-engineering time by 60-80%. Developers instantly understand business rules and file dependencies without relying on unavailable legacy SMEs."),
        ("De-Risks Cloud Replatforming",
         "Zero Missed Gotchas",
         "Proactively surfaces critical migration risks: arithmetic truncation, 88-level data conditions, autonomous transactions, dynamic SQL injection, and JCL COND logic."),
        ("Zero IP & Compliance Risk",
         "100% Air-Gapped",
         "Zero third-party cloud dependencies, strict Content-Security-Policy, and literal masking. Safe for regulated banking, defense, healthcare, and utility environments."),
        ("Seamless Adoption & Tooling",
         "Zero Package Approvals",
         "Python standard library only; runs anywhere with zero installation friction. Supports both interactive browser review and high-throughput CLI batch pipelines.")
    ]

    for i, (title, highlight, desc) in enumerate(val_pillars):
        col = i % 2
        row = i // 2
        cx = Inches(0.8 + col * 5.95)
        cy = Inches(1.8 + row * 2.5)
        card = create_card(s12, cx, cy, Inches(5.75), Inches(2.3), bg_color=C_CARD_BG)
        tf = card.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_left = tf.margin_right = Inches(0.25)
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(15)
        p.font.bold = True
        p.font.color.rgb = C_DARK

        p_sub = tf.add_paragraph()
        p_sub.text = highlight
        p_sub.font.size = Pt(11)
        p_sub.font.bold = True
        p_sub.font.color.rgb = C_BLUE

        p_desc = tf.add_paragraph()
        p_desc.text = desc
        p_desc.font.size = Pt(11)
        p_desc.font.color.rgb = C_TEXT
        p_desc.space_before = Pt(6)

    prs.save(output_path)
    print(f"Successfully generated {output_path} with {len(prs.slides)} slides.")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "Legacy_Code_Commenter_Presentation.pptx"
    create_presentation(out)
