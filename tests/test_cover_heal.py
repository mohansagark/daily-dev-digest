from pathlib import Path

from PIL import Image

import cover_heal as ch
import cover_status as cs


def _write_jpeg(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 50, 60)).save(path, "JPEG")


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
    _write_jpeg(tmp_path / "images" / "good.jpg", cs.EDITORIAL_SIZE)
    _post(
        tmp_path,
        "wrong",
        [
            "title: Wrong",
            "slug: wrong",
            "date: '2025-01-01'",
            "image: /blog-images/wrong.jpg",
            "image_prompt: soft-focus photo without schematic keywords",
            "cover_status: none",
        ],
    )
    _write_jpeg(tmp_path / "images" / "wrong.jpg", (800, 800))
    _post(
        tmp_path,
        "missing",
        ["title: M", "slug: missing", "date: '2025-02-01'", "cover_status: none"],
    )

    result = ch.seed_status(str(tmp_path), dry_run=False)
    assert "good" in result["buckets"]["seeded_done"]
    assert "wrong" in result["buckets"]["eligible_wrong_size"]
    assert "missing" in result["buckets"]["eligible_missing"]
    assert "eligible_schematic" not in result["buckets"]

    text = (tmp_path / "posts" / "good.mdx").read_text(encoding="utf-8")
    assert "cover_status: done" in text
    wrong = (tmp_path / "posts" / "wrong.mdx").read_text(encoding="utf-8")
    assert "cover_status: none" in wrong


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


def test_main_seed_writes_report(tmp_path: Path):
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
    _write_jpeg(tmp_path / "images" / "good.jpg", cs.EDITORIAL_SIZE)
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
    assert "eligible_wrong_size" in body
    assert "eligible_schematic" not in body
    assert "good" in body


def test_heal_one_success_overwrites_multiline_prompt(tmp_path: Path, monkeypatch):
    slug = "reheal"
    _post(
        tmp_path,
        slug,
        [
            "title: Reheal",
            f"slug: {slug}",
            "date: '2025-01-01'",
            f"image: /blog-images/{slug}.jpg",
            "image_prompt: |",
            "  old line one",
            "  old line two",
            "cover_status: failed",
        ],
    )
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", (800, 800))
    rows = ch.select_eligible(str(tmp_path), slugs=[slug])
    assert len(rows) == 1

    def fake_cover(*_a, **_k):
        return {
            "image": f"/blog-images/{slug}.jpg",
            "alt": "new alt",
            "prompt": "fresh single-line brief",
        }

    monkeypatch.setattr(ch.gd, "generate_editorial_cover", fake_cover)
    assert ch.heal_one(str(tmp_path), rows[0], dry_run=False) == "ok"
    text = (tmp_path / "posts" / f"{slug}.mdx").read_text(encoding="utf-8")
    assert "cover_status: done" in text
    assert "fresh single-line brief" in text
    assert "old line one" not in text
    assert "old line two" not in text


def test_heal_one_failure_preserves_image(tmp_path: Path, monkeypatch):
    slug = "boom"
    _post(
        tmp_path,
        slug,
        [
            "title: Boom",
            f"slug: {slug}",
            f"image: /blog-images/{slug}.jpg",
            "image_prompt: keep me",
            "cover_status: none",
        ],
    )
    _write_jpeg(tmp_path / "images" / f"{slug}.jpg", (800, 800))
    rows = ch.select_eligible(str(tmp_path), slugs=[slug])

    def boom(*_a, **_k):
        raise RuntimeError("flux down")

    monkeypatch.setattr(ch.gd, "generate_editorial_cover", boom)
    assert ch.heal_one(str(tmp_path), rows[0], dry_run=False) == "failed"
    text = (tmp_path / "posts" / f"{slug}.mdx").read_text(encoding="utf-8")
    assert "cover_status: failed" in text
    assert "image: /blog-images/boom.jpg" in text
    assert "image_prompt: keep me" in text
