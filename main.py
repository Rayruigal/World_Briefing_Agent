#!/usr/bin/env python3
"""world_brief – Daily World Briefing Agent.

Usage:
    python main.py              # run once (default)
    python main.py --schedule   # run on built-in schedule (07:30 Europe/Zurich)
    DRY_RUN=1 python main.py    # print email instead of sending
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ── Ensure project root is on sys.path ───────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env file (if present) ──────────────────────────────────────
_env_path = PROJECT_ROOT / ".env"
load_dotenv(_env_path, override=True)  # override=True so .env always wins

from emailer.send import send_brief
from ingest.rss import ingest_all_feeds
from ingest.youtube import ingest_all_channels
from process.classify import classify_items
from process.dedupe import deduplicate
from process.summarize import summarize
from storage.db import init_db, save_items

# ── Logging setup ────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


log = logging.getLogger("world_brief")


# ── Config loading ───────────────────────────────────────────────────
CONFIG_DIR = PROJECT_ROOT / "config"


def load_sources() -> dict:
    path = CONFIG_DIR / "sources.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_category_config() -> dict:
    """Load the full hierarchical category config (taxonomy + disambiguation)."""
    path = CONFIG_DIR / "categories.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_categories() -> list[str]:
    """Return a flat list of leaf category names (for validation / grouping)."""
    data = load_category_config()
    taxonomy = data.get("taxonomy", {})
    cats: list[str] = []
    for group_items in taxonomy.values():
        for entry in group_items:
            cats.append(entry["name"])
    return cats


# ── Output persistence ────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_ROOT / "output"


def _save_briefing(run_date: str, brief_text: str, items: list) -> None:
    """Save briefing text and structured JSON for the web dashboard."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Plain-text version
    txt_path = OUTPUT_DIR / f"{run_date}.txt"
    txt_path.write_text(brief_text, encoding="utf-8")

    # Structured JSON version (for the web UI)
    from collections import defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item.category or "Other"].append(item.to_dict())

    json_path = OUTPUT_DIR / f"{run_date}.json"
    json_path.write_text(
        json.dumps(
            {
                "date": run_date,
                "brief_text": brief_text,
                "categories": {
                    cat: items_list for cat, items_list in grouped.items()
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log.info("Briefing saved to %s (.txt + .json)", OUTPUT_DIR)


# ── Auto-push to GitHub ──────────────────────────────────────────────


def _git_push(run_date: str) -> None:
    """Commit and push new briefing output to GitHub.

    This triggers an auto-redeploy on Render so the public dashboard
    is updated with today's briefing.  Requires git to be configured
    with SSH access to the remote.
    """
    import subprocess

    try:
        # Stage output files
        subprocess.run(
            ["git", "add", "output/"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
        )

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
        )
        if result.returncode == 0:
            log.info("No new output to push – skipping git push")
            return

        # Commit
        subprocess.run(
            ["git", "commit", "-m", f"Briefing {run_date}"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
        )

        # Push
        subprocess.run(
            ["git", "push"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
        )
        log.info("Briefing pushed to GitHub → Render will auto-redeploy")

    except subprocess.CalledProcessError as exc:
        log.warning("Git push failed (non-fatal): %s", exc.stderr.decode().strip() if exc.stderr else exc)
    except FileNotFoundError:
        log.warning("git not found – skipping auto-push")


# ── Main pipeline ────────────────────────────────────────────────────


def run_pipeline() -> None:
    """Execute the full daily-briefing pipeline once."""
    _setup_logging()
    log.info("=== world_brief pipeline starting ===")

    dry_run = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
    if dry_run:
        log.info("DRY_RUN mode enabled")

    # 1) Load config
    sources = load_sources()
    cat_config = load_category_config()
    categories = load_categories()
    log.info(
        "Config loaded: %d RSS feeds, %d YouTube channels, %d categories",
        len(sources.get("rss_feeds", [])),
        len(sources.get("youtube_channels", [])),
        len(categories),
    )

    # 2) Determine time window
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    run_date = now.strftime("%Y-%m-%d")

    # 3) Initialise DB
    init_db()

    # 4) Ingest
    max_per_source = sources.get("max_items_per_source", 10)
    rss_items = ingest_all_feeds(
        sources.get("rss_feeds", []), since=since, max_per_source=max_per_source,
    )
    yt_items = ingest_all_channels(sources.get("youtube_channels", []), since=since)
    all_items = rss_items + yt_items
    log.info("Ingested %d total items (RSS=%d, YouTube=%d)", len(all_items), len(rss_items), len(yt_items))

    if not all_items:
        log.warning("No items ingested – nothing to do")
        return

    # 5) Deduplicate
    unique_items = deduplicate(all_items)
    log.info("After dedup: %d unique items", len(unique_items))

    if not unique_items:
        log.warning("All items were duplicates – nothing to do")
        return

    # 6) Persist raw items
    save_items(unique_items, run_date)

    # 7) Classify
    classified = classify_items(unique_items, categories, cat_config)

    # 8) Update DB with classifications
    from storage.db import update_classification

    for item in classified:
        if item.category:
            update_classification(item.url, item.category, item.confidence or 0.0, item.tags)

    # 9) Summarise
    brief_text = summarize(classified, run_date)

    # 10) Save briefing to output/ for the web dashboard
    _save_briefing(run_date, brief_text, classified)

    # 11) Email
    subject = f"Daily World Brief — {run_date}"
    send_brief(subject, brief_text, dry_run=dry_run)

    # 12) Auto-push to GitHub (updates Render dashboard)
    auto_push = os.getenv("AUTO_PUSH", "").lower() in ("1", "true", "yes")
    if auto_push:
        _git_push(run_date)

    log.info("=== world_brief pipeline finished ===")


# ── Scheduler ────────────────────────────────────────────────────────


def run_scheduled() -> None:
    """Run the pipeline on a daily schedule at 07:30 Europe/Zurich."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.error("apscheduler is required for --schedule mode.  pip install apscheduler")
        sys.exit(1)

    scheduler = BlockingScheduler()
    trigger = CronTrigger(hour=7, minute=30, timezone="Europe/Zurich")
    scheduler.add_job(run_pipeline, trigger, id="daily_brief", name="Daily World Brief")
    log.info("Scheduler started – next run at 07:30 Europe/Zurich")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")


# ── CLI ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily World Briefing Agent")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on built-in schedule (07:30 Europe/Zurich) instead of once",
    )
    args = parser.parse_args()

    if args.schedule:
        _setup_logging()
        run_scheduled()
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
