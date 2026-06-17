import html
import json
import sys
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent))

API = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Agentic Financial Document Audit Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Force sidebar always open — click the expand button if it's collapsed
components.html("""
<script>
(function expandSidebar() {
    function tryExpand() {
        var btn = window.parent.document.querySelector('[data-testid="collapsedControl"] button');
        if (!btn) btn = window.parent.document.querySelector('[data-testid="collapsedControl"]');
        if (btn) { btn.click(); return; }
        // If sidebar already open nothing happens; retry once in case DOM not ready
    }
    tryExpand();
    setTimeout(tryExpand, 600);
})();
</script>
""", height=0)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {display: none !important;}
/* Prevent Streamlit from dimming the page during reruns/indexing */
[data-stale], [data-stale="true"] { opacity: 1 !important; transition: none !important; }
[data-testid="stApp"] { opacity: 1 !important; }
.main, .main * { opacity: 1 !important; }
div[data-testid="stDecoration"] { display: none !important; }
/* Force sidebar always visible */
[data-testid="stSidebar"],
section[data-testid="stSidebar"] {
    display: block !important;
    visibility: visible !important;
    transform: none !important;
    left: 0 !important;
    width: 21rem !important;
    min-width: 21rem !important;
    z-index: 100 !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }
.block-container { padding: 0 2.5rem 3rem 2.5rem; max-width: 1400px; }

