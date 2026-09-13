# DepoIndex — Validation Report

**Deposition:** Persis Yu (Heather Turrey v. Vervent, Inc.), March 28, 2023
**Transcript pages indexed:** 6–88 (2,036 extracted transcript lines)
**Pipeline run mode:** offline cache (no live API key in this sandbox — see
`llm_usage.md`); backend: `pdfplumber` (PyMuPDF fallback — see
`methodology.md` §2)

## Evaluation methodology

All **20** entries in the generated Topic Index (exceeding the required
minimum of 20) were manually reviewed against the source PDF for:

- **Location accuracy** — does the cited `(page, line)` actually contain
  the start/end of the described discussion when the PDF is opened to
  that page?
- **Topic relevance** — is the label an accurate description of what is
  actually discussed in that span, not a generic restatement of "witness
  answers a question"?
- **Boundary quality** — does the span capture the full discussion
  without including large amounts of unrelated material, and without
  cutting the discussion off mid-exchange?
- **Coverage** — does the chronological set of topics account for the
  substantive arc of the examination (background → servicing history →
  ITT practices → PEAKS loan enforceability → regulatory history → close),
  without large unindexed gaps of substantive testimony?
- **Redundancy** — after merging, are there near-duplicate entries that
  should have been collapsed into one?

Each of the 20 entries was opened at its cited page/line in the source
PDF and read against its summary and evidence quote by hand; this is the
same check `pipeline.validate_topic()` performs mechanically for
existence/ordering, extended here to the *semantic* dimension a Python
script cannot check.

## Results

- **20 / 20** topics have accurate, existing `(page, line)` locations
  (mechanically guaranteed by `validate_topic()`, and confirmed by manual
  spot-opening of the PDF at each boundary).
- **20 / 20** topic labels were judged, on manual read-through, to
  accurately describe the corresponding span (subjective judgment — see
  Limitations).
- **Boundary quality:** 17 / 20 spans were judged clean on manual review.
  3 spans (Topics 12, 14, and 19 — all touching PEAKS-loan
  enforceability) have boundaries that a different reviewer could
  reasonably draw slightly differently, because the witness's testimony
  on enforceability is itself non-linear (counsel returns to the subject
  three separate times). These are flagged for manual review rather than
  claimed as unambiguous — see Failure Case 1 below.
- **Coverage:** the 20 topics jointly span pages 7–88 with no gap larger
  than a page of procedural material (breaks, admonitions, exhibit
  marking) between consecutive topics. Two short procedural
  interludes (the mid-deposition breaks at pages 37 and 76) are not
  independently indexed as topics, which is intentional per the brief's
  "do not create a topic for every question" instruction — they are
  neither substantive nor findable subjects an attorney would search for.
- **Redundancy:** the raw (pre-merge) LLM output for this run contained
  24 candidate topics; 2 were duplicate detections of the same topic from
  overlapping chunks (see `pipeline.merge_topics`) and were correctly
  collapsed, and 2 were deliberately-injected hallucinations (see below)
  that were correctly rejected before merge — leaving the final 20 with
  no remaining duplicates found on manual review.

**Accuracy figure:** we are not reporting a single "% accuracy" number
for topic quality, because topic-boundary and topic-relevance judgments
are inherently subjective (see Limitations) and a manufactured precision
statistic would overstate what was actually measured. What can be stated
as a hard, mechanically verified fact is: **0 of the 20 shipped topics
have an invalid, nonexistent, or misordered page/line citation**, because
that property is enforced by `validate_topic()` before a topic can ever
reach `outputs/index.json`.

## Three-run stability

The full pipeline (`pipeline.run_pipeline`) was run three consecutive
times against the same PDF, same code, same offline cache:

| Run | Topic count | Accepted | Rejected | Diff vs. previous run |
|-----|-------------|----------|----------|------------------------|
| 1   | 20          | 22       | 2        | —                      |
| 2   | 20          | 22       | 2        | **byte-identical**     |
| 3   | 20          | 22       | 2        | **byte-identical**     |

All three runs produced byte-identical `index.json` output (`diff`
confirmed no differences). This is expected and not very informative on
its own: in offline-cache mode there is no live model call, so
determinism is guaranteed by construction (the same cached input is
re-validated and re-merged by the same deterministic Python code every
time), rather than being evidence that a live LLM would also be
perfectly stable.

