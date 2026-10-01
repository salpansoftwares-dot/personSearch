"""
Automated tests for the Labelled Evaluation Set and Extraction Benchmark.

Validates that:
  1. The labelled evaluation dataset is structurally valid and spans are 100% verbatim.
  2. Hallucinated / altered spans are strictly dropped by span verification.
  3. The extraction benchmark meets V1 exit criteria (precision >= 85%, 0 leaks).
"""

import json
from pathlib import Path
import pytest

from tests.evaluate_extraction import (
    EVAL_DATA_PATH,
    load_eval_dataset,
    run_evaluation,
)
from app.core.extraction import extract_claims, _verify_span


def test_labelled_dataset_integrity():
    """Verify that every ground truth claim in the evaluation set is valid."""
    assert EVAL_DATA_PATH.exists(), f"Evaluation dataset not found at {EVAL_DATA_PATH}"
    dataset = load_eval_dataset()

    assert len(dataset) >= 10, f"Expected at least 10 evaluation examples, found {len(dataset)}"

    allowlisted_types = {
        "occupation",
        "organization",
        "role",
        "publication",
        "talk",
        "education",
        "profile_url",
        "project",
    }

    for ex in dataset:
        assert "example_id" in ex
        assert "target_name" in ex
        assert "source_text" in ex
        assert "source_url" in ex
        assert "ground_truth_claims" in ex

        source_text = ex["source_text"]

        for gt in ex["ground_truth_claims"]:
            assert gt["claim_type"] in allowlisted_types, (
                f"Invalid claim_type {gt['claim_type']} in {ex['example_id']}"
            )
            # Verbatim span check
            span = gt["evidence_span"]
            assert span in source_text, (
                f"Span '{span}' is not a verbatim substring of source_text in {ex['example_id']}"
            )


@pytest.mark.asyncio
async def test_span_verification_rejects_hallucinations():
    """Simulate an LLM fabricating an employer or role that is not in the text."""
    source_text = "Alice Cooper works as Senior Auditor at Ernst & Young in London."

    # Valid span
    valid_claim = {
        "claim_type": "occupation",
        "value": "Senior Auditor",
        "evidence_span": "Alice Cooper works as Senior Auditor",
    }
    assert _verify_span(valid_claim, source_text) is True

    # Hallucinated span (not in source text)
    fabricated_claim = {
        "claim_type": "organization",
        "value": "PwC",
        "evidence_span": "works at PwC in London",
    }
    assert _verify_span(fabricated_claim, source_text) is False


@pytest.mark.asyncio
async def test_extraction_benchmark_meets_v1_exit_criteria():
    """Run the evaluation benchmark and assert it meets the V1 exit criteria."""
    results = await run_evaluation(live=False)

    assert results["total_examples"] >= 10
    assert results["span_verification_failures"] == 0, "Span verification failures must be 0"
    assert results["out_of_scope_leaks"] == 0, "Out-of-scope personal data leaks must be 0"
    assert results["precision"] >= 0.85, f"Precision {results['precision']:.2f} must be >= 0.85"
    assert results["recall"] >= 0.85, f"Recall {results['recall']:.2f} must be >= 0.85"
