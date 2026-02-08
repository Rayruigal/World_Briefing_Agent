"""FastAPI web server – serves the briefing dashboard and REST API.

Run:
    python -m web.app                 # or
    uvicorn web.app:app --reload
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.geo import extract_locations, extract_words

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="World Brief", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Dashboard ────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the single-page dashboard."""
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


# ── API: list briefings ─────────────────────────────────────────────


@app.get("/api/briefings")
async def list_briefings():
    """Return a list of available briefing dates (newest first)."""
    if not OUTPUT_DIR.exists():
        return {"dates": []}
    dates = sorted(
        [f.stem for f in OUTPUT_DIR.glob("*.json")],
        reverse=True,
    )
    return {"dates": dates}


# ── API: get one briefing ────────────────────────────────────────────


@app.get("/api/briefings/{date}")
async def get_briefing(date: str):
    """Return a single briefing by date (YYYY-MM-DD)."""
    json_path = OUTPUT_DIR / f"{date}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"No briefing for {date}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data


# ── API: briefing overview (visual dashboard) ───────────────────────


@app.get("/api/briefings/{date}/overview")
async def get_briefing_overview(date: str):
    """Return per-category stats for the visual dashboard view."""
    json_path = OUTPUT_DIR / f"{date}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"No briefing for {date}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    brief_text = data.get("brief_text", "")
    cat_items_map = data.get("categories", {})

    # Parse each category section
    sections: list[dict] = []
    parsed = _parse_all_categories(brief_text)

    for cat_name, section in parsed.items():
        # Gather text for extraction
        all_text = section["bullets"] + [section["why_matters"]]

        # Add stored item titles/text if available
        stored = cat_items_map.get(cat_name, [])
        item_count = len(stored) if stored else len(section["bullets"])
        for item in stored:
            if isinstance(item, dict):
                all_text.append(item.get("title", ""))
                all_text.append(item.get("text", ""))

        locations = extract_locations(all_text)
        words = extract_words(all_text, top_n=12)

        sections.append({
            "category": cat_name,
            "bullet_count": len(section["bullets"]),
            "item_count": item_count,
            "location_count": len(locations),
            "why_matters": section["why_matters"],
            "top_words": [w[0] for w in words[:10]],
            "top_locations": [loc["name"] for loc in locations[:5]],
            "locations": locations,  # full list with lat/lng for global map
            "link_count": len(section["links"]),
        })

    return {"date": date, "sections": sections}


# ── API: category detail ──────────────────────────────────────────────


def _parse_all_categories(brief_text: str) -> dict[str, dict]:
    """Parse ALL category sections from the briefing text.

    Returns {category_name: {"bullets": [...], "why_matters": "...", "links": [...]}}.
    """
    lines = brief_text.split("\n")
    result: dict[str, dict] = {}
    current_name: str | None = None
    current: dict | None = None

    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        # Detect category header
        if re.match(r"^[A-Z][A-Za-z &\-]+$", trimmed) and len(trimmed) < 50 \
           and not trimmed.startswith("Why it matters"):
            if current_name and current:
                result[current_name] = current
            current_name = trimmed
            current = {"bullets": [], "why_matters": "", "links": []}
            continue
        if current is None:
            continue
        if trimmed.startswith("Why it matters"):
            current["why_matters"] = re.sub(r"^Why it matters:\s*", "", trimmed)
        elif trimmed.startswith("http"):
            current["links"].append(trimmed)
        elif trimmed.startswith("•"):
            current["bullets"].append(trimmed.lstrip("• "))
        elif current["bullets"]:
            current["bullets"][-1] += " " + trimmed

    if current_name and current:
        result[current_name] = current
    return result


def _parse_category_from_brief(brief_text: str, category: str) -> dict:
    """Extract bullets, why-it-matters, and links for one category from the brief text."""
    lines = brief_text.split("\n")
    in_section = False
    bullets: list[str] = []
    why_matters = ""
    links: list[str] = []

    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        # Detect category headers
        if trimmed == category:
            in_section = True
            continue
        # Detect start of NEXT category (a line that looks like a header)
        if in_section and not trimmed.startswith("•") and not trimmed.startswith("http") and \
           not trimmed.startswith("Why it matters") and re.match(r"^[A-Z][A-Za-z &]+$", trimmed) and len(trimmed) < 50:
            break
        if not in_section:
            continue
        if trimmed.startswith("Why it matters"):
            why_matters = re.sub(r"^Why it matters:\s*", "", trimmed)
        elif trimmed.startswith("http"):
            links.append(trimmed)
        elif trimmed.startswith("•"):
            bullets.append(trimmed.lstrip("• "))
        elif bullets:
            bullets[-1] += " " + trimmed

    return {"bullets": bullets, "why_matters": why_matters, "links": links}


@app.get("/api/briefings/{date}/categories/{category}")
async def get_category_detail(date: str, category: str):
    """Return detailed data for one category including map locations and word cloud."""
    json_path = OUTPUT_DIR / f"{date}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"No briefing for {date}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    brief_text = data.get("brief_text", "")

    # Parse the section from the briefing text
    section = _parse_category_from_brief(brief_text, category)
    if not section["bullets"]:
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found in {date}")

    # Gather text for NLP extraction: bullets + why-it-matters + raw article titles/text
    all_text = section["bullets"] + [section["why_matters"]]

    # If structured items were stored, use their titles and text for richer extraction
    cat_items = data.get("categories", {}).get(category, [])
    source_items: list[dict] = []
    for item in cat_items:
        if isinstance(item, dict):
            all_text.append(item.get("title", ""))
            all_text.append(item.get("text", ""))
            source_items.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source_name": item.get("source_name", ""),
                "published_at": item.get("published_at", ""),
            })

    locations = extract_locations(all_text)
    words = extract_words(all_text, top_n=60)

    return {
        "date": date,
        "category": category,
        "bullets": section["bullets"],
        "why_matters": section["why_matters"],
        "links": section["links"],
        "locations": locations,
        "words": words,
        "source_items": source_items,
    }


# ── Category detail page ─────────────────────────────────────────────


@app.get("/category/{date}/{category}", response_class=HTMLResponse)
async def category_page(date: str, category: str):
    """Serve the category detail page."""
    page = STATIC_DIR / "category.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


# ── Group detail page ────────────────────────────────────────────────


@app.get("/group/{date}/{group}", response_class=HTMLResponse)
async def group_page(date: str, group: str):
    """Serve the group detail page."""
    page = STATIC_DIR / "group.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


# ── API: search across briefings ─────────────────────────────────────


@app.get("/api/search")
async def search_briefings(q: str = ""):
    """Search across all briefings for a keyword (case-insensitive)."""
    if not q or not OUTPUT_DIR.exists():
        return {"results": []}

    q_lower = q.lower()
    results: list[dict] = []

    for json_path in sorted(OUTPUT_DIR.glob("*.json"), reverse=True):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        brief_text: str = data.get("brief_text", "")
        if q_lower in brief_text.lower():
            # Find matching snippet
            idx = brief_text.lower().index(q_lower)
            start = max(0, idx - 80)
            end = min(len(brief_text), idx + len(q) + 80)
            snippet = brief_text[start:end]
            if start > 0:
                snippet = "…" + snippet
            if end < len(brief_text):
                snippet = snippet + "…"
            results.append({"date": data["date"], "snippet": snippet})

    return {"query": q, "results": results}


# ── Run directly ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    sys.path.insert(0, str(PROJECT_ROOT))
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
