from pathlib import Path

import cover_heal as ch
import cover_status as cs


def _post(root: Path, slug: str, lines: list[str]):
    (root / "posts").mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "posts" / f"{slug}.mdx").write_text(
        "---\n" + "\n".join(lines) + "\n---\n## Body\n\nhello\n",
        encoding="utf-8",
    )


def test_seed_status_only(tmp_path: Path):
    _post(
        tmp_path,
        "good",
        [
            "title: Good",
            "slug: good",
            "date: '2025-08-01'",
            "image: /blog-images/good.jpg",
            "image_prompt: soft-focus photo of a keyboard",
            "cover_status: none",
        ],
    )
    (tmp_path / "images" / "good.jpg").write_bytes(b"\xff\xd8\xff")
    _post(
        tmp_path,
        "schem",
        [
            "title: Schem",
            "slug: schem",
            "date: '2025-01-01'",
            "image: /blog-images/schem.jpg",
            "image_prompt: Isometric technical illustration with layered depth",
            "cover_status: none",
        ],
    )
    (tmp_path / "images" / "schem.jpg").write_bytes(b"\xff\xd8\xff")
    _post(
        tmp_path,
        "missing",
        ["title: M", "slug: missing", "date: '2025-02-01'", "cover_status: none"],
    )

    result = ch.seed_status(str(tmp_path), dry_run=False)
    assert "good" in result["buckets"]["seeded_done"]
    assert "schem" in result["buckets"]["eligible_schematic"]
    assert "missing" in result["buckets"]["eligible_missing"]

    text = (tmp_path / "posts" / "good.mdx").read_text(encoding="utf-8")
    assert "cover_status: done" in text
    schem = (tmp_path / "posts" / "schem.mdx").read_text(encoding="utf-8")
    assert "cover_status: none" in schem


def test_select_batch_prefers_failed(tmp_path: Path):
    _post(
        tmp_path,
        "old-miss",
        ["title: O", "slug: old-miss", "date: '2024-01-01'", "cover_status: none"],
    )
    _post(
        tmp_path,
        "new-fail",
        ["title: N", "slug: new-fail", "date: '2025-08-01'", "cover_status: failed"],
    )
    batch = ch.select_batch(str(tmp_path), limit=1, slugs=None)
    assert [r["slug"] for r in batch] == ["new-fail"]


def test_main_seed_writes_report(tmp_path: Path, monkeypatch):
    _post(
        tmp_path,
        "good",
        [
            "title: Good",
            "image: /blog-images/good.jpg",
            "image_prompt: soft-focus photo",
            "cover_status: none",
        ],
    )
    (tmp_path / "images" / "good.jpg").write_bytes(b"\xff\xd8\xff")
    report = tmp_path / "report.md"
    rc = ch.main(
        [
            "--blog-root",
            str(tmp_path),
            "--seed-status-only",
            "--report",
            str(report),
        ]
    )
    assert rc == 0
    body = report.read_text(encoding="utf-8")
    assert "seeded_done" in body
    assert "good" in body
