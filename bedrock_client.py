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
import time

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
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.1
RETRYABLE_ERROR_CODES = {
    "InternalServerError",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
    "RequestTimeout",
    "ServiceUnavailableException",
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
}


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


def _is_retryable_error(exc):
    """Return whether a Bedrock transport or service error is transient."""
    response = getattr(exc, "response", {})
    if not isinstance(response, dict):
        response = {}
    error = response.get("Error") or {}
    metadata = response.get("ResponseMetadata") or {}
    status_code = metadata.get("HTTPStatusCode")
    error_code = error.get("Code")
    error_type = type(exc).__name__
    return (
        error_code in RETRYABLE_ERROR_CODES
        or status_code == 429
        or isinstance(status_code, int) and 500 <= status_code < 600
        or error_type
        in {"ConnectTimeoutError", "EndpointConnectionError", "ReadTimeoutError"}
    )


def converse(system_prompt, user_prompt, max_tokens=3000, temperature=0.4):
    """
    Single-turn call to the Bedrock `converse` API.

    Returns the raw assistant text. Retryable transport and service failures use
    bounded exponential backoff; other errors raise immediately.
    """
    client = _client()
    request = {
        "modelId": get_model_id(),
        "system": [{"text": system_prompt}],
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            response = client.converse(**request)
            break
        except Exception as exc:
            if not _is_retryable_error(exc) or attempt == MAX_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
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
