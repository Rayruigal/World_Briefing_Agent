"""Text-to-Speech audio briefing generator using edge-tts (free, no API key).

Generates per-section MP3 files from the briefing text.
Each group section gets its own audio file, and the frontend plays them
sequentially for a full briefing experience.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Microsoft Edge TTS voice – warm, conversational English
VOICE = "en-US-JennyNeural"  # softer, warmer tone than Aria
RATE = "+5%"  # only slightly faster for a calm newscast feel

# Word limit per section to keep audio files compact (~1 min per 150 words)
MAX_WORDS_PER_SECTION = 300  # ~2 min of audio per section, ~12 min total

# Section order matching the dashboard groups
GROUP_SECTIONS: dict[str, list[str]] = {
    "Science & Innovation": ["Artificial Intelligence", "Science & Technology"],
    "Health & Longevity": ["Health & Pandemic", "Longevity & Anti-Aging"],
    "Culture & Entertainment": ["Art & Culture", "Entertainment", "Sports"],
    "Environment & Planet": ["Climate & Environment"],
    "Economy": ["Economy & Markets"],
    "World & Politics": [
        "Geopolitics & Diplomacy",
        "Armed Conflict & Security",
        "Society & Human Rights",
    ],
}

# Display order (matches dashboard)
GROUP_ORDER = [
    "Science & Innovation",
    "Health & Longevity",
    "Culture & Entertainment",
    "Environment & Planet",
    "Economy",
    "World & Politics",
]


def _slugify(name: str) -> str:
    """Convert a group name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _clean_for_speech(text: str) -> str:
    """Clean briefing text for better TTS output."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove bullet markers
    text = re.sub(r"^[•\-]\s*", "", text, flags=re.MULTILINE)
    # Clean "Why it matters:" prefix
    text = text.replace("Why it matters:", "Why it matters.")
    # Collapse excess whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_sections(brief_text: str) -> dict[str, str]:
    """Parse the briefing text into {category_name: section_text}."""
    lines = brief_text.split("\n")
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in lines:
        trimmed = line.strip()
        # Detect category header (e.g. "Geopolitics & Diplomacy")
        if (
            trimmed
            and re.match(r"^[A-Z][A-Za-z &\-]+$", trimmed)
            and len(trimmed) < 50
            and not trimmed.startswith("Why it matters")
        ):
            if current_name and current_lines:
                sections[current_name] = "\n".join(current_lines)
            current_name = trimmed
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line)

    if current_name and current_lines:
        sections[current_name] = "\n".join(current_lines)

    return sections


def _truncate_words(text: str, max_words: int) -> str:
    """Truncate text to at most *max_words* words, ending at a sentence."""
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    # Try to end at a sentence boundary
    for punct in (".", "!", "?"):
        last = truncated.rfind(punct)
        if last > len(truncated) // 2:
            return truncated[: last + 1]
    return truncated + "."


def _build_group_text(
    group_name: str, categories: list[str], sections: dict[str, str]
) -> str:
    """Build spoken text for one group from its category sections."""
    parts: list[str] = []

    # Group intro
    parts.append(f"{group_name}.")

    for cat_name in categories:
        section_text = sections.get(cat_name, "")
        if not section_text.strip():
            continue
        # If the group has multiple sub-categories, announce each one
        if len(categories) > 1:
            parts.append(f"{cat_name}.")
        cleaned = _clean_for_speech(section_text)
        if cleaned:
            parts.append(cleaned)

    full = "\n\n".join(parts)
    return _truncate_words(full, MAX_WORDS_PER_SECTION)


async def _generate_audio(text: str, output_path: Path) -> None:
    """Use edge-tts to generate an MP3 asynchronously."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=VOICE, rate=RATE)
    await communicate.save(str(output_path))


def generate_section_audio(
    brief_text: str, output_dir: Path
) -> dict[str, str]:
    """Generate per-group MP3 files from the briefing text.

    Creates output_dir/{slug}.mp3 for each group that has content.

    Returns a dict of {group_name: filename} for successfully generated files.
    """
    if not brief_text or not brief_text.strip():
        log.warning("No briefing text to convert to audio")
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    sections = _parse_sections(brief_text)

    if not sections:
        log.warning("No sections parsed from briefing text")
        return {}

    generated: dict[str, str] = {}
    total_size = 0

    for idx, group_name in enumerate(GROUP_ORDER, 1):
        categories = GROUP_SECTIONS.get(group_name, [])
        group_text = _build_group_text(group_name, categories, sections)

        if len(group_text.strip()) < 30:
            log.info("Skipping %s — no content", group_name)
            continue

        slug = _slugify(group_name)
        filename = f"{slug}.mp3"
        mp3_path = output_dir / filename

        try:
            log.info(
                "Generating audio [%d/%d] %s (%d chars)",
                idx,
                len(GROUP_ORDER),
                group_name,
                len(group_text),
            )
            asyncio.run(_generate_audio(group_text, mp3_path))

            if mp3_path.exists() and mp3_path.stat().st_size > 0:
                size = mp3_path.stat().st_size
                total_size += size
                generated[group_name] = filename
                log.info("  → %s (%.1f KB)", filename, size / 1024)
            else:
                log.warning("  → File not created for %s", group_name)

        except Exception:
            log.exception("Audio generation failed for %s (non-fatal)", group_name)

    log.info(
        "Audio generation complete: %d/%d sections, %.1f MB total",
        len(generated),
        len(GROUP_ORDER),
        total_size / (1024 * 1024),
    )
    return generated


# Legacy single-file generation (kept for backward compat)
def generate_audio_briefing(brief_text: str, output_path: Path) -> bool:
    """Generate a single MP3 audio briefing from the full brief text."""
    if not brief_text or not brief_text.strip():
        log.warning("No briefing text to convert to audio")
        return False

    try:
        cleaned = _clean_for_speech(brief_text)
        if len(cleaned) < 50:
            log.warning("Cleaned text too short for audio (%d chars)", len(cleaned))
            return False

        log.info("Generating full audio briefing (%d chars) → %s", len(cleaned), output_path)
        asyncio.run(_generate_audio(cleaned, output_path))

        if output_path.exists() and output_path.stat().st_size > 0:
            size_mb = output_path.stat().st_size / (1024 * 1024)
            log.info("Audio briefing generated: %.1f MB", size_mb)
            return True
        else:
            log.warning("Audio file was not created or is empty")
            return False

    except Exception:
        log.exception("Audio briefing generation failed (non-fatal)")
        return False
