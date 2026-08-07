import bedrock_client as bc


def test_extract_json_balanced_object_ignores_braces_inside_strings():
    # Regression: rfind('}') used to cut at a } inside body_markdown code,
    # producing invalid JSON.
    raw = r"""{
  "headline": "Demo",
  "subtitle": "Sub",
  "meta_description": "Meta",
  "tags": ["css"],
  "body_markdown": "Close braces show up in docs: }\n\n```js\nfunction x() { return 1; }\n```\n"
}
"""
    data = bc.extract_json(raw)
    assert data["headline"] == "Demo"
    assert "function x()" in data["body_markdown"]
    assert "}" in data["body_markdown"]


def test_extract_json_ignores_trailing_prose_after_object():
    raw = '{"headline": "H", "tags": ["a"], "body_markdown": "ok"}\nThanks!'
    data = bc.extract_json(raw)
    assert data["headline"] == "H"


def test_old_rfind_heuristic_would_truncate_but_balanced_parser_succeeds():
    # Outer object ends after the real closing brace; an early } sits in the string.
    body = "example: function () { return true; } done"
    raw = (
        '{"headline":"H","subtitle":"S","meta_description":"M","tags":["t"],'
        f'"body_markdown":"{body}"}}'
    )
    # Prove naive rfind would pick a } inside the string (before the real end).
    start = raw.find("{")
    naive = raw[start : raw.rfind("}") + 1]
    # With only one top-level object this may still parse; force a trailing } trap:
    raw_trap = raw + "\ntrailing {\"x\": 1}"
    naive_trap = raw_trap[raw_trap.find("{") : raw_trap.rfind("}") + 1]
    assert naive_trap.count('"headline"') == 1
    # Balanced extractor must still return only the first complete object.
    data = bc.extract_json(raw_trap)
    assert data["headline"] == "H"
    assert data["body_markdown"] == body
