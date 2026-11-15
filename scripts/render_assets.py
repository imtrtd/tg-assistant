"""Рисует ассеты бота: SVG и PNG одного стиля, без чужих логотипов.

Шрифт в подписях — Inter (SIL Open Font License). В рантайме бот использует только PNG.
Запуск из корня репозитория: python scripts/render_assets.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "tg_assistant" / "assets"
STATIC = ROOT / "src" / "tg_assistant" / "web" / "static"
FONT = Path("/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf")
FONT_REG = Path("/usr/share/fonts/truetype/macos/Inter-Regular.ttf")

INDIGO = "#4F62F0"
INDIGO_DEEP = "#3949C4"
INK = "#141824"
PAPER = "#F5F6FB"
WHITE = "#FFFFFF"
AMBER = "#F0B429"
MUTED_DARK = "#A8B0C4"
MUTED_LIGHT = "#5E677C"
CARD_DARK = "#1E2433"
LINE_LIGHT = "#E3E7F1"


def _font_face() -> str:
    return (
        "<style>"
        f"@font-face{{font-family:'Inter';font-weight:600;"
        f"src:url('{FONT.as_uri()}') format('truetype');}}"
        f"@font-face{{font-family:'Inter';font-weight:400;"
        f"src:url('{FONT_REG.as_uri()}') format('truetype');}}"
        "</style>"
    )


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )


def _with_font(svg: str) -> str:
    """Подключает Inter только на время растеризации, в файл SVG путь к шрифту не пишем."""
    end = svg.find(">")
    return svg[: end + 1] + _font_face() + svg[end + 1 :]


def _note(x: float, y: float, s: float, *, paper: str, fold: str, lines: str, badge: str) -> str:
    """Карточка с загнутым углом и значком часов. Базовый размер 80."""
    k = s / 80
    return (
        f'<g transform="translate({x} {y}) scale({k})">{_note_raw(paper, fold, lines, badge)}</g>'
    )


def _note_raw(paper: str, fold: str, lines: str, badge: str) -> str:
    return f"""
    <rect x="8" y="6" width="48" height="62" rx="8" fill="{paper}"/>
    <path d="M40 6h16v16H46a6 6 0 0 1-6-6V6z" fill="{fold}"/>
    <path d="M20 32h26M20 42h26M20 52h16" stroke="{lines}" stroke-width="3.4"
          stroke-linecap="round" fill="none"/>
    <circle cx="60" cy="62" r="16" fill="{badge}"/>
    <path d="M60 54.5V63l5.5 3.2" stroke="{paper}" stroke-width="2.6"
          stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    """


def _bell(x: float, y: float, s: float, *, fill: str, accent: str) -> str:
    k = s / 80
    return f"""
    <g transform="translate({x} {y}) scale({k})" fill="none" stroke="{fill}"
       stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M16 48V32a24 24 0 0 1 48 0v16l6 8H10z" fill="{accent}"/>
      <path d="M32 60a8 8 0 0 0 16 0"/>
      <path d="M40 10v6"/>
    </g>
    """


def _tray(x: float, y: float, s: float, *, back: str, front: str, lines: str) -> str:
    """Две карточки стопкой — архив."""
    k = s / 80
    return f"""
    <g transform="translate({x} {y}) scale({k})">
      <rect x="16" y="14" width="52" height="40" rx="8" fill="{back}"/>
      <rect x="8" y="26" width="52" height="40" rx="8" fill="{front}"/>
      <path d="M20 44h28M20 54h16" stroke="{lines}" stroke-width="3.2" stroke-linecap="round"/>
    </g>
    """


def _sun(x: float, y: float, s: float, *, fill: str, accent: str) -> str:
    k = s / 80
    rays = []
    for x1, y1, x2, y2 in (
        (40, 8, 40, 16),
        (40, 64, 40, 72),
        (8, 40, 16, 40),
        (64, 40, 72, 40),
        (16, 16, 22, 22),
        (58, 58, 64, 64),
        (64, 16, 58, 22),
        (22, 58, 16, 64),
    ):
        rays.append(
            f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{accent}" '
            f'stroke-width="3.2" stroke-linecap="round"/>'
        )
    return f"""
    <g transform="translate({x} {y}) scale({k})" fill="none">
      {"".join(rays)}
      <circle cx="40" cy="40" r="14" fill="{fill}" stroke="{accent}" stroke-width="3"/>
    </g>
    """


def _sliders(x: float, y: float, s: float, *, fill: str, accent: str) -> str:
    k = s / 80
    return f"""
    <g transform="translate({x} {y}) scale({k})" fill="none" stroke-linecap="round">
      <path d="M14 28h52M14 52h52" stroke="{fill}" stroke-width="3.4"/>
      <circle cx="32" cy="28" r="7" fill="{accent}"/>
      <circle cx="50" cy="52" r="7" fill="{accent}"/>
    </g>
    """


def _phone(x: float, y: float, s: float, *, fill: str, accent: str, paper: str) -> str:
    k = s / 80
    return f"""
    <g transform="translate({x} {y}) scale({k})">
      <rect x="22" y="6" width="36" height="68" rx="8" fill="{fill}" stroke="{accent}"
            stroke-width="3"/>
      <rect x="30" y="18" width="20" height="28" rx="3" fill="{paper}"/>
      <circle cx="40" cy="62" r="3" fill="{accent}"/>
    </g>
    """


def _bg(width: int, height: int, dark: bool) -> str:
    if dark:
        return (
            f'<rect width="{width}" height="{height}" fill="{INK}"/>'
            f'<circle cx="{width * 0.86}" cy="{height * 0.18}" r="{height * 0.55}" '
            f'fill="{INDIGO}" opacity="0.16"/>'
            f'<circle cx="{width * 0.08}" cy="{height * 0.92}" r="{height * 0.38}" '
            f'fill="{INDIGO_DEEP}" opacity="0.22"/>'
        )
    return (
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>'
        f'<circle cx="{width * 0.9}" cy="{height * 0.1}" r="{height * 0.5}" '
        f'fill="{INDIGO}" opacity="0.08"/>'
        f'<circle cx="{width * 0.05}" cy="{height * 0.95}" r="{height * 0.32}" '
        f'fill="{INDIGO}" opacity="0.06"/>'
    )


def _text(x: float, y: float, content: str, size: float, fill: str, weight: int = 600) -> str:
    escaped = content.replace("&", "&amp;").replace("<", "&lt;")
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="Inter" font-weight="{weight}" '
        f'font-size="{size}">{escaped}</text>'
    )


def avatar_svg(*, dark: bool) -> str:
    if dark:
        bg = f"""
        <defs>
          <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#6E7DFF"/>
            <stop offset="1" stop-color="{INDIGO_DEEP}"/>
          </linearGradient>
        </defs>
        <rect width="640" height="640" fill="url(#g)"/>
        """
        paper, fold, lines, badge = WHITE, "#E4E8F5", AMBER, AMBER
    else:
        bg = f'<rect width="640" height="640" fill="{PAPER}"/>'
        bg += f'<rect x="70" y="70" width="500" height="500" rx="112" fill="{INDIGO}"/>'
        paper, fold, lines, badge = WHITE, "#D5DCF5", AMBER, AMBER
    glyph = _note(150, 150, 340, paper=paper, fold=fold, lines=lines, badge=badge)
    return _svg(640, 640, bg + glyph)


def description_svg(*, dark: bool) -> str:
    title = WHITE if dark else INK
    tile = CARD_DARK if dark else WHITE
    body = _bg(640, 360, dark)
    body += f'<rect x="44" y="72" width="200" height="216" rx="48" fill="{INDIGO}"/>'
    body += _note(58, 96, 168, paper=WHITE, fold="#E4E8F5", lines=AMBER, badge=AMBER)
    body += _text(276, 62, "Ассистент", 34, title)
    rows = (
        (108, "Заметки", "note"),
        (184, "Напоминания", "bell"),
        (260, "Архив чатов", "tray"),
    )
    for top, label, kind in rows:
        body += f'<rect x="276" y="{top}" width="324" height="68" rx="16" fill="{tile}"/>'
        if not dark:
            body += (
                f'<rect x="276" y="{top}" width="324" height="68" rx="16" fill="none" '
                f'stroke="{LINE_LIGHT}" stroke-width="2"/>'
            )
        icon_y = top + 8
        if kind == "note":
            body += _note(
                292, icon_y, 50, paper="#FFF8E8", fold="#F3E2B0", lines=AMBER, badge=AMBER
            )
        elif kind == "bell":
            body += _bell(286, icon_y - 4, 54, fill=title, accent="#2A3350" if dark else "#E7EBFF")
        else:
            body += _tray(
                286,
                icon_y - 2,
                54,
                back=INDIGO,
                front=WHITE if dark else "#EEF2FA",
                lines=INDIGO,
            )
        body += _text(358, top + 42, label, 22, title)
    return _svg(640, 360, body)


def _section_icon(name: str, x: float, y: float, dark: bool) -> str:
    ink = WHITE if dark else INK
    paper = WHITE if dark else "#EEF2FA"
    fold = "#E4E8F5" if dark else "#D5DCEB"
    if name == "home":
        return _note(x, y, 280, paper=paper, fold=fold, lines=AMBER, badge=AMBER)
    if name == "notes":
        return _note(x, y, 300, paper=paper, fold=fold, lines=INDIGO, badge=AMBER)
    if name == "reminders":
        return _bell(x, y, 300, fill=ink, accent="#2A3350" if dark else "#E4E8FF")
    if name == "archive":
        return _tray(
            x,
            y,
            300,
            back=INDIGO,
            front=WHITE if dark else "#F7F8FC",
            lines=INDIGO,
        )
    if name == "digest":
        return _sun(x, y, 300, fill=AMBER, accent=AMBER)
    if name == "settings":
        return _sliders(x, y, 300, fill=ink, accent=INDIGO)
    if name == "app":
        return _phone(x, y, 300, fill=WHITE if not dark else "#222A40", accent=INDIGO, paper=PAPER)
    raise KeyError(name)


BANNERS = {
    "home": ("Ассистент", "Заметки, напоминания и архив чатов"),
    "notes": ("Заметки", "Поиск, теги и быстрое сохранение"),
    "reminders": ("Напоминания", "Один раз или с повтором"),
    "archive": ("Архив чатов", "Правки и удаления в личных чатах"),
    "digest": ("Сводка", "План на день каждое утро"),
    "settings": ("Настройки", "Пояс, сводка и экспорт"),
    "app": ("Приложение", "Заметки и напоминания в одном окне"),
}


def banner_svg(name: str, *, dark: bool) -> str:
    title, subtitle = BANNERS[name]
    title_fill = WHITE if dark else INK
    sub_fill = MUTED_DARK if dark else MUTED_LIGHT
    tile = "#222A40" if dark else WHITE
    body = _bg(1280, 640, dark)
    body += f'<rect x="760" y="90" width="420" height="460" rx="56" fill="{tile}"/>'
    if not dark:
        body += (
            f'<rect x="760" y="90" width="420" height="460" rx="56" fill="none" '
            f'stroke="{LINE_LIGHT}" stroke-width="2"/>'
        )
    body += _text(88, 250, title, 72, title_fill)
    body += _text(88, 318, subtitle, 28, sub_fill, 400)
    body += _section_icon(name, 830, 160, dark)
    return _svg(1280, 640, body)


def icon_svg() -> str:
    """Квадратная иконка мини-приложения, viewBox 64."""
    body = f"""
    <rect width="64" height="64" rx="16" fill="{INDIGO}"/>
    {_note(6, 6, 52, paper=WHITE, fold="#E4E8F5", lines=AMBER, badge=AMBER)}
    """
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{body}</svg>'


def _write(path: Path, svg: str, png_size: tuple[int, int] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".svg").write_text(svg, encoding="utf-8")
    if png_size is None:
        return
    png = path.with_suffix(".png")
    cairosvg.svg2png(
        bytestring=_with_font(svg).encode(),
        write_to=str(png),
        output_width=png_size[0],
        output_height=png_size[1],
    )


def main() -> None:
    if not FONT.is_file() or not FONT_REG.is_file():
        raise SystemExit(f"Inter not found at {FONT}")

    _write(ASSETS / "avatar", avatar_svg(dark=True), (640, 640))
    _write(ASSETS / "avatar-light", avatar_svg(dark=False), (640, 640))
    _write(ASSETS / "description", description_svg(dark=True), (640, 360))
    _write(ASSETS / "description-light", description_svg(dark=False), (640, 360))
    for name in BANNERS:
        _write(ASSETS / "banners" / name, banner_svg(name, dark=True), (1280, 640))
        _write(ASSETS / "banners" / f"{name}-light", banner_svg(name, dark=False), (1280, 640))

    icon = icon_svg()
    (ASSETS / "icons").mkdir(parents=True, exist_ok=True)
    (ASSETS / "icons" / "icon.svg").write_text(icon, encoding="utf-8")
    STATIC.mkdir(parents=True, exist_ok=True)
    (STATIC / "icon.svg").write_text(icon, encoding="utf-8")
    for size, dest in (
        (180, STATIC / "icon-180.png"),
        (192, STATIC / "icon-192.png"),
        (512, STATIC / "icon-512.png"),
        (192, ASSETS / "icons" / "icon-192.png"),
        (512, ASSETS / "icons" / "icon-512.png"),
    ):
        cairosvg.svg2png(
            bytestring=icon.encode(),
            write_to=str(dest),
            output_width=size,
            output_height=size,
        )
    shutil.copyfile(ASSETS / "icons" / "icon.svg", STATIC / "icon.svg")
    print(f"wrote assets to {ASSETS}")


if __name__ == "__main__":
    main()
