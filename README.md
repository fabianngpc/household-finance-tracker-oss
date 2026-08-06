# Household Finance Tracker

A self-hosted, LAN-only finance app for two people sharing a household. A
FastAPI backend serves a built SvelteKit single-page app, with multi-currency
expense tracking, per-user categories, a shared dashboard, monthly/yearly
reports, budgets with alerts, recurring expenses, and settle-up between
partners. An optional Telegram bot lets you capture expenses from your phone.

Everything runs on your own machine. There is no cloud, no third-party account,
and no data leaves your network.

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="Dashboard — shared spending, settle-up balance, budget progress, and spend-by-category breakdown" width="840">
</p>

> Screenshots use demo data with placeholder names (Maya & Daniel).

---

## Features

- **Shared ledger for two** — each person has their own login and categories;
  the dashboard can show your spending, your partner's, or both combined.
- **Multi-currency** — enter an expense in any currency; amounts are converted
  to a single base currency for reporting.
- **Budgets & alerts** — set monthly category budgets and get notified as you
  approach or exceed them.
- **Recurring expenses** — define rules (e.g. rent, subscriptions) that generate
  entries automatically.
- **Settle up** — track who owes whom on shared expenses.
- **Telegram capture (optional)** — text an expense from your phone and it lands
  in the ledger.
- **Local & private** — SQLite on disk, LAN-only web server, no external
  services required for the core app.

---

## Screenshots

| Expenses | Reports |
|:--:|:--:|
| ![Expense ledger with per-category colours and split badges](docs/screenshots/expenses.png) | ![Monthly and yearly reports with spend-by-category and category breakdown](docs/screenshots/reports.png) |
| Multi-currency ledger with split-expense badges | Monthly & yearly breakdowns per person or combined |
| **Budgets** | **Recurring** |
| ![Monthly total budget and per-category caps with progress bars](docs/screenshots/budgets.png) | ![Recurring rules that log expenses automatically on a schedule](docs/screenshots/recurring.png) |
| Total cap plus per-category watch limits | Rules that log rent, subscriptions, etc. automatically |

---

## Requirements

