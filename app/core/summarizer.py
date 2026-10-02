"""
Profile Summarizer module.

Architecture principle:
"Writes a short summary from verified claims only.
Each sentence must cite a claim ID; untraceable sentences are removed.
Never delegated to AI: Filling gaps from the model's own knowledge: if no source says it, the profile does not."
"""

import uuid
from typing import Any
import structlog
from pydantic import BaseModel, Field

from app.core.ai.model_adapter import ModelAdapter
from app.schemas.search import CitedSentence, ProfileSummary

logger = structlog.get_logger(__name__)


class LLMSentenceCitation(BaseModel):
    text: str = Field(..., description="A single factual sentence strictly grounded in the verified claims.")
    claim_ids: list[str] = Field(..., description="List of claim UUIDs that directly support this sentence.")


class LLMSummaryResponse(BaseModel):
    sentences: list[LLMSentenceCitation] = Field(default_factory=list)


def validate_and_filter_sentences(
    raw_sentences: list[dict[str, Any]],
    valid_claim_ids: set[uuid.UUID],
) -> list[CitedSentence]:
    """
    Guardrail:
    1. Parse and validate each cited claim ID against the person's real verified claims.
    2. Any sentence lacking valid verified claim citations is untraceable and is DROPPED.
    3. Invalid citation IDs are filtered out.
    """
    validated: list[CitedSentence] = []
    for item in raw_sentences:
        text = (item.get("text") or "").strip()
        raw_ids = item.get("claim_ids") or []
        if not text:
            continue

        valid_cids: list[uuid.UUID] = []
        for raw in raw_ids:
            try:
                cid = uuid.UUID(str(raw)) if not isinstance(raw, uuid.UUID) else raw
                if cid in valid_claim_ids and cid not in valid_cids:
                    valid_cids.append(cid)
            except (ValueError, TypeError):
                continue

        if valid_cids:
            validated.append(CitedSentence(text=text, claim_ids=valid_cids))
        else:
            logger.warning(
                "summarizer.untraceable_sentence_dropped",
                text=text[:80],
                reason="no_valid_claim_citations",
            )

    return validated


def synthesize_cited_summary(
    canonical_name: str,
    claims: list[dict | Any],
) -> ProfileSummary:
    """
    Deterministic rule-based summary synthesizer.
    Generates structured, grammatically clean sentences citing verified claim IDs directly.
    Guarantees reliable cited summaries offline and when LLM is unavailable.
    """
    occupations: list[tuple[str, uuid.UUID]] = []
    organizations: list[tuple[str, uuid.UUID]] = []
    education: list[tuple[str, uuid.UUID]] = []
    publications: list[tuple[str, uuid.UUID]] = []
    talks: list[tuple[str, uuid.UUID]] = []
    projects: list[tuple[str, uuid.UUID]] = []

    for c in claims:
        ctype = getattr(c, "type", None) or getattr(c, "claim_type", None) or (c.get("claim_type") or c.get("type") if isinstance(c, dict) else None)
        val = getattr(c, "value", None) or (c.get("value") if isinstance(c, dict) else None)
        cid = getattr(c, "claim_id", None) or getattr(c, "id", None) or (c.get("claim_id") or c.get("id") if isinstance(c, dict) else None)

        if not val or not cid:
            continue
        try:
            cid_uuid = uuid.UUID(str(cid)) if not isinstance(cid, uuid.UUID) else cid
        except (ValueError, TypeError):
            continue

        val_str = str(val).strip()
        if ctype in ("occupation", "role"):
            occupations.append((val_str, cid_uuid))
        elif ctype == "organization":
            organizations.append((val_str, cid_uuid))
        elif ctype == "education":
            education.append((val_str, cid_uuid))
        elif ctype == "publication":
            publications.append((val_str, cid_uuid))
        elif ctype == "talk":
            talks.append((val_str, cid_uuid))
        elif ctype == "project":
            projects.append((val_str, cid_uuid))

    sentences: list[CitedSentence] = []

    # 1. Role & Organization sentence
    if occupations and organizations:
        role, role_id = occupations[0]
        org, org_id = organizations[0]
        sentences.append(
            CitedSentence(
                text=f"{canonical_name} is a {role} at {org}.",
                claim_ids=[role_id, org_id] if role_id != org_id else [role_id],
            )
        )
    elif occupations:
        role, role_id = occupations[0]
        sentences.append(
            CitedSentence(
                text=f"{canonical_name} is a {role}.",
                claim_ids=[role_id],
            )
        )
    elif organizations:
        org, org_id = organizations[0]
        sentences.append(
            CitedSentence(
                text=f"{canonical_name} is affiliated with {org}.",
                claim_ids=[org_id],
            )
        )

    # 2. Education sentence
    if education:
        edu, edu_id = education[0]
        sentences.append(
            CitedSentence(
                text=f"Educational background includes {edu}.",
                claim_ids=[edu_id],
            )
        )

    # 3. Publications / Talks
    pub_list = publications + talks
    if pub_list:
        pub, pub_id = pub_list[0]
        sentences.append(
            CitedSentence(
                text=f'Authored or presented works include "{pub}".',
                claim_ids=[pub_id],
            )
        )

    # 4. Key projects
    if projects:
        proj, proj_id = projects[0]
        sentences.append(
            CitedSentence(
                text=f"Associated with key project: {proj}.",
                claim_ids=[proj_id],
            )
        )

    full_text = " ".join(s.text for s in sentences)
    return ProfileSummary(full_text=full_text, sentences=sentences)


