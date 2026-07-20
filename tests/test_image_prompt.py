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


def test_slots_ending_in_a_period_do_not_double_up():
    # The LLM usually returns slots as full sentences ending in '.', and the
    # joiner used to append its own — producing "platform.. Composition:".
    brief = {"subject": "a paved highway stretching into the horizon.",
             "composition": "highway is the focal point.",
             "mood": "empowering, streamlined.",
             "palette": "muted modern tech palette."}
    p = build_image_prompt(brief, "H", [])
    assert ".." not in p
    assert "horizon. Composition:" in p
    assert "focal point. Mood:" in p
    assert "streamlined. Color palette:" in p


def test_other_trailing_punctuation_is_preserved():
    # Only a trailing '.' is redundant; '?' / '!' carry meaning and stay put.
    p = build_image_prompt({"subject": "what if code could fly?"}, "H", [])
    assert "what if code could fly? Composition:" in p


def test_tags_become_a_domain_anchor():
    # tags are the strongest topical signal we have; they used to be accepted
    # and silently discarded, which is why covers drifted into generic stock.
    p = build_image_prompt(FULL, "H", ["gitops", "kubernetes"])
    assert "Subject domain: gitops, kubernetes." in p
    # anchored after the subject, before the framing
    assert p.index("lighthouse") < p.index("Subject domain:") < p.index("Composition:")


def test_tags_absent_or_junk_add_no_clause():
    for junk in ([], None, "not-a-list", [""], [None, 42]):
        p = build_image_prompt(FULL, "H", junk)
        assert "Subject domain:" not in p
        assert ".." not in p          # no dangling separator when omitted


def test_tags_are_capped():
    p = build_image_prompt(FULL, "H", ["a", "b", "c", "d", "e", "f", "g"])
    assert "Subject domain: a, b, c, d, e." in p
    assert "f" not in p.split("Composition:")[0].split("Subject domain:")[1]


def test_slot_trims_and_guards():
    assert _slot({"a": "  hi  "}, "a") == "hi"
    assert _slot({"a": ""}, "a") == ""
    assert _slot({}, "a") == ""
    assert _slot({"a": 5}, "a") == ""
