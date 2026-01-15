#!/usr/bin/env python3
"""Harmonize an asset JSON into a unified Asset schema using pydantic-ai.

- Loads environment variables from .env
- Accepts JSON input only (via --input or first *.json in trials/assets/)
- Uses an Agent with `output_type=Asset` to map input into the schema
- If input JSON contains key `type` with value "Hardware" or "Software",
  sets `Asset.type` accordingly and ensures the proper extension block is used.

Usage:
  python trials/harmonizing_asset_example.py --input trials/assets/sample.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import InlineDefsJsonSchemaTransformer, ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

# Load environment variables from .env in the project root
load_dotenv()

# Paths
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]

# Define a model profile for Qwen's behavior
qwen_profile = ModelProfile(
    supports_tools=True,
    supports_json_schema_output=True,  # Enable JSON schema output
    default_structured_output_mode='native',  # Use native JSON schema mode instead of tool wrapping
    thinking_tags=("<think>", "</think>"),
    ignore_streamed_leading_whitespace=True,
    json_schema_transformer=InlineDefsJsonSchemaTransformer
)

# Configure the model from .env
base_url = (
    os.getenv("OPENAI_API_BASE")
    or os.getenv("vllm_url")
    or "http://localhost:8000/v1"
)
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("vllm_api_key") or "EMPTY"

client = AsyncOpenAI(base_url=base_url, api_key=api_key)
provider = OpenAIProvider(openai_client=client)

model = OpenAIChatModel(
    model_name="default",
    provider=provider,
    profile=qwen_profile,
)


# ===== Canonical Asset Schema =====
class AssetType(str):
    SOFTWARE = "software"
    HARDWARE = "hardware"
    # For now, only accept software or hardware assets


class AssetStatus(str):
    DRAFT = "draft"
    UNTAGGED = "untagged"
    UNSCORED = "unscored"
    SCORED = "scored"


class Reference(BaseModel):
    id: Optional[str] = Field(None, description="Referenced asset ID")
    relation: Optional[str] = Field(None, description="Relationship (e.g., dependsOn, providedBy)")


class HardwareExtension(BaseModel):
    manufacturer: Optional[str] = Field(None, description="name of the manufacturer")
    model: Optional[str] = Field(None, description="hardware model description")


class SoftwareExtension(BaseModel):
    manufacturer: Optional[str] = Field(None, description="name of the manufacturer")
    version: Optional[str] = Field(None, description="software version")
    licenseType: Optional[str] = Field(None, description="software's license type")


class Asset(BaseModel):
    # Basis
    id: Optional[str] = Field(None, description="the asset's ID")
    name: Optional[str] = Field(None, description="name of the asset")
    description: Optional[str] = Field(None, description="further description of the asset")
    type: Optional[
        Literal[
            AssetType.SOFTWARE,
            AssetType.HARDWARE,
        ]
    ] = Field(None, description="overall type of asset")

    externalId: Optional[Dict[str, str]] = Field(
        default=None,
        description="identifiers from source systems (key: source system, value: external ID)",
    )
    status: Optional[
        Literal[
            AssetStatus.DRAFT,
            AssetStatus.UNTAGGED,
            AssetStatus.UNSCORED,
            AssetStatus.SCORED,
        ]
    ] = Field(None, description="current status of this asset")

    # After-harmonizing policy: these must be null
    tags: Optional[List[str]] = Field(default=None, description="list of tags associated with this asset (null after harmonizing)")
    references: Optional[List[Reference]] = Field(default=None, description="references to other assets (null after harmonizing)")
    additionalProperties: Optional[Dict[str, Any]] = Field(default=None, description="Dictionary of unprocessed source properties")

    # Extensions
    hardware: Optional[HardwareExtension] = None
    software: Optional[SoftwareExtension] = None


# ===== Helpers =====


def read_asset_json(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def pick_default_json() -> Path:
    assets_dir = REPO_ROOT / "trials" / "assets"
    candidates = sorted(assets_dir.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON files found in {assets_dir}")
    return candidates[0]


def normalize_type(input_type: Optional[str]) -> Optional[str]:
    if not input_type:
        return None
    t = str(input_type).strip().lower()
    if t == "hardware":
        return AssetType.HARDWARE
    if t == "software":
        return AssetType.SOFTWARE
    # Leave None for unknown; agent may infer from context
    return None


# ===== Main =====


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harmonize an asset JSON into the canonical Asset schema using pydantic-ai",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Path to asset JSON (default: first JSON in trials/assets)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to write the harmonized Asset JSON output",
    )
    args = parser.parse_args()

    asset_path = Path(args.input) if args.input else pick_default_json()
    source = read_asset_json(asset_path)

    # Optional domain context if available
    context_path = REPO_ROOT / "trials" / "asset_typen_uebersicht.md"
    try:
        context_md = context_path.read_text(encoding="utf-8")
    except Exception:
        context_md = ""

    input_type_norm = normalize_type(source.get("type"))

    instructions = (
        "You are an expert in asset data harmonization.\n"
        "Map the provided input JSON to the canonical Asset schema.\n"
        "Strict rules (must follow):\n"
        "- Only accept assets of type 'hardware' or 'software'. Do not output other types. If unsure, leave type null.\n"
        "- The following fields MUST be null in the output (per after-harmonizing spec): id, externalId, tags, references.\n"
        "- The field 'status' MUST be set to 'draft'.\n"
        "- Use only the schema fields defined by the model (no extras).\n"
        "- Do not hallucinate values. If data is missing, leave fields null.\n"
        "- If input indicates 'Hardware', set Asset.type='hardware' and populate the 'hardware' extension; leave 'software' null.\n"
        "- If input indicates 'Software', set Asset.type='software' and populate the 'software' extension; leave 'hardware' null.\n"
        "- Populate meaningful 'name' and a concise, informative 'description' derived from the input (no marketing fluff).\n"
        "- Extract and map extension fields precisely: for hardware (manufacturer, model); for software (manufacturer, version, licenseType).\n"
        "- For now, do NOT use 'additionalProperties'. If something is unmapped, omit it.\n"
        "- Output ONLY a pure JSON object compatible with the schema. No prose, no Markdown, no code fences/backticks, no <think> tags."
    )

    parts = [
        "Context (asset types):\n\n" + context_md,
        "Input JSON:\n" + json.dumps(source, ensure_ascii=False, indent=2),
    ]
    if input_type_norm:
        parts.append(f"\nNormalized type hint: {input_type_norm}")
    user_msg = "\n\n".join(parts)

    agent = Agent(
        model,
        output_type=Asset,
        system_prompt=instructions,
        model_settings={
            "temperature": 0.0,
            "stop": ["```"]  # avoid fenced code blocks
        }
    )

    result = agent.run_sync(user_msg)
    out: Asset = result.output

    # Enforce extension consistency with normalized type (post-check)
    if input_type_norm == AssetType.HARDWARE:
        out.type = AssetType.HARDWARE
        out.software = None
    elif input_type_norm == AssetType.SOFTWARE:
        out.type = AssetType.SOFTWARE
        out.hardware = None

    # Hard post-conditions per after-harmonizing policy
    # 1) Only hardware/software types are permitted; otherwise leave as None
    if out.type not in (AssetType.HARDWARE, AssetType.SOFTWARE):
        out.type = None

    # 2) Status must always be draft
    out.status = AssetStatus.DRAFT

    # 3) Fields that must be null after harmonizing
    out.id = None
    out.externalId = None
    out.tags = None
    out.references = None

    # Prepare output payload with custom transformations
    output_payload = out.model_dump()

    # Drop additionalProperties from output (even if present)
    output_payload.pop("additionalProperties", None)

    # Extension handling: omit null extension and rename the present one
    hw = output_payload.pop("hardware", None)
    sw = output_payload.pop("software", None)
    if hw is not None:
        output_payload["hardware_extension"] = hw
    if sw is not None:
        output_payload["software_extension"] = sw

    output_json = json.dumps(output_payload, ensure_ascii=False, indent=2)

    # Write to --output if provided
    if args.output:
        output_path = Path(args.output)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        output_path.write_text(output_json, encoding="utf-8")

    print(output_json)


if __name__ == "__main__":
    main()