**What would differ in live-API mode:** with `OPENAI_API_KEY` set and
`temperature=0`, we would expect labels and boundaries to be highly
consistent across runs but not necessarily byte-identical — minor label
rewording (e.g. "PEAKS Loan Enforceability" vs. "Enforceability of the
PEAKS Loans") and occasional ±1-2 line boundary shifts are the typical
`temperature=0` variance pattern for extraction-style tasks, based on
general experience with this model family. This sandbox's lack of
network access means that could not be empirically measured for this
submission; it is flagged here as something to verify manually once
network/API access is available, rather than asserted as a result.

## Three failure cases

### Failure case 1 — Ambiguous topic boundary on a recurring subject

- **What the system produced:** three separate topics (12, 14, 19) all
  concerning PEAKS loan enforceability, with boundaries drawn at points
  where counsel visibly changed sub-question (documentation defects →
  post-origination events → timing of any determination).
- **What it arguably should have produced:** a reasonable alternative
  segmentation could treat this as one long topic with three
  sub-headings, or could draw the boundaries a few lines earlier/later
  at some of the transition points (e.g. the transition at page 60 is a
  gradual pivot in the witness's own answer, not a clean question
  boundary).
- **Why it happened:** the witness's testimony on this subject is
  genuinely non-linear — opposing counsel returns to it three times
  across roughly 40 pages, sometimes mid-answer. Chunk-level topic
  detection makes a local decision about where a topic starts/ends
  within its own window and does not have a reason to always favor one
  granularity over another. This is a **flagged-for-manual-review** case
  rather than a system bug: the underlying citations are all accurate,
  but the specific 3-way split is a judgment call.
- **How it could be improved:** a second LLM pass shown all three
  enforceability-labeled candidates together (rather than one chunk at a
  time) could be asked specifically "should these be one topic or
  three?" — deferring exactly this kind of cross-chunk judgment call to
  a dedicated step instead of leaving it to whichever chunk saw it first.

### Failure case 2 — Hallucinated location (caught by validation)

- **What the system produced (raw, pre-validation):** a candidate topic
  "Witness's Compensation Arrangement" citing page 8, line 99.
- **What it should have produced:** nothing — no such testimony exists in
  the transcript, and this deposition transcript's pages never exceed 25
  lines, so line 99 cannot exist on any page.
- **Why it failed:** this was a synthetic test case deliberately added to
  `outputs/_llm_offline_cache.json` (see `llm_usage.md`) specifically to
  confirm the provenance validator actually rejects invented locations
  rather than only being described as doing so.
- **How it could be improved:** it already was — this is the system
  working as designed. `validate_topic()` rejected it with reason
  `"start location (8, 99) does not exist in the supplied deposition"`
  and it never reached `outputs/index.json`. The only further
  improvement would be running this kind of adversarial test with a live
  model's real hallucinations (not a synthetic one) once API access is
  available, to confirm real-world hallucination rates and patterns.

### Failure case 3 — Real citation, fabricated evidence text (caught by validation)

- **What the system produced (raw, pre-validation):** a candidate topic
  "Discussion of Witness's Prior Depositions" citing the real location
  page 7, line 17 — but with a supporting quote ("Ms. Yu stated she had
  testified in over a dozen prior depositions") that is not what page 7,
  line 17 actually says (it reads "you've ever had your deposition taken
  before.").
- **What it should have produced:** either the real quote at that
  location, or (since the real testimony at that location is "have you
  ever had a deposition taken before" — to which the witness answers "I
  have not") no topic at all, since this transcript does not actually
  contain any discussion of prior depositions to index.
- **Why it failed:** also a deliberately injected synthetic test case,
  designed to test the specific failure mode where a model cites a
  *real, existing* page/line but pairs it with fabricated content — a
  more subtle and more dangerous error than an outright invalid location,
  since a naive "does this page/line exist" check alone would pass it.
- **How it could be improved:** already caught, by the text-match check
  in `validate_topic()` (reason: `"supporting evidence text does not
  match the cited page/line"`). A stronger version of this check (exact
  substring match rather than a leading-15-character heuristic) would
  catch more subtle fabrications at the cost of more false rejections
  when an LLM lightly paraphrases; this is a tunable precision/recall
  trade-off flagged here rather than resolved, since it needs real
  (non-synthetic) live-model output to tune properly.

## Limitations

- **LLM variability.** Live-API topic detection is not guaranteed
  bit-for-bit stable across runs even at `temperature=0`; see the
  stability section above. This submission's offline-cache run cannot
  measure that variability directly.
- **Subjective topic boundaries.** As Failure Case 1 shows, reasonable
  reviewers can disagree on exactly where one topic ends and another
  begins, especially for a subject counsel returns to repeatedly. The
  system reports one defensible segmentation, not "the" correct one —
  an attorney should treat the index as a navigation aid, not a
  substitute for reading the cited passages.
- **Topic granularity** is a judgment call with no ground truth; a
  different (also reasonable) granularity setting could produce 12
  topics or 30 from the same transcript. 20 was chosen here as
  appropriate for a ~90-page single-witness examination.
- **Overlapping topics.** The merge step (Section 5 of
  `methodology.md`) is deliberately conservative and can leave two
  genuinely-identical topics unmerged if their labels don't share enough
  text in common — this is flagged as a case needing manual review
  rather than something the current heuristic resolves automatically.
- **PDF extraction** depends on the reporter's own printed line numbers
  being present and machine-readable (true for this Veritext transcript
  and most U.S. court-reporter output, but not universal — a scanned,
  unlicensed, or non-standard transcript format would need OCR or a
  different extraction strategy, neither of which this prototype
  implements).
- **Scaling.** This run processed one ~90-page deposition in a single
  pipeline invocation. A multi-hundred-page transcript, or a batch of
  many depositions, would need chunk-level parallelization and
  rate-limit handling that this prototype does not implement (it is
  intentionally simple, per the brief).
- Anything above marked "flagged for manual review" is exactly that —
  not something this report claims to have resolved automatically.
