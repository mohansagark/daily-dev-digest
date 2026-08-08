"""Daily editorial cover self-heal for portfolio-blog posts.

See docs/superpowers/specs/2026-08-07-cover-self-heal-pipeline-design.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import cover_status as cs
import generate_digest as gd

REPORT_PATH = "cover_heal_report.md"


def _load_mdx(path: str) -> tuple[dict, str, str]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("no front-matter")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("unterminated front-matter")
    fm = yaml.safe_load(text[3:end]) or {}
    if not isinstance(fm, dict):
        raise ValueError("front-matter is not a mapping")
    body = text[end + 4 :]
    return fm, body, text


def _scan_posts(blog_root: str) -> list[dict]:
    posts_dir = Path(blog_root) / "posts"
    rows = []
    for path in sorted(posts_dir.glob("*.mdx")):
        slug = path.stem
        try:
            fm, body, raw = _load_mdx(str(path))
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Skip {slug}: load failed ({exc})")
            continue
        rows.append(
            {
                "slug": slug,
                "path": str(path),
                "fm": fm,
                "body": body,
                "raw": raw,
            }
        )
    return rows


def seed_status(blog_root: str, *, dry_run: bool = False) -> dict:
    buckets = {
        "seeded_done": [],
        "eligible_wrong_size": [],
        "eligible_missing": [],
        "already_done": [],
    }
    changed = 0
    for row in _scan_posts(blog_root):
        slug = row["slug"]
        fm = row["fm"]
        kind = cs.classify_for_seed(fm, blog_root, slug)
        buckets[kind].append(slug)
        if kind != "seeded_done":
            continue
        if dry_run:
            continue
        new_text = cs.upsert_cover_fields(row["raw"], cover_status="done")
        Path(row["path"]).write_text(new_text, encoding="utf-8")
        changed += 1
        print(f"✅ Seeded cover_status: done → {slug}")
    return {"buckets": buckets, "changed": changed}


def select_eligible(blog_root: str, *, slugs: list[str] | None) -> list[dict]:
    wanted = set(slugs or [])
    eligible = []
    for row in _scan_posts(blog_root):
        slug = row["slug"]
        if wanted and slug not in wanted:
            continue
        fm = row["fm"]
        if not cs.is_eligible(fm, blog_root, slug):
            continue
        eligible.append(
            {
                **row,
                "tier": cs.selection_tier(fm, blog_root, slug),
                "date": cs.parse_post_date(fm),
            }
        )
    return cs.sort_eligible(eligible)


def select_batch(
    blog_root: str, *, limit: int, slugs: list[str] | None
) -> list[dict]:
    return select_eligible(blog_root, slugs=slugs)[: max(0, limit)]


def heal_one(blog_root: str, row: dict, *, dry_run: bool) -> str:
    """Return 'ok' | 'failed'."""
    slug = row["slug"]
    fm = row["fm"]
    title = str(fm.get("title") or slug)
    tags = fm.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    body = row["body"] or ""
    images_dir = os.path.join(blog_root, "images")

    try:
        if dry_run:
            print(f"🧪 [dry-run] Would heal cover for {slug}")
            return "ok"
        cover = gd.generate_editorial_cover(
            title,
            tags,
            body[:8000],
            slug,
            dry_run=False,
            images_dir=images_dir,
        )
        new_text = cs.upsert_cover_fields(
            row["raw"],
            cover_status="done",
            image=cover["image"],
            image_alt=cover["alt"],
            image_prompt=cover["prompt"],
        )
        Path(row["path"]).write_text(new_text, encoding="utf-8")
        print(f"✅ Healed cover: {slug}")
        return "ok"
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Heal failed for {slug}: {exc}")
        try:
            new_text = cs.upsert_cover_fields(row["raw"], cover_status="failed")
            Path(row["path"]).write_text(new_text, encoding="utf-8")
        except Exception as write_exc:  # noqa: BLE001
            print(f"⚠️ Could not mark failed for {slug}: {write_exc}")
        return "failed"


def write_report(
    path: str,
    *,
    mode: str,
    buckets: dict | None = None,
    attempted: list[str] | None = None,
    succeeded: list[str] | None = None,
    failed: list[str] | None = None,
    remaining: int | None = None,
) -> None:
    lines = [
        "# Cover heal report",
        "",
        f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"- mode: {mode}",
        "",
    ]
    if buckets is not None:
        lines.append("## Seed buckets")
        lines.append("")
        for key in (
            "seeded_done",
            "eligible_wrong_size",
            "eligible_missing",
            "already_done",
        ):
            slugs = buckets.get(key) or []
            lines.append(f"### {key} ({len(slugs)})")
            lines.append("")
            for s in slugs:
                lines.append(f"- {s}")
            lines.append("")
    if attempted is not None:
        lines.append("## Heal batch")
        lines.append("")
        lines.append(f"- attempted: {len(attempted)}")
        lines.append(f"- succeeded: {len(succeeded or [])}")
        lines.append(f"- failed: {len(failed or [])}")
        if remaining is not None:
            lines.append(f"- remaining_eligible_estimate: {remaining}")
        lines.append("")
        lines.append("### succeeded")
        lines.append("")
        for s in succeeded or []:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("### failed")
        lines.append("")
        for s in failed or []:
            lines.append(f"- {s}")
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"📝 Wrote {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Editorial cover self-heal")
    p.add_argument("--blog-root", required=True)
    # 35 covers x ~192 neurons (measured) = ~6.7k, plus the digest's daily cover,
    # keeps a run under ~70% of the 10k/day Workers AI free tier.
    p.add_argument("--limit", type=int, default=35)
    p.add_argument("--slugs", default="", help="Comma-separated slug filter")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seed-status-only", action="store_true")
    p.add_argument("--report", default=REPORT_PATH)
    args = p.parse_args(argv)

    blog_root = args.blog_root
    if not os.path.isdir(os.path.join(blog_root, "posts")):
        print(f"❌ No posts/ under {blog_root}", file=sys.stderr)
        return 2

    slug_filter = [s.strip() for s in args.slugs.split(",") if s.strip()] or None

    if args.seed_status_only:
        result = seed_status(blog_root, dry_run=args.dry_run)
        write_report(
            args.report,
            mode="seed-status-only" + ("-dry-run" if args.dry_run else ""),
            buckets=result["buckets"],
        )
        return 0

    all_eligible = select_eligible(blog_root, slugs=slug_filter)
    batch = all_eligible[: max(0, args.limit)]
    remaining = max(0, len(all_eligible) - len(batch))

    attempted: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []
    for row in batch:
        attempted.append(row["slug"])
        # Re-read raw before write in case prior iteration... each row is independent
        outcome = heal_one(blog_root, row, dry_run=args.dry_run)
        if outcome == "ok":
            succeeded.append(row["slug"])
        else:
            failed.append(row["slug"])

    write_report(
        args.report,
        mode="heal" + ("-dry-run" if args.dry_run else ""),
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        remaining=remaining,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
