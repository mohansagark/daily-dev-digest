import json

import generate_digest as gd
from generate_digest import generate_post, GENERATE_KEYS

STRATEGY = {"focus": ["css", "js"], "style": "energetic", "description": "Frontend"}
ARTICLE = {"title": "T", "link": "http://x", "content": "body " * 50, "author": "A"}


def test_dry_run_has_required_keys_without_image_brief():
    out = generate_post(ARTICLE, STRATEGY, dry_run=True)
    for k in GENERATE_KEYS:
        assert k in out
    assert "image_brief" not in out


def test_image_brief_not_in_generate_keys():
    assert "image_brief" not in GENERATE_KEYS


def test_generate_template_omits_image_brief():
    assert "image_brief" not in gd.GENERATE_USER_TEMPLATE


def test_generate_prompts_depersonalize_first_person_journals():
    sys_l = gd.GENERATE_SYSTEM_PROMPT.lower()
    user_l = gd.GENERATE_USER_TEMPLATE.lower()
    assert "knowledge article" in sys_l
    assert "first-person journal" in sys_l
    assert "never present someone else's" in sys_l
    assert "knowledge article, not a personal diary" in user_l
    assert "depersonalize" in user_l


def test_generate_prompts_require_seo_structure():
    user = gd.GENERATE_USER_TEMPLATE
    assert "answer-first" in user
    assert "## Key Takeaways" in user
    assert "## FAQ" in user
    assert "question-style" in user
    assert "never \"Takeaways\" alone" in user


def test_verify_prompts_strip_fabricated_autobiography():
    sys_l = gd.VERIFY_SYSTEM_PROMPT.lower()
    user_l = gd.VERIFY_USER_TEMPLATE.lower()
    assert "first-person autobiography" in sys_l
    assert "knowledge-article" in sys_l
    assert "depersonalize" in user_l
    assert "key takeaways" in user_l


def test_malformed_extra_image_brief_ignored(monkeypatch):
    # Extra keys from the model are fine; we no longer normalize image_brief.
    raw = json.dumps({
        "headline": "H",
        "subtitle": "S",
        "meta_description": "M",
        "tags": ["css", "js"],
        "image_brief": "oops",
        "body_markdown": "## Body\n\ntext",
    })
    monkeypatch.setattr(gd.bedrock_client, "converse", lambda *a, **k: raw)
    out = generate_post(ARTICLE, STRATEGY, dry_run=False)
    assert out["headline"] == "H"
    assert out.get("image_brief") == "oops"  # untouched; unused by cover path