- **Python 3.14+** with [uv](https://github.com/astral-sh/uv)
  (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js 18+** with npm

---

## Quick start

Run these once, in order, from the project root.

```bash
# 1. Install backend dependencies
uv sync

# 2. Install and build the frontend (FastAPI serves the built output)
cd web && npm install && npm run build && cd ..

# 3. Create your session secret
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
# then open .env and remove the placeholder SECRET_KEY line if present

# 4. Create the database schema
uv run alembic upgrade head

# 5. Seed the two starter accounts and default categories
uv run python -m app.seed

# 6. Start the server (LAN-accessible)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000** in a browser.

---

## First-time login — getting both people onto the dashboard

Step 5 above (`app.seed`) creates **two accounts**, each with default
categories. Both use the temporary password `changeme`:

| Username  | Password   | Display name |
|-----------|------------|--------------|
| `alice`   | `changeme` | Alice        |
| `partner` | `changeme` | Bob          |

These names are placeholders — rename the display names to suit your household
(see "Renaming the accounts" below).

**You (first person):**

1. Open http://localhost:8000 on your computer.
2. Log in as `alice` / `changeme`.
3. Go to **Settings** and change your password immediately.

**Your partner (second person):**

Your partner does **not** create their own account — the second account already
exists from seeding. They just log into it:

1. On their phone or laptop, open the app. If they're on the same Wi‑Fi, use the
   host machine's LAN address instead of `localhost`, e.g.
   **http://192.168.1.50:8000** (find the host's IP with `ipconfig getifaddr en0`
   on macOS, or `hostname -I` on Linux).
2. Log in as `partner` / `changeme`.
3. Go to **Settings** and change the password.

Once both people have logged in, the dashboard's **Mine / Partner / Both**
toggle shows each person's spending or the combined household view.

> The app is **LAN-only** — do not expose port 8000 to the public internet. It
> has no TLS and no rate limiting. Keep it on your home network.

### Renaming the accounts

The starter accounts are seeded with placeholder names. To use your own:

- **Display names** (what shows in the app): change them in **Settings**, or edit
  the `users_to_seed` list in `app/seed.py` **before** running step 5.
- **Usernames**: edit `app/seed.py` before seeding. If you've already seeded,
  the simplest reset is to delete `data/finance.db` and re-run steps 4–5 (this
  erases all data).

---

## Telegram bot (optional)

The bot lets each person capture expenses by texting them from their phone. It
writes into the same ledger as the web app.

### 1. Configure environment variables

Add these to your `.env`:

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Create a bot with [@BotFather](https://t.me/BotFather) and copy the token |
| `TELEGRAM_ALLOWED_IDS` | Each person's numeric Telegram user ID, comma-separated. Send `/start` to [@userinfobot](https://t.me/userinfobot) to find yours. Example: `111111111,222222222` |

Only IDs in `TELEGRAM_ALLOWED_IDS` can use the bot; messages from anyone else
are silently ignored.

### 2. Run the three processes

The web server, the bot, and the queue worker must run as **separate
processes** (the bot's long-poller cannot share the web server's event loop).
Each opens the same WAL-mode SQLite file.

```bash
# Terminal 1 — web server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Telegram bot (long-polling)
uv run python -m bot.main

# Terminal 3 — queue worker (captures + budget/recurring notifications)
uv run python -m bot.worker
```

### 3. Each person links their account once

1. Log into the web app.
2. Go to **Settings → Generate link code**.
3. Send `/link <code>` to the bot within 15 minutes.

### Using the bot

- **Auto-log** — send `$12 lunch` and it's saved immediately.
- **Confirm flow** — send `lunch`; the bot asks for the amount, reply `8.50`.
- **Commands** — `/recent`, `/undo`, `/balance`, `/budget`, `/recurring`, `/help`.

---

## Backup & restore

Back up at any time against a live database (uses SQLite `VACUUM INTO`, safe for
WAL mode):

```bash
uv run python scripts/backup.py
```

This writes `backups/finance_<timestamp>.db` and verifies its integrity.
Schedule it via cron or launchd for regular automated backups.

**To restore:** stop the server, replace `data/finance.db` with a backup file,
then restart.

---

## Secret key

`SECRET_KEY` signs session cookies and lives in `.env`. Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Do **not** regenerate it after users have logged in — it invalidates every
existing session.

---

## Always-on deployment

For unattended 24/7 operation on a dedicated always-on machine (e.g. a Mac
mini), five processes run as macOS user LaunchAgents instead of manual
terminal sessions: the web server, the Telegram bot, the queue worker, an
optional local-inference sidecar, and a short-lived scheduler that generates
due recurring expenses and runs the daily backup.

The launchd `.plist` templates in `deploy/launchd/` use placeholders
(`__FILL_ME__` for secrets, `/Users/YOUR_USERNAME/...` for paths) — fill them in
before installing. See **[DEPLOY.md](./DEPLOY.md)** for the full
install / relocate / restore runbook and the boot, restart, no-sleep, and
restore verification checklist.

---

## Development

Run the backend test suite:

```bash
SECRET_KEY=test uv run pytest tests/ -q
```

Run the frontend type checker:

```bash
cd web && npx svelte-check
```

---

## Contributing

Contributions are welcome — bug fixes, features, and docs alike.

1. **Set up** — follow [Quick start](#quick-start) to get the app running
   locally.
2. **Branch** — create a feature branch off `main`.
3. **Make your change** — keep it focused, and match the style of the
   surrounding code.
4. **Verify before you push** — both must pass:

   ```bash
   SECRET_KEY=test uv run pytest tests/ -q   # backend tests
   cd web && npx svelte-check                # frontend types
   ```

5. **Open a pull request** — describe *what* changed and *why*. Screenshots
   help for any UI change.

A couple of things to keep in mind:

- **Local-first by design.** The app is self-hosted and LAN-only, with no
  cloud services or telemetry. Please keep new features working offline and
  don't add external calls to the core app without discussion (the optional
  Telegram bot and FX-rate lookup are the deliberate exceptions).
- **Not sure where to start?** Open an issue to discuss the idea first — it
  saves everyone time.

---

## License

Released under the [MIT License](./LICENSE).
