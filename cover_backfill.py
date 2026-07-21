"""
One-off / backfill helper: attach a generated cover to an ALREADY-published post.

The daily pipeline writes covers only at post-creation time. This module is the
missing operation — take an existing `.mdx`, generate a structural image brief
from its own body, render + downscale a cover, and splice the image front-matter
in without disturbing the body. It is the shared foundation the future retry (D)
and legacy-backfill (E) workstreams will build on, so the risky part — the
front-matter splice — is pure and thoroughly tested.

`--dry-run` renders images and prints prompts but writes no `.mdx` changes.
"""

import argparse
import json
import os
import sys

from yaml_utils import yaml_safe_value
import bedrock_client
import image_client
import generate_digest as gd


# --------------------------------------------------------------------------
# Front-matter splice (pure; the riskiest surface — keep it dumb and tested)
# --------------------------------------------------------------------------
def attach_image_frontmatter(mdx_text, image_rel, alt, prompt):
    """Return `mdx_text` with image/image_alt/image_prompt spliced into the
    front-matter, canonically placed right after the `tags:` line (matching
    build_mdx's field order) so `source_url` stays adjacent to the image block.

    - Idempotent: if the post already has an `image:` line, returns it unchanged.
    - The body after the closing `---` is left byte-identical.
    - Raises ValueError if the text has no `--- ... ---` front-matter block.
    """
    if not mdx_text.startswith("---\n"):
        raise ValueError("no front-matter block at start of document")
    try:
        end = mdx_text.index("\n---\n", 4)
    except ValueError as e:
        raise ValueError("unterminated front-matter block") from e

    fm = mdx_text[4:end]
    rest = mdx_text[end:]  # starts with "\n---\n" + body — never modified
    lines = fm.split("\n")

    if any(l.startswith("image:") for l in lines):
        return mdx_text  # already has a cover; do not double-splice

    block = [
        f"image: {yaml_safe_value(image_rel)}",
        f"image_alt: {yaml_safe_value(alt)}",
        f"image_prompt: {yaml_safe_value(prompt)}",
    ]

    insert_at = next(
        (i + 1 for i, l in enumerate(lines) if l.startswith("tags:")),
        None,
    )
    if insert_at is None:
        # No tags line: place the block just before source_url, else at the end.
        insert_at = next(
            (i for i, l in enumerate(lines) if l.startswith("source_url:")),
            len(lines),
        )

    new_fm = "\n".join(lines[:insert_at] + block + lines[insert_at:])
    return "---\n" + new_fm + rest


# --------------------------------------------------------------------------
# Brief-only Bedrock call (cheaper than a full post generation)
# --------------------------------------------------------------------------
BRIEF_SYSTEM = (
    "You are an art director producing ONE structured image brief for the cover "
    "of an existing technical blog post. Return ONLY a JSON object, no prose."
)

BRIEF_USER = """Produce a cover image brief for this post as a JSON object with
exactly these keys:
{{
  "subject": "the STRUCTURE of the system or idea this post describes, as abstract geometry a person could sketch — nodes, layers, pipelines, flows, boundaries, groupings. Describe topology and relationships ONLY. Do NOT name screens, dashboards, panels, sidebars, charts, windows or any interface region. Do NOT name products, languages or their mascots. Do NOT use a metaphor. Banned as lazy/generic: roads, paths, highways, bridges, mountains, sunrises, horizons, lightbulbs, puzzle pieces, handshakes, rockets, chess pieces, icebergs.",
  "composition": "how it is framed — focal point and negative space",
  "mood": "2-4 word emotional tone",
  "palette": "2-3 dominant colors that fit the topic"
}}

TITLE: {title}
TAGS: {tags}

BODY:
\"\"\"
{body}
\"\"\"
"""


def generate_image_brief(title, body, tags):
    """Ask the LLM for a structural image brief for an existing post.

    Returns a dict (possibly with missing keys — build_image_prompt fills gaps).
    """
    prompt = BRIEF_USER.format(
        title=title, tags=", ".join(tags or []), body=(body or "")[:6000]
    )
    raw = bedrock_client.converse(BRIEF_SYSTEM, prompt, max_tokens=600, temperature=0.4)
    try:
        data = bedrock_client.extract_json(raw)
    except Exception:  # noqa: BLE001 - a bad brief must fall back, not crash
        data = {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def _parse_post(path):
    """Return (front_matter_dict, title, tags, body) from an .mdx file."""
    import yaml  # local import: only the orchestrator needs PyYAML

    text = open(path, encoding="utf-8").read()
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: no front-matter")
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :]
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return fm, fm.get("title", ""), tags, body, text


def regenerate_cover(blog_root, slug, *, dry_run, review_dir):
    """Generate + attach a cover for one existing post. Returns a status dict."""
    post_path = os.path.join(blog_root, "posts", f"{slug}.mdx")
    if not os.path.exists(post_path):
        return {"slug": slug, "status": "missing_post"}

    fm, title, tags, body, text = _parse_post(post_path)
    if fm.get("image"):
        return {"slug": slug, "status": "already_has_cover"}

    brief = generate_image_brief(title, body, tags)
    prompt = gd.build_image_prompt(brief, title, tags)
    alt = gd._slot(brief, "subject") or title

    raw = image_client.generate(prompt)
    img = gd.downscale_cover(raw)

    image_rel = f"/blog-images/{slug}.jpg"
    os.makedirs(review_dir, exist_ok=True)
    with open(os.path.join(review_dir, f"{slug}.jpg"), "wb") as f:
        f.write(img)

    if not dry_run:
        with open(os.path.join(blog_root, "images", f"{slug}.jpg"), "wb") as f:
            f.write(img)
        new_text = attach_image_frontmatter(text, image_rel, alt, prompt)
        with open(post_path, "w", encoding="utf-8") as f:
            f.write(new_text)

    return {
        "slug": slug,
        "status": "rendered" if dry_run else "attached",
        "bytes": len(img),
        "prompt": prompt,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Regenerate covers for existing posts.")
    p.add_argument("--blog-root", required=True, help="path to a clone of portfolio-blog")
    p.add_argument("--slugs", required=True, help="comma-separated post slugs")
    p.add_argument("--dry-run", action="store_true", help="render only; do not write .mdx/images")
    p.add_argument("--review-dir", default="cover-review", help="where preview jpgs are written")
    args = p.parse_args(argv)

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    results = []
    for slug in slugs:
        r = regenerate_cover(
            args.blog_root, slug, dry_run=args.dry_run, review_dir=args.review_dir
        )
        results.append(r)
        print(f"• {r['status']:<18} {slug}")
        if r.get("prompt"):
            print(f"    prompt: {r['prompt'][:200]}")

    print("\n" + json.dumps({"results": results, "usage": bedrock_client.usage_summary()}, indent=2))
    ok = all(r["status"] in ("rendered", "attached", "already_has_cover") for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
