import selection_triage as st


def _shortlist(*titles):
    items = []
    for i, title in enumerate(titles, start=1):
        items.append(
            {
                "_triage_id": i,
                "title": title,
                "link": f"https://example.test/{i}",
                "content": "body " * 100,
                "_theme_hits": 1 if i == 1 else 0,
                "_matched_keywords": ["ai"] if i == 1 else [],
                "_score_breakdown": {"total": 1.0 - (i * 0.1)},
            }
        )
    return items


def test_validate_triage_accepts_valid_winner():
    shortlist = _shortlist("A", "B")
    ok, why = st.validate_triage(
        {
            "winner_id": 2,
            "none_good_enough": False,
            "rankings": [
                {"id": 1, "reject": False, "rewrite_worthiness": 0.4},
                {"id": 2, "reject": False, "rewrite_worthiness": 0.9},
            ],
        },
        shortlist,
    )
    assert ok and why == "ok"


def test_validate_triage_rejects_hallucinated_winner():
    ok, why = st.validate_triage(
        {"winner_id": 99, "none_good_enough": False, "rankings": []},
        _shortlist("A"),
    )
    assert not ok
    assert "not in shortlist" in why


def test_validate_triage_rejects_winner_marked_reject():
    ok, why = st.validate_triage(
        {
            "winner_id": 1,
            "none_good_enough": False,
            "rankings": [{"id": 1, "reject": True, "rewrite_worthiness": 0.1}],
        },
        _shortlist("A", "B"),
    )
    assert not ok
    assert "marked reject" in why


def test_validate_none_good_enough():
    ok, why = st.validate_triage(
        {"winner_id": None, "none_good_enough": True, "rankings": []},
        _shortlist("A"),
    )
    assert ok and why == "none_good_enough"


def test_ordered_attempt_ids_skips_rejected():
    shortlist = _shortlist("A", "B", "C")
    triage = {
        "rankings": [
            {"id": 1, "reject": False, "rewrite_worthiness": 0.5},
            {"id": 2, "reject": True, "rewrite_worthiness": 0.9},
            {"id": 3, "reject": False, "rewrite_worthiness": 0.8},
        ]
    }
    ordered = st.ordered_attempt_ids(shortlist, triage, winner_id=1)
    assert ordered == [1, 3]
    assert 2 not in ordered


def test_triage_rejects_to_mark_threshold():
    triage = {
        "rankings": [
            {"id": 1, "reject": True, "rewrite_worthiness": 0.1},
            {"id": 2, "reject": True, "rewrite_worthiness": 0.5},
            {"id": 3, "reject": False, "rewrite_worthiness": 0.0},
        ]
    }
    assert st.triage_rejects_to_mark(triage) == [1]


def test_dry_run_triage_picks_theme_hit(monkeypatch):
    shortlist = _shortlist("off", "on")
    shortlist[0]["_theme_hits"] = 0
    shortlist[1]["_theme_hits"] = 2
    out = st.triage_shortlist(shortlist, {"key": "ai", "focus": ["ai"], "description": "AI"}, dry_run=True)
    assert out["winner_id"] == 2
    assert out["triage_fallback"] is None


def test_triage_invalid_winner_falls_back_to_deterministic(monkeypatch):
    shortlist = _shortlist("A", "B")

    def converse(*_a, **_k):
        return '{"winner_id": 99, "none_good_enough": false, "rankings": []}'

    monkeypatch.setattr(st.bedrock_client, "converse", converse)
    out = st.triage_shortlist(shortlist, {"key": "ai", "focus": ["ai"], "description": "AI"})
    assert out["winner_id"] == 1
    assert out["triage_fallback"] in {"deterministic", "invalid_winner"}


def test_triage_prompts_keep_technical_journals():
    sys_l = st.TRIAGE_SYSTEM_PROMPT.lower()
    user_l = st.TRIAGE_USER_TEMPLATE.lower()
    assert "first-person journals are fine" in sys_l
    assert "knowledge articles" in sys_l
    assert "first-person journal" in user_l
    assert "not a reject by itself" in user_l


def test_iter_triage_batches_slices_ranked_list():
    ranked = [{"title": f"t{i}", "link": f"https://ex/{i}"} for i in range(12)]
    batches = list(st.iter_triage_batches(ranked, batch_size=5, max_batches=3))
    assert [n for n, _ in batches] == [1, 2, 3]
    assert [item["title"] for item in batches[0][1]] == ["t0", "t1", "t2", "t3", "t4"]
    assert [item["title"] for item in batches[1][1]] == ["t5", "t6", "t7", "t8", "t9"]
    assert [item["title"] for item in batches[2][1]] == ["t10", "t11"]
    assert batches[0][1][0]["_triage_id"] == 1
    assert batches[1][1][0]["_triage_id"] == 1  # ids reset per batch


def test_iter_triage_batches_respects_max_batches():
    ranked = [{"title": f"t{i}"} for i in range(20)]
    batches = list(st.iter_triage_batches(ranked, batch_size=5, max_batches=2))
    assert len(batches) == 2
    assert len(batches[1][1]) == 5
