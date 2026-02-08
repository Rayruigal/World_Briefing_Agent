"""Text-to-Speech audio briefing generator using edge-tts (free, no API key).

Generates an MP3 file from the briefing text.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Microsoft Edge TTS voice – natural, professional English
VOICE = "en-US-AriaNeural"  # clear female voice, great for news
RATE = "+10%"  # slightly faster than default for a newscast feel


def _clean_for_speech(text: str) -> str:
    """Clean briefing text for better TTS output."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove bullet markers
    text = re.sub(r"^[•\-]\s*", "", text, flags=re.MULTILINE)
    # Replace category-style headers with spoken transitions
    text = re.sub(
        r"^([A-Z][A-Za-z &\-]+)$",
        r"Next, \1.",
        text,
        flags=re.MULTILINE,
    )
    # Clean "Why it matters:" prefix
    text = text.replace("Why it matters:", "Why it matters.")
    # Collapse excess whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _generate_audio(text: str, output_path: Path) -> None:
    """Use edge-tts to generate an MP3 asynchronously."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=VOICE, rate=RATE)
    await communicate.save(str(output_path))


def generate_audio_briefing(brief_text: str, output_path: Path) -> bool:
    """Generate an MP3 audio briefing from the brief text.

    Returns True if the file was successfully created, False otherwise.
    """
    if not brief_text or not brief_text.strip():
        log.warning("No briefing text to convert to audio")
        return False

    try:
        cleaned = _clean_for_speech(brief_text)
        if len(cleaned) < 50:
            log.warning("Cleaned text too short for audio (%d chars)", len(cleaned))
            return False

        log.info("Generating audio briefing (%d chars) → %s", len(cleaned), output_path)

        # edge-tts is async; run it in an event loop
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
