"""
DepoIndex pipeline
===================

PDF -> provenance-preserving extraction -> overlapping chunks ->
LLM topic detection -> topic merging -> deterministic provenance
validation -> chronological Topic Index.

Design principles (see methodology.md for full detail):
  1. The LLM is ONLY ever shown transcript text that carries explicit
     [PAGE n | LINE m] markers copied verbatim from the extraction step.
  2. The LLM is NEVER trusted with provenance. Every page/line the LLM
     returns is independently re-checked against the extracted transcript
     by plain Python before it is allowed into the final index.
  3. Anything that fails validation is rejected (or flagged), never
     silently "corrected" or guessed at.

This file has three usable entry points:
  - extract_transcript(pdf_path)   -> list[TranscriptLine]
  - run_pipeline(pdf_path, ...)    -> (topics, validation_report)
  - main()                         -> CLI: builds outputs/index.json + .md
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Optional


# --------------------------------------------------------------------------
# 1. EXTRACTION
# --------------------------------------------------------------------------
# PyMuPDF (fitz) is the primary extraction library, as required for this
# project. If it is not installed in the current environment, we fall back
# to pdfplumber.
#
# IMPORTANT:
# The supplied deposition PDF does not extract as:
#
#     22 MR. PURCELL: ...
#
# Instead, PyMuPDF extracts the printed line number and the transcript text
# as separate text objects. Therefore, for PyMuPDF we use the coordinates of
# the words on the page to reconstruct each physical transcript line.
# --------------------------------------------------------------------------

try:
    import fitz  # PyMuPDF

    _PDF_BACKEND = "pymupdf"

except ImportError:  # pragma: no cover - environment dependent
    fitz = None
    _PDF_BACKEND = "pdfplumber"


if _PDF_BACKEND == "pdfplumber":
    import pdfplumber


LINE_RE = re.compile(r"^(\d{1,2})\s+(.*)$")
TIMECODE_RE = re.compile(r"\s+\d{2}:\d{2}$")


@dataclass
class TranscriptLine:
    page: int          # 1-indexed PDF page number
    line: int          # transcript line number as printed by the reporter (1-25)
    text: str          # exact line text (timecodes stripped)


def _page_text_pymupdf(pdf_path: str):
    doc = fitz.open(pdf_path)

    for i in range(len(doc)):
        yield i + 1, doc[i].get_text()


def _page_text_pdfplumber(pdf_path: str):
    with pdfplumber.open(pdf_path) as pdf:

        for i, page in enumerate(pdf.pages):
            yield i + 1, page.extract_text() or ""


def extract_transcript(
    pdf_path: str,
    first_testimony_page: int = 6,
    last_testimony_page: Optional[int] = 88,
) -> list[TranscriptLine]:
    """
    Extract (page, line, text) records for the substantive Q&A portion of
    the transcript.

    The supplied PDF stores transcript line numbers separately from the
    transcript text in PyMuPDF's normal text extraction order.

    We therefore use PyMuPDF word coordinates to associate each printed
    transcript line number (1-25) with the words physically appearing on
    that same line.

    first_testimony_page / last_testimony_page bound the extraction to the
    examination itself.
    """

    # ------------------------------------------------------------------
    # PDFPLUMBER FALLBACK
    # ------------------------------------------------------------------

    if _PDF_BACKEND != "pymupdf":

        page_iter = _page_text_pdfplumber(pdf_path)

        records: list[TranscriptLine] = []

        for page_num, text in page_iter:

            if page_num < first_testimony_page:
                continue

            if last_testimony_page and page_num > last_testimony_page:
                continue

            for raw_line in text.split("\n"):

                raw_line = raw_line.strip()

                m = LINE_RE.match(raw_line)

                if not m:
                    continue

                line_no = int(m.group(1))

                if not (1 <= line_no <= 25):
                    continue

                content = TIMECODE_RE.sub("", m.group(2)).strip()

                if not content:
                    continue

                records.append(
                    TranscriptLine(
                        page=page_num,
                        line=line_no,
                        text=content,
                    )
                )

        return records


    # ------------------------------------------------------------------
    # PYMUPDF COORDINATE-BASED EXTRACTION
    # ------------------------------------------------------------------

    doc = fitz.open(pdf_path)

    records: list[TranscriptLine] = []


    for page_index in range(len(doc)):

        page_num = page_index + 1

        # Only process the actual testimony pages.
        if page_num < first_testimony_page:
            continue

        if last_testimony_page and page_num > last_testimony_page:
            continue

        # IMPORTANT:
        # Get the actual PDF page object before calling get_text().
        page = doc[page_index]

        # Extract words together with their physical coordinates.
        #
        # Each tuple returned by PyMuPDF is:
        #
        # x0, y0, x1, y1, word, block_no, line_no, word_no
        #
        words = page.get_text("words")


        # --------------------------------------------------------------
        # Group words by their physical Y coordinate.
        # --------------------------------------------------------------

        rows: dict[float, list] = {}

        for word in words:

            x0, y0, x1, y1, text, block_no, pdf_line_no, word_no = word

            # Round the Y coordinate so tiny rendering differences do not
            # split words that belong to the same physical transcript line.
            y_key = round(y0, 1)

            rows.setdefault(y_key, []).append(word)


        # --------------------------------------------------------------
        # Process each physical row from top to bottom.
        # --------------------------------------------------------------

        for y_key in sorted(rows.keys()):

            row_words = rows[y_key]

            # Read words from left to right.
            row_words.sort(key=lambda w: w[0])


            # ----------------------------------------------------------
            # Find the printed transcript line number.
            #
            # Court reporter pages contain line numbers 1-25 near the
            # left margin.
            # ----------------------------------------------------------

            line_candidate = None

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                if not text.isdigit():
                    continue

                number = int(text)

                if 1 <= number <= 25 and x0 < 100:

                    line_candidate = (x0, number)

                    break


            if line_candidate is None:
                continue


            line_x, line_no = line_candidate


            # ----------------------------------------------------------
            # Collect all text physically to the right of the line number.
            # ----------------------------------------------------------

            content_words = []

            for word in row_words:

                x0, y0, x1, y1, text, *_ = word

                # Ignore anything to the left of / at the line-number
                # position.
                if x0 <= line_x + 2:
                    continue

                # Ignore another standalone transcript line number.
                if text.isdigit():

                    number = int(text)

                    if 1 <= number <= 25:
                        continue

                # Ignore the page footer.
                if text.lower() == "page":
                    continue

                # Ignore an isolated page number.
                if text.isdigit() and int(text) == page_num:
                    continue

                content_words.append(text)


            # Reconstruct the physical line.
            content = " ".join(content_words).strip()


            # Remove trailing reporter timecodes such as:
            #
            # 01:16
            #
            content = TIMECODE_RE.sub("", content).strip()


            if not content:
                continue


            # Ignore page footer text.
            if content.lower() == f"page {page_num}".lower():
                continue


            records.append(
                TranscriptLine(
                    page=page_num,
                    line=line_no,
                    text=content,
                )
            )


    # ------------------------------------------------------------------
    # Remove duplicate (page, line) combinations.
    # ------------------------------------------------------------------

    unique: dict[tuple[int, int], TranscriptLine] = {}

    for record in records:

        key = (record.page, record.line)

        unique[key] = record


    records = list(unique.values())


    # ------------------------------------------------------------------
    # Sort chronologically.
    # ------------------------------------------------------------------

    records.sort(
        key=lambda r: (r.page, r.line)
    )


    return records


# --------------------------------------------------------------------------
# 2. OVERLAPPING CHUNKS (for the LLM prompt)
# --------------------------------------------------------------------------

def build_chunks(
    lines: list[TranscriptLine],
    lines_per_chunk: int = 90,
    overlap_lines: int = 20,
) -> list[list[TranscriptLine]]:
    """
    Split the transcript into overlapping windows so that a topic whose
    boundary falls near a chunk edge is still fully visible to the LLM in
    at least one chunk.

    Overlap intentionally causes the same testimony to appear in two chunks;
    duplicate/overlapping topic detections are resolved later in
    merge_topics().
    """

    chunks = []

    step = lines_per_chunk - overlap_lines

    for start in range(0, len(lines), step):

        chunk = lines[start:start + lines_per_chunk]

        if chunk:
            chunks.append(chunk)

        if start + lines_per_chunk >= len(lines):
            break

    return chunks


def format_chunk_for_llm(chunk: list[TranscriptLine]) -> str:
    """
    Render a chunk with explicit [PAGE n | LINE m] markers.

    These markers allow the LLM to refer only to transcript locations
    that actually exist in the supplied chunk.
    """

    out = []

    for rec in chunk:

        out.append(
            f"[PAGE {rec.page} | LINE {rec.line}]\n{rec.text}"
        )

    return "\n".join(out)


# --------------------------------------------------------------------------
# 3. LLM TOPIC DETECTION
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a legal deposition analyst. You will be given a
window of deposition transcript text. Every line is tagged with its exact
[PAGE n | LINE m] identifier copied from the original transcript.

Identify substantive topics discussed in this window (ignore procedural
chatter like "let's take a break" or court-reporter interruptions unless
that IS the point being discussed). For each topic return:
  - "topic": short descriptive label
  - "start_page" / "start_line": the identifier of the first line of this topic
  - "end_page" / "end_line": the identifier of the last line of this topic
  - "evidence_page" / "evidence_line": one identifier that best supports the topic
  - "kind": one of "new_topic" | "continuation" | "digression" | "return_to_earlier"

RULES:
- You may ONLY use page/line identifiers that literally appear in the
  supplied text. Never invent, estimate, or renumber identifiers.
- Use topic-level granularity (a handful of topics per window), not one
  topic per question and answer.
- Return ONLY a JSON array of topic objects. No prose, no markdown fences.
"""


