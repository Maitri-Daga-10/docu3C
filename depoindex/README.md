# DepoIndex — AI-Powered Deposition Topic Index

A small, interview-explainable prototype that turns a deposition PDF into
a chronological, attorney-verifiable topic index — every entry traceable
back to an exact page and line in the original transcript.

## Problem

Attorneys preparing for trial or a motion need to find "everywhere the
witness discussed X" in a 90-page deposition. Doing this by hand means
re-reading the whole transcript. Handing it to an LLM naively is
dangerous: LLMs can plausibly invent a page/line citation that doesn't
exist, and a false citation in a legal filing is a serious problem.

## Solution

DepoIndex separates two concerns that a naive "LLM summarizes the
deposition" approach conflates:

1. **Semantic judgment** (what is this testimony about, where does a
   topic start/end) — this is genuinely a language-understanding task,
   so it's given to an LLM.
2. **Provenance** (does that page/line actually exist, does the quoted
   testimony actually say that) — this is a lookup, not a judgment call,
   so it is never left to the LLM. It's checked by plain Python against
   the extracted transcript, and anything unverifiable is rejected.

> The LLM identifies semantic topics, while deterministic Python logic
> validates source provenance against the original transcript.

## Architecture

```
PDF → provenance-preserving extraction → overlapping chunks
    → LLM topic detection → topic merging
    → deterministic provenance validation → chronological Topic Index
    → Streamlit attorney interface
```

See `methodology.md` for the full design rationale, and `llm_usage.md`
for an honest account of exactly what was run to produce the outputs in
this submission (including the constraints of the sandbox it was built
in).

## Project layout

```
depoindex/
├── app.py                       # Streamlit UI
├── pipeline.py                  # extraction, LLM calls, validation, merge
├── requirements.txt
├── README.md
├── methodology.md                # provenance design, in depth
├── llm_usage.md                  # honest LLM usage disclosure
├── data/
│   └── Persis_Yu_Deposition.pdf
└── outputs/
    ├── index.json                 # topics + full run report
    ├── index.md                   # human-readable topic index
    ├── validation_report.md       # evaluation, stability, failure cases
    └── _llm_offline_cache.json    # see llm_usage.md — offline fallback data
```

## Installation

```bash
cd depoindex
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

## Environment variables

| Variable          | Required? | Purpose                                                                 |
|--------------------|-----------|--------------------------------------------------------------------------|
| `OPENAI_API_KEY`  | No        | If set, the pipeline calls the live OpenAI API for topic detection (temperature 0). If unset, it uses the pre-computed offline cache in `outputs/_llm_offline_cache.json` so the app still runs end-to-end without a key. |

No key is required to run the app — the offline cache lets you see the
full pipeline (extraction → validation → merge → UI) without any API
cost. See `llm_usage.md` for exactly how that cache was produced.

## How to run

**Regenerate the index from the command line:**
```bash
python pipeline.py
```
This writes `outputs/index.json` and `outputs/index.md`.

**Run the attorney-facing UI:**
```bash
streamlit run app.py
```
Click **Generate Topic Index** in the sidebar (or just view the
already-generated results — the app loads `outputs/index.json` on
startup if present).

## Output description

- **`outputs/index.json`** — `{"topics": [...], "run_report": {...}}`.
  Each topic has `topic`, `start_page`/`start_line`,
  `end_page`/`end_line`, `summary`, and `supporting_evidence`
  (`page`/`line`/`quote`). `run_report` records the PDF backend used, LLM
  mode, line/topic counts, and full detail on any rejected candidate
  topics.
- **`outputs/index.md`** — the same topics rendered as a readable
  Markdown index.
- **`outputs/validation_report.md`** — manual review methodology,
  results, a three-run stability comparison, three real failure cases
  from testing, and limitations.

## Provenance strategy

Summarized here; full detail in `methodology.md` §4. The LLM only ever
sees transcript text pre-tagged with `[PAGE n | LINE m]` markers copied
verbatim from extraction. Every identifier it returns — start, end, and
supporting-evidence location plus quote — is independently re-checked
against a ground-truth `{(page, line): text}` index built directly from
the PDF. Nonexistent locations, out-of-order spans, and evidence text
that doesn't match its cited location are all rejected automatically and
logged with a specific reason; nothing is silently corrected or passed
through.

## Validation approach

Manual review of every topic entry (all 20 in this run — the brief's
"at least 20" threshold), a three-run stability comparison, and three
concrete failure cases pulled from actual testing (including the two
deliberately injected hallucinations used to confirm the rejection logic
fires). See `outputs/validation_report.md` for the full write-up.

## Limitations

LLM output can vary between runs (though `temperature=0` and the
Python-side validation constrain how much that matters); topic
granularity and boundaries are inherently somewhat subjective; PDF
extraction assumes the reporter's own printed line numbers, which is
standard but not universal across all transcript formats; the
chunk-overlap merge heuristic is deliberately conservative and can
occasionally leave two genuinely-identical topics unmerged rather than
risk merging two genuinely-different ones. Full discussion in
`outputs/validation_report.md`.

## Future improvements

- Add a "jump to PDF page" deep link once a PDF viewer is embedded in the
  Streamlit app, instead of just displaying the page/line number.
- Support multi-witness deposition sets with cross-deposition topic
  linking.
- Let an attorney manually accept/reject/edit a topic in the UI and
  persist that correction back into `index.json`.
- Add a second LLM pass to specifically re-check ambiguous topic
  boundaries the first pass flagged with low confidence.

## Demo instructions

1. `pip install -r requirements.txt`
2. `streamlit run app.py`
3. Click **Generate Topic Index** (or view the pre-generated results).
4. Use the search box to find a topic (try "TILA", "RICO", or "servicer
   transfer"), select it from the list, and inspect its page/line
   boundaries and supporting evidence in the detail panel.
5. Download `index.json` or `index.md` from the buttons at the bottom.
