"""
V1.5 Entity Resolution Evaluation Harness.

Measures:
  - Pairwise false-merge rate on ambiguous same-name pairs (Kenyan + international).
  - True-merge rate (should-merge pairs that were correctly merged).
  - False-merge rate must remain below the agreed target (default 5%).

Covers common Kenyan names (Kamau, Otieno, Wanjiku, Odhiambo, Mwangi, etc.)
and common internationally ambiguous names (John Smith, Li Wei, Mohammed Ali, etc.).

Usage:
    python tests/evaluate_entity_resolution.py

Exit code 0 = all thresholds met.
Exit code 1 = false-merge rate or true-merge rate out of threshold.
"""

import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.entity_resolution import (
    evaluate_pairwise_merge,
    PersonCluster,
)

# ── Thresholds ─────────────────────────────────────────────────────────────────
MAX_FALSE_MERGE_RATE = 0.05   # Must be ≤ 5 %
MIN_TRUE_MERGE_RATE  = 0.70   # Must be ≥ 70 %


# ── Test corpus ────────────────────────────────────────────────────────────────
# Each entry is (profile_a, profile_b, should_merge: bool, label: str)
# Profiles are minimal dicts matching CandidateProfile structure.

def _p(name, employer=None, title=None, sources=None, handles=None):
    """Helper: build a minimal candidate profile dict."""
    return {
        "name": name,
        "employer": employer,
        "title": title,
        "sources": sources or [],
        "handles": handles or {},
    }


EVAL_PAIRS: list[tuple[dict, dict, bool, str]] = [

    # ── Kenyan same-name, DIFFERENT people (must NOT merge) ──────────────────
    (
        _p("John Kamau", employer="Safaricom PLC", title="Software Engineer"),
        _p("John Kamau", employer="Kenya Power", title="Electrical Engineer"),
        False,
        "KE: John Kamau — different employers, different sector",
    ),
    (
        _p("Grace Wanjiku", employer="Equity Bank", title="Branch Manager"),
        _p("Grace Wanjiku", employer="KCB Group", title="Credit Analyst"),
        False,
        "KE: Grace Wanjiku — different banks, different roles",
    ),
    (
        _p("Peter Otieno", employer="University of Nairobi", title="Lecturer"),
        _p("Peter Otieno", employer="Strathmore University", title="Professor"),
        False,
        "KE: Peter Otieno — different universities",
    ),
    (
        _p("Samuel Odhiambo", employer="Nation Media Group", title="Journalist"),
        _p("Samuel Odhiambo", employer="Standard Group", title="Reporter"),
        False,
        "KE: Samuel Odhiambo — different media houses",
    ),
    (
        _p("Mary Mwangi", employer="Nairobi Hospital", title="Nurse"),
        _p("Mary Mwangi", employer="Kenyatta National Hospital", title="Clinical Officer"),
        False,
        "KE: Mary Mwangi — different hospitals, different titles",
    ),
    (
        _p("David Njoroge", employer="PwC Kenya", title="Audit Associate"),
        _p("David Njoroge", employer="KPMG Kenya", title="Tax Manager"),
        False,
        "KE: David Njoroge — different Big-4 firms",
    ),
    (
        _p("Lucy Achieng", employer="Kenya Red Cross", title="Field Officer"),
        _p("Lucy Achieng", employer="UNHCR Kenya", title="Protection Officer"),
        False,
        "KE: Lucy Achieng — different NGOs, different functions",
    ),
    (
        _p("James Kipchoge", employer="Athletics Kenya", title="Athlete"),
        _p("James Kipchoge", employer="Rift Valley Sports Club", title="Coach"),
        False,
        "KE: James Kipchoge — athlete vs coach, different orgs",
    ),

    # ── International same-name, DIFFERENT people (must NOT merge) ───────────
    (
        _p("Mohammed Ali", employer="Al Jazeera", title="Correspondent"),
        _p("Mohammed Ali", employer="BBC Arabic", title="Presenter"),
        False,
        "INT: Mohammed Ali — different broadcasters",
    ),
    (
        _p("Li Wei", employer="Tsinghua University", title="Professor of Chemistry"),
        _p("Li Wei", employer="Peking University", title="Associate Professor of Physics"),
        False,
        "INT: Li Wei — different universities, different disciplines",
    ),
    (
        _p("John Smith", employer="Goldman Sachs", title="Analyst"),
        _p("John Smith", employer="Morgan Stanley", title="Trader"),
        False,
        "INT: John Smith — different banks, different roles",
    ),
    (
        _p("Maria Garcia", employer="Universidad de Madrid", title="Researcher"),
        _p("Maria Garcia", employer="Universidad de Barcelona", title="Lecturer"),
        False,
        "INT: Maria Garcia — different Spanish universities",
    ),
    (
        _p("Ahmed Hassan", employer="Egyptian Ministry of Health", title="Director"),
        _p("Ahmed Hassan", employer="Cairo University Hospital", title="Consultant"),
        False,
        "INT: Ahmed Hassan — ministry vs hospital",
    ),

    # ── SAME person, should merge ─────────────────────────────────────────────
    (
        _p(
            "Jane Muthoni",
            employer="Andela",
            title="Software Engineer",
            sources=["https://linkedin.com/in/janemuthoni"],
            handles={"github": "janemuthoni"},
        ),
        _p(
            "Jane Muthoni",
            employer="Andela",
            title="Software Engineer",
            sources=["https://github.com/janemuthoni"],
            handles={"github": "janemuthoni"},
        ),
        True,
        "KE: Jane Muthoni — same employer + shared GitHub handle → should merge",
    ),
    (
        _p(
            "Amina Osman",
            employer="African Union",
            title="Policy Analyst",
            sources=["https://au.int/staff/aminaosman"],
        ),
        _p(
            "Amina Osman",
            employer="African Union",
            title="Policy Analyst",
            sources=["https://linkedin.com/in/aminaosman-au"],
        ),
        True,
        "INT: Amina Osman — same employer, AU domain cross-link → should merge",
    ),
    (
        _p(
            "Kevin Mutua",
            employer="iHub Nairobi",
            title="Community Manager",
            handles={"twitter": "@kevinmutua_ke"},
        ),
        _p(
            "Kevin Mutua",
            employer="iHub",
            title="Community Manager",
            handles={"twitter": "@kevinmutua_ke"},
        ),
        True,
        "KE: Kevin Mutua — same role, shared Twitter handle, employer abbreviation → should merge",
    ),
]


