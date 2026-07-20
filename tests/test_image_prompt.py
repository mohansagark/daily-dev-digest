from generate_digest import build_image_prompt, _slot, BRAND_STYLE, NEGATIVES

FULL = {"subject": "a lighthouse over circuit-board waves",
        "composition": "centered hero, wide negative space",
        "mood": "calm, precise",
        "palette": "deep indigo, warm amber"}


def test_all_slots_present_and_ordered():
    p = build_image_prompt(FULL, "Some Headline", ["css"])
    assert p.startswith("a lighthouse over circuit-board waves.")
    assert "Composition: centered hero, wide negative space" in p
    assert "Mood: calm, precise" in p
    assert "Color palette: deep indigo, warm amber" in p
    assert BRAND_STYLE in p
    assert f"Avoid: {NEGATIVES}" in p
    # subject appears before style, style before avoid
    assert p.index("lighthouse") < p.index(BRAND_STYLE) < p.index("Avoid:")


def test_empty_slots_fall_back():
    p = build_image_prompt({}, "My Great Post", ["react"])
    assert "My Great Post" in p           # subject fallback uses headline
    assert BRAND_STYLE in p
    assert "Avoid:" in p


def test_non_string_slots_are_ignored():
    p = build_image_prompt({"subject": None, "mood": 123}, "H", [])
    assert "H" in p                       # falls back cleanly, no crash


def test_truncates_to_2048():
    brief = {"subject": "x" * 5000, "composition": "c", "mood": "m", "palette": "p"}
    assert len(build_image_prompt(brief, "H", [])) <= 2048


def test_slot_trims_and_guards():
    assert _slot({"a": "  hi  "}, "a") == "hi"
    assert _slot({"a": ""}, "a") == ""
    assert _slot({}, "a") == ""
    assert _slot({"a": 5}, "a") == ""
