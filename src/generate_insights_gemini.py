#!/usr/bin/env python3
"""Extract structured insights per job offer with Gemini API.

This script reads scraped offers, calls Gemini once per offer,
and writes the aggregated results as JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = Path("laSalsa/rawData.json")
DEFAULT_OUTPUT_PATH = Path("laSalsa/insights.json")

EXTRACTION_PROMPT_TEMPLATE = """#TAREA
Tu objetivo es extraer informacion estructurada de una oferta de trabajo.

Si la oferta tiene la siguiente informacion, extraela de forma estructurada en formato JSON:
- Tipo de puesto
- Ambito (sector/area profesional)
- Habilidades practicas
- Conocimientos practicos

# EXTRACTION RULES
- Usa SOLO la informacion explicitamente presente en el JSON.
- NO inventes, NO infieras, NO completes informacion faltante.
- Si un campo no esta claramente presente, NO lo incluyas en la salida.
- Extrae la informacion de forma literal o ligeramente normalizada (ej: eliminar redundancias).

# OUTPUT FORMAT
Devuelve un JSON con esta estructura:
{
  "tipo_puesto": "",
  "ambito": "",
  "habilidades_practicas": [],
  "conocimientos_practicos": []
}

# ADDITIONAL NOTES
- "tipo_puesto" debe reflejar el rol (ej: Administrativo, Tecnico Laboral).
- "ambito" debe reflejar el sector o o el ambito de estudios (ej: Administracion de Empresas, Recursos Humanos, Ingenieria industrial).

# INPUT DATA
{{JOB_OFFER_JSON}}
"""

ALLOWED_KEYS = {
    "tipo_puesto",
    "ambito",
    "habilidades_practicas",
    "conocimientos_practicos",
}


def resolve_path_arg(raw_path: str, default_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path == default_path:
        return PROJECT_ROOT / path
    return path


def build_prompt(offer: dict[str, Any]) -> str:
    offer_json = json.dumps(offer, ensure_ascii=False, indent=2)
    return EXTRACTION_PROMPT_TEMPLATE.replace("{{JOB_OFFER_JSON}}", offer_json)


def parse_json_from_text(text: str) -> dict[str, Any]:
    clean = text.strip()

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", clean, flags=re.S)
    if fenced:
        return json.loads(fenced.group(1))

    first = clean.find("{")
    last = clean.rfind("}")
    if first == -1 or last == -1 or last < first:
        raise ValueError("No JSON object found in model response")

    return json.loads(clean[first : last + 1])


def normalize_insight(raw: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in ALLOWED_KEYS:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                normalized[key] = value
            continue
        if isinstance(value, list):
            filtered = [str(item).strip() for item in value if str(item).strip()]
            if filtered:
                normalized[key] = filtered
            continue
    return normalized


def extract_offer_insight(
    client: Any,
    model_name: str,
    offer: dict[str, Any],
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    prompt = build_prompt(offer)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            response_text = (response.text or "").strip()
            if not response_text:
                raise ValueError("Empty response from model")

            parsed = parse_json_from_text(response_text)
            return normalize_insight(parsed)
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))

    raise RuntimeError(f"Gemini extraction failed: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract job insights with Gemini API")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_PATH.as_posix(),
        help=(
            "Path to input raw data JSON "
            f"(default: {DEFAULT_INPUT_PATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH.as_posix(),
        help=(
            "Path to output insights JSON "
            f"(default: {DEFAULT_OUTPUT_PATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--model",
        default="gemini-3-flash-preview",
        help="Gemini model name (default: gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retries per offer on failure (default: 2)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.5,
        help="Base retry delay in seconds (default: 1.5)",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv  # type: ignore
    except ModuleNotFoundError:
        print(
            "Missing dependency 'python-dotenv'. Install it with: uv add python-dotenv",
            file=sys.stderr,
        )
        return 1

    load_dotenv()

    try:
        from google import genai  # type: ignore
    except ModuleNotFoundError:
        print(
            "Missing dependency 'google-genai'. Install it with: uv add google-genai",
            file=sys.stderr,
        )
        return 1

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY environment variable", file=sys.stderr)
        return 1

    input_path = resolve_path_arg(args.input, DEFAULT_INPUT_PATH)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    offers = payload.get("offers") or []
    if not isinstance(offers, list):
        print("Invalid input: expected 'offers' to be a list", file=sys.stderr)
        return 1

    client = genai.Client(api_key=api_key)
    started = dt.datetime.now(dt.timezone.utc)

    insights: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, offer in enumerate(offers, start=1):
        if not isinstance(offer, dict):
            errors.append(
                {
                    "index": idx,
                    "error": "Offer is not an object",
                }
            )
            continue

        try:
            insight = extract_offer_insight(
                client=client,
                model_name=args.model,
                offer=offer,
                retries=max(args.retries, 0),
                retry_delay=max(args.retry_delay, 0.1),
            )
            insights.append(
                {
                    "index": idx,
                    "title": str(offer.get("title") or "").strip(),
                    "company": str(offer.get("company") or "").strip(),
                    "url": str(offer.get("url") or "").strip(),
                    "insight": insight,
                }
            )
            print(f"[{idx}/{len(offers)}] OK")
        except Exception as exc:  # pylint: disable=broad-except
            errors.append(
                {
                    "index": idx,
                    "title": str(offer.get("title") or "").strip(),
                    "url": str(offer.get("url") or "").strip(),
                    "error": str(exc),
                }
            )
            print(f"[{idx}/{len(offers)}] ERROR: {exc}", file=sys.stderr)

    output_payload = {
        "source_input": args.input,
        "model": args.model,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_offers_in_input": len(offers),
        "total_offers_processed": len(insights),
        "total_errors": len(errors),
        "insights": insights,
        "errors": errors,
        "runtime_seconds": round(
            (dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2
        ),
    }

    output_path = resolve_path_arg(args.output, DEFAULT_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved {len(insights)} insights to {args.output}")
    if errors:
        print(f"Warnings: {len(errors)} offers failed. See errors[] in output JSON.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
