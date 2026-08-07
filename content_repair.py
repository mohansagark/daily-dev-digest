"""Content repair helpers — origin heuristic, junk gate, FM splice, ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import bedrock_client
import repair_prompts
import search_client

# Safe posts/ filename stems: lowercase alnum + hyphens only (blocks path segments).
# Allows trailing hyphens — some legacy truncated slugs end that way.
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _non_empty(value) -> bool:
    return bool(str(value or "").strip())


def is_valid_slug(slug: str) -> bool:
    """Return True when ``slug`` is a safe posts/ filename stem (no path segments)."""
    return bool(_SLUG_RE.fullmatch(slug or "")) and ".." not in slug


def detect_origin(fm: dict) -> str:
    """Return ``bot`` when both ``image`` and ``image_prompt`` are present; else ``scraper``."""
    if _non_empty(fm.get("image")) and _non_empty(fm.get("image_prompt")):
        return "bot"
    return "scraper"


def should_delete(verdict: str, confidence: str) -> bool:
    """Delete only high-confidence junk (spec §6 delete policy)."""
    return verdict == "junk" and confidence == "high"


def _parse_mdx_text(text: str) -> tuple[dict, str]:
    import yaml  # local import: only MDX helpers need PyYAML

    if not text.startswith("---\n"):
        raise ValueError("no front-matter block at start of document")
    try:
        end = text.index("\n---\n", 4)
    except ValueError as e:
        raise ValueError("unterminated front-matter block") from e
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :]
    return fm, body


def load_mdx(path: str) -> tuple[dict, str]:
    """Load front matter and body from an ``.mdx`` file."""
    with open(path, encoding="utf-8") as f:
        return _parse_mdx_text(f.read())


def dump_mdx(fm: dict, body: str) -> str:
    """Serialize front matter and body to MDX text."""
    import yaml  # local import: only MDX helpers need PyYAML

    fm_yaml = yaml.safe_dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).rstrip("\n")
    return f"---\n{fm_yaml}\n---\n{body}"


def apply_kept_frontmatter(fm: dict, *, origin: str, image_suggestion: str) -> dict:
    """Return FM with repair stamps for kept posts; preserve existing ``source_url`` only."""
    out = dict(fm)
    out["ai"] = True
    out["origin"] = origin
    out["author"] = "Mohan Sagar"
    out["cover_status"] = "none"
    out["image_suggestion"] = image_suggestion
    return out


def _local_cover_path(blog_root: str, slug: str) -> str:
    return os.path.join(blog_root, "images", f"{slug}.jpg")


def maybe_delete_local_cover(blog_root: str, fm: dict, slug: str) -> bool:
    """Delete ``images/{slug}.jpg`` only when FM ``image`` is a local slug cover path."""
    image = str(fm.get("image") or "").strip()
    if not image or image.startswith(("http://", "https://")):
        return False
    allowed = {f"/blog-images/{slug}.jpg", f"images/{slug}.jpg"}
    if image not in allowed:
        return False
    path = _local_cover_path(blog_root, slug)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def body_hash(body: str) -> str:
    """Stable hash for ledger idempotency (matches digest helper)."""
    return hashlib.md5(body.encode("utf-8")).hexdigest()


DEFAULT_LEDGER_PATH = os.path.join(os.path.dirname(__file__), "repair_ledger.json")


class Ledger:
    """Durable idempotency store keyed by slug + input body hash."""

    COMPLETED_ACTIONS = {"deleted", "rewritten", "kept"}

    def __init__(self, path: str | None = None):
        self.path = path or DEFAULT_LEDGER_PATH

    def load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")

    def should_skip(self, slug: str, body: str, *, force: bool = False) -> bool:
        if force:
            return False
        entry = self.load().get(slug)
        if not isinstance(entry, dict):
            return False
        return (
            entry.get("body_hash") == body_hash(body)
            and entry.get("action") in self.COMPLETED_ACTIONS
        )

    def record(self, slug: str, body: str, **fields: Any) -> None:
        data = self.load()
        entry = dict(fields)
        entry["body_hash"] = body_hash(body)
        data[slug] = entry
        self.save(data)


def _gist(body: str, *, limit: int = 8000) -> str:
    """Bound legacy content before including it in an LLM prompt."""
    return (body or "").strip()[:limit]


def _json_response(system_prompt: str, user_prompt: str, *, max_tokens: int, temperature: float) -> dict:
    raw = bedrock_client.converse(
        system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature
    )
    data = bedrock_client.extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Bedrock response must be a JSON object")
    return data


def _triage(title: str, body: str) -> dict:
    data = _json_response(
        repair_prompts.TRIAGE_SYSTEM_PROMPT,
        repair_prompts.TRIAGE_USER_TEMPLATE.format(title=title, body_gist=_gist(body)),
        max_tokens=500,
        temperature=0.1,
    )
    if data.get("verdict") not in {"junk", "rewrite", "clean"}:
        raise ValueError(f"invalid triage verdict: {data.get('verdict')!r}")
    if data.get("confidence") not in {"high", "medium", "low"}:
        raise ValueError(f"invalid triage confidence: {data.get('confidence')!r}")
    data["reason"] = str(data.get("reason") or "").strip()
    return data


def _has_unclosed_code_fence(body: str) -> bool:
    """Detect an unmatched Markdown code fence without relying on model triage."""
    open_fences = {"```": 0, "~~~": 0}
    for line in body.splitlines():
        stripped = line.lstrip()
        for fence in open_fences:
            if stripped.startswith(fence):
                open_fences[fence] += 1
    return any(count % 2 for count in open_fences.values())


def _search_notes(title: str, body: str) -> tuple[str, bool]:
    query = f"{title}\n{_gist(body, limit=1000)}".strip()
    try:
        return search_client.format_notes(search_client.search(query)), False
    except Exception as exc:  # noqa: BLE001 - search is explicitly best-effort
        print(f"⚠️ Search failed for {title!r}: {exc}")
        return "", True


def _generate(title: str, body: str, search_notes: str) -> dict:
    data = _json_response(
        repair_prompts.GENERATE_SYSTEM_PROMPT,
        repair_prompts.GENERATE_USER_TEMPLATE.format(
            style="clear, pragmatic, and lightly opinionated",
            title=title,
            body_gist=_gist(body),
            search_notes=search_notes,
        ),
        max_tokens=5000,
        temperature=0.6,
    )
    missing = [key for key in repair_prompts.GENERATE_KEYS if key not in data]
    if missing:
        raise ValueError(f"generate response missing keys: {missing}")
    if not isinstance(data["tags"], list):
        data["tags"] = [str(data["tags"])]
    return data


def _verify(body: str, generated: dict, search_notes: str) -> dict:
    data = _json_response(
        repair_prompts.VERIFY_SYSTEM_PROMPT,
        repair_prompts.VERIFY_USER_TEMPLATE.format(
            body_gist=_gist(body),
            search_notes=search_notes,
            draft_body=generated["body_markdown"],
        ),
        max_tokens=5000,
        temperature=0.1,
    )
    data["corrected_body_markdown"] = (
        data.get("corrected_body_markdown") or generated["body_markdown"]
    )
    return data


def _image_suggestion(fm: dict, body: str) -> str:
    prompt = repair_prompts.IMAGE_SUGGESTION_USER_TEMPLATE.format(
        image_subject=repair_prompts.IMAGE_SUBJECT_INSTRUCTION,
        title=str(fm.get("title") or ""),
        tags=", ".join(str(tag) for tag in fm.get("tags") or []),
        body=_gist(body, limit=6000),
    )
    raw = bedrock_client.converse(
        repair_prompts.IMAGE_SUGGESTION_SYSTEM_PROMPT,
        prompt,
        max_tokens=800,
        temperature=0.5,
    )
    return str(raw or "").strip()


def _record(
    ledger: Ledger,
    post_slug: str,
    body: str,
    *,
    verdict: str,
    confidence: str,
    reason: str,
    action: str,
    **extra: Any,
) -> None:
    extra.pop("slug", None)
    ledger.record(
        post_slug,
        body,
        verdict=verdict,
        confidence=confidence,
        reason=reason,
        action=action,
        timestamp=datetime.now(timezone.utc).isoformat(),
        **extra,
    )


def repair_one(blog_root: str, slug: str, *, dry_run: bool = False, force: bool = False) -> dict:
    """Triage and repair one post, returning its reviewable action record."""
    if not is_valid_slug(slug):
        return {
            "slug": slug,
            "action": "error",
            "reason": f"invalid slug: {slug!r}",
            "verdict": "error",
            "confidence": "",
        }

    path = os.path.join(blog_root, "posts", f"{slug}.mdx")
    ledger = Ledger()
    try:
        fm, original_body = load_mdx(path)
    except Exception as exc:  # noqa: BLE001 - malformed legacy posts must not kill the batch
        result = {
            "slug": slug,
            "action": "error",
            "reason": f"load failed: {exc}",
            "verdict": "error",
            "confidence": "",
        }
        if not dry_run:
            _record(
                ledger,
                slug,
                "",
                bedrock_calls=0,
                search_calls=0,
                search_failed=False,
                **result,
            )
        return result

    if ledger.should_skip(slug, original_body, force=force):
        return {"slug": slug, "action": "skipped", "reason": "ledger body hash matches"}

    bedrock_calls = 0
    search_calls = 0

    try:
        bedrock_calls += 1
        triage = _triage(str(fm.get("title") or slug), original_body)
    except Exception as exc:  # noqa: BLE001 - continue a batch after Bedrock failure
        result = {
            "slug": slug,
            "action": "error",
            "reason": f"triage failed: {exc}",
            "verdict": "error",
            "confidence": "",
        }
        _record(
            ledger,
            slug,
            original_body,
            bedrock_calls=bedrock_calls,
            search_calls=search_calls,
            search_failed=False,
            **result,
        )
        return result

    verdict = triage["verdict"]
    confidence = triage["confidence"]
    reason = triage["reason"]
    if verdict in {"clean", "junk"} and _has_unclosed_code_fence(original_body):
        verdict = "rewrite"
        reason = f"{reason}; deterministic guard: unclosed code fence".lstrip("; ")
    result = {"slug": slug, "verdict": verdict, "confidence": confidence, "reason": reason}

    if should_delete(verdict, confidence):
        result["action"] = "would_delete" if dry_run else "deleted"
        if not dry_run:
            try:
                os.remove(path)
                result["local_cover_deleted"] = maybe_delete_local_cover(blog_root, fm, slug)
                _record(
                    ledger,
                    slug,
                    original_body,
                    bedrock_calls=bedrock_calls,
                    search_calls=search_calls,
                    search_failed=False,
                    **result,
                )
            except OSError as exc:
                result["action"] = "error"
                result["reason"] = f"delete failed: {exc}"
                _record(
                    ledger,
                    slug,
                    original_body,
                    bedrock_calls=bedrock_calls,
                    search_calls=search_calls,
                    search_failed=False,
                    **result,
                )
        return result

    rewrite = verdict == "rewrite" or verdict == "junk"
    if dry_run:
        result["action"] = "would_rewrite" if rewrite else "would_keep"
        if rewrite:
            print(f"🧪 [dry-run] Would search and rewrite {slug!r}.")
        return result

    updated_fm = dict(fm)
    final_body = original_body
    search_failed = False
    if rewrite:
        search_calls += 1
        search_notes, search_failed = _search_notes(str(fm.get("title") or slug), original_body)
        try:
            bedrock_calls += 1
            generated = _generate(str(fm.get("title") or slug), original_body, search_notes)
            bedrock_calls += 1
            verified = _verify(original_body, generated, search_notes)
        except Exception as exc:  # noqa: BLE001 - never replace on an incomplete rewrite
            result["action"] = "error"
            result["reason"] = f"rewrite failed: {exc}"
            _record(
                ledger,
                slug,
                original_body,
                bedrock_calls=bedrock_calls,
                search_calls=search_calls,
                search_failed=search_failed,
                **result,
            )
            return result
        final_body = str(verified["corrected_body_markdown"])
        updated_fm.update(
            title=generated["headline"],
            subtitle=generated["subtitle"],
            summary=generated["meta_description"],
            tags=generated["tags"],
        )
        result["action"] = "rewritten"
    else:
        result["action"] = "kept"

    try:
        try:
            bedrock_calls += 1
            suggestion = _image_suggestion(updated_fm, final_body)
        except Exception as exc:  # noqa: BLE001 - keepers may retain prior suggestion
            print(f"⚠️ Image suggestion failed for {slug!r}: {exc}")
            result["image_suggestion_error"] = type(exc).__name__
            if result.get("action") == "rewritten":
                # Stale pre-rewrite suggestion would describe the old post — clear it.
                suggestion = ""
            else:
                suggestion = str(fm.get("image_suggestion") or "")
        updated_fm = apply_kept_frontmatter(
            updated_fm, origin=detect_origin(fm), image_suggestion=suggestion
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump_mdx(updated_fm, final_body))
        _record(
            ledger,
            slug,
            original_body,
            bedrock_calls=bedrock_calls,
            search_calls=search_calls,
            search_failed=search_failed,
            **result,
        )
    except OSError as exc:
        result["action"] = "error"
        result["reason"] = f"write failed: {exc}"
        _record(
            ledger,
            slug,
            original_body,
            bedrock_calls=bedrock_calls,
            search_calls=search_calls,
            search_failed=search_failed,
            **result,
        )
    return result


def write_triage_report(blog_root: str, records: list[dict]) -> str:
    """Write a concise, reviewable Markdown table for this invocation."""
    path = os.path.join(blog_root, "triage-report.md")
    columns = (
        "slug",
        "verdict",
        "confidence",
        "action",
        "reason",
        "image_suggestion_error",
    )
    rows = [
        "# Content repair triage report",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for record in records:
        cells = [
            str(record.get(key, "")).replace("|", "\\|").replace("\n", " ")
            for key in columns
        ]
        rows.append("| " + " | ".join(cells) + " |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return path


def _post_slugs(blog_root: str) -> list[str]:
    posts = os.path.join(blog_root, "posts")
    if not os.path.isdir(posts):
        return []
    return sorted(
        filename[:-4] for filename in os.listdir(posts) if filename.endswith(".mdx")
    )


def main(argv: list[str] | None = None) -> list[dict]:
    """Run repair over selected posts; dry-runs write only the Markdown report."""
    parser = argparse.ArgumentParser(
        description=(
            "Repair legacy MDX posts. --dry-run writes triage-report.md but does not "
            "modify MDX files or repair_ledger.json."
        )
    )
    parser.add_argument("--blog-root", required=True, help="Path to the portfolio-blog checkout")
    parser.add_argument("--slugs", help="Comma-separated explicit slug subset")
    parser.add_argument("--limit", type=int, help="Maximum number of unfinished posts to process")
    parser.add_argument("--dry-run", action="store_true", help="Do not modify MDX or ledger; report only")
    parser.add_argument("--force", action="store_true", help="Re-process posts even when the ledger matches")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be non-negative")

    slugs = (
        [slug.strip() for slug in args.slugs.split(",") if slug.strip()]
        if args.slugs
        else _post_slugs(args.blog_root)
    )
    records: list[dict] = []
    processed = 0
    for slug in slugs:
        if args.limit is not None and processed >= args.limit:
            break
        record = repair_one(
            args.blog_root, slug, dry_run=args.dry_run, force=args.force
        )
        records.append(record)
        if record["action"] != "skipped":
            processed += 1
    report = write_triage_report(args.blog_root, records)
    print(f"Wrote {report}")
    return records


if __name__ == "__main__":
    main()
