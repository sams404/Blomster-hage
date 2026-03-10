# 🌸 Blomster Hage — AI Agent Garden

> Автоматизированный заработок через ИИ-агентов. Норвегия. NOK.

## Страницы

| Файл | URL | Назначение |
|------|-----|-----------|
| `index.html` | `/` | Главная — агенты, waitlist, AI-чат |
| `blog.html` | `/blog` | Кейсы и статьи для трафика |
| `admin.html` | `/admin` | Управление waitlist и рассылкой |
| `intel.html` | `/intel` | Поиск трендов и фриланс-задач |

## Быстрый старт

```bash
# Клонировать
git clone <repo-url>
cd blomster-hage

# Запустить локально
npm run dev
# → http://localhost:3000

# Или через Python
npm run serve
# → http://localhost:8080
```

## Деплой на Vercel

```bash
npm i -g vercel
vercel --prod
```

## Деплой на Netlify

```bash
# Просто перетащи папку на netlify.com/drop
# или:
npx netlify-cli deploy --prod --dir .
```

## Стек

- **Frontend:** чистый HTML/CSS/JS (zero dependencies)
- **AI:** Anthropic API — `claude-sonnet-4-20250514`
- **Fonts:** Cormorant Garamond + DM Mono (Google Fonts)
- **Payments:** Stripe (настроить в `admin.html`)
- **Automation:** Make.com webhooks

## Текущий статус

- ✅ Сайт + агенты + waitlist
- ✅ Блог с 6 кейсами
- ✅ Admin панель (47 участников)
- ✅ Intelligence Hub (тренды + задачи + AI питчи)
- ⏳ Stripe интеграция
- ⏳ Make.com webhooks
- ⏳ PWA (manifest + service worker)

## Цель: kr 15 000/мес за 90 дней

```
47 waitlist × средний kr 344 = kr 16 203/мес (цель достигнута)
```

---

*Blomster Hage — © 2026 · Norge 🇳🇴*
