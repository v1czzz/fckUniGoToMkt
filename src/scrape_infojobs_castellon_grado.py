#!/usr/bin/env python3
"""Step 1 scraper for InfoJobs (Castellon + university degree filter).

This script uses the Firecrawl CLI to:
1) Discover offer URLs from the filtered InfoJobs result pages.
2) Extract title, company, requirements and description from each offer.
3) Save the aggregated result as JSON.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = Path("laSalsa/rawData.json")


SEARCH_URL_TEMPLATE = (
    "https://www.infojobs.net/jobsearch/search-results/list.xhtml"
    "?keyword="
    "&cityIds=Castell%C3%B3n%20de%20la%20Plana%2FCastell%C3%B3%20de%20la%20Plana"
    "&cityId=909"
    "&searchByType=city"
    "&radius=10"
    "&referer=search-filtered"
    "&educationIds=125"
    "&segmentId="
    "&page={page}"
    "&sortBy=PUBLICATION_DATE"
    "&onlyForeignCountry=false"
    "&sinceDate=ANY"
)

OFFER_URL_RE = re.compile(r"^https://www\.infojobs\.net/.+/of-[^/?]+(?:\?.*)?$")

EXTRACTION_PROMPT = (
    "Devuelve SOLO JSON valido con claves exactas: "
    '"title", "company", "requirements", "description". '
    "Si falta algun dato, usa cadena vacia. "
    "No incluyas markdown ni texto adicional."
)


def resolve_path_arg(raw_path: str, default_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path == default_path:
        return PROJECT_ROOT / path
    return path


def run_command(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Command failed")
    return proc.stdout


def parse_json_from_firecrawl_output(raw: str) -> dict:
    """Parse Firecrawl CLI output that may include scrape id headers/code fences."""
    text = raw.strip()

    fence = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    if fence:
        return json.loads(fence.group(1))

    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last < first:
        raise ValueError("No JSON object found in Firecrawl output")

    return json.loads(text[first : last + 1])


def canonical_offer_url(url: str) -> str:
    """Drop query params to deduplicate the same offer across listing pages."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def scrape_listing_links(page: int, wait_for_ms: int) -> list[str]:
    url = SEARCH_URL_TEMPLATE.format(page=page)
    output = run_command(
        [
            "firecrawl",
            "scrape",
            url,
            "--format",
            "links",
            "--wait-for",
            str(wait_for_ms),
            "--json",
        ]
    )
    parsed = parse_json_from_firecrawl_output(output)
    links = parsed.get("links") or []
    return [link for link in links if isinstance(link, str) and OFFER_URL_RE.match(link)]


def scrape_offer(url: str, wait_for_ms: int, retries: int = 2) -> dict:
    last_error = None
    for attempt in range(retries + 1):
        try:
            output = run_command(
                [
                    "firecrawl",
                    "scrape",
                    url,
                    "--only-main-content",
                    "--wait-for",
                    str(wait_for_ms),
                    "--query",
                    EXTRACTION_PROMPT,
                    "--json",
                ]
            )
            parsed = parse_json_from_firecrawl_output(output)
            return {
                "title": str(parsed.get("title") or "").strip(),
                "company": str(parsed.get("company") or "").strip(),
                "requirements": str(parsed.get("requirements") or "").strip(),
                "description": str(parsed.get("description") or "").strip(),
                "url": url,
            }
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
            if attempt < retries:
                time.sleep(1.25 * (attempt + 1))

    raise RuntimeError(f"Could not scrape offer {url}: {last_error}")


def discover_offer_urls(max_pages: int, wait_for_ms: int) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        links = scrape_listing_links(page=page, wait_for_ms=wait_for_ms)
        if not links:
            break

        new_in_page = 0
        for link in links:
            canon = canonical_offer_url(link)
            if canon in seen:
                continue
            seen.add(canon)
            found.append(canon)
            new_in_page += 1

        # Stop when pagination no longer contributes fresh offers.
        if new_in_page == 0:
            break

    return found


def chunked(iterable: Iterable[str], size: int) -> Iterable[list[str]]:
    chunk: list[str] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape InfoJobs Castellon+Grado offers")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH.as_posix(),
        help=f"Output JSON path (default: {DEFAULT_OUTPUT_PATH.as_posix()})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
        help="Maximum result pages to inspect (default: 12)",
    )
    parser.add_argument(
        "--wait-for-ms",
        type=int,
        default=8000,
        help="Milliseconds to wait for page rendering (default: 8000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Parallel offer scrapes (default: 2, matches your current Firecrawl concurrency)",
    )
    args = parser.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    offer_urls = discover_offer_urls(max_pages=args.max_pages, wait_for_ms=args.wait_for_ms)

    results: list[dict] = []
    errors: list[dict] = []

    # Keep small batches to avoid overwhelming the provider and to simplify retries.
    for batch in chunked(offer_urls, max(args.workers * 2, 2)):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scrape_offer, url, args.wait_for_ms): url for url in batch}
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    item = future.result()
                    if item["title"] or item["company"] or item["description"]:
                        results.append(item)
                except Exception as exc:  # pylint: disable=broad-except
                    errors.append({"url": url, "error": str(exc)})

    payload = {
        "source": "InfoJobs",
        "location_filter": "Castellon de la Plana / Castello de la Plana",
        "education_filter": "Grado (educationIds=125)",
        "search_url_template": SEARCH_URL_TEMPLATE,
        "scraped_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_offers_found": len(offer_urls),
        "total_offers_extracted": len(results),
        "offers": sorted(results, key=lambda x: (x.get("title", ""), x.get("company", ""))),
        "errors": errors,
        "runtime_seconds": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2),
    }

    output_path = resolve_path_arg(args.output, DEFAULT_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(results)} offers to {args.output}")
    if errors:
        print(f"Warnings: {len(errors)} offers failed. See errors[] in output JSON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
