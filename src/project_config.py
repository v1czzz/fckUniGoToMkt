#!/usr/bin/env python3
"""Shared project defaults."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DATA_PATH = PROJECT_ROOT / "laSalsa/rawData.json"
INSIGHTS_PATH = PROJECT_ROOT / "laSalsa/insights.json"

SCRAPER_MAX_PAGES = 12
SCRAPER_WAIT_FOR_MS = 8000
SCRAPER_WORKERS = 2

GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_RETRIES = 2
GEMINI_RETRY_DELAY_SECONDS = 1.5