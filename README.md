# Telegram Campaign Bot

## Requirements
- Python 3.10 or higher
- pip

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables

**Option A — .env file (recommended)**

Copy `.env.example` to `.env` and fill in your values:
```bash
cp .env.example .env
```

Then edit `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
PYROGRAM_API_ID=your_api_id_here
PYROGRAM_API_HASH=your_api_hash_here
```

The bot loads `.env` automatically on startup.

**Option B — export directly in terminal**
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export PYROGRAM_API_ID="your_api_id_here"
export PYROGRAM_API_HASH="your_api_hash_here"
```

---

### 3. Run the bot
```bash
python bot.py
```

---

## Where to get credentials

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) → `/newbot` |
| `PYROGRAM_API_ID` | [https://my.telegram.org/apps](https://my.telegram.org/apps) |
| `PYROGRAM_API_HASH` | Same page as API ID |

---

## Running 24/7

**Linux (systemd)**
```bash
# /etc/systemd/system/tgbot.service
[Unit]
Description=Telegram Campaign Bot
After=network.target

[Service]
WorkingDirectory=/path/to/bot
EnvironmentFile=/path/to/bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable tgbot && sudo systemctl start tgbot
```

**Screen (simple)**
```bash
screen -S tgbot python bot.py
# Detach: Ctrl+A then D
# Reattach: screen -r tgbot
```

**Docker**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "bot.py"]
```
```bash
docker build -t tgbot .
docker run -d --env-file .env --name tgbot tgbot
```

---

## Primary-owner login ZIP export

The primary owner can export the login sessions belonging to a selected bot
user:

1. Open **Owner Panel → Users List**.
2. Open the target user.
3. Tap **Export Login ZIP**, review the warning, and confirm.
4. Keep the ZIP private. It contains login credentials for that user's
   Telegram accounts.

The ZIP includes one combined `sessions/session_ids.txt` file containing all
Pyrogram session strings, one per line, an `accounts.csv` manifest, and
instructions for importing it through **Add Account → Bulk Import**. The
session-string order matches the `Account Number` column in `accounts.csv`.
The ZIP also includes individual `.txt` copies for tools that require one
Pyrogram string per uploaded file. These are text strings, not SQLite
`.session` databases, so they must not be renamed to `.session`.
Co-owners do not receive this export action.

The primary owner can also use **Logout Other Devices** from a selected user.
This uses Telegram's authorization reset for the selected accounts: it logs
those accounts out from the user's phone and other Telegram devices while
keeping RAVI's current bot session connected.
