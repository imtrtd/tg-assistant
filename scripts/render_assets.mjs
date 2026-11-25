// Рисует картинки бота по дизайн-системе imtrtd: аватар, картинку описания, баннеры
// разделов и иконки мини-приложения. Тёмная тема, один акцент (violet), квадратные
// углы со срезом, волосяные линии, моно-лейблы, звёздное небо.
//
// Шрифты — из web/static/fonts (Arimo, Geist Mono, Space Grotesk, все OFL).
// PNG рендерит Chromium через Playwright; рядом пишется SVG-исходник (шрифты в нём
// по имени, без встраивания). Запуск из корня репозитория:
//   node scripts/render_assets.mjs

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// require, а не import: так Playwright находится и в глобальной установке (NODE_PATH).
const { chromium } = createRequire(import.meta.url)("playwright");

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ASSETS = join(ROOT, "src/tg_assistant/assets");
const STATIC = join(ROOT, "src/tg_assistant/web/static");
const FONTS = join(STATIC, "fonts");

// токены imtrtd
const INK = "#0a0a0f";
const INK_SOFT = "#14141c";
const INK_RAISE = "#1c1c27";
const PAPER = "#f3effa";
const FOG = "#c8cedb";
const MUTE = "#8b93a7";
const SIGNAL = "#b28dff";
const SIGNAL_DEEP = "#7b5cff";
const HAIR = "rgb(178 141 255 / 0.18)";
const HAIR_STRONG = "rgb(178 141 255 / 0.34)";
const OK = "#3dff9e";
const ERROR = "#ff2bd6";

const SANS = "Arial, Arimo, sans-serif";
const DISPLAY = "'Space Grotesk', Arimo, Arial, sans-serif";
const MONO = "'Geist Mono', ui-monospace, monospace";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// --- примитивы ---------------------------------------------------------------

function svg(w, h, body) {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<defs><linearGradient id="card" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="${INK_RAISE}"/><stop offset="1" stop-color="${INK_SOFT}"/>` +
    `</linearGradient>` +
    `<radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">` +
    `<stop offset="0" stop-color="${SIGNAL_DEEP}" stop-opacity="0.28"/>` +
    `<stop offset="1" stop-color="${SIGNAL_DEEP}" stop-opacity="0"/>` +
    `</radialGradient></defs>${body}</svg>`
  );
}

// детерминированное звёздное небо
function stars(w, h, count, seed = 7) {
  let x = seed;
  const rnd = () => ((x = (x * 1103515245 + 12345) % 2147483648) / 2147483648);
  let out = "";
  for (let i = 0; i < count; i++) {
    const cx = (rnd() * w).toFixed(1);
    const cy = (rnd() * h).toFixed(1);
    const r = (0.6 + rnd() * 1.1).toFixed(2);
    const violet = rnd() < 0.3;
    const op = (0.18 + rnd() * 0.5).toFixed(2);
    out += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${violet ? SIGNAL : PAPER}" opacity="${op}"/>`;
  }
  return out;
}

function ground(w, h, { glowX = 0.75, glowY = 0.35, glowR = 0.55, count } = {}) {
  const r = Math.max(w, h) * glowR;
  return (
    `<rect width="${w}" height="${h}" fill="${INK}"/>` +
    `<circle cx="${w * glowX}" cy="${h * glowY}" r="${r}" fill="url(#glow)"/>` +
    stars(w, h, count ?? Math.round((w * h) / 2600))
  );
}

// многоугольник со срезанными правым верхним и левым нижним углами (как знак I/TD)
function cutPath(x, y, w, h, c) {
  return `M${x} ${y}H${x + w - c}L${x + w} ${y + c}V${y + h}H${x + c}L${x} ${y + h - c}Z`;
}

function cutRect(x, y, w, h, c, attrs) {
  return `<path d="${cutPath(x, y, w, h, c)}" ${attrs}/>`;
}

function card(x, y, w, h, c = 18) {
  return cutRect(x, y, w, h, c, `fill="url(#card)" stroke="${HAIR}" stroke-width="2"`);
}

