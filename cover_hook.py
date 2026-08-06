"""Bedrock cover_hook: catchy chrome copy + photo brief for editorial covers."""

from __future__ import annotations

import bedrock_client

COVER_HOOK_SYSTEM = (
    "You are an art director and copywriter for a developer blog cover. "
    "Return ONLY a single valid JSON object, no prose."
)

COVER_HOOK_USER = """\
Write cover copy and a photo brief for this published technical post.

INPUT
TITLE: {title}
TAGS: {tags}
BODY (excerpt):
\"\"\"
{body}
\"\"\"

Return ONLY this JSON:
{{
  "headline": "short tension/contradiction hook, all-caps friendly, not 'A Guide to…'",
  "subtitle": "curiosity beat that does not spoil the how-to",
  "pill": ["beat1", "beat2", "beat3"],
  "photo_brief": "photographable scene description",
  "tone": "warm_bw | cool_steel | muted_color | vivid_night"
}}

Rules:
- pill: exactly 3 short topic beats (prefer under ~18 chars each) for ✓ A | ✓ B | ✓ C
- photo_brief: realistic artifact/environment ONLY — no human faces or people
- Prefer soft-focus or non-legible screens if a display appears; no sharp readable UI type or labeled diagrams
- Place the main subject OFF-CENTER toward the RIGHT side of the frame (for a diagonal crop)
- tone must be one of: warm_bw, cool_steel, muted_color, vivid_night
- No isometric node diagrams or abstract geometry decoration
"""

TONES = ("warm_bw", "cool_steel", "muted_color", "vivid_night")

TONE_FLAVOR = {
    "warm_bw": "warm desaturated black-and-white, quiet luxury, soft light",
    "cool_steel": "cool blue-grey desaturated steel tones, soft light",
    "muted_color": "muted natural color, soft professional light, not neon",
    "vivid_night": "moody night lighting with restrained color accents",
}

PILL_MAX_TOTAL_CHARS = 52  # heuristic for one-line pill at cover scale


def shorten_pill_beats(pill, max_total=PILL_MAX_TOTAL_CHARS):
    """Ensure three beats fit a one-line pill; shorten the longest if needed."""
    beats = [str(b).strip() for b in (pill or []) if str(b).strip()]
    while len(beats) < 3:
        beats.append("Insights")
    beats = beats[:3]

    def total(bs):
        return sum(len(b) for b in bs) + len(" | ") * 2 + len("✓ ") * 3

    for _ in range(12):
        if total(beats) <= max_total:
            break
        i = max(range(3), key=lambda k: len(beats[k]))
        if len(beats[i]) <= 4:
            break
        # Drop last word, else truncate
        parts = beats[i].split()
        if len(parts) > 1:
            beats[i] = " ".join(parts[:-1])
        else:
            beats[i] = beats[i][:-1]
    return beats


def normalize_hook(data):
    """Coerce model output into a safe hook dict."""
    if not isinstance(data, dict):
        data = {}
    tone = data.get("tone") if data.get("tone") in TONES else "muted_color"
    pill = shorten_pill_beats(data.get("pill") or [])
    headline = (data.get("headline") or "READ WHAT CHANGED").strip()
    subtitle = (data.get("subtitle") or "THE DETAIL MOST SUMMARIES SKIP").strip()
    photo_brief = (
        data.get("photo_brief")
        or "close-up of a developer desk with a laptop, soft light, no people"
    ).strip()
    return {
        "headline": headline,
        "subtitle": subtitle,
        "pill": pill,
        "photo_brief": photo_brief,
        "tone": tone,
    }


def build_flux_photo_prompt(hook):
    """Assemble FLUX prompt for right-pane photo only (no cover chrome)."""
    h = normalize_hook(hook)
    flavor = TONE_FLAVOR[h["tone"]]
    return (
        f"{h['photo_brief']}. "
        f"Photorealistic photograph, {flavor}. "
        "Main subject placed off-center toward the right third of the frame. "
        "No people, no faces, no readable text overlays, no watermarks, no logos, "
        "no UI mockup with sharp letters. Soft professional lighting."
    )[:2048]


def _format_cover_hook_user(title, tags, body):
    """Fill COVER_HOOK_USER without choking on `{`/`}` in post bodies."""

    def _escape(value):
        # .format() treats braces as placeholders; double them so literals survive.
        return str(value).replace("{", "{{").replace("}", "}}")

    return COVER_HOOK_USER.format(
        title=_escape(title or ""),
        tags=_escape(", ".join(tags or [])),
        body=_escape((body or "")[:6000]),
    )


def generate_cover_hook(title, tags, body, *, dry_run=False):
    """LLM cover_hook. Returns normalized dict. Dry-run returns a stub."""
    if dry_run:
        print("🧪 [dry-run] Skipping Bedrock cover_hook; emitting mock hook.")
        return normalize_hook(
            {
                "headline": "THE DETAIL HIDING IN PLAIN SIGHT",
                "subtitle": "WHAT THE SUMMARY NEVER MENTIONS",
                "pill": ["Clarity", "Depth", "Craft"],
                "photo_brief": (
                    "angled close-up of an open notebook and laptop on a wooden desk, "
                    "subject on the right, shallow depth of field, no people"
                ),
                "tone": "muted_color",
            }
        )

    prompt = _format_cover_hook_user(title, tags, body)
    raw = bedrock_client.converse(
        COVER_HOOK_SYSTEM, prompt, max_tokens=800, temperature=0.5
    )
    try:
        data = bedrock_client.extract_json(raw)
    except Exception:  # noqa: BLE001
        data = {}
    return normalize_hook(data)
