"""Lightweight geographic entity extraction – maps keywords to coordinates.

No NLP dependency; uses a curated dictionary of countries, regions, and
major cities.  Returns a list of {name, lat, lng, count} for map markers.
"""

from __future__ import annotations

import re
from collections import Counter

# ── Gazetteer: name → (lat, lng) ─────────────────────────────────────
# Countries, territories, and major cities frequently in world news.
_PLACES: dict[str, tuple[float, float]] = {
    # Countries
    "afghanistan": (33.93, 67.71), "albania": (41.15, 20.17),
    "algeria": (28.03, 1.66), "argentina": (-38.42, -63.62),
    "australia": (-25.27, 133.78), "austria": (47.52, 14.55),
    "azerbaijan": (40.14, 47.58), "bangladesh": (23.68, 90.36),
    "belarus": (53.71, 27.95), "belgium": (50.50, 4.47),
    "brazil": (-14.24, -51.93), "canada": (56.13, -106.35),
    "chile": (-35.68, -71.54), "china": (35.86, 104.20),
    "colombia": (4.57, -74.30), "congo": (-4.04, 21.76),
    "croatia": (45.10, 15.20), "cuba": (21.52, -77.78),
    "czech": (49.82, 15.47), "denmark": (56.26, 9.50),
    "egypt": (26.82, 30.80), "eritrea": (15.18, 39.78),
    "ethiopia": (9.15, 40.49), "finland": (61.92, 25.75),
    "france": (46.23, 2.21), "georgia": (42.32, 43.36),
    "germany": (51.17, 10.45), "ghana": (7.95, -1.02),
    "greece": (39.07, 21.82), "haiti": (18.97, -72.29),
    "honduras": (15.20, -86.24), "hungary": (47.16, 19.50),
    "india": (20.59, 78.96), "indonesia": (-0.79, 113.92),
    "iran": (32.43, 53.69), "iraq": (33.22, 43.68),
    "ireland": (53.14, -7.69), "israel": (31.05, 34.85),
    "italy": (41.87, 12.57), "japan": (36.20, 138.25),
    "jordan": (30.59, 36.24), "kazakhstan": (48.02, 66.92),
    "kenya": (-0.02, 37.91), "korea": (35.91, 127.77),
    "kuwait": (29.31, 47.48), "lebanon": (33.85, 35.86),
    "libya": (26.34, 17.23), "malaysia": (4.21, 101.98),
    "mali": (17.57, -4.00), "mexico": (23.63, -102.55),
    "morocco": (31.79, -7.09), "mozambique": (-18.67, 35.53),
    "myanmar": (21.91, 95.96), "nepal": (28.39, 84.12),
    "netherlands": (52.13, 5.29), "new zealand": (-40.90, 174.89),
    "nicaragua": (12.87, -85.21), "niger": (17.61, 8.08),
    "nigeria": (9.08, 8.68), "norway": (60.47, 8.47),
    "pakistan": (30.38, 69.35), "palestine": (31.95, 35.23),
    "panama": (8.54, -80.78), "peru": (-9.19, -75.02),
    "philippines": (12.88, 121.77), "poland": (51.92, 19.15),
    "portugal": (39.40, -8.22), "qatar": (25.35, 51.18),
    "romania": (45.94, 24.97), "russia": (61.52, 105.32),
    "saudi": (23.89, 45.08), "senegal": (14.50, -14.45),
    "serbia": (44.02, 21.01), "singapore": (1.35, 103.82),
    "slovakia": (48.67, 19.70), "somalia": (5.15, 46.20),
    "south africa": (-30.56, 22.94), "spain": (40.46, -3.75),
    "sri lanka": (7.87, 80.77), "sudan": (12.86, 30.22),
    "sweden": (60.13, 18.64), "switzerland": (46.82, 8.23),
    "syria": (34.80, 38.99), "taiwan": (23.70, 120.96),
    "tanzania": (-6.37, 34.89), "thailand": (15.87, 100.99),
    "tunisia": (33.89, 9.54), "turkey": (38.96, 35.24),
    "turkiye": (38.96, 35.24),
    "uganda": (1.37, 32.29), "ukraine": (48.38, 31.17),
    "uae": (23.42, 53.85), "united arab emirates": (23.42, 53.85),
    "dubai": (25.20, 55.27),
    "uk": (55.38, -3.44), "united kingdom": (55.38, -3.44),
    "britain": (55.38, -3.44), "british": (55.38, -3.44),
    "england": (52.36, -1.17),
    "usa": (37.09, -95.71), "united states": (37.09, -95.71),
    "america": (37.09, -95.71), "american": (37.09, -95.71),
    "u.s.": (37.09, -95.71),
    "venezuela": (6.42, -66.59), "vietnam": (14.06, 108.28),
    "yemen": (15.55, 48.52), "zambia": (-13.13, 27.85),
    "zimbabwe": (-19.02, 29.15),
    # Regions / territories
    "gaza": (31.35, 34.31), "west bank": (31.95, 35.23),
    "crimea": (44.95, 34.10), "kashmir": (34.08, 74.80),
    "hong kong": (22.32, 114.17), "somaliland": (9.56, 44.06),
    "kurdistan": (36.41, 44.39),
    # Major cities in the news
    "moscow": (55.76, 37.62), "kyiv": (50.45, 30.52),
    "beijing": (39.90, 116.41), "tokyo": (35.68, 139.65),
    "london": (51.51, -0.13), "paris": (48.86, 2.35),
    "berlin": (52.52, 13.41), "rome": (41.90, 12.50),
    "milan": (45.46, 9.19), "turin": (45.07, 7.69),
    "istanbul": (41.01, 28.98), "tehran": (35.69, 51.39),
    "islamabad": (33.69, 73.04), "kabul": (34.53, 69.17),
    "baghdad": (33.31, 44.37), "damascus": (33.51, 36.28),
    "riyadh": (24.71, 46.68), "jerusalem": (31.77, 35.23),
    "tel aviv": (32.09, 34.78), "cairo": (30.04, 31.24),
    "nairobi": (-1.29, 36.82), "lagos": (6.52, 3.38),
    "johannesburg": (-26.20, 28.05), "cape town": (-33.93, 18.42),
    "mumbai": (19.08, 72.88), "new delhi": (28.61, 77.21),
    "delhi": (28.70, 77.10), "taipei": (25.03, 121.57),
    "seoul": (37.57, 126.98), "pyongyang": (39.04, 125.76),
    "hanoi": (21.03, 105.85), "bangkok": (13.76, 100.50),
    "washington": (38.91, -77.04), "new york": (40.71, -74.01),
    "mar-a-lago": (26.68, -80.04),
    "brussels": (50.85, 4.35), "geneva": (46.20, 6.14),
    "zurich": (47.38, 8.54), "vienna": (48.21, 16.37),
    "buenos aires": (-34.60, -58.38), "mexico city": (19.43, -99.13),
    "sydney": (-33.87, 151.21), "canberra": (-35.28, 149.13),
    "muscat": (23.59, 58.55), "tucson": (32.22, -110.97),
}


