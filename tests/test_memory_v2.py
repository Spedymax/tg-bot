"""Memory v2 policy, ranking and helpers (offline)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services import memory_v2 as mv

NOW = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)
MAX, YURA, BOGDAN = 741542965, 742272644, 855951767
BATCH = {
    101: {"user_id": BOGDAN, "name": "Богдан", "is_bot": False},
    102: {"user_id": YURA, "name": "Юра", "is_bot": False},
    103: {"user_id": MAX, "name": "Макс", "is_bot": False},
    104: {"user_id": 0, "name": "Jarvis", "is_bot": True},
}


def cand(**kw):
    base = dict(kind="profile_fact", text="Богдан подрабатывает репетитором", subject="Богдан",
                source_message_ids=[101], claim_type="self")
    base.update(kw)
    return mv.Candidate(**base)


def test_self_claim_is_stored_with_high_confidence_and_no_ttl():
    d = mv.decide(cand(), BATCH, {}, NOW)
    assert d.action == "insert" and d.subject_user_id == BOGDAN and d.subject_name == "Богдан"
    assert d.confidence == 0.85 and d.expires_at is None


def test_hearsay_becomes_attributed_claim_not_fact():
    d = mv.decide(cand(text="Богдан спит до обеда", source_message_ids=[102]), BATCH, {}, NOW)
    assert d.action == "insert"
    assert d.candidate.kind == "attributed_claim" and d.candidate.claim_type == "third_party"
    assert d.candidate.text.startswith("Юра говорит, что")
    assert d.confidence == 0.45 and d.expires_at == NOW + timedelta(days=60)


def test_bot_sources_sensitive_unknown_and_unsourced_are_rejected():
    assert mv.decide(cand(source_message_ids=[104]), BATCH, {}, NOW).reason == "bot-authored source"
    assert mv.decide(cand(sensitive=True), BATCH, {}, NOW).action == "reject"
    assert mv.decide(cand(kind="gossip"), BATCH, {}, NOW).action == "reject"
    assert mv.decide(cand(source_message_ids=[999]), BATCH, {}, NOW).reason == "no source message in batch"


def test_two_independent_authors_raise_confidence():
    d = mv.decide(cand(kind="episode", subject=None, claim_type="group", text="В субботу 26.09 играют в доту",
                       source_message_ids=[101, 102]), BATCH, {}, NOW)
    assert d.confidence == 0.8 and d.expires_at == NOW + timedelta(days=21)


def test_repeat_is_confirmed_and_contradiction_supersedes():
    existing = {7: {"kind": "profile_fact", "subject_user_id": BOGDAN, "text": "Богдан подрабатывает репетитором по математике"}}
    assert mv.decide(cand(), BATCH, existing, NOW).action == "confirm"
    d = mv.decide(cand(text="Богдан бросил репетиторство", supersedes=7), BATCH, existing, NOW)
    assert d.action == "supersede" and d.target_id == 7


def test_parse_candidates_drops_malformed():
    raw = {"memories": [
        {"kind": "episode", "text": "ok", "source_message_ids": [1]},
        {"kind": "episode", "text": "", "source_message_ids": [1]},
        {"kind": "episode", "text": "no sources", "source_message_ids": []},
        {"kind": "episode", "text": "bad ids", "source_message_ids": ["x"]},
        "junk",
    ]}
    assert [c.text for c in mv.parse_candidates(raw)] == ["ok"]


def test_aliases_and_mentions():
    assert mv.resolve_subject("Spatifilum") == (YURA, "Юра")
    assert mv.resolve_subject("@lofiSnitch") == (BOGDAN, "Богдан")
    assert mv.resolve_subject("Шева") == (None, "Шева")
    assert mv.mentioned_user_ids("джарвис, а что Бодя вчера говорил про Макса?") == {BOGDAN, MAX}


def _item(id, subject, fts, **kw):
    base = dict(id=id, subject_user_id=subject, fts=fts, confidence=0.85, kind="profile_fact",
                text=f"запись {id}", last_seen_at=NOW - timedelta(days=30), last_used_at=None)
    base.update(kw)
    return base


def test_rank_needs_topic_or_explicit_mention_not_just_author():
    items = [_item(1, BOGDAN, 0.0), _item(2, BOGDAN, 0.1), _item(3, YURA, 0.0)]
    # Богдан asks something unrelated: his own untopical memory is NOT pulled in
    assert [r["id"] for r in mv.rank(items, BOGDAN, set(), NOW)] == [2]
    # someone explicitly asks about Юра
    assert 3 in [r["id"] for r in mv.rank(items, MAX, {YURA}, NOW)]


def test_rank_penalises_recent_use_and_out_of_scene_hearsay():
    fresh = _item(1, BOGDAN, 0.08, last_used_at=NOW - timedelta(hours=1))
    hearsay = _item(2, YURA, 0.08, kind="attributed_claim")
    assert mv.rank([fresh, hearsay], MAX, set(), NOW) == []


def test_rank_respects_limit_and_budget():
    items = [_item(i, None, 0.2, text="x" * 500) for i in range(10)]
    out = mv.rank(items, None, set(), NOW)
    assert len(out) <= mv.RETRIEVE_LIMIT and sum(len(i["text"]) for i in out) <= mv.RETRIEVE_CHAR_BUDGET


def test_format_block_and_mark_used():
    items = [{"id": 5, "kind": "attributed_claim", "confidence": 0.45, "text": "Юра говорит, что Богдан спит до обеда"},
             {"id": 6, "kind": "episode", "confidence": 0.8, "text": "В субботу играют в доту на миде"}]
    block = mv.format_block(items)
    assert "недоверенные данные" in block and "(со слов, уверенность 0.5)" in block
    assert mv.format_block([]) == ""
    assert mv.mark_used_ids(items, "Юра, опять про то, что Богдан спит до обеда?") == [5]


def test_subject_among_authors_is_self_even_if_extractor_says_third_party():
    d = mv.decide(cand(subject="Юра", text="Юра работает на складе, куда привозят книги",
                       claim_type="third_party", source_message_ids=[101, 102]), BATCH, {}, NOW)
    assert d.candidate.claim_type == "self" and d.candidate.kind == "profile_fact"
    assert not d.candidate.text.startswith("Богдан говорит")


def test_name_declensions_are_mentions_not_topic_words():
    assert mv.mentioned_user_ids("что там у Юры на работе, и где Бодю носит? спроси Максом") == {YURA, BOGDAN, MAX}
    assert mv.mentioned_user_ids("юрист сказал, что максимум можно") == set()
    assert "юры" not in mv.topic_words("что там у Юры на работе")
