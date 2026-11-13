from tg_assistant.db import User
from tg_assistant.db import notes as repo

OWNER, OTHER = 1, 2


async def _users(session):
    session.add_all(
        [
            User(id=OWNER, first_name="A", timezone="UTC"),
            User(id=OTHER, first_name="B", timezone="UTC"),
        ]
    )
    await session.commit()


async def test_list_is_newest_first_and_paginated(session):
    await _users(session)
    for i in range(7):
        await repo.add_note(session, OWNER, f"note {i}")
    await repo.add_note(session, OTHER, "чужая")

    first, total = await repo.list_notes(session, OWNER, offset=0, limit=5)
    second, _ = await repo.list_notes(session, OWNER, offset=5, limit=5)

    assert total == 7
    assert [n.text for n in first] == [f"note {i}" for i in (6, 5, 4, 3, 2)]
    assert [n.text for n in second] == ["note 1", "note 0"]


async def test_search_is_case_insensitive_for_cyrillic_and_needs_all_words(session):
    await _users(session)
    await repo.add_note(session, OWNER, "Купить МОЛОКО и хлеб #дом")
    await repo.add_note(session, OWNER, "Молоко для работы #работа")
    await repo.add_note(session, OTHER, "молоко чужое")

    assert len(await repo.search_notes(session, OWNER, "молоко", limit=20)) == 2
    assert [n.text for n in await repo.search_notes(session, OWNER, "молоко #ДОМ", limit=20)] == [
        "Купить МОЛОКО и хлеб #дом"
    ]


async def test_search_treats_wildcards_literally(session):
    await _users(session)
    await repo.add_note(session, OWNER, "скидка 50%")
    await repo.add_note(session, OWNER, "скидка 500")

    assert [n.text for n in await repo.search_notes(session, OWNER, "50%", limit=20)] == [
        "скидка 50%"
    ]


async def test_cannot_touch_other_users_notes(session):
    await _users(session)
    note = await repo.add_note(session, OTHER, "секрет")

    assert await repo.get_note(session, OWNER, note.id) is None
    assert not await repo.update_note(session, OWNER, note.id, "взлом")
    assert not await repo.delete_note(session, OWNER, note.id)
    assert (await repo.get_note(session, OTHER, note.id)).text == "секрет"


async def test_update_and_delete(session):
    await _users(session)
    note = await repo.add_note(session, OWNER, "старое")

    assert await repo.update_note(session, OWNER, note.id, "Новое")
    assert [n.id for n in await repo.search_notes(session, OWNER, "новое", limit=5)] == [note.id]
    assert await repo.delete_note(session, OWNER, note.id)
    assert not await repo.delete_note(session, OWNER, note.id)