async def generate_profile_summary(
    canonical_name: str,
    claims: list[dict | Any],
    adapter: ModelAdapter | None = None,
) -> ProfileSummary:
    """
    Generate an evidence-grounded profile summary where every sentence cites verified claim IDs.
    """
    if not claims:
        return ProfileSummary(full_text="", sentences=[])

    valid_claim_ids: set[uuid.UUID] = set()
    claim_items: list[dict[str, str]] = []

    for c in claims:
        cid = getattr(c, "claim_id", None) or getattr(c, "id", None) or (c.get("claim_id") or c.get("id") if isinstance(c, dict) else None)
        ctype = getattr(c, "type", None) or getattr(c, "claim_type", None) or (c.get("claim_type") or c.get("type") if isinstance(c, dict) else None)
        val = getattr(c, "value", None) or (c.get("value") if isinstance(c, dict) else None)

        if not cid or not val:
            continue
        try:
            cid_uuid = uuid.UUID(str(cid)) if not isinstance(cid, uuid.UUID) else cid
            valid_claim_ids.add(cid_uuid)
            claim_items.append({"id": str(cid_uuid), "type": str(ctype or "info"), "value": str(val)})
        except (ValueError, TypeError):
            continue

    if not valid_claim_ids:
        return ProfileSummary(full_text="", sentences=[])

    # Attempt AI summary if adapter is configured with a strict 3.5s timeout
    if adapter is not None:
        import asyncio
        try:
            claims_text = "\n".join(f"- ID: {item['id']} | {item['type']}: {item['value']}" for item in claim_items[:12])
            prompt = (
                f"Write a concise, professional summary for '{canonical_name}' based ONLY on the verified claims below.\n"
                f"RULES:\n"
                f"1. Every sentence MUST be directly grounded in the verified claims provided.\n"
                f"2. Each sentence MUST cite the claim UUID(s) that support it.\n"
                f"3. NEVER assume, invent, or add information not explicitly in the claims.\n"
                f"4. If no claims are relevant, return an empty list of sentences.\n\n"
                f"VERIFIED CLAIMS:\n{claims_text}\n\n"
                f"Output strictly JSON conforming to the schema."
            )
            res = await asyncio.wait_for(
                adapter.complete(
                    prompt=prompt,
                    response_schema=LLMSummaryResponse,
                    model_tier="extraction",
                    system_instruction="You are an evidence-grounded summarizer. Every sentence must cite verified claim IDs.",
                    stage="profile_summary",
                ),
                timeout=3.5,
            )
            raw_sentences = res.get("sentences", [])
            validated = validate_and_filter_sentences(raw_sentences, valid_claim_ids)
            if validated:
                full_text = " ".join(s.text for s in validated)
                return ProfileSummary(full_text=full_text, sentences=validated)
        except Exception as exc:
            logger.info("summarizer.ai_fallback", error=str(exc))

    # Instant fallback to deterministic synthesis (0.1ms)
    return synthesize_cited_summary(canonical_name, claims)

