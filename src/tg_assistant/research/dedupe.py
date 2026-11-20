from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PostRef:
    peer_id: int
    message_id: int


def post_key(peer_id: int, message_id: int) -> tuple[int, int]:
    return (int(peer_id), int(message_id))


def filter_new_posts(
    already_seen: set[tuple[int, int]],
    posts: Iterable[PostRef],
) -> list[PostRef]:
    """Return posts whose (peer_id, message_id) has not been seen, preserving order.

    The first occurrence of a duplicate inside *posts* is kept; later copies are dropped.
    """
    seen = set(already_seen)
    fresh: list[PostRef] = []
    for post in posts:
        key = post_key(post.peer_id, post.message_id)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(post)
    return fresh