# ── Resolver shim ──────────────────────────────────────────────────────────────
# EntityResolver operates on full PersonCluster lists. For evaluation we build
# minimal clusters from pairs and check if they merge.

def _build_cluster(profile: dict, cluster_id: str) -> PersonCluster:
    """Convert a minimal profile dict into a PersonCluster for the resolver."""
    return PersonCluster(
        cluster_id=cluster_id,
        canonical_name=profile["name"],
        claims=[
            {"claim_type": "occupation", "value": profile["title"] or "", "confidence": 0.9,
             "source_url": (profile["sources"] or ["https://example.com"])[0], "evidence_span": profile["title"] or ""},
            {"claim_type": "organization", "value": profile["employer"] or "", "confidence": 0.9,
             "source_url": (profile["sources"] or ["https://example.com"])[0], "evidence_span": profile["employer"] or ""},
        ] if profile.get("title") or profile.get("employer") else [],
        score=0.6,
        source_urls=profile["sources"],
    )


def _would_merge(profile_a: dict, profile_b: dict) -> bool:
    """
    Use evaluate_pairwise_merge to check whether two profiles should be merged.
    Returns True if the resolver decides to merge them.
    """
    cluster_a = _build_cluster(profile_a, "eval_a")
    cluster_b = _build_cluster(profile_b, "eval_b")
    should_merge, score, signals = evaluate_pairwise_merge(cluster_a, cluster_b)
    return should_merge


# ── Evaluation runner ──────────────────────────────────────────────────────────

def run_evaluation() -> int:
    """Run all evaluation pairs and print a report. Returns exit code."""

    total         = len(EVAL_PAIRS)
    true_positives  = 0   # should_merge=True  and DID merge
    true_negatives  = 0   # should_merge=False and did NOT merge
    false_positives = 0   # should_merge=False but DID merge   ← false merge
    false_negatives = 0   # should_merge=True  but did NOT merge

    fp_labels: list[str] = []
    fn_labels: list[str] = []

    for profile_a, profile_b, should_merge, label in EVAL_PAIRS:
        merged = _would_merge(profile_a, profile_b)

        if should_merge and merged:
            true_positives += 1
        elif not should_merge and not merged:
            true_negatives += 1
        elif not should_merge and merged:
            false_positives += 1
            fp_labels.append(label)
        else:  # should_merge and not merged
            false_negatives += 1
            fn_labels.append(label)

    should_not_merge_total = sum(1 for _, _, s, _ in EVAL_PAIRS if not s)
    should_merge_total     = sum(1 for _, _, s, _ in EVAL_PAIRS if s)

    false_merge_rate = false_positives / max(should_not_merge_total, 1)
    true_merge_rate  = true_positives  / max(should_merge_total, 1)

    width = 72
    print("=" * width)
    print("  PERSONSEARCH ENTITY RESOLUTION EVALUATION REPORT (V1.5 HARNESS)")
    print("=" * width)
    print(f"Total Evaluation Pairs        : {total}")
    print(f"  Should-merge pairs          : {should_merge_total}")
    print(f"  Should-NOT-merge pairs      : {should_not_merge_total}")
    print("-" * width)
    print(f"True Positives  (correct merge)    : {true_positives}")
    print(f"True Negatives  (correct separate) : {true_negatives}")
    print(f"False Positives (false merge)      : {false_positives}   ← MUST be 0 at ≤{MAX_FALSE_MERGE_RATE:.0%}")
    print(f"False Negatives (missed merge)     : {false_negatives}")
    print("-" * width)
    print(f"False-Merge Rate : {false_merge_rate:.2%}  (target ≤ {MAX_FALSE_MERGE_RATE:.0%})")
    print(f"True-Merge Rate  : {true_merge_rate:.2%}   (target ≥ {MIN_TRUE_MERGE_RATE:.0%})")
    print("=" * width)

    passed = True

    if false_merge_rate > MAX_FALSE_MERGE_RATE:
        print(f"\n❌ FAIL — false-merge rate {false_merge_rate:.2%} exceeds {MAX_FALSE_MERGE_RATE:.0%} target.")
        for lbl in fp_labels:
            print(f"   → FALSE MERGE: {lbl}")
        passed = False

    if true_merge_rate < MIN_TRUE_MERGE_RATE:
        print(f"\n❌ FAIL — true-merge rate {true_merge_rate:.2%} is below {MIN_TRUE_MERGE_RATE:.0%} target.")
        for lbl in fn_labels:
            print(f"   → MISSED MERGE: {lbl}")
        passed = False

    if passed:
        print("\n✅ PASS — all entity resolution thresholds met.")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run_evaluation())
