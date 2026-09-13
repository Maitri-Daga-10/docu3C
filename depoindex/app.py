"""
DepoIndex — AI-Powered Deposition Topic Index
Streamlit UI for attorneys to generate, verify, and export a chronological
topic index for a deposition transcript, with every entry traceable back
to an exact page and line in the original PDF.
"""

import json
import os

import streamlit as st

import pipeline

st.set_page_config(page_title="DepoIndex", page_icon="📑", layout="wide")

BASE_DIR = os.path.dirname(__file__)
PDF_PATH = os.path.join(BASE_DIR, "data", "Persis_Yu_Deposition.pdf")
OUTPUT_JSON = os.path.join(BASE_DIR, "outputs", "index.json")
OUTPUT_MD = os.path.join(BASE_DIR, "outputs", "index.md")


def load_existing_outputs():
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON) as f:
            data = json.load(f)
        return data.get("topics", []), data.get("run_report", {})
    return None, None


st.title("📑 DepoIndex")
st.caption("AI-powered deposition topic index — every entry is traceable back to an exact page and line.")

with st.sidebar:
    st.header("Deposition")
    if os.path.exists(PDF_PATH):
        st.success("Persis Yu Deposition.pdf loaded")
        with open(PDF_PATH, "rb") as f:
            st.download_button("View source PDF", f, file_name="Persis_Yu_Deposition.pdf")
    else:
        st.error("No deposition PDF found in data/")

    st.divider()
    llm_mode = "Live OpenAI API" if os.environ.get("OPENAI_API_KEY") else "Offline cache (no API key set)"
    st.caption(f"LLM mode: **{llm_mode}**")
    st.caption(f"PDF backend: **{pipeline._PDF_BACKEND}**")

    generate = st.button("⚙️ Generate Topic Index", type="primary", use_container_width=True)

if "topics" not in st.session_state:
    topics, report = load_existing_outputs()
    st.session_state.topics = topics or []
    st.session_state.report = report or {}

if generate:
    with st.spinner("Extracting transcript, running topic detection, and validating provenance..."):
        topics, report = pipeline.run_pipeline(PDF_PATH)
        os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
        with open(OUTPUT_JSON, "w") as f:
            json.dump({"topics": topics, "run_report": report}, f, indent=2)
        with open(OUTPUT_MD, "w") as f:
            f.write(pipeline.to_markdown(topics))
        st.session_state.topics = topics
        st.session_state.report = report
    st.success("Topic index generated.")

topics = st.session_state.topics
report = st.session_state.report

if not topics:
    st.info("Click **Generate Topic Index** in the sidebar to build the index.")
    st.stop()

# --- Summary metrics -------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Topics identified", len(topics))
col2.metric("Transcript lines indexed", report.get("total_lines_extracted", "—"))
accepted = report.get("accepted_topics")
rejected = report.get("rejected_topics")
if accepted is not None:
    col3.metric("Provenance validation", f"{accepted} passed", delta=f"{rejected} rejected" if rejected else None,
                delta_color="inverse")
else:
    col3.metric("Provenance validation", "n/a")
col4.metric("Page span", f"{topics[0]['start_page']}–{topics[-1]['end_page']}")

if rejected:
    with st.expander(f"⚠️ {rejected} candidate topic(s) rejected by provenance validation"):
        st.caption("These were proposed by the LLM but failed deterministic Python validation "
                   "(nonexistent page/line, or evidence text that didn't match the cited location) "
                   "and were excluded from the index automatically.")
        for r in report.get("rejected_detail", []):
            st.write(f"**{r['topic']}** — {', '.join(r['_rejection_reasons'])}")

st.divider()

# --- Search / filter ---------------------------------------------------
search = st.text_input("🔍 Search topics", placeholder="e.g. TILA, RICO, enforceability, servicer transfer")
filtered = [
    t for t in topics
    if search.lower() in t["topic"].lower() or search.lower() in t.get("summary", "").lower()
] if search else topics

st.write(f"Showing {len(filtered)} of {len(topics)} topics")

left, right = st.columns([1, 1.3])

with left:
    st.subheader("Chronological Topic Index")
    labels = [f"{i+1}. {t['topic']}  (p.{t['start_page']}:{t['start_line']}–p.{t['end_page']}:{t['end_line']})"
              for i, t in enumerate(filtered)]
    selected_idx = st.radio("Select a topic to inspect", range(len(filtered)),
                             format_func=lambda i: labels[i], label_visibility="collapsed")

with right:
    st.subheader("Topic Detail")
    t = filtered[selected_idx]
    st.markdown(f"### {t['topic']}")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Start:** Page {t['start_page']}, Line {t['start_line']}")
    c2.markdown(f"**End:** Page {t['end_page']}, Line {t['end_line']}")
    st.markdown("**Summary**")
    st.write(t.get("summary", "—"))
    ev = t.get("supporting_evidence", {})
    st.markdown(f"**Supporting evidence** — Page {ev.get('page')}, Line {ev.get('line')}")
    st.code(ev.get("quote", ""), language=None)
    st.caption("Verify this entry against the original PDF using the page/line above before relying on it.")

st.divider()

# --- Downloads -----------------------------------------------------
d1, d2 = st.columns(2)
with open(OUTPUT_JSON, "rb") as f:
    d1.download_button("⬇️ Download index.json", f, file_name="index.json", mime="application/json",
                        use_container_width=True)
with open(OUTPUT_MD, "rb") as f:
    d2.download_button("⬇️ Download index.md", f, file_name="index.md", mime="text/markdown",
                        use_container_width=True)

st.caption(
    "The LLM identifies semantic topics, while deterministic Python logic validates source "
    "provenance against the original transcript."
)
