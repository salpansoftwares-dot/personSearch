"""
Query Understanding module.

Takes free-text user input and returns a structured QueryContext:
  - canonical name
  - name variants (transliterations, initials, common short forms)
  - optional hints (organization, sector, country, role)

AI is used to generate name variants only. The output is schema-
constrained and shown to the user, never silently acted upon.
"""

from pydantic import BaseModel, Field

import structlog

from app.core.ai.model_adapter import ModelAdapter
from app.schemas.search import SearchHints, SearchRequest

logger = structlog.get_logger(__name__)

_SYSTEM_INSTRUCTION = """
You are a name-parsing assistant for a professional profile discovery system.
Given a name and optional hints, return ONLY valid JSON matching the required schema.
Do NOT add information not present in the input.
Do NOT infer sensitive attributes.
""".strip()

_PROMPT_TEMPLATE = """
Parse the following search input.

Name: {name}
Hints: {hints}

Return a JSON object with these fields:
  canonical_name   (string)         — the name as given, cleaned of extra whitespace
  name_variants    (list of strings) — plausible spellings, transliterations, initials
                                       variants (e.g. "John K. Kamau" → ["J. Kamau", "John Kamau"])
  hints            (object)          — pass through any organization, sector, country, role from input

Return ONLY the JSON object, no explanation.
""".strip()


class QueryContext(BaseModel):
    """Structured output of the query understanding stage."""
    canonical_name: str = Field(..., min_length=1)
    name_variants: list[str] = Field(default_factory=list)
    hints: dict = Field(default_factory=dict)


async def understand_query(
    request: SearchRequest,
    adapter: ModelAdapter,
) -> QueryContext:
    """
    Parse the user's search request into a QueryContext.

    Falls back to a deterministic minimal context if the AI call fails,
    so a temporary model outage never breaks the search entirely.
    """
    import asyncio
    hints_text = request.hints.model_dump(exclude_none=True)
    prompt = _PROMPT_TEMPLATE.format(name=request.name, hints=hints_text)

    # Pre-generate deterministic name variants for immediate fallback
    clean_name = request.name.strip()
    parts = clean_name.split()
    fallback_variants = [clean_name]
    if len(parts) >= 2:
        fallback_variants.append(f"{parts[0][0]}. {' '.join(parts[1:])}")
        fallback_variants.append(f"{parts[0]} {parts[-1]}")
    fallback_ctx = QueryContext(
        canonical_name=clean_name,
        name_variants=list(dict.fromkeys(fallback_variants)),
        hints=hints_text,
    )

    try:
        raw = await asyncio.wait_for(
            adapter.complete(
                prompt=prompt,
                response_schema=QueryContext,
                model_tier="extraction",
                system_instruction=_SYSTEM_INSTRUCTION,
                stage="query_understanding",
            ),
            timeout=8.0,
        )
        ctx = QueryContext(**raw)
        logger.info(
            "query_understanding.success",
            canonical=ctx.canonical_name,
            variants=ctx.name_variants,
        )
        return ctx
    except Exception as exc:
        logger.info(
            "query_understanding.fast_fallback",
            error=str(exc),
            name=request.name,
        )
        return fallback_ctx

