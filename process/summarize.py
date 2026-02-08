"""LLM-based summarisation – produce the final daily brief."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from process.llm import chat_completion_kwargs, get_client, get_model
from storage.models import NormalizedItem

log = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────────
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "summarize.txt"
_PROMPT_TEMPLATE: str | None = None


def _load_prompt() -> str:
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is None:
        _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")
    return _PROMPT_TEMPLATE


# ── Summarisation ────────────────────────────────────────────────────


def _group_by_category(
    items: Sequence[NormalizedItem],
) -> dict[str, list[dict]]:
    """Group items by category, converting to dicts for the prompt."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        cat = item.category or "Other"
        groups[cat].append(
            {
                "title": item.title,
                "text": item.text[:500],
                "url": item.url,
                "source": item.source_name,
                "published_at": item.published_at,
                "tags": item.tags,
            }
        )
    return dict(groups)


def summarize(
    items: Sequence[NormalizedItem],
    date_str: str,
) -> str:
    """Produce the full daily brief as a plaintext string."""
    if not items:
        return f"Daily World Brief — {date_str}\n\nNo items to report today."

    grouped = _group_by_category(items)
    items_json = json.dumps(grouped, indent=2, ensure_ascii=False)

    prompt = _load_prompt().format(
        date=date_str,
        items_json=items_json,
    )

    client = get_client()
    model = get_model(task="summarize")

    log.info("Generating summary with model=%s, categories=%d, items=%d", model, len(grouped), len(items))

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior news editor writing a concise daily world briefing email. "
                        "Respond ONLY with the briefing text (plaintext, no markdown)."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            **chat_completion_kwargs(model=model, temperature=0.4, max_tokens=2000),
        )
        brief = resp.choices[0].message.content or ""
        brief = brief.strip()
    except Exception:
        log.exception("Summarisation LLM call failed")
        # Emergency fallback: just list titles
        lines = [f"Daily World Brief — {date_str}", "", "⚠ LLM summarisation failed – raw headlines:", ""]
        for cat, group_items in grouped.items():
            lines.append(f"== {cat} ==")
            for gi in group_items:
                lines.append(f"  • {gi['title']}  ({gi['url']})")
            lines.append("")
        brief = "\n".join(lines)

    return brief
