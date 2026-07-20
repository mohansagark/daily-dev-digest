"""
Thin wrapper around the Amazon Bedrock Runtime `converse` API.

Kept model-agnostic on purpose: everything goes through `converse`, so swapping
BEDROCK_MODEL_ID to any Converse-capable model works without code changes.

boto3 is imported lazily so the deterministic pipeline (and `--dry-run`) can run
in environments where boto3 / AWS credentials are not available.
"""

import os
import json
import re

# Base model id vs. cross-region inference profile:
#   - amazon.nova-pro-v1:0      -> base model id
#   - us.amazon.nova-pro-v1:0   -> US cross-region inference profile (usually
#                                  required for on-demand Nova Pro in us-east-1)
# Default to the inference profile; override with BEDROCK_MODEL_ID if needed.
DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"


def get_model_id():
    return os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)


def get_region():
    return os.getenv("AWS_REGION", "us-east-1")


def _client():
    """Create a bedrock-runtime client. Imported lazily (see module docstring)."""
    import boto3  # noqa: WPS433 (intentional lazy import)

    return boto3.client("bedrock-runtime", region_name=get_region())


# Bedrock returns exact token counts on every call and we used to discard them,
# leaving cost a ~4-chars-per-token guess. Accumulate them so a run's real spend
# is visible in the workflow log and a future backfill can gate on measured cost.
USAGE = {"calls": 0, "inputTokens": 0, "outputTokens": 0}


def _record_usage(usage):
    USAGE["calls"] += 1
    USAGE["inputTokens"] += int(usage.get("inputTokens") or 0)
    USAGE["outputTokens"] += int(usage.get("outputTokens") or 0)
    print(
        f"🧮 Bedrock call {USAGE['calls']}: "
        f"in={usage.get('inputTokens')} out={usage.get('outputTokens')} "
        f"(run total in={USAGE['inputTokens']} out={USAGE['outputTokens']})"
    )


def usage_summary():
    """Token totals for this process. Returns a copy so callers cannot mutate it."""
    return dict(USAGE)


def converse(system_prompt, user_prompt, max_tokens=3000, temperature=0.4):
    """
    Single-turn call to the Bedrock `converse` API.

    Returns the raw assistant text. Raises on transport/API errors so the caller
    can decide how to handle failures (we fail the run rather than push garbage).
    """
    client = _client()
    response = client.converse(
        modelId=get_model_id(),
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    )
    _record_usage(response.get("usage") or {})
    return response["output"]["message"]["content"][0]["text"]


def extract_json(text):
    """
    Best-effort extraction of a single JSON object from an LLM response.

    Models sometimes wrap JSON in ```json fences or add a sentence before/after,
    so we strip fences and fall back to the first balanced {...} block.
    """
    if not text:
        raise ValueError("Empty LLM response, cannot parse JSON")

    candidate = text.strip()

    # Only unwrap a fence if the WHOLE response is fenced (anchored at start),
    # so we don't accidentally grab a ```code``` block inside body_markdown.
    if candidate.startswith("```"):
        m = re.match(r"```(?:json)?\s*(.*?)```\s*$", candidate, re.DOTALL)
        if m:
            candidate = m.group(1).strip()

    # Isolate the outermost {...} object (drops any prose before/after it).
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]

    # strict=False tolerates literal newlines/tabs inside string values, which
    # LLMs routinely emit inside a long markdown field (strict JSON forbids them).
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse JSON from LLM response: {text[:200]}..."
        ) from e