/* ── Tabs — make inactive tabs readable on white ── */
[data-baseweb="tab-list"] { border-bottom: 2px solid #e2e8f0 !important; gap: .4rem; }
[data-baseweb="tab"] {
    color: #475569 !important; font-weight: 500 !important;
    font-size: .88rem !important; padding: .55rem 1rem !important;
}
[data-baseweb="tab"]:hover { color: #1d4ed8 !important; background: #eff6ff !important; border-radius: 8px 8px 0 0; }
[aria-selected="true"][data-baseweb="tab"] { color: #1d4ed8 !important; font-weight: 700 !important; }

/* ── Hero ── */
.hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 60%, #1d4ed8 100%);
    border-radius: 16px; padding: 2.2rem 2.8rem;
    margin: 1.2rem 0 1.8rem 0; position: relative; overflow: hidden;
}
.hero::before {
    content: ''; position: absolute; top: -60px; right: -60px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(99,179,237,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.hero-title  { font-size:1.75rem; font-weight:800; color:#fff; margin:0 0 .35rem 0; letter-spacing:-.3px; }
.hero-sub    { color:#93c5fd; font-size:.84rem; font-weight:400; margin:0; letter-spacing:.2px; }
.hero-badges { display:flex; gap:.6rem; margin-top:1.1rem; flex-wrap:wrap; }
.badge {
    background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.18);
    color:#e0f2fe; font-size:.72rem; font-weight:500;
    padding:.25rem .7rem; border-radius:20px; backdrop-filter:blur(4px);
}

/* ── Sidebar ── */
[data-testid="stSidebar"] { background:#0f172a !important; border-right:1px solid #1e293b; }
[data-testid="stSidebar"] * { color:#cbd5e1 !important; }
[data-testid="stSidebar"] .sidebar-section-title {
    color:#94a3b8 !important; font-size:.7rem; font-weight:600;
    letter-spacing:.08em; text-transform:uppercase; margin:1.4rem 0 .6rem 0;
}
[data-testid="stSidebar"] .doc-chip {
    background:#1e293b; border:1px solid #334155; border-radius:8px;
    padding:.45rem .8rem; font-size:.78rem; color:#60a5fa !important;
    margin:.25rem 0; display:flex; align-items:center; gap:.4rem;
}
.node-list { background:#1e293b; border-radius:10px; padding:.9rem 1rem; margin-top:.5rem; }
.node-item { display:flex; align-items:center; gap:.5rem; font-size:.78rem; color:#94a3b8 !important; padding:.28rem 0; }
.node-num {
    background:#334155; color:#60a5fa !important; border-radius:50%;
    width:18px; height:18px; display:inline-flex; align-items:center;
    justify-content:center; font-size:.65rem; font-weight:700; flex-shrink:0;
}

/* ── Pipeline steps ── */
.pipeline-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:.7rem; margin:1rem 0 1.4rem 0; }
.step-card { border-radius:12px; padding:.85rem .9rem; text-align:center; transition:all .3s ease; }
.step-wait { background:#f8fafc; border:1.5px solid #e2e8f0; color:#94a3b8; }
.step-run  {
    background:linear-gradient(135deg,#eff6ff,#dbeafe); border:1.5px solid #93c5fd;
    color:#1d4ed8; box-shadow:0 0 0 3px rgba(59,130,246,.12);
    animation:glow 1.4s ease-in-out infinite;
}
.step-done {
    background:linear-gradient(135deg,#f0fdf4,#dcfce7); border:1.5px solid #86efac;
    color:#15803d; box-shadow:0 2px 8px rgba(22,163,74,.12);
}
.step-flag {
    background:linear-gradient(135deg,#fff7ed,#fed7aa); border:1.5px solid #fb923c;
    color:#c2410c; box-shadow:0 2px 8px rgba(234,88,12,.12);
}
@keyframes glow {
    0%,100% { box-shadow:0 0 0 3px rgba(59,130,246,.12); }
    50%      { box-shadow:0 0 0 6px rgba(59,130,246,.22); }
}
.step-icon   { font-size:1.2rem; margin-bottom:.3rem; }
.step-label  { font-size:.75rem; font-weight:600; letter-spacing:.01em; }
.step-detail { font-size:.68rem; margin-top:.2rem; opacity:.85; }

/* ── Metric cards ── */
.metrics-row { display:grid; grid-template-columns:repeat(4,1fr); gap:1rem; margin:1.2rem 0; }
.metric-card {
    background:#fff; border:1px solid #e2e8f0; border-radius:14px;
    padding:1.2rem 1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.05),0 4px 12px rgba(0,0,0,.04);
    text-align:center;
}
.metric-label { font-size:.72rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:.06em; margin-bottom:.4rem; }
.metric-value { font-size:2.2rem; font-weight:800; color:#0f172a; line-height:1; }
.metric-icon  { font-size:1.1rem; margin-bottom:.3rem; }

/* ── Memo ── */
.memo-wrapper {
    background:#fff; border:1px solid #e2e8f0; border-radius:16px;
    padding:2rem 2.4rem; box-shadow:0 2px 6px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.04);
    margin-top:1.2rem;
}
.memo-header {
    display:flex; align-items:center; gap:.6rem; margin-bottom:1.6rem;
    padding-bottom:1rem; border-bottom:1px solid #f1f5f9;
}
.memo-title { font-size:1.25rem; font-weight:700; color:#0f172a; }
.memo-stamp {
    background:#dbeafe; color:#1d4ed8; font-size:.68rem; font-weight:700;
    padding:.2rem .6rem; border-radius:6px; text-transform:uppercase; letter-spacing:.05em;
}
.section-label {
    font-size:.68rem; font-weight:700; text-transform:uppercase;
    letter-spacing:.08em; color:#94a3b8; margin:1.6rem 0 .6rem 0;
}
.exec-card {
    background:linear-gradient(135deg,#f0f7ff 0%,#e8f4fd 100%);
    border-left:4px solid #2563eb; border-radius:0 12px 12px 0;
    padding:1.1rem 1.5rem; font-size:.93rem; line-height:1.7; color:#1e293b;
}
.finding-item {
    display:flex; gap:.7rem; align-items:flex-start; padding:.6rem 0;
    border-bottom:1px solid #f8fafc; font-size:.88rem; color:#334155; line-height:1.5;
}
.finding-dot { width:6px; height:6px; background:#2563eb; border-radius:50%; margin-top:.5rem; flex-shrink:0; }
.warn-card {
    background:linear-gradient(135deg,#fffbeb,#fef3c7);
    border:1px solid #fde68a; border-left:4px solid #f59e0b;
    border-radius:0 12px 12px 0; padding:.9rem 1.3rem; margin:.5rem 0;
    font-size:.87rem; color:#78350f; line-height:1.5;
}
.ok-card {
    background:linear-gradient(135deg,#f0fdf4,#dcfce7); border:1px solid #86efac;
    border-radius:12px; padding:.8rem 1.2rem; font-size:.87rem; color:#14532d;
    display:flex; align-items:center; gap:.5rem;
}

/* ── Citations ── */
.cite-table { width:100%; border-collapse:collapse; font-size:.81rem; margin-top:.5rem; }
.cite-table th {
    background:#f8fafc; color:#64748b; font-size:.7rem; font-weight:600;
    text-transform:uppercase; letter-spacing:.05em; padding:.6rem .9rem;
    text-align:left; border-bottom:1px solid #e2e8f0;
}
.cite-table td { padding:.65rem .9rem; border-bottom:1px solid #f1f5f9; color:#334155; vertical-align:top; }
.cite-table tr:hover td { background:#f8fafc; }
.conf-pill { display:inline-block; padding:.15rem .5rem; border-radius:20px; font-size:.7rem; font-weight:600; }
.conf-high { background:#dcfce7; color:#15803d; }
.conf-med  { background:#fef9c3; color:#854d0e; }
.conf-low  { background:#fee2e2; color:#b91c1c; }

/* ── Review queue tab ── */
.rq-stats {
    display:grid; grid-template-columns:repeat(3,1fr); gap:1rem; margin-bottom:1.4rem;
}
.rq-stat {
    border-radius:14px; padding:1.1rem 1.4rem; text-align:center;
    border:1px solid #e2e8f0; background:#fff;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
}
.rq-stat-pending  { border-top:3px solid #f59e0b; }
.rq-stat-approved { border-top:3px solid #22c55e; }
.rq-stat-rejected { border-top:3px solid #ef4444; }
.rq-stat-num  { font-size:2rem; font-weight:800; color:#0f172a; }
.rq-stat-lbl  { font-size:.7rem; font-weight:600; text-transform:uppercase; letter-spacing:.06em; color:#64748b; margin-top:.2rem; }

.rq-card {
    background:#fff; border:1px solid #e2e8f0; border-radius:14px;
    padding:1.4rem 1.6rem; margin-bottom:1rem;
    box-shadow:0 1px 3px rgba(0,0,0,.05),0 4px 12px rgba(0,0,0,.03);
    border-left:4px solid #f59e0b;
}
.rq-card-meta {
    display:flex; gap:.6rem; align-items:center; flex-wrap:wrap; margin-bottom:.8rem;
}
.rq-badge-flag {
    background:#fff7ed; color:#c2410c; border:1px solid #fed7aa;
    font-size:.68rem; font-weight:600; padding:.18rem .55rem; border-radius:20px;
}
.rq-badge-conf {
    background:#f1f5f9; color:#475569;
    font-size:.68rem; font-weight:600; padding:.18rem .55rem; border-radius:20px;
}
.rq-badge-src {
    background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;
    font-size:.68rem; font-weight:600; padding:.18rem .55rem; border-radius:20px;
}
.rq-claim { font-size:.9rem; color:#1e293b; line-height:1.6; margin-bottom:.9rem; }
.rq-empty {
    text-align:center; padding:3rem; color:#94a3b8;
    background:#f8fafc; border-radius:14px; border:1px dashed #e2e8f0;
}

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {
    border-bottom:1px solid #e2e8f0; padding-bottom:0;
}
[data-testid="stTabs"] button[role="tab"] {
    font-size:.85rem; font-weight:600; color:#64748b;
    padding:.6rem 1.2rem; border-radius:8px 8px 0 0;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color:#1d4ed8 !important; border-bottom:2px solid #1d4ed8 !important;
    background:#eff6ff;
}

/* ── Overrides ── */
[data-testid="stTextInput"] input {
    border:1.5px solid #e2e8f0 !important; border-radius:10px !important;
    font-size:.88rem !important; padding:.6rem .9rem !important;
    background:#fff !important; color:#0f172a !important;
}
[data-testid="stTextInput"] input:focus {
    border-color:#2563eb !important; box-shadow:0 0 0 3px rgba(37,99,235,.1) !important;
}
[data-testid="stFileUploader"] {
    border:1.5px dashed #cbd5e1 !important; border-radius:10px !important;
    background:#1e293b !important;
}
[data-testid="stBaseButton-primary"] {
    background:linear-gradient(135deg,#1d4ed8,#2563eb) !important;
    border:none !important; border-radius:10px !important;
    font-weight:600 !important; font-size:.88rem !important;
    padding:.55rem 1.4rem !important; box-shadow:0 2px 8px rgba(37,99,235,.35) !important;
    transition:all .2s !important;
}
[data-testid="stBaseButton-primary"]:hover {
    transform:translateY(-1px) !important; box-shadow:0 4px 14px rgba(37,99,235,.45) !important;
}
[data-testid="stExpander"] {
    border:1px solid #e2e8f0 !important; border-radius:12px !important;
    background:#fff !important; outline:none !important; box-shadow:none !important;
}
[data-testid="stExpander"]:focus-within { border-color:#e2e8f0 !important; box-shadow:none !important; }
[data-testid="stExpander"] summary:focus { outline:none !important; box-shadow:none !important; }
div[data-testid="stMetricValue"] { display:none; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:1.2rem 0 .5rem 0;">
        <div style="font-size:1.1rem;font-weight:700;color:#f8fafc;letter-spacing:-.2px;">
            FinAudit <span style="color:#60a5fa;">AI</span>
        </div>
        <div style="font-size:.7rem;color:#475569;margin-top:.2rem;">Document Intelligence Platform</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-title">Upload Document</div>', unsafe_allow_html=True)
    uploaded   = st.file_uploader("PDF", type="pdf", label_visibility="collapsed")
    manual_path = st.text_input("or path", placeholder="data/aapl_10k_2023.pdf", label_visibility="collapsed")

    if st.button("Index Document", use_container_width=True, type="primary"):
        target_path = None
        if uploaded:
            save_path = Path("data") / uploaded.name
            save_path.parent.mkdir(exist_ok=True)
            save_path.write_bytes(uploaded.read())
            target_path = str(save_path)
        elif manual_path.strip():
            target_path = manual_path.strip()

        if target_path:
            with st.spinner("Parsing & indexing…"):
                try:
                    r = requests.post(f"{API}/index", json={"doc_paths": [target_path]}, timeout=180)
                    r.raise_for_status()
                    data = r.json()
                    st.session_state.setdefault("indexed", [])
                    for doc_id in data["indexed_doc_ids"]:
                        if doc_id not in st.session_state["indexed"]:
                            st.session_state["indexed"].append(doc_id)
                    tbl = data.get("total_table_records", 0)
                    st.success(f"{data['total_chunks']} chunks · {tbl} table records indexed")
                except Exception as e:
                    st.error(str(e))
        else:
            st.warning("Upload a file or enter a path.")

    if st.session_state.get("indexed"):
        st.markdown('<div class="sidebar-section-title">Indexed Documents</div>', unsafe_allow_html=True)
        for d in st.session_state["indexed"]:
            st.markdown(f'<div class="doc-chip">📄 {d}</div>', unsafe_allow_html=True)

        # ── Extracted financial tables viewer ──────────────────────────────
        st.markdown('<div class="sidebar-section-title">Extracted Tables</div>', unsafe_allow_html=True)
        selected_doc = st.session_state["indexed"][0] if len(st.session_state["indexed"]) == 1 \
            else st.selectbox("Document", st.session_state["indexed"], label_visibility="collapsed")
        year_filter = st.selectbox("Year", ["All", "2023", "2022", "2021"], label_visibility="collapsed")
        if st.button("View Table Records", use_container_width=True):
            try:
                params = {"year": int(year_filter)} if year_filter != "All" else {}
                resp = requests.get(f"{API}/tables/{selected_doc}", params=params, timeout=10)
                rows = resp.json() if resp.ok else []
                if rows:
                    import pandas as pd
                    df = pd.DataFrame(rows)[["line_item", "value", "year", "table_type", "source_page"]]
                    df.columns = ["Line Item", "Value (M)", "Year", "Type", "Page"]
                    st.dataframe(df, width="stretch", height=300)
                    st.caption(f"{len(rows)} records")
                else:
                    st.info("No table records found. Re-index to extract tables.")
            except Exception as e:
                st.error(str(e))

    st.markdown('<div class="sidebar-section-title">LangGraph Agents</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="node-list">
        <div class="node-item">
            <span class="node-num" style="background:#1e3a5f;color:#93c5fd !important;">1</span>
            <span style="color:#94a3b8 !important;">Hybrid Retriever</span>
            <span style="margin-left:auto;font-size:.6rem;color:#475569 !important;">BM25 + ChromaDB</span>
        </div>
        <div class="node-item" style="border-left:2px solid #3b82f6;margin-left:.4rem;padding-left:.6rem;">
            <span class="node-num" style="background:#1d4ed8;color:#fff !important;">2</span>
            <span style="color:#93c5fd !important;font-weight:600;">Evidence Extractor</span>
            <span style="margin-left:auto;font-size:.6rem;color:#60a5fa !important;">Agent</span>
        </div>
        <div class="node-item" style="border-left:2px solid #3b82f6;margin-left:.4rem;padding-left:.6rem;">
            <span class="node-num" style="background:#1d4ed8;color:#fff !important;">3</span>
            <span style="color:#93c5fd !important;font-weight:600;">Cross-Verifier</span>
            <span style="margin-left:auto;font-size:.6rem;color:#60a5fa !important;">Agent</span>
        </div>
        <div class="node-item">
            <span class="node-num" style="background:#78350f;color:#fef3c7 !important;">4</span>
            <span style="color:#94a3b8 !important;">Review Gate</span>
            <span style="margin-left:auto;font-size:.6rem;color:#475569 !important;">HITL</span>
        </div>
        <div class="node-item" style="border-left:2px solid #3b82f6;margin-left:.4rem;padding-left:.6rem;">
            <span class="node-num" style="background:#1d4ed8;color:#fff !important;">5</span>
            <span style="color:#93c5fd !important;font-weight:600;">Memo Generator</span>
            <span style="margin-left:auto;font-size:.6rem;color:#60a5fa !important;">Agent</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="margin-top:1.4rem;padding:.8rem;background:#1e293b;border-radius:10px;
                border:1px solid #334155;font-size:.72rem;color:#64748b;line-height:1.6;">
        <div style="color:#94a3b8;font-weight:600;margin-bottom:.3rem;">Stack</div>
        LangGraph &middot; BM25 + ChromaDB<br>
        Groq llama-3.1-8b / 3.3-70b<br>
        pdfplumber &middot; sentence-transformers<br>
        FastAPI SSE &middot; SQLite
    </div>
    """, unsafe_allow_html=True)


# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
    <div class="hero-title">Agentic Financial Document Audit Assistant</div>
    <div class="hero-sub">
        Multi-agent LangGraph pipeline &nbsp;·&nbsp; Hybrid RAG retrieval &nbsp;·&nbsp;
        Structured table extraction &nbsp;·&nbsp; Two-tier verification (table → LLM) &nbsp;·&nbsp;
        Human-in-the-loop review
    </div>
    <div class="hero-badges">
        <span class="badge">LangGraph 1.2</span>
        <span class="badge">BM25 + ChromaDB</span>
        <span class="badge">Groq llama-3.1-8b / 3.3-70b</span>
        <span class="badge">Structured Table Extraction</span>
        <span class="badge">FastAPI SSE</span>
        <span class="badge">Human Review Queue</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_audit, tab_review, tab_eval = st.tabs(["📋  Audit", "🔍  Review Queue", "📊  Evaluation"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — AUDIT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_audit:
    col_q, col_d, col_btn = st.columns([5, 2, 1])
    with col_q:
        question = st.text_input(
            "q", label_visibility="collapsed",
            value="What was Apple's total net revenue for fiscal year 2023?",
            placeholder="Ask an audit question about your financial document…",
        )
    with col_d:
        doc_ids_raw = st.text_input(
            "d", label_visibility="collapsed",
            value=", ".join(st.session_state.get("indexed", ["aapl-20230930"])),
            placeholder="doc-id, doc-id2",
        )
    with col_btn:
        run = st.button("Run Audit", type="primary", use_container_width=True)

    st.markdown("<div style='height:.2rem'></div>", unsafe_allow_html=True)

    if run:
        if not question.strip():
            st.warning("Enter an audit question first.")
            st.stop()

        # Quick health-check to surface "not indexed" before burning LLM tokens
        try:
            h = requests.get(f"{API}/health", timeout=3)
            if not h.ok:
                st.error("API server not reachable.")
                st.stop()
        except Exception:
            st.error("API server not reachable — start uvicorn first.")
            st.stop()

        doc_ids = [d.strip() for d in doc_ids_raw.split(",") if d.strip()]

        steps = [
            ("🔍", "Retrieval",     "BM25 + ChromaDB"),
            ("🧠", "Evidence",      "Claim extraction"),
            ("⚖️",  "Verification",  "Consistency check"),
            ("🚦", "Review Gate",   "Confidence filter"),
            ("📝", "Memo",          "Report generation"),
        ]

        pipeline_ph = st.empty()

        def render_pipeline(states: list[str], details: list[str]):
            css_map = {"wait": "step-wait", "run": "step-run",
                       "done": "step-done", "flag": "step-flag"}
            cards = ""
            for (icon, label, sub), state, detail in zip(steps, states, details):
                css = css_map[state]
                spin = " …" if state == "run" else ""
                cards += f"""
                <div class="step-card {css}">
                    <div class="step-icon">{icon}</div>
                    <div class="step-label">{label}{spin}</div>
                    <div class="step-detail">{detail if state in ('done','flag') else sub}</div>
                </div>"""
            pipeline_ph.markdown(
                f'<div class="pipeline-grid">{cards}</div>',
                unsafe_allow_html=True,
            )

        step_states  = ["wait", "wait", "wait", "wait", "wait"]
        step_details = ["", "", "", "", ""]
        render_pipeline(step_states, step_details)

        metrics_ph = st.empty()
        memo_ph    = st.empty()
        counts = {"chunks": 0, "claims": 0, "verifications": 0,
                  "structured": 0, "llm_fallback": 0, "approved": 0, "pending": 0}
        memo   = None

        step_states[0] = "run"
        render_pipeline(step_states, step_details)

        try:
            with requests.post(
                f"{API}/audit/stream",
                json={"question": question, "doc_ids": doc_ids},
                stream=True, timeout=300,
            ) as resp:
                if not resp.ok:
                    st.error(f"API error {resp.status_code}: {resp.text}")
                    st.stop()

                for raw in resp.iter_lines():
                    if not raw or not raw.startswith(b"data: "):
                        continue
                    event = json.loads(raw[6:])
                    node  = event.get("node")

                    if node == "retrieval":
                        counts["chunks"] = event["chunks"]
                        step_states[0]   = "done"
                        step_details[0]  = f"{counts['chunks']} chunks"
                        step_states[1]   = "run"
                        render_pipeline(step_states, step_details)
                        if counts["chunks"] == 0:
                            st.warning(
                                "Retrieval returned 0 chunks — the document is not indexed. "
                                "Re-index it from the sidebar (the index is lost on server restart)."
                            )
                            st.stop()

                    elif node == "evidence_extractor":
                        counts["claims"] = event["claims"]
                        step_states[1]   = "done"
                        step_details[1]  = f"{counts['claims']} claims"
                        if counts["claims"] > 0:
                            step_states[2] = "run"
                        else:
                            # no claims → cross_verifier is skipped by conditional edge
                            step_states[2] = "done"
                            step_details[2] = "skipped (no claims)"
                            step_states[3] = "run"
                        render_pipeline(step_states, step_details)

                    elif node == "cross_verifier":
                        counts["verifications"] = event["verifications"]
                        counts["structured"]    = event.get("structured", 0)
                        counts["llm_fallback"]  = event.get("llm_fallback", 0)
                        step_states[2]  = "done"
                        n = counts["verifications"]
                        s = counts["structured"]
                        detail = f"{n} check{'s' if n!=1 else ''}"
                        if s > 0:
                            detail += f" · {s} structured"
                        step_details[2] = detail
                        step_states[3]  = "run"
                        render_pipeline(step_states, step_details)

                    elif node == "review_gate":
                        counts["approved"] = event["approved"]
                        counts["pending"]  = event["pending"]
                        if counts["pending"] > 0:
                            step_states[3]  = "flag"
                            step_details[3] = f"{counts['approved']} ok · {counts['pending']} flagged"
                        else:
                            step_states[3]  = "done"
                            step_details[3] = f"all {counts['approved']} approved"
                        step_states[4]  = "run"
                        render_pipeline(step_states, step_details)

                    elif node == "memo_generator":
                        memo = event["memo"]
                        step_states[4]  = "done"
                        step_details[4] = "Memo ready"
                        render_pipeline(step_states, step_details)

                    elif node == "rate_limit":
                        st.warning(f"⏳ {event.get('message')}\n\n"
                                   "**Quick fix:** edit `.env`, uncomment "
                                   "`LLM_MODEL=llama-3.1-8b-instant`, restart the server.")
                        st.stop()

                    elif node == "error":
                        st.error(f"Pipeline error: {event.get('message')}")
                        st.stop()

        except Exception as e:
            st.error(f"Request failed: {e}")
            st.stop()

        if memo is None:
            st.error("Pipeline produced no memo.")
            st.stop()

        # ── Metrics row ──
        pending_badge = ""
        if counts["pending"] > 0:
            pending_badge = f'<span style="font-size:.65rem;background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;padding:.1rem .45rem;border-radius:20px;font-weight:600;margin-left:.4rem;">+{counts["pending"]} in review</span>'

        with metrics_ph.container():
            st.markdown(f"""
            <div class="metrics-row">
                <div class="metric-card">
                    <div class="metric-icon">📄</div>
                    <div class="metric-label">Chunks Retrieved</div>
                    <div class="metric-value">{counts['chunks']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">🔎</div>
                    <div class="metric-label">Claims Extracted</div>
                    <div class="metric-value">{counts['claims']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">⚖️</div>
                    <div class="metric-label">Cross-Checks</div>
                    <div class="metric-value">{counts['verifications']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-icon">🚦</div>
                    <div class="metric-label">Auto-Approved{pending_badge}</div>
                    <div class="metric-value">{counts['approved']}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ── Pending review banner ──
        if counts["pending"] > 0:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#fff7ed,#ffedd5);
                        border:1px solid #fed7aa; border-left:4px solid #f59e0b;
                        border-radius:0 12px 12px 0; padding:.9rem 1.3rem; margin:.5rem 0 1rem 0;
                        font-size:.88rem; color:#92400e; display:flex; align-items:center; gap:.7rem;">
                ⚠️&nbsp; <strong>{counts['pending']} claim(s)</strong> routed to human review
                (low confidence or inconsistency detected). Switch to the
                <strong>Review Queue</strong> tab to approve or reject them.
            </div>
            """, unsafe_allow_html=True)

        # ── Memo ──
        exec_summary = html.escape(memo["executive_summary"])
        findings_html = "".join(
            f'<div class="finding-item"><div class="finding-dot"></div>'
            f'<div>{html.escape(f)}</div></div>'
            for f in memo["findings"]
        )
        issues = memo.get("flagged_inconsistencies", [])
        if issues:
            def _issue_card(text: str) -> str:
                if "extracted table data" in text.lower() or "financial_records" in text.lower() or "table=" in text:
                    badge = ('<span style="background:#dcfce7;color:#166534;border:1px solid #86efac;'
                             'font-size:.68rem;font-weight:700;padding:.1rem .45rem;border-radius:20px;'
                             'margin-right:.5rem;vertical-align:middle;">STRUCTURED ✓</span>')
                elif "[llm]" in text.lower():
                    badge = ('<span style="background:#eff6ff;color:#1d4ed8;border:1px solid #93c5fd;'
                             'font-size:.68rem;font-weight:700;padding:.1rem .45rem;border-radius:20px;'
                             'margin-right:.5rem;vertical-align:middle;">LLM</span>')
                else:
                    badge = ""
                clean = text.replace("[STRUCTURED]", "").replace("[LLM]", "").strip()
                return f'<div class="warn-card">{badge}&#9888;&nbsp; {html.escape(clean)}</div>'
            issues_html = "".join(_issue_card(i) for i in issues)
            issues_section = f'<div class="section-label">Flagged Inconsistencies</div>{issues_html}'
        else:
            issues_section = """
            <div class="section-label">Consistency Check</div>
            <div class="ok-card">&#10003;&nbsp; No inconsistencies detected across document sections.</div>
            """

        cit_rows = ""
        for i, c in enumerate(memo["citations"], 1):
            conf = c["confidence"]
            pill_cls = "conf-high" if conf >= 0.8 else ("conf-med" if conf >= 0.5 else "conf-low")
            pill = f'<span class="conf-pill {pill_cls}">{conf:.0%}</span>'
            claim_short = html.escape(c["claim"][:140] + ("…" if len(c["claim"]) > 140 else ""))
            cit_rows += f"""
            <tr>
                <td style="color:#64748b;font-weight:600">[{i}]</td>
                <td><code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;
                    font-size:.75rem">{html.escape(c['source_doc'])}</code></td>
                <td style="font-weight:600">p.{c['source_page']}</td>
                <td>{pill}</td>
                <td style="color:#475569">{claim_short}</td>
            </tr>"""

        with memo_ph.container():
            st.markdown(f"""
            <div class="memo-wrapper">
                <div class="memo-header">
                    <span style="font-size:1.3rem">📋</span>
                    <span class="memo-title">Audit Memo</span>
                    <span class="memo-stamp">Confidential</span>
                </div>
                <div class="section-label">Executive Summary</div>
                <div class="exec-card">{exec_summary}</div>
                <div class="section-label">Key Findings</div>
                {findings_html}
                {issues_section}
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"Citations  ({len(memo['citations'])})"):
                st.markdown(f"""
                <table class="cite-table">
                    <thead><tr>
                        <th>#</th><th>Document</th><th>Page</th><th>Confidence</th><th>Claim</th>
                    </tr></thead>
                    <tbody>{cit_rows}</tbody>
                </table>
                """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — REVIEW QUEUE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_review:
    col_hdr, col_refresh = st.columns([5, 1])
    with col_hdr:
        st.markdown("""
        <div style="margin:.8rem 0 .4rem 0;">
            <div style="font-size:1.15rem;font-weight:700;color:#0f172a;">Human Review Queue</div>
            <div style="font-size:.8rem;color:#64748b;margin-top:.2rem;">
                Claims flagged for low confidence or cross-verification inconsistencies.
                Approve to include in the final memo · Reject to discard.
            </div>
        </div>
        """, unsafe_allow_html=True)
    with col_refresh:
        refresh = st.button("Refresh", use_container_width=True)

    # Stats
    try:
        stats_resp = requests.get(f"{API}/review/stats", timeout=5)
        stats = stats_resp.json() if stats_resp.ok else {"total": 0, "pending": 0, "approved": 0, "rejected": 0}
    except Exception:
        stats = {"total": 0, "pending": 0, "approved": 0, "rejected": 0}

    st.markdown(f"""
    <div class="rq-stats">
        <div class="rq-stat rq-stat-pending">
            <div class="rq-stat-num">{stats['pending']}</div>
            <div class="rq-stat-lbl">Pending Review</div>
        </div>
        <div class="rq-stat rq-stat-approved">
            <div class="rq-stat-num">{stats['approved']}</div>
            <div class="rq-stat-lbl">Approved</div>
        </div>
        <div class="rq-stat rq-stat-rejected">
            <div class="rq-stat-num">{stats['rejected']}</div>
            <div class="rq-stat-lbl">Rejected</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Fetch pending items
    try:
        items_resp = requests.get(f"{API}/review/pending", timeout=5)
        items = items_resp.json() if items_resp.ok else []
    except Exception:
        items = []
        st.error("Cannot reach API — is the server running?")

    if not items:
        st.markdown("""
        <div class="rq-empty">
            <div style="font-size:2rem;margin-bottom:.5rem;">✅</div>
            <div style="font-size:.95rem;font-weight:600;color:#475569;">No pending items</div>
            <div style="font-size:.8rem;margin-top:.3rem;">
                Run an audit — claims with confidence &lt; 0.8 or flagged inconsistencies appear here.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:.78rem;color:#64748b;margin-bottom:.8rem;'>"
                    f"{len(items)} item(s) awaiting review</div>", unsafe_allow_html=True)

        for item in items:
            item_id   = item["id"]
            claim     = item["claim"]
            conf      = item["confidence"]
            flag      = item["flag_reason"].replace("_", " ")
            src_doc   = item["source_doc"]
            src_page  = item["source_page"]
            session   = item.get("session_id", "")

            flag_label = {"low confidence": "Low Confidence",
                          "inconsistency flagged": "Inconsistency",
                          "both": "Low Conf + Inconsistency"}.get(flag, flag.title())

            st.markdown(f"""
            <div class="rq-card">
                <div class="rq-card-meta">
                    <span class="rq-badge-flag">⚑ {flag_label}</span>
                    <span class="rq-badge-conf">conf {conf:.0%}</span>
                    <span class="rq-badge-src">📄 {html.escape(src_doc)} · p.{src_page}</span>
                    <span style="font-size:.65rem;color:#94a3b8;margin-left:auto;">ID #{item_id}</span>
                </div>
                <div class="rq-claim">{html.escape(claim)}</div>
            </div>
            """, unsafe_allow_html=True)

            note_key    = f"note_{item_id}"
            approve_key = f"approve_{item_id}"
            reject_key  = f"reject_{item_id}"

            note = st.text_input(
                f"Reviewer note (optional) — #{item_id}",
                key=note_key,
                placeholder="e.g. Verified against p.40 of income statement",
                label_visibility="collapsed",
            )

            col_a, col_r, col_sp = st.columns([1, 1, 4])
            with col_a:
                if st.button("✓  Approve", key=approve_key, type="primary", use_container_width=True):
                    try:
                        r = requests.post(
                            f"{API}/review/{item_id}/approve",
                            json={"reviewer_note": note},
                            timeout=10,
                        )
                        if r.ok:
                            st.success(f"Claim #{item_id} approved.")
                            st.rerun()
                        else:
                            st.error(r.text)
                    except Exception as e:
                        st.error(str(e))
            with col_r:
                if st.button("✕  Reject", key=reject_key, use_container_width=True):
                    try:
                        r = requests.post(
                            f"{API}/review/{item_id}/reject",
                            json={"reviewer_note": note},
                            timeout=10,
                        )
                        if r.ok:
                            st.warning(f"Claim #{item_id} rejected.")
                            st.rerun()
                        else:
                            st.error(r.text)
                    except Exception as e:
                        st.error(str(e))

            st.markdown("<hr style='border:none;border-top:1px solid #f1f5f9;margin:.2rem 0 .8rem 0;'>",
                        unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════
with tab_eval:
    import json as _json
    from pathlib import Path as _Path
    import math

    st.markdown("""
    <div style="margin-bottom:1.2rem;">
        <div style="font-size:1.15rem;font-weight:700;color:#0f172a;margin-bottom:.25rem;">
            Ragas-Style Evaluation
        </div>
        <div style="font-size:.83rem;color:#64748b;line-height:1.55;">
            Hand-implemented metrics evaluated on a 50-question Apple 10-K test set.
            Faithfulness and Context Precision use LLM-as-judge (Groq).
            Answer Relevancy uses embedding cosine similarity.
            Recall@K and MRR are computed directly from retrieved page numbers.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Load checkpoint or results file
    results_dir = _Path(__file__).parent.parent / "evaluation" / "results"
    checkpoint  = results_dir / "checkpoint_aapl-20230930.json"
    data: dict = {}
    if checkpoint.exists():
        try:
            data = _json.loads(checkpoint.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    if not data:
        st.info("No evaluation results yet. Run: `python -m evaluation.ragas_style_eval`")
    else:
        n = len(data)
        faithfulness      = [v["faithfulness"]      for v in data.values() if "faithfulness"      in v]
        answer_relevancy  = [v["answer_relevancy"]  for v in data.values() if "answer_relevancy"  in v]
        context_precision = [v["context_precision"] for v in data.values() if "context_precision" in v]

        avg_f  = sum(faithfulness)      / len(faithfulness)      if faithfulness      else 0
        avg_ar = sum(answer_relevancy)  / len(answer_relevancy)  if answer_relevancy  else 0
        avg_cp = sum(context_precision) / len(context_precision) if context_precision else 0

        # ── Metric cards ────────────────────────────────────────────────────
        def _score_color(v):
            if v >= 0.8: return "#16a34a", "#dcfce7"
            if v >= 0.6: return "#d97706", "#fef3c7"
            return "#dc2626", "#fee2e2"

        def _metric_card(label, value, description):
            fc, bc = _score_color(value)
            bar_w  = int(value * 100)
            return f"""
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;
                        padding:1.1rem 1.3rem;flex:1;min-width:180px;">
                <div style="font-size:.7rem;font-weight:600;color:#64748b;
                            text-transform:uppercase;letter-spacing:.06em;margin-bottom:.4rem;">
                    {label}
                </div>
                <div style="font-size:2rem;font-weight:800;color:{fc};line-height:1;">
                    {value:.2f}
                </div>
                <div style="background:#f1f5f9;border-radius:4px;height:5px;margin:.55rem 0 .4rem 0;">
                    <div style="background:{fc};width:{bar_w}%;height:5px;border-radius:4px;"></div>
                </div>
                <div style="font-size:.72rem;color:#94a3b8;">{description}</div>
            </div>"""

        cards_html = (
            _metric_card("Faithfulness",       avg_f,  "Claims grounded in retrieved context")
            + _metric_card("Answer Relevancy", avg_ar, "Answer addresses the question")
            + _metric_card("Context Precision",avg_cp, "Retrieved chunks are useful")
        )
        st.markdown(
            f'<div style="display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:1.2rem;">{cards_html}</div>',
            unsafe_allow_html=True,
        )

        st.caption(f"Averaged over {n} questions (checkpoint). Full run: 50 questions.")

        # ── Per-question breakdown ──────────────────────────────────────────
        with st.expander(f"Per-question breakdown ({n} questions evaluated)", expanded=False):
            import pandas as pd
            rows = []
            for qid, v in sorted(data.items()):
                rows.append({
                    "Question": qid,
                    "Faithfulness":       round(v.get("faithfulness",      0), 3),
                    "Answer Relevancy":   round(v.get("answer_relevancy",  0), 3),
                    "Context Precision":  round(v.get("context_precision", 0), 3),
                })
            df = pd.DataFrame(rows).set_index("Question")
            st.dataframe(
                df.style.background_gradient(cmap="RdYlGn", vmin=0, vmax=1),
                width="stretch",
            )

        # ── Methodology ─────────────────────────────────────────────────────
        st.markdown("""
        <div style="margin-top:1rem;background:#f8fafc;border:1px solid #e2e8f0;
                    border-radius:12px;padding:1.1rem 1.4rem;">
            <div style="font-size:.78rem;font-weight:700;color:#334155;margin-bottom:.7rem;">
                How each metric is computed
            </div>
            <div style="font-size:.78rem;color:#475569;line-height:1.8;">
                <b>Faithfulness</b> — LLM decomposes the answer into atomic statements,
                then judges each one: "Is this statement directly supported by the retrieved context?"
                Score = supported statements / total statements.<br>
                <b>Answer Relevancy</b> — LLM generates N pseudo-questions from the answer,
                embeds them alongside the original question, returns mean cosine similarity.
                High score = answer stays on topic.<br>
                <b>Context Precision</b> — LLM judges each retrieved chunk: "Is this chunk
                relevant to the question?" Returns Average Precision@K (rewards relevant chunks
                ranked higher).<br>
                <b>Recall@K / MRR</b> — Computed from gold page numbers in the test set.
                Recall@K = fraction of gold pages appearing in top-K retrieved chunks.
                MRR = mean(1 / rank_of_first_gold_hit).
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Test set summary ────────────────────────────────────────────────
        test_set_path = _Path(__file__).parent.parent / "evaluation" / "test_set.json"
        if test_set_path.exists():
            try:
                test_set = _json.loads(test_set_path.read_text(encoding="utf-8"))
                cats: dict = {}
                for q in test_set:
                    c = q.get("category", "other")
                    cats[c] = cats.get(c, 0) + 1
                cat_html = "".join(
                    f'<span style="background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;'
                    f'font-size:.7rem;padding:.15rem .55rem;border-radius:20px;margin:.15rem;">'
                    f'{c.replace("_"," ").title()} ({n})</span>'
                    for c, n in sorted(cats.items())
                )
                st.markdown(f"""
                <div style="margin-top:.9rem;">
                    <div style="font-size:.72rem;font-weight:600;color:#64748b;margin-bottom:.4rem;">
                        TEST SET — {len(test_set)} questions · Apple 10-K FY2023
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:.3rem;">{cat_html}</div>
                </div>
                """, unsafe_allow_html=True)
            except Exception:
                pass