function text(x, y, s, { size, fill = PAPER, family = SANS, weight = 400, ls = 0, anchor = "start", extra = "" }) {
  return (
    `<text x="${x}" y="${y}" font-family="${family}" font-size="${size}" font-weight="${weight}" ` +
    `letter-spacing="${ls}" fill="${fill}" text-anchor="${anchor}" ${extra}>${esc(s)}</text>`
  );
}

const label = (x, y, s, size, fill = MUTE, anchor = "start") =>
  text(x, y, s.toUpperCase(), { size, fill, family: MONO, ls: size * 0.14, anchor });

const display = (x, y, s, size, fill = PAPER, anchor = "start") =>
  text(x, y, s, { size, fill, family: DISPLAY, weight: 600, ls: -size * 0.03, anchor });

// индекс раздела: короткая линия акцентом и моно-подпись
function index(x, y, s, size) {
  const line = size * 1.6;
  return (
    `<rect x="${x}" y="${y - size * 0.38}" width="${line}" height="2" fill="${SIGNAL}"/>` +
    label(x + line + size * 0.6, y, s, size, SIGNAL)
  );
}

function chip(x, y, s, size, { color = FOG, border = HAIR_STRONG } = {}) {
  const w = s.length * size * 0.74 + size * 1.6;
  const h = size * 2.3;
  return {
    w,
    svg:
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="${border}" stroke-width="1.5"/>` +
      label(x + size * 0.8, y + h / 2 + size * 0.36, s, size, color),
  };
}

function chips(x, y, items, size, gap) {
  let out = "";
  let cx = x;
  for (const item of items) {
    const c = chip(cx, y, item, size);
    out += c.svg;
    cx += c.w + gap;
  }
  return out;
}

// маленький квадрат-маркер списка, как на imtrtd.space
const bullet = (x, y, s, fill = SIGNAL) => `<rect x="${x}" y="${y}" width="${s}" height="${s}" fill="${fill}"/>`;

// знак бота: срезанный фиолетовый квадрат с буквами «TA» цветом ink
function mark(x, y, s) {
  return (
    cutRect(x, y, s, s, s * 0.16, `fill="${SIGNAL}"`) +
    text(x + s / 2, y + s * 0.66, "TA", {
      size: s * 0.46,
      fill: INK,
      family: DISPLAY,
      weight: 600,
      ls: -s * 0.02,
      anchor: "middle",
    })
  );
}

// волосяная рамка с засечками по углам
function frame(w, h, m) {
  const t = 22;
  const ticks = [
    [m, m, 1, 1],
    [w - m, m, -1, 1],
    [m, h - m, 1, -1],
    [w - m, h - m, -1, -1],
  ]
    .map(
      ([x, y, dx, dy]) =>
        `<path d="M${x} ${y + dy * t}V${y}H${x + dx * t}" fill="none" stroke="${SIGNAL}" stroke-width="2"/>`,
    )
    .join("");
  return `<rect x="${m}" y="${m}" width="${w - 2 * m}" height="${h - 2 * m}" fill="none" stroke="${HAIR}" stroke-width="1.5"/>${ticks}`;
}

// --- аватар, описание, иконка ------------------------------------------------

function avatar() {
  // Telegram обрезает аватар кругом: всё важное — в центре.
  const s = 640;
  return svg(s, s, ground(s, s, { glowX: 0.5, glowY: 0.5, glowR: 0.5, count: 120 }) + mark(170, 170, 300));
}

function description() {
  const w = 640;
  const h = 360;
  let b = ground(w, h, { glowX: 0.85, glowY: 0.2 });
  b += frame(w, h, 16);
  b += index(44, 66, "tg-assistant · бот", 14);
  b += display(44, 132, "Заметки,", 44);
  b += display(44, 180, "напоминания,", 44);
  b += display(44, 228, "архив чатов", 44, SIGNAL);
  b += text(44, 266, "Напишите или перешлите — бот сохранит.", { size: 17, fill: FOG });
  b += chips(44, 292, ["/note", "/remind", "/archive"], 13, 10);
  b += mark(486, 44, 110);
  return svg(w, h, b);
}

function icon() {
  // viewBox 64: фон ink (иконки на домашнем экране не бывают прозрачными), знак по центру
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
    `<rect width="64" height="64" fill="${INK}"/>` +
    mark(8, 8, 48).replace(/font-size="[^"]+"/, 'font-size="22"') +
    `</svg>`
  );
}

// --- баннеры разделов ---------------------------------------------------------

const BANNERS = {
  home: ["00", "Ассистент", "Заметки, напоминания и архив чатов", ["/notes", "/remind", "/archive"]],
  notes: ["01", "Заметки", "Поиск, теги и быстрое сохранение", ["/note", "/find", "/export"]],
  reminders: ["02", "Напоминания", "Один раз или с повтором", ["/remind", "/reminders"]],
  archive: ["03", "Архив чатов", "Правки и удаления в личных чатах", ["/archive", "/deleted"]],
  digest: ["04", "Сводка", "План на день каждое утро", ["/digest"]],
  settings: ["05", "Настройки", "Пояс, сводка и экспорт", ["/timezone", "/digest"]],
  app: ["06", "Приложение", "Заметки и напоминания в одном окне", ["/app", "/web"]],
  guide: ["07", "Инструкции", "Деплой, @BotFather, архив и стирание", ["/topics", "/wipe"]],
};

const CX = 744;
const CY = 96;
const CW = 448;
const CH = 448;

function row(y, left, right, { leftColor = MUTE, rightColor = PAPER, line = true } = {}) {
  return (
    label(CX + 40, y, left, 18, leftColor) +
    text(CX + CW - 40, y, right, { size: 24, fill: rightColor, family: SANS, anchor: "end" }) +
    (line ? `<rect x="${CX + 40}" y="${y + 26}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>` : "")
  );
}

