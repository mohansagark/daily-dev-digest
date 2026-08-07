import search_client as sc


def test_format_notes_empty():
    assert sc.format_notes([]) == ""


def test_format_notes_includes_url_and_snippet():
    text = sc.format_notes([
        {"title": "CSS shapes", "url": "https://ex.com/a", "snippet": "border-shape lands"}
    ])
    assert "https://ex.com/a" in text
    assert "border-shape" in text


def test_search_requires_env(monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    import pytest
    with pytest.raises(RuntimeError):
        sc.search("css border-shape")
