import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import copy

from depoindex.pipeline import (
    TranscriptLine,
    validate_topic,
    offline_semantic_validate_topic,
)


def make_lines():
    return [
        TranscriptLine(
            page=7,
            line=12,
            text="Q Good afternoon, Ms. Yu. My name's John Purcell.",
        ),
        TranscriptLine(
            page=7,
            line=13,
            text="I represent the defendants, and we will discuss the deposition.",
        ),
        TranscriptLine(
            page=7,
            line=14,
            text="THE WITNESS: Good afternoon.",
        ),
    ]


def make_line_index():
    return {
        (record.page, record.line): record.text
        for record in make_lines()
    }
def valid_topic():
    return {
        "topic": "Deposition Discussion",
        "subtopic": "Opening discussion",
        "start_page": 7,
        "start_line": 12,
        "end_page": 7,
        "end_line": 13,
        "supporting_evidence": {
            "page": 7,
            "line": 12,
            "quote": "Q Good afternoon, Ms. Yu. My name's John Purcell.",
        },
    }


def test_valid_topic_passes():
    result = validate_topic(valid_topic(), make_line_index())
    assert result.valid is True


def test_missing_subtopic_is_rejected():
    topic = copy.deepcopy(valid_topic())
    topic.pop("subtopic")

    result = validate_topic(topic, make_lines())
    assert result.valid is False


def test_nonexistent_location_is_rejected():
    topic = copy.deepcopy(valid_topic())
    topic["start_page"] = 999
    topic["end_page"] = 999

    result = validate_topic(topic, make_lines())
    assert result.valid is False


def test_fabricated_evidence_is_rejected():
    topic = copy.deepcopy(valid_topic())
    topic["supporting_evidence"]["quote"] = "This sentence does not exist."

    result = validate_topic(topic, make_lines())
    assert result.valid is False


def test_semantic_validator_rejects_unrelated_topic():
    topic = copy.deepcopy(valid_topic())
    topic["topic"] = "Quantum Computing Hardware"
    topic["subtopic"] = "Superconducting qubits"

    result = offline_semantic_validate_topic(topic, make_lines())
    assert result.valid is False


def test_semantic_validator_accepts_supported_topic():
    result = offline_semantic_validate_topic(valid_topic(), make_lines())
    assert result.valid is True


if __name__ == "__main__":
    tests = [
        test_valid_topic_passes,
        test_missing_subtopic_is_rejected,
        test_nonexistent_location_is_rejected,
        test_fabricated_evidence_is_rejected,
        test_semantic_validator_rejects_unrelated_topic,
        test_semantic_validator_accepts_supported_topic,
    ]

    for test in tests:
        test()
        print(f"PASS: {test.__name__}")

    print(f"\nAll {len(tests)} adversarial validation tests passed.")