USER_PROMPT_TEMPLATE = """TRANSCRIPT WINDOW:
{chunk_text}

Return the JSON array of topics for this window now.
"""


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Calls the configured LLM API.

    Requires OPENAI_API_KEY to be set in the environment.

    Uses temperature=0 for maximum reproducibility.
    """

    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")


    import urllib.request


    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    }


    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )


    with urllib.request.urlopen(req, timeout=60) as resp:

        data = json.loads(
            resp.read()
        )


    return data["choices"][0]["message"]["content"]


def _load_offline_cache(cache_path: str) -> list[dict]:
    """
    Offline / no-API-key fallback.

    The cache was produced by running the chunking + prompting design
    through an LLM and recording topic output per chunk.

    Every identifier in the cache still goes through the same independent
    Python validation step as a live API response would.
    """

    with open(cache_path) as f:

        return json.load(f)


# --------------------------------------------------------------------------
# 4. DETERMINISTIC PROVENANCE VALIDATION
# --------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    reasons: list[str]


def validate_topic(
    topic: dict,
    line_index: dict[tuple[int, int], str],
) -> ValidationResult:
    """
    Independently verifies a single LLM-proposed topic against the
    extracted transcript.

    The LLM is never trusted here.

    Every page/line is checked against the ground-truth line index built
    directly from the PDF.
    """

    reasons = []


    # --------------------------------------------------------------
    # Required fields
    # --------------------------------------------------------------

    required = [
        "topic",
        "start_page",
        "start_line",
        "end_page",
        "end_line",
    ]


    for field in required:

        if field not in topic or topic[field] in (None, ""):

            reasons.append(
                f"missing required field '{field}'"
            )


    if reasons:

        return ValidationResult(
            False,
            reasons
        )


    # --------------------------------------------------------------
    # Start / end locations
    # --------------------------------------------------------------

    start_key = (
        topic["start_page"],
        topic["start_line"],
    )

    end_key = (
        topic["end_page"],
        topic["end_line"],
    )


    if start_key not in line_index:

        reasons.append(
            f"start location {start_key} does not exist in the supplied deposition"
        )


    if end_key not in line_index:

        reasons.append(
            f"end location {end_key} does not exist in the supplied deposition"
        )


    # --------------------------------------------------------------
    # Start must come before end
    # --------------------------------------------------------------

    if not reasons and start_key > end_key:

        reasons.append(
            f"start {start_key} comes after end {end_key}"
        )


    # --------------------------------------------------------------
    # Supporting evidence
    # --------------------------------------------------------------

    evidence = topic.get("supporting_evidence") or {}


    ev_key = (
        evidence.get("page"),
        evidence.get("line"),
    )


    if ev_key[0] is not None:

        if ev_key not in line_index:

            reasons.append(
                f"supporting evidence location {ev_key} "
                f"does not exist in the supplied deposition"
            )

        else:

            quote = evidence.get("quote", "")

            actual_text = line_index[ev_key]


            # The quoted text must genuinely match the cited line.
            #
            # We check the first 15 characters in either direction.
            if (
                quote
                and actual_text[:15] not in quote
                and quote[:15] not in actual_text
            ):

                reasons.append(
                    "supporting evidence text does not match "
                    "the cited page/line"
                )


    return ValidationResult(
        len(reasons) == 0,
        reasons
    )


def validate_all(
    topics: list[dict],
    lines: list[TranscriptLine],
) -> tuple[list[dict], list[dict]]:
    """
    Returns:

        accepted_topics
        rejected_topics_with_reasons
    """

    line_index = {
        (r.page, r.line): r.text
        for r in lines
    }


    accepted = []
    rejected = []


    for t in topics:

        result = validate_topic(
            t,
            line_index
        )


        if result.valid:

            accepted.append(t)

        else:

            rejected.append(
                {
                    **t,
                    "_rejection_reasons": result.reasons,
                }
            )


    return accepted, rejected


# --------------------------------------------------------------------------
# 5. MERGE / DEDUPLICATE
# --------------------------------------------------------------------------

def _overlaps(
    a: dict,
    b: dict,
) -> bool:

    a_start = (
        a["start_page"],
        a["start_line"],
    )

    a_end = (
        a["end_page"],
        a["end_line"],
    )


    b_start = (
        b["start_page"],
        b["start_line"],
    )

    b_end = (
        b["end_page"],
        b["end_line"],
    )


    return (
        a_start <= b_end
        and
        b_start <= a_end
    )


def merge_topics(
    topics: list[dict],
) -> list[dict]:
    """
    Overlapping chunks mean the same topic can be detected twice.

    This merges topics whose page/line spans overlap AND whose labels
    are near-duplicates.

    Distinct topics that merely happen to be adjacent are left alone.
    """

    topics_sorted = sorted(
        topics,
        key=lambda t: (
            t["start_page"],
            t["start_line"],
        ),
    )


    merged: list[dict] = []


    for t in topics_sorted:

        match = None


        for m in merged:

            same_label = (
                t["topic"].lower() in m["topic"].lower()
                or
                m["topic"].lower() in t["topic"].lower()
            )


            if same_label and _overlaps(t, m):

                match = m

                break


        if match:

            match["start_page"], match["start_line"] = min(
                (
                    match["start_page"],
                    match["start_line"],
                ),
                (
                    t["start_page"],
                    t["start_line"],
                ),
            )


            match["end_page"], match["end_line"] = max(
                (
                    match["end_page"],
                    match["end_line"],
                ),
                (
                    t["end_page"],
                    t["end_line"],
                ),
            )

        else:

            merged.append(
                dict(t)
            )


    merged.sort(
        key=lambda t: (
            t["start_page"],
            t["start_line"],
        )
    )


    return merged


# --------------------------------------------------------------------------
# 6. TOP-LEVEL PIPELINE
# --------------------------------------------------------------------------

def run_pipeline(
    pdf_path: str,
    offline_cache_path: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """
    Runs the full PDF -> validated, chronological Topic Index pipeline.

    Returns:

        (topics, run_report)

    where run_report captures counts used by validation_report.md.
    """

    # --------------------------------------------------------------
    # STEP 1: Extract transcript
    # --------------------------------------------------------------

    lines = extract_transcript(
        pdf_path
    )


    # --------------------------------------------------------------
    # STEP 2: Decide between live LLM and offline cache
    # --------------------------------------------------------------

    use_live_llm = bool(
        os.environ.get("OPENAI_API_KEY")
    )


    raw_topics: list[dict] = []


    # --------------------------------------------------------------
    # LIVE OPENAI MODE
    # --------------------------------------------------------------

    if use_live_llm:

        chunks = build_chunks(
            lines
        )


        for chunk in chunks:

            chunk_text = format_chunk_for_llm(
                chunk
            )


            content = call_llm(
                SYSTEM_PROMPT,
                USER_PROMPT_TEMPLATE.format(
                    chunk_text=chunk_text
                ),
            )


            try:

                raw_topics.extend(
                    json.loads(content)
                )

            except json.JSONDecodeError:

                # Malformed model output is dropped rather than guessed.
                continue


    # --------------------------------------------------------------
    # OFFLINE CACHE MODE
    # --------------------------------------------------------------

    else:

        cache_path = (
            offline_cache_path
            or
            os.path.join(
                os.path.dirname(__file__),
                "outputs",
                "_llm_offline_cache.json",
            )
        )


        raw_topics = _load_offline_cache(
            cache_path
        )


    # --------------------------------------------------------------
    # STEP 3: Deterministic validation
    # --------------------------------------------------------------

    accepted, rejected = validate_all(
        raw_topics,
        lines,
    )


    # --------------------------------------------------------------
    # STEP 4: Merge overlapping duplicate topics
    # --------------------------------------------------------------

    merged = merge_topics(
        accepted
    )


    # --------------------------------------------------------------
    # STEP 5: Build run report
    # --------------------------------------------------------------

    report = {
        "pdf_backend": _PDF_BACKEND,

        "llm_mode": (
            "live_openai_api"
            if use_live_llm
            else "offline_cache"
        ),

        "total_lines_extracted": len(lines),

        "raw_topics_from_llm": len(raw_topics),

        "accepted_topics": len(accepted),

        "rejected_topics": len(rejected),

        "rejected_detail": rejected,

        "final_topic_count_after_merge": len(merged),
    }


    return merged, report


# --------------------------------------------------------------------------
# 7. MARKDOWN OUTPUT
# --------------------------------------------------------------------------

def to_markdown(
    topics: list[dict],
) -> str:

    lines = [
        "# DepoIndex — Topic Index",
        "",
        "Persis Yu Deposition",
        "",
    ]


    for t in topics:

        lines.append(
            f"## {t['topic']}"
        )


        lines.append(
            f"- **Start:** Page {t['start_page']}, "
            f"Line {t['start_line']}"
        )


        lines.append(
            f"- **End:** Page {t['end_page']}, "
            f"Line {t['end_line']}"
        )


        summary = (
            t.get("summary")
            or
            t.get("description", "")
        )


        if summary:

            lines.append(
                f"- **Summary:** {summary}"
            )


        ev = t.get(
            "supporting_evidence",
            {}
        )


        if ev:

            lines.append(
                f"- **Supporting evidence:** "
                f"Page {ev.get('page')}, "
                f"Line {ev.get('line')} — "
                f"\"{ev.get('quote', '').strip()}\""
            )


        lines.append("")


    return "\n".join(
        lines
    )


# --------------------------------------------------------------------------
# 8. COMMAND-LINE ENTRY POINT
# --------------------------------------------------------------------------

def main():

    base = os.path.dirname(
        __file__
    )


    pdf_path = os.path.join(
        base,
        "data",
        "Persis_Yu_Deposition.pdf",
    )


    out_dir = os.path.join(
        base,
        "outputs",
    )


    os.makedirs(
        out_dir,
        exist_ok=True
    )


    # Run the complete pipeline.
    topics, report = run_pipeline(
        pdf_path
    )


    # --------------------------------------------------------------
    # Save JSON output
    # --------------------------------------------------------------

    with open(
        os.path.join(
            out_dir,
            "index.json",
        ),
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "topics": topics,
                "run_report": report,
            },
            f,
            indent=2,
        )


    # --------------------------------------------------------------
    # Save Markdown output
    # --------------------------------------------------------------

    with open(
        os.path.join(
            out_dir,
            "index.md",
        ),
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            to_markdown(
                topics
            )
        )


    # --------------------------------------------------------------
    # Print pipeline statistics
    # --------------------------------------------------------------

    print(
        f"Backend: {report['pdf_backend']} | "
        f"LLM mode: {report['llm_mode']}"
    )


    print(
        f"Extracted "
        f"{report['total_lines_extracted']} "
        f"transcript lines"
    )


    print(
        f"LLM proposed "
        f"{report['raw_topics_from_llm']} "
        f"raw topics"
    )


    print(
        f"Validation accepted "
        f"{report['accepted_topics']}, "
        f"rejected "
        f"{report['rejected_topics']}"
    )


    print(
        f"Final chronological topic count after merge: "
        f"{report['final_topic_count_after_merge']}"
    )


# --------------------------------------------------------------------------
# Run when executed directly
# --------------------------------------------------------------------------

if __name__ == "__main__":
    main()