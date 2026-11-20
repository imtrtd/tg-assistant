from datetime import UTC, datetime

from tg_assistant.research.dedupe import PostRef, filter_new_posts, post_key
from tg_assistant.research.store import (
    Watch,
    add_watch,
    is_seen,
    list_watches,
    mark_seen,
    remove_watch,
)
from tg_assistant.research.watch_service import apply_watch_hits


def test_filter_new_posts_skips_seen_and_inner_duplicates():
    already = {post_key(10, 1), post_key(11, 2)}
    posts = [
        PostRef(10, 1),
        PostRef(10, 3),
        PostRef(11, 2),
        PostRef(10, 3),  # duplicate in the same batch
        PostRef(12, 4),
    ]
    fresh = filter_new_posts(already, posts)
    assert fresh == [PostRef(10, 3), PostRef(12, 4)]
    # input set is not mutated
    assert already == {post_key(10, 1), post_key(11, 2)}


def test_filter_new_posts_empty():
    assert filter_new_posts(set(), []) == []
    assert filter_new_posts({(1, 1)}, [PostRef(1, 1)]) == []


def _watch(watch_id: int = 1) -> Watch:
    return Watch(
        id=watch_id,
        chat_id=100,
        user_id=200,
        term="brand",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _hit(peer: int, msg: int) -> dict:
    return {"peer_id": peer, "message_id": msg, "url": f"https://t.me/c/{peer}/{msg}"}


def test_apply_watch_hits_baseline_marks_without_alerts():
    hits = [_hit(1, 10), _hit(1, 11), _hit(1, 10)]
    alerts, keys = apply_watch_hits(_watch(), hits, set(), baseline=True)
    assert alerts == []
    assert keys == [(1, 10), (1, 11)]


def test_apply_watch_hits_alerts_only_unseen():
    hits = [_hit(1, 10), _hit(1, 11), _hit(2, 5)]
    already = {(1, 10)}
    alerts, keys = apply_watch_hits(_watch(), hits, already, baseline=False)
    assert [(h["peer_id"], h["message_id"]) for h in alerts] == [(1, 11), (2, 5)]
    assert keys == [(1, 11), (2, 5)]


async def test_database_mark_seen_and_watch_uniqueness(session):
    first, created = await add_watch(session, 1, 42, "Brand")
    assert created is True
    second, created_again = await add_watch(session, 1, 42, "brand")
    assert created_again is False
    assert second.id == first.id
    other, other_created = await add_watch(session, 2, 42, "Brand")
    assert other_created is True

    assert await mark_seen(session, first.id, 99, 1) is True
    assert await mark_seen(session, first.id, 99, 1) is False
    assert await is_seen(session, first.id, 99, 1) is True
    assert await is_seen(session, other.id, 99, 1) is False

    assert await remove_watch(session, 1, "BRAND") is True
    assert await list_watches(session, 1) == []
    # связанные seen-строки удаляются вместе с наблюдением
    assert await is_seen(session, first.id, 99, 1) is False
