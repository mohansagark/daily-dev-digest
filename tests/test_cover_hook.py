import cover_hook as ch


def test_shorten_pill_beats_pads_to_three():
    assert len(ch.shorten_pill_beats(["A"])) == 3


def test_shorten_pill_beats_reduces_longest():
    long = ["Very Long Beat Name Here", "OK", "Yes"]
    out = ch.shorten_pill_beats(long, max_total=40)
    assert sum(len(b) for b in out) < sum(len(b) for b in long)
    assert len(out) == 3


def test_normalize_hook_defaults_tone():
    h = ch.normalize_hook({"tone": "neon", "pill": ["a", "b", "c"]})
    assert h["tone"] == "muted_color"
    assert len(h["pill"]) == 3


def test_build_flux_photo_prompt_includes_guards():
    p = ch.build_flux_photo_prompt(
        {
            "photo_brief": "desk with laptop",
            "tone": "cool_steel",
            "pill": ["a", "b", "c"],
            "headline": "H",
            "subtitle": "S",
        }
    )
    assert "no people" in p.lower() or "No people" in p
    assert "right" in p.lower()
    assert len(p) <= 2048


def test_dry_run_hook_stub():
    h = ch.generate_cover_hook("Title", ["ai"], "body text", dry_run=True)
    assert h["headline"]
    assert len(h["pill"]) == 3
    assert h["tone"] in ch.TONES


def test_format_cover_hook_user_tolerates_braces_in_body():
    body = "Use `map.get(key, {default: 1})` and a `{slug}` token."
    prompt = ch._format_cover_hook_user("T", ["css"], body)
    assert "map.get(key, {default: 1})" in prompt
    assert "{slug}" in prompt
    assert "TITLE: T" in prompt


def test_cover_hook_logs_fallback_on_bad_json(monkeypatch, capsys):
    monkeypatch.setattr(ch.bedrock_client, "converse", lambda *a, **k: "not-json")
    monkeypatch.setattr(
        ch.bedrock_client,
        "extract_json",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")),
    )
    h = ch.generate_cover_hook("T", ["ai"], "body", dry_run=False)
    assert h["headline"]
    out = capsys.readouterr().out
    assert "COVER_HOOK_STATUS=fallback" in out