def _tokenize(text: str) -> str:
    """Lowercase and strip punctuation for matching."""
    return re.sub(r"[''\".,;:!?()\[\]{}]", " ", text.lower())


def extract_locations(texts: list[str]) -> list[dict]:
    """Extract geographic locations from a list of text strings.

    Returns a list of ``{"name": ..., "lat": ..., "lng": ..., "count": ...}``
    sorted by count descending.
    """
    blob = _tokenize(" ".join(texts))
    hits: Counter[str] = Counter()

    # Match multi-word names first, then single words
    sorted_places = sorted(_PLACES.keys(), key=len, reverse=True)
    for place in sorted_places:
        # Use word boundaries for short names to avoid false positives
        if len(place) <= 3:
            pattern = rf"\b{re.escape(place)}\b"
        else:
            pattern = re.escape(place)
        count = len(re.findall(pattern, blob))
        if count > 0:
            hits[place] += count

    # Merge aliases (e.g. "uk" + "united kingdom" + "britain")
    alias_groups = [
        ["uk", "united kingdom", "britain", "british", "england"],
        ["usa", "united states", "america", "american", "u.s."],
        ["uae", "united arab emirates", "dubai"],
        ["turkey", "turkiye"],
        ["palestine", "gaza", "west bank"],
    ]
    for group in alias_groups:
        total = sum(hits.pop(a, 0) for a in group)
        if total > 0:
            canonical = group[0]
            hits[canonical] = total

    results = []
    for name, count in hits.most_common():
        lat, lng = _PLACES[name]
        display = name.title()
        if name in ("uk", "usa", "uae"):
            display = name.upper()
        results.append({"name": display, "lat": lat, "lng": lng, "count": count})

    return results


def extract_words(texts: list[str], top_n: int = 60) -> list[list]:
    """Extract significant words for a word cloud.

    Returns a list of [word, weight] pairs sorted by weight descending.
    """
    _STOP = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "up", "about", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "can", "will", "just", "should",
        "now", "also", "has", "had", "have", "was", "were", "been", "being",
        "is", "are", "do", "does", "did", "would", "could", "may", "might",
        "shall", "its", "it", "he", "she", "they", "we", "you", "his", "her",
        "their", "our", "my", "this", "that", "these", "those", "which", "what",
        "who", "whom", "as", "if", "while", "says", "said", "new", "one", "two",
        "three", "first", "last", "after", "since", "year", "years", "day", "days",
        "time", "people", "told", "including", "according", "many", "still",
        "part", "made", "make", "set", "amid", "come", "get", "back", "well",
        "us", "going", "way",
    }

    blob = _tokenize(" ".join(texts))
    words = re.findall(r"\b[a-z]{3,}\b", blob)
    counts: Counter[str] = Counter()
    for w in words:
        if w not in _STOP and not w.isdigit():
            counts[w] += 1

    # Scale weights: most frequent = 100
    if not counts:
        return []
    max_c = counts.most_common(1)[0][1]
    return [
        [word, round(count / max_c * 100)]
        for word, count in counts.most_common(top_n)
        if count > 1
    ]