function bars(x, y, widths, gap = 26, fill = FOG) {
  return widths
    .map((w, i) => `<rect x="${x}" y="${y + i * gap}" width="${w}" height="8" fill="${fill}" opacity="0.32"/>`)
    .join("");
}

const CARDS = {
  home() {
    let b = card(CX, CY, CW, CH);
    b += mark(CX + 40, CY + 40, 96);
    b += label(CX + 156, CY + 86, "tg-assistant", 18, SIGNAL);
    b += label(CX + 156, CY + 116, "online", 15, MUTE);
    b += `<circle cx="${CX + 245}" cy="${CY + 110}" r="6" fill="${OK}"/>`;
    const items = ["Заметки", "Напоминания", "Архив чатов", "Сводка дня"];
    items.forEach((it, i) => {
      const y = CY + 214 + i * 56;
      b += label(CX + 40, y, `0${i + 1}`, 17, SIGNAL);
      b += text(CX + 96, y + 1, it, { size: 27, fill: PAPER });
      b += `<rect x="${CX + 40}" y="${y + 22}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
    });
    return b;
  },
  notes() {
    let b = card(CX, CY, CW, CH);
    b += label(CX + 40, CY + 66, "# идеи", 20, SIGNAL);
    b += text(CX + 40, CY + 122, "Купить плёнку для", { size: 30, fill: PAPER });
    b += text(CX + 40, CY + 160, "съёмки в субботу", { size: 30, fill: PAPER });
    b += bars(CX + 40, CY + 200, [360, 300, 330, 210]);
    b += `<rect x="${CX + 40}" y="${CY + 318}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
    b += chips(CX + 40, CY + 352, ["#дом", "#работа", "#фото"], 15, 10);
    return b;
  },
  reminders() {
    let b = card(CX, CY, CW, CH);
    b += label(CX + 40, CY + 66, "завтра", 20, SIGNAL);
    b += display(CX + 34, CY + 196, "09:00", 132);
    b += text(CX + 40, CY + 252, "Позвонить маме", { size: 30, fill: PAPER });
    b += `<rect x="${CX + 40}" y="${CY + 296}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
    b += label(CX + 40, CY + 344, "↻ каждый день", 17, FOG);
    b += label(CX + 40, CY + 390, "+ через 10 минут", 17, MUTE);
    return b;
  },
  archive() {
    let b = card(CX, CY, CW, CH);
    // сообщение, удалённое собеседником
    b += `<rect x="${CX + 40}" y="${CY + 48}" width="300" height="118" fill="rgb(255 43 214 / 0.1)" stroke="rgb(255 43 214 / 0.5)" stroke-width="1.5"/>`;
    b += label(CX + 62, CY + 84, "Аня", 16, SIGNAL);
    b += text(CX + 62, CY + 124, "Забудь, что я писала", { size: 23, fill: PAPER });
    b += label(CX + 62, CY + 152, "■ удалено", 14, ERROR);
    // изменённое сообщение
    b += `<rect x="${CX + 108}" y="${CY + 196}" width="300" height="152" fill="rgb(178 141 255 / 0.12)" stroke="${HAIR_STRONG}" stroke-width="1.5"/>`;
    b += label(CX + 130, CY + 232, "Аня", 16, SIGNAL);
    b += text(CX + 130, CY + 272, "Встречаемся в 19:30", { size: 23, fill: PAPER });
    b += text(CX + 130, CY + 306, "было: в 18:00", { size: 19, fill: MUTE, extra: 'text-decoration="line-through"' });
    b += label(CX + 130, CY + 334, "✎ изменено", 14, SIGNAL);
    b += label(CX + 40, CY + 404, "личные чаты · business", 15, MUTE);
    return b;
  },
  digest() {
    let b = card(CX, CY, CW, CH);
    b += label(CX + 40, CY + 66, "утро · 07:30", 20, SIGNAL);
    b += display(CX + 40, CY + 150, "План на день", 50);
    const items = [
      ["10:00", "Созвон с клиентом"],
      ["13:30", "Забрать посылку"],
      ["19:00", "Спортзал"],
    ];
    items.forEach(([t, s], i) => {
      const y = CY + 226 + i * 62;
      b += bullet(CX + 40, y - 12, 10);
      b += label(CX + 66, y, t, 18, FOG);
      b += text(CX + 160, y + 1, s, { size: 25, fill: PAPER });
      b += `<rect x="${CX + 40}" y="${y + 24}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
    });
    return b;
  },
  settings() {
    let b = card(CX, CY, CW, CH);
    b += label(CX + 40, CY + 66, "профиль", 20, SIGNAL);
    b += row(CY + 150, "пояс", "Europe/Kyiv");
    b += row(CY + 230, "сводка", "08:00");
    b += row(CY + 310, "экспорт", ".md");
    // переключатель в стиле системы: квадратный, акцентом
    b += `<rect x="${CX + 40}" y="${CY + 360}" width="64" height="34" fill="none" stroke="${SIGNAL}" stroke-width="1.5"/>`;
    b += `<rect x="${CX + 74}" y="${CY + 366}" width="24" height="22" fill="${SIGNAL}"/>`;
    b += label(CX + 124, CY + 384, "присылать план", 16, FOG);
    return b;
  },
  app() {
    let b = card(CX, CY, CW, CH);
    b += label(CX + 40, CY + 66, "мини-приложение", 20, SIGNAL);
    const cells = [
      ["3", "сегодня"],
      ["09:00", "следующее"],
      ["24", "заметки"],
    ];
    const cw = (CW - 80 - 20) / 3;
    cells.forEach(([n, l], i) => {
      const x = CX + 40 + i * (cw + 10);
      b += `<rect x="${x}" y="${CY + 100}" width="${cw}" height="132" fill="${INK_SOFT}" stroke="${HAIR}" stroke-width="1.5"/>`;
      b += `<rect x="${x}" y="${CY + 100}" width="${cw}" height="3" fill="${SIGNAL}"/>`;
      b += display(x + 16, CY + 170, n, n.length > 2 ? 32 : 44);
      b += label(x + 16, CY + 210, l, 12, MUTE);
    });
    b += `<rect x="${CX + 40}" y="${CY + 268}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
    b += `<rect x="${CX + 40}" y="${CY + 320}" width="${CW - 80}" height="76" fill="${SIGNAL}"/>`;
    b += label(CX + CW / 2, CY + 366, "открыть  →", 20, INK, "middle");
    return b;
  },
};

CARDS.guide = function () {
  let b = card(CX, CY, CW, CH);
  b += label(CX + 40, CY + 66, "чек-лист", 20, SIGNAL);
  const items = [
    ["01", "Деплой и перезапуск"],
    ["02", "Картинки в @BotFather"],
    ["03", "Архив: Business"],
    ["04", "Пароль: /wipe set"],
    ["05", "Приложение и темы"],
  ];
  items.forEach(([n, s], i) => {
    const y = CY + 134 + i * 60;
    b += label(CX + 40, y, n, 17, SIGNAL);
    b += text(CX + 96, y + 1, s, { size: 26, fill: PAPER });
    b += `<rect x="${CX + 40}" y="${y + 24}" width="${CW - 80}" height="1.5" fill="${HAIR}"/>`;
  });
  return b;
};

function banner(name) {
  const [num, title, lead, cmds] = BANNERS[name];
  const w = 1280;
  const h = 640;
  let b = ground(w, h, { glowX: 0.78, glowY: 0.45, glowR: 0.5 });
  b += frame(w, h, 28);
  b += index(88, 150, `${num} · ${title}`, 20);
  const size = title.length > 9 ? 84 : 104;
  b += display(84, 296, title, size);
  b += text(88, 362, lead, { size: 30, fill: FOG });
  b += chips(88, 420, cmds, 18, 14);
  b += label(88, 566, "tg-assistant", 16, MUTE);
  b += CARDS[name]();
  return svg(w, h, b);
}

// --- рендер -------------------------------------------------------------------

// Шрифты встраиваются data-URL: страница из setContent не может читать file://.
const FACE = (family, file, weight, range) =>
  `@font-face{font-family:"${family}";` +
  `src:url("data:font/woff2;base64,${readFileSync(join(FONTS, file)).toString("base64")}") format("woff2");` +
  `font-weight:${weight};unicode-range:${range};}`;
const LAT = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2190-21FF,U+2212,U+25A0,U+270E,U+FEFF";
const CYR = "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116";
const STYLE =
  FACE("Arimo", "arimo-latin.woff2", "400 700", LAT) +
  FACE("Arimo", "arimo-cyrillic.woff2", "400 700", CYR) +
  FACE("Geist Mono", "geist-mono-latin.woff2", "400 700", LAT) +
  FACE("Geist Mono", "geist-mono-cyrillic.woff2", "400 700", CYR) +
  FACE("Space Grotesk", "space-grotesk-latin.woff2", "500 700", LAT) +
  "html,body{margin:0;background:#0a0a0f}svg{display:block}";

async function render(page, markup, w, h, out) {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>${STYLE}</style>${markup}`);
  // У текста в SVG шрифты грузятся лениво: подгружаем их явно до снимка.
  await page.evaluate(() =>
    Promise.all(
      ['600 40px "Space Grotesk"', '400 20px "Geist Mono"', '400 20px "Arimo"', '600 20px "Arimo"'].flatMap(
        (f) => [document.fonts.load(f, "AZ09"), document.fonts.load(f, "АЯая")],
      ),
    ),
  );
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: out, clip: { x: 0, y: 0, width: w, height: h } });
}

function save(path, markup) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, markup + "\n", "utf-8");
}

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

const jobs = [
  ["avatar", avatar(), 640, 640],
  ["description", description(), 640, 360],
  ...Object.keys(BANNERS).map((n) => [`banners/${n}`, banner(n), 1280, 640]),
];
for (const [name, markup, w, h] of jobs) {
  save(join(ASSETS, `${name}.svg`), markup);
  await render(page, markup, w, h, join(ASSETS, `${name}.png`));
}

const iconSvg = icon();
save(join(ASSETS, "icons/icon.svg"), iconSvg);
save(join(STATIC, "icon.svg"), iconSvg);
const sized = (s) => iconSvg.replace("<svg ", `<svg width="${s}" height="${s}" `);
for (const [s, out] of [
  [180, join(STATIC, "icon-180.png")],
  [192, join(STATIC, "icon-192.png")],
  [512, join(STATIC, "icon-512.png")],
  [192, join(ASSETS, "icons/icon-192.png")],
  [512, join(ASSETS, "icons/icon-512.png")],
]) {
  await render(page, sized(s), s, s, out);
}

await browser.close();
console.log("assets rendered");
