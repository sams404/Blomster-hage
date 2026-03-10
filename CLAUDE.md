# Blomster Hage — Claude Code Project

## Что это
Автоматизированная платформа заработка через ИИ-агентов. Норвегия. NOK.

## Структура файлов
```
index.html   — публичный сайт (главная, агенты, waitlist, AI-чат)
blog.html    — блог с кейсами (6 статей, фильтрация, newsletter)
admin.html   — панель управления (waitlist, рассылка, метрики)
intel.html   — Intelligence Hub (тренды, задачи фриланса, AI-питчи)
CLAUDE.md    — этот файл
```

## Стек
- Чистый HTML/CSS/JS — никаких фреймворков, никаких зависимостей
- Anthropic API (claude-sonnet-4-20250514) — чат и генерация питчей
- Google Fonts: Cormorant Garamond + DM Mono
- Все файлы self-contained, открываются напрямую в браузере

## Дизайн-система
```
--bg:     #080808  (главный фон)
--gold:   #c9a96e  (акцент, CTA)
--text:   #e6e2d8  (текст)
--muted:  rgba(230,226,216,0.38)
--border: rgba(255,255,255,0.055)
```
Intel Hub использует cyan (#4fc3f7) вместо gold.

## Агенты (6 штук)
| # | Emoji | Name | Codename | Status |
|---|-------|------|----------|--------|
| 01 | ✍️🌸 | Контент-мастер | Rosa Damascena | Active |
| 02 | 📊🌻 | Крипто-трейдер | Helianthus | Active |
| 03 | ⚙️🌿 | Автоматизатор | Fern Protocol | Active |
| 04 | 🤝🌺 | Аутрич-охотник | Poppy Sales | Beta |
| 05 | 🎬🌷 | Видео-резчик | Tulipa Reels | Beta |
| 06 | 🧠🔮 | ИИ-аналитик | Iris Intelligence | Soon |

## Тарифы (NOK/мес)
- 🌱 Росток: kr 149 — 1 агент
- 🌿 Сад: kr 349 — 3 агента (featured)
- 🌺 Полный сад: kr 699 — все 6

## Цель
kr 15 000/мес через 90 дней. Уже: kr 16 203 (47 в waitlist).

## Правила при редактировании
1. Никаких внешних зависимостей — всё inline
2. Сохранять DM Mono + Cormorant Garamond
3. Цвета только через CSS переменные
4. Все тексты поддерживают data-ru / data-no / data-en
5. API модель всегда: claude-sonnet-4-20250514
6. Mobile-first — проверять @media breakpoints (960px, 580px)

## Команды для разработки
```bash
# Открыть сайт локально
npx serve .

# Или через Python
python3 -m http.server 8080

# Линт HTML
npx html-validate index.html
```

## Следующие задачи
- [ ] Подключить реальный Stripe для waitlist
- [ ] Make.com webhook для новых подписчиков
- [ ] PWA manifest + service worker (offline)
- [ ] Реальный парсинг задач Upwork/Kwork API
- [ ] Деплой на Vercel / Netlify
