# DepoIndex — Methodology

## 1. Pipeline overview

```
PDF
 → provenance-preserving extraction (page + line + text)
 → overlapping chunks tagged with [PAGE n | LINE m]
 → LLM topic detection (per chunk)
 → deterministic Python provenance validation (reject anything unverifiable)
 → merge duplicate/overlapping detections
 → chronological Topic Index (index.json / index.md)
 → Streamlit interface for attorney review
```

Every step after "extraction" is either (a) a call to an LLM that is only
ever shown text it cannot alter, or (b) plain, auditable Python. There is
no step where an LLM output is written to the final index without first
passing through (b).

## 2. Extraction

The deposition PDF used in this submission is a Veritext-style
court-reporter transcript: every physical line on every page is prefixed
with its own line number, 1–25, printed by the reporting service itself
(this is standard in U.S. deposition transcripts so that testimony can be
cited as "page 44, line 13" during trial). `pipeline.extract_transcript()`
reads each page's text and keys directly off that printed line number —
it does not invent line numbers by counting text lines itself. This means
every `(page, line)` pair in the index corresponds exactly to what an
attorney would find by opening the PDF and counting to that line.

The extraction step:
- Restricts itself to pages 6–88, i.e. the actual examination (`BY MR.
  PURCELL:` ... `THE VIDEOGRAPHER: We are going off the record ... this
  concludes today's testimony`). Pages 1–5 (caption/appearances/index) and
  89–94 (declaration, reporter certificate, errata sheet, and the
  automatically generated word index) are not testimony and are excluded
  so they cannot be mistaken for topics.
- Strips only the trailing video timecode (e.g. `01:16`) that Veritext
  appends to each line. No other text is modified, reordered, or
  summarized at this stage.
- Uses PyMuPDF (`fitz`) as the primary extraction library, with a
  pdfplumber fallback used automatically if PyMuPDF is not installed in
  the current environment (both return the same plain per-page text for
  this document type). `requirements.txt` installs both so either path
  works out of the box. In the current pipeline run, PyMuPDF was not
  installable in the sandbox that produced this submission (no outbound
  network access to fetch the wheel), so the pdfplumber fallback path is
  what actually generated the shipped `outputs/`. `pipeline._PDF_BACKEND`
  reports which backend produced any given run, and the Streamlit sidebar
  displays it live.

## 3. Overlapping chunks

The transcript is split into windows of 90 extracted lines with a 20-line
overlap (`pipeline.build_chunks`). A topic whose boundary happens to fall
near a chunk edge — for example, one that starts a few lines before a
chunk cutoff — will still appear complete in the *next* chunk, since that
next chunk starts 20 lines earlier than a non-overlapping split would.
This is what "topics continuing across pages" and "digressions" require:
a chunk boundary is not allowed to be the reason a topic looks truncated.

The trade-off is that the same topic is frequently detected twice (once
per chunk it spans), which is expected and handled by the merge step
below rather than by trying to make chunking boundary-aware up front.

## 4. Critical provenance design

**Never allow the LLM to invent page or line numbers.**

Every chunk sent to the LLM is rendered with a `[PAGE n | LINE m]` marker
directly in front of the exact line it was extracted from
(`pipeline.format_chunk_for_llm`). The system prompt tells the model it
may only select identifiers that literally appear in the text it was
given — but the pipeline does **not** trust the model to follow that
instruction. Every topic the model returns (`start_page`/`start_line`,
`end_page`/`end_line`, and the cited supporting-evidence
`page`/`line`/`quote`) is independently re-checked by
`pipeline.validate_topic()` against a ground-truth index built straight
from the extraction step:

1. **Page exists** — the cited page/line pair is looked up directly in
   the `{(page, line): text}` map built from `extract_transcript()`.
2. **Line exists** — same lookup; a page that exists but a line number
   that was never printed on it (e.g. line 40 on a 25-line page) fails.
3. **Start comes before end** — compared as `(page, line)` tuples.
4. **Cited evidence exists** — the evidence identifier is checked the
   same way as start/end.
5. **Cited evidence text actually matches** — the first ~15 characters of
   the model's quoted evidence must appear in the real line's text (or
   vice versa). This catches the failure mode where a model cites a real,
   existing page/line but then fabricates *different* testimony as the
   "quote" for it — a real location does not by itself prove the
   attributed content is real.
6. **Belongs to the supplied deposition** — because the ground-truth
   index is built only from this PDF's own extracted lines, any
   identifier from a different document (or a hallucinated one) fails (1)
   or (2) automatically; there is no separate step needed.

Anything that fails **any** of these checks is dropped from the index and
recorded in `run_report.rejected_detail` with the specific reason(s) — it
is never silently corrected, snapped to the nearest valid line, or passed
through anyway. Two synthetic hallucination test cases (a nonexistent
line number, and a real location paired with fabricated quote text) were
deliberately included in this run to confirm the rejection logic actually
fires; see `outputs/validation_report.md` for the result.

## 5. Topic segmentation and merging

The LLM is asked, per chunk, to label each topic's `kind` as one of
`new_topic`, `continuation`, `digression`, or `return_to_earlier`. This
is informational for a human reviewer (and is preserved in the raw LLM
output) rather than something the merge step branches on — merging is
done purely on page/line overlap plus label similarity
(`pipeline.merge_topics`), which is a simpler and more auditable rule
than trying to encode "is this really the same topic" as an LLM judgment
call:

- Two detections merge only if their labels are near-duplicates
  (case-insensitive substring match either direction) **and** their
  page/line spans overlap.
- When they merge, the wider span (min of the two starts, max of the two
  ends) is kept.
- Detections that are adjacent but not label-matches are left as
  separate entries — this is intentional, so that a witness returning to
  an earlier subject after 20 pages of unrelated testimony produces a
  distinct, correctly-placed second index entry rather than being folded
  into one artificially long span that would misrepresent where in the
  transcript that subject was actually discussed.

## 6. What the LLM is trusted to do, and what it is not

The LLM is trusted to *read testimony and propose a topic label, a
boundary, and a supporting citation*. It is not trusted with anything
that could silently corrupt provenance: not page numbers, not line
numbers, not the substance of a citation, and not the final list that
ships in `outputs/`. See `llm_usage.md` for the complete, unvarnished
description of what was actually run to produce this submission.

## 7. Reproducibility

- `temperature=0` is used for the live API path (`pipeline.call_llm`).
- Structured JSON output is requested explicitly in the system prompt.
- Source identifiers are preserved character-for-character from
  extraction through to the final index — nothing is renumbered.
- All references are validated programmatically before being accepted
  (Section 4); this is what actually determines reproducibility in
  practice, since even a non-deterministic model call cannot introduce
  invalid citations into the shipped index.
