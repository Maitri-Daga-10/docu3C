# DepoIndex Validation Report

## End-to-End Run

- PDF backend: pymupdf
- LLM mode: offline_cache
- Transcript lines extracted: 2036
- Raw topics proposed: 24
- Provenance accepted: 21
- Provenance rejected: 3
- Semantic validation checked: 21
- Semantic validation accepted: 16
- Semantic validation rejected: 5
- Final topics after overlap merge: 15

## Validation Chain

The pipeline applies validation in this order:

1. PDF transcript extraction.
2. Topic generation from the offline cache or live OpenAI API.
3. Deterministic provenance validation of topic locations and evidence.
4. Semantic validation of the topic, subtopic, and supporting evidence.
5. Merge of overlapping validated topics only.
6. Final export to `index.json` and `index.md`.

A final-export invariant verifies that every exported topic has
`semantic_validation.valid == true`.

## Provenance Rejections

- **Digression: Formatting of Expert Report Paragraph Numbers**: supporting evidence text does not match the cited page/line span\n- **Witness's Compensation Arrangement**: start location (8, 99) does not exist in the supplied deposition; end location (8, 100) does not exist in the supplied deposition; supporting evidence location (8, 99) does not exist in the supplied deposition\n- **Discussion of Witness's Prior Depositions**: supporting evidence text does not match the cited page/line span\n
## Semantic Rejections

- **Deposition Ground Rules and Admonitions**: topic/subtopic has insufficient lexical support in transcript span (coverage=0.17)\n- **Legislative and Regulatory Advocacy Record**: topic/subtopic has insufficient lexical support in transcript span (coverage=0.20)\n- **Scope of Opinion on PEAKS Loan Enforceability and Documentation Defects**: supporting evidence is not contained in the cited transcript span\n- **Regulatory and Enforcement History: CFPB, SEC, and State AG Actions Against ITT/PEAKS**: topic/subtopic has insufficient lexical support in transcript span (coverage=0.27)\n- **Witness's Self-Assessment as a Non-Investigator**: topic/subtopic has insufficient lexical support in transcript span (coverage=0.20)\n
## Final Export

The final exported topic count is derived only from topics that passed
both provenance and semantic validation. Overlapping validated topics
may be merged, so the final count can be lower than the semantic
validation accepted count.

The current run produced a non-empty final index and retained explicit
rejection records for invalid candidates.
