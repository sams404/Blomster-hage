# 🌸 Blomster Hage — AI Agent Garden

> Автоматизированный заработок через ИИ-агентов. Норвегия. NOK.

## Страницы

| Файл | URL | Назначение |
|------|-----|-----------|
| `index.html` | `/` | Главная — агенты, waitlist, AI-чат |
| `blog.html` | `/blog` | Кейсы и статьи для трафика |
| `admin.html` | `/admin` | Управление waitlist и рассылкой |
| `intel.html` | `/intel` | Поиск трендов и фриланс-задач |
| `garden.html` | `/garden` | Приложение: агенты-фигурки, финансы, лента |

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

## 💰🌼 Финансовый агент — Crocus Aurum

Торгует **одновременно на Binance и Revolut X** (`FIN_BROKERS=binance,revolut`).
Каждый час, для каждой биржи: портфель → риск-проверки → EMA/RSI по свечам этой биржи →
ордер → уведомление в Telegram. В 21:00 — общий отчёт в NOK: по биржам, P&L,
спред Revolut X vs Binance, оценка налога 22% → email + Telegram.

```bash
cp .env.example .env          # задай ADMIN_KEY, TELEGRAM_*, FIN_*
pip install -r requirements.txt
python run.py test crocus     # один цикл + отчёт (paper)
python run.py all             # API + все агенты по расписанию
```

| Режим | Binance | Revolut X |
|-------|---------|-----------|
| `paper` | виртуальные 1000 USDT | виртуальные 1000 USD |
| `testnet` | фейковые деньги, реальные ордера | — (нет testnet) |
| `live` | ключ без Withdraw + `FIN_LIVE_CONFIRM` | Ed25519-ключ + `FIN_LIVE_CONFIRM` |

Режим можно задать на биржу отдельно: `FIN_MODE_BINANCE=live`, `FIN_MODE_REVOLUT=paper`.
Revolut: API есть только у крипто-биржи Revolut X; акции в обычном приложении API не имеют.

Защита (на каждой бирже): лимит на ордер, лимит позиции, стоп-лосс, автостоп при
дневном убытке, лимит сделок в день. В приложении: «⏸ Пауза» для одной биржи и «🛑 Стоп всё».

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
