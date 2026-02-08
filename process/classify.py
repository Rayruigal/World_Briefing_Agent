"""LLM-based classification of news items.

The LLM client is behind a thin interface (process/llm.py) so you can swap
providers by changing environment variables.  Supports OpenAI and Azure OpenAI.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Sequence

from process.llm import chat_completion_kwargs, get_client, get_model, is_reasoning_model
from storage.models import NormalizedItem

log = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────────
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"
_PROMPT_TEMPLATE: str | None = None


def _load_prompt() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")
    return _PROMPT_TEMPLATE


# ── Format helpers ───────────────────────────────────────────────────

def _format_taxonomy(cat_config: dict) -> str:
    """Render the hierarchical taxonomy into a readable text block for the LLM."""
    taxonomy = cat_config.get("taxonomy", {})
    lines: list[str] = []
    for group_name, entries in taxonomy.items():
        lines.append(f"  [{group_name}]")
        for entry in entries:
            lines.append(f"    - {entry['name']}")
            if entry.get("scope"):
                lines.append(f"      Scope: {entry['scope']}")
        lines.append("")  # blank line between groups
    return "\n".join(lines)


def _format_disambiguation(cat_config: dict) -> str:
    """Render disambiguation rules into a readable text block for the LLM."""
    rules = cat_config.get("disambiguation", [])
    if not rules:
        return ""
    lines: list[str] = []
    for i, rule in enumerate(rules, 1):
        lines.append(f"  {i}. {rule}")
    return "\n".join(lines)


# ── JSON parsing with repair ────────────────────────────────────────
def _extract_json(text: str) -> dict:
    """Extract the first JSON object from *text*, tolerating markdown fences."""
    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # Find first { … }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {text!r:.200}")
    return json.loads(text[start : end + 1])


# ── Classification ───────────────────────────────────────────────────
_MAX_RETRIES = 3


def classify_item(
    item: NormalizedItem,
    categories: list[str],
    cat_config: dict | None = None,
) -> dict[str, Any]:
    """Classify a single item.  Returns {"category", "confidence", "tags"}.

    Retries up to _MAX_RETRIES times on JSON-parse failures.
    Falls back to {"category": "Other", "confidence": 0.0, "tags": []} on total failure.
    """
    # Build the prompt – use hierarchy if config available, else flat list
    if cat_config:
        prompt = _load_prompt().format(
            category_hierarchy=_format_taxonomy(cat_config),
            disambiguation=_format_disambiguation(cat_config),
            title=item.title,
            text=item.text[:1500],  # cap context size
            source_name=item.source_name,
            url=item.url,
        )
    else:
        # Legacy fallback – flat list
        prompt = _load_prompt().format(
            category_hierarchy="\n".join(f"  - {c}" for c in categories),
            disambiguation="(none)",
            title=item.title,
            text=item.text[:1500],
            source_name=item.source_name,
            url=item.url,
        )

    client = get_client()
    model = get_model(task="classify")
    fallback = {"category": "Other", "confidence": 0.0, "tags": []}

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "developer" if is_reasoning_model(model) else "system",
                        "content": "You are a strict JSON-only classifier.",
                    },
                    {"role": "user", "content": prompt},
                ],
                **chat_completion_kwargs(model=model, temperature=0.1, max_tokens=200),
            )
            raw = resp.choices[0].message.content or ""
            result = _extract_json(raw)

            # Validate required fields
            cat = result.get("category", "Other")
            if cat not in categories:
                log.warning("LLM returned unknown category %r – falling back to Other", cat)
                cat = "Other"
            confidence = float(result.get("confidence", 0.5))
            tags = result.get("tags", [])
            if not isinstance(tags, list):
                tags = []

            return {"category": cat, "confidence": confidence, "tags": tags}

        except json.JSONDecodeError:
            log.warning("JSON parse error on attempt %d for %r", attempt, item.title[:60])
        except Exception:
            log.exception("LLM call failed on attempt %d for %r", attempt, item.title[:60])

    log.error("Classification failed after %d retries for %r – using fallback", _MAX_RETRIES, item.title[:60])
    return fallback


def classify_items(
    items: Sequence[NormalizedItem],
    categories: list[str],
    cat_config: dict | None = None,
) -> list[NormalizedItem]:
    """Classify every item in-place and return the list."""
    total = len(items)
    for idx, item in enumerate(items, 1):
        log.info("Classifying [%d/%d]: %s", idx, total, item.title[:80])
        result = classify_item(item, categories, cat_config)
        item.category = result["category"]
        item.confidence = result["confidence"]
        item.tags = result["tags"]
    return list(items)
