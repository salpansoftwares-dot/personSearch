"""
Extraction module.

Reads source text and calls the model adapter to produce structured claims.
Each claim must include a verbatim evidence_span that exists in the source text.
Claims that fail span verification are dropped here — they never reach storage.
"""

import structlog
from pydantic import BaseModel, Field

from app.core.ai.model_adapter import ModelAdapter
from app.core.scope_filter import filter_claims

logger = structlog.get_logger(__name__)

_SYSTEM_INSTRUCTION = """
You are a structured-data extraction assistant for a professional profile system.
Extract ONLY factual professional claims visible in the source text.
For each claim you MUST include the exact verbatim quote (evidence_span) from the source.
Do NOT fabricate, infer, or add information not present in the text.
Do NOT extract home addresses, personal contacts, relationships, or health information.
Return ONLY valid JSON.
""".strip()

_PROMPT_TEMPLATE = """
Source URL: {url}
Source text (excerpt):
---
{text}
---

Extract professional claims about the person named: {name}

Return a JSON object with this structure:
{{
  "claims": [
    {{
      "claim_type": "<one of: occupation|organization|role|publication|talk|education|profile_url|project>",
      "value": "<extracted value>",
      "evidence_span": "<exact verbatim quote from the source text above>"
    }}
  ]
}}

Rules:
- evidence_span MUST be a substring of the source text above.
- If you cannot find a verbatim span, omit the claim entirely.
- Do NOT include any claim type not listed above.
""".strip()


class RawClaim(BaseModel):
    claim_type: str
    value: str
    evidence_span: str = Field(..., min_length=3)


class ExtractionResult(BaseModel):
    claims: list[RawClaim] = Field(default_factory=list)


def _verify_span(claim: dict, source_text: str) -> bool:
    """Return True if the evidence_span appears verbatim in the source."""
    span = claim.get("evidence_span", "")
    if not span or span not in source_text:
        logger.warning(
            "extraction.span_verification_failed",
            claim_type=claim.get("claim_type"),
            value=claim.get("value"),
            span_preview=span[:80],
        )
        return False
    return True


async def extract_claims(
    *,
    source_url: str,
    source_text: str,
    target_name: str,
    source_id: str,
    adapter: ModelAdapter,
) -> list[dict]:
    """
    Extract and validate claims from a single source.

    Pipeline:
      1. Call model adapter (structured JSON output, no tools).
      2. Span verification — drop any claim whose evidence_span is not
         literally present in source_text.
      3. Scope filter — drop any claim whose type is not on the allowlist.

    Returns a list of verified, in-scope claim dicts.
    """
    import asyncio

    prompt = _PROMPT_TEMPLATE.format(
        url=source_url,
        text=source_text[:6000],  # cap to keep extraction fast and responsive
        name=target_name,
    )

    try:
        raw = await asyncio.wait_for(
            adapter.complete(
                prompt=prompt,
                response_schema=ExtractionResult,
                model_tier="extraction",
                system_instruction=_SYSTEM_INSTRUCTION,
                source_id=source_id,
                stage="extraction",
            ),
            timeout=25.0,
        )
        raw_claims = [c.model_dump() if hasattr(c, "model_dump") else c for c in raw.get("claims", [])]
    except Exception as exc:
        logger.error("extraction.failed", source_url=source_url, error=str(exc))
        return []

    # Step 1: Span verification.
    span_verified = [c for c in raw_claims if _verify_span(c, source_text)]
    logger.info(
        "extraction.span_verification",
        total=len(raw_claims),
        verified=len(span_verified),
        dropped=len(raw_claims) - len(span_verified),
    )

    # Step 2: Scope filter.
    scoped = filter_claims(span_verified)
    return scoped
