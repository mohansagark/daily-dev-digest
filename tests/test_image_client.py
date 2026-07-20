import base64
import pytest
import requests
import image_client


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self._status = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        return self._payload


def _ok_payload(raw: bytes):
    return {"success": True, "result": {"image": base64.b64encode(raw).decode()}}


def test_generate_returns_decoded_bytes(monkeypatch):
    raw = b"\xff\xd8\xffFAKEJPEG"
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResp(200, _ok_payload(raw))

    monkeypatch.setattr(image_client.requests, "post", fake_post)
    assert image_client.generate("a robot reading") == raw
    assert "acct" in captured["url"]
    assert captured["json"]["steps"] == 4          # IMAGE_STEPS default
    assert captured["json"]["prompt"] == "a robot reading"


def test_generate_truncates_prompt_to_2048(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    seen = {}
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: seen.update(k["json"]) or _FakeResp(200, _ok_payload(b"x")))
    image_client.generate("z" * 5000)
    assert len(seen["prompt"]) == 2048


def test_generate_missing_env_raises(monkeypatch):
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        image_client.generate("x")


def test_generate_http_error_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post", lambda url, **k: _FakeResp(500, {}))
    with pytest.raises(requests.HTTPError):
        image_client.generate("x")


def test_generate_unsuccessful_payload_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: _FakeResp(200, {"success": False, "errors": ["nope"]}))
    with pytest.raises(RuntimeError):
        image_client.generate("x")


def test_generate_missing_image_field_raises(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    monkeypatch.setattr(image_client.requests, "post",
                        lambda url, **k: _FakeResp(200, {"success": True, "result": {}}))
    with pytest.raises(RuntimeError):
        image_client.generate("x")
