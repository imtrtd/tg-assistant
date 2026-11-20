from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .stats import ChannelStats


def load_timezone(name: str) -> ZoneInfo:
    for candidate in (name, "Europe/Kyiv", "Europe/Kiev", "UTC"):
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return ZoneInfo("UTC")


def format_datetime(value: datetime | None, tz: ZoneInfo) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    local = value.astimezone(tz)
    return local.strftime("%Y-%m-%d %H:%M") + f" ({tz.key})"


def h(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_search_results(
    query: str,
    hits: list[dict],
    tz: ZoneInfo,
    *,
    date_note: str | None = None,
) -> str:
    header = f"Поиск: <b>{h(query)}</b>"
    if date_note:
        header += f"\nФильтр дат: {h(date_note)}"
    if not hits:
        return header + "\n\nНичего не найдено в публичных каналах."
    lines = [header, f"Найдено: {len(hits)}", ""]
    for i, hit in enumerate(hits, 1):
        title = hit.get("title") or hit.get("username") or "канал"
        username = hit.get("username")
        handle = f"@{username}" if username else title
        date = format_datetime(hit.get("date"), tz)
        url = hit.get("url")
        snippet = hit.get("snippet") or "—"
        link = f'<a href="{h(url)}">{h(handle)}</a>' if url else h(handle)
        lines.append(f"{i}. {link} · {h(date)}")
        lines.append(h(snippet))
        lines.append("")
    return "\n".join(lines).strip()


def format_find_results(topic: str, chats: list[dict]) -> str:
    header = f"Каналы и чаты по теме: <b>{h(topic)}</b>"
    if not chats:
        return header + "\n\nНичего не найдено среди публичных каналов и групп."
    lines = [header, f"Найдено: {len(chats)}", ""]
    for i, chat in enumerate(chats, 1):
        username = chat.get("username")
        title = chat.get("title") or username or "без названия"
        kind = chat.get("kind") or "канал"
        url = f"https://t.me/{username}" if username else None
        title_html = f'<a href="{h(url)}">{h(title)}</a>' if url else h(title)
        handle = f" @{username}" if username else ""
        members = chat.get("participants")
        extra = f" · {members} подписчиков" if members else ""
        lines.append(f"{i}. {title_html}{h(handle)} ({h(kind)}{extra})")
        about = chat.get("about")
        if about:
            lines.append(h(about if len(about) <= 200 else about[:199] + "…"))
    return "\n".join(lines).strip()


def format_channel_summary(info: dict, stats: ChannelStats, tz: ZoneInfo) -> str:
    username = info.get("username")
    title = info.get("title") or username or "канал"
    handle = f"@{username}" if username else title
    url = f"https://t.me/{username}" if username else None
    title_html = f'<a href="{h(url)}">{h(title)}</a>' if url else h(title)

    lines = [
        f"{title_html} ({h(handle)})",
        f"Тип: {h(info.get('kind') or 'канал')}",
    ]
    if info.get("participants") is not None:
        lines.append(f"Подписчики / участники: {info['participants']}")
    if info.get("created_at"):
        lines.append(f"Дата создания (публичное поле): {format_datetime(info['created_at'], tz)}")
    about = info.get("about") or "—"
    lines.append(f"Описание:\n{h(about)}")
    lines.append("")
    lines.append(f"Статистика по последним {stats.posts_analyzed} постам:")
    if stats.posts_analyzed == 0:
        lines.append("Недостаточно публикаций для оценки частоты.")
        return "\n".join(lines)

    if stats.span_days:
        lines.append(
            f"Частота: {stats.posts_per_day} постов/день "
            f"(окно {stats.span_days:.1f} дн., с {format_datetime(stats.first_post_date, tz)} "
            f"по {format_datetime(stats.last_post_date, tz)})"
        )
        lines.append(f"За последние 7 дней: {stats.posts_last_7d} постов")
    if stats.average_views is not None:
        lines.append(f"Средние просмотры: {stats.average_views} (по {stats.views_sample} постам)")
    else:
        lines.append("Просмотры недоступны (типично для групп, не каналов).")

    lines.append("")
    lines.append("Топ источников пересылок:")
    if stats.top_forward_sources:
        for name, count in stats.top_forward_sources:
            lines.append(f"· {h(name)} — {count}")
    else:
        lines.append("· пересылок не найдено")

    lines.append("")
    lines.append("Связанные и упомянутые каналы (форварды и ссылки t.me в постах):")
    linked = info.get("linked_username")
    if linked:
        lines.append(f"· официально связанный чат: @{h(linked)}")
    if stats.mentioned_channels:
        for name, count in stats.mentioned_channels:
            lines.append(f"· {h(name)} — {count}")
    elif not linked:
        lines.append("· упоминаний не найдено")
    return "\n".join(lines)


def format_watch_alert(term: str, hit: dict, tz: ZoneInfo) -> str:
    username = hit.get("username")
    handle = f"@{username}" if username else (hit.get("title") or "канал")
    url = hit.get("url")
    link = f'<a href="{h(url)}">{h(handle)}</a>' if url else h(handle)
    return (
        f"🔔 Новое упоминание: <b>{h(term)}</b>\n"
        f"Канал: {link}\n"
        f"Дата: {h(format_datetime(hit.get('date'), tz))}\n\n"
        f"{h(hit.get('snippet') or '—')}"
    )


def date_range_note(start: datetime | None, end: datetime | None, tz: ZoneInfo) -> str | None:
    if start is None and end is None:
        return None
    return f"{format_datetime(start, tz)} — {format_datetime(end, tz)}"
