# SarcasticInstaBot (Discloud — background process)

Instagram group-chat bot. Pure background process: no FastAPI, no HTTP port.
Polls DMs and replies only on `@BOT_USERNAME` mention. Owner controls it via Instagram DM.

## Behavior

- Polls DMs every `POLL_INTERVAL_SEC` (10s). `TARGET_THREADS=ALL`.
- Public: `@bot ...` → Groq roast. `@bot !image <prompt>` → Pollinations flux image (if enabled).
- Owner-only DM commands (send from `OWNER_USERNAME` account, no mention needed):
  `!health`, `!stats`, `!pause`, `!resume`, `!imagegenon`, `!imagegenoff`
- No news module (`NEWS_ON=no`).
- Session at `./session.json` in working directory. Discloud persists files between
  restarts — loaded on startup, fresh login + dump if missing/corrupt.
- 2s min gap between replies. Cold-start poll marks existing messages seen.

## Project structure

```
main.py           # Entry point — asyncio.run(start_listener())
config.py         # Env loading
ig_handler.py     # instagrapi client, listener, mention detection, admin DMs
ai_handler.py     # Groq sarcastic persona
image_handler.py  # Pollinations image generation
requirements.txt  # No FastAPI / no uvicorn
discloud.config   # Discloud bot config
.env              # Real credentials (NEVER commit)
.discloudignore   # Upload exclusions
```

## Env vars (Discloud dashboard → your app → Config/Env)

```
INSTA_USERNAME=the_honered_
INSTA_PASSWORD=<your-password>
BOT_USERNAME=the_honered_
OWNER_USERNAME=kaustup.dhakal
OWNER_USER_ID=0
GROQ_API_KEY=<your-key>
NEWS_API_KEY=NONE
TARGET_THREADS=ALL
POLL_INTERVAL_SEC=10
IMAGE_ON=yes
NEWS_ON=no
```

`GROQ_MODEL` is optional (default `llama-3.3-70b-versatile`).
`SESSION_PATH` is optional (default `session.json` in CWD).
There is no `ADMIN_TOKEN` — admin now goes through Instagram DM.

## Run locally

```
pip install -r requirements.txt
cp .env.example .env   # then fill in real values
python main.py
```

## Deploy on Discloud (step by step)

### 0. Rotate exposed credentials
If you ever pasted your Instagram password or Groq key publicly, change the
Instagram password and regenerate the Groq key first.

### 1. Prepare the project folder
- Put these files in one folder: all `.py` files, `requirements.txt`,
  `discloud.config`, `.env` (with real credentials).
- Do NOT include `venv/`, `.git/`, `__pycache__/`.

### 2. Create the zip
- Zip the **contents** of the folder (not the folder itself).
- Must include at the zip root: `main.py`, `discloud.config`, `requirements.txt`, `.env`.
- Exclude per `.discloudignore`: `venv/`, `.git/`, `__pycache__/`, `*.pyc`, `session.json`.

Windows (PowerShell, run inside the folder):

```powershell
Compress-Archive -Path main.py, config.py, ig_handler.py, ai_handler.py, image_handler.py, requirements.txt, discloud.config, .env -DestinationPath bot.zip -Force
```

### 3. Upload via Discloud dashboard
1. Go to `https://discloud.app` and sign up / log in.
2. Click **New App** (or **Deploy**) → select **Bot**.
3. Upload your `.zip` file.
4. Wait for the build (`pip install -r requirements.txt` runs automatically).

### 4. Set environment variables
- If you bundled `.env` in the zip, the bot reads it via `python-dotenv`.
- Preferred: set vars in the dashboard (App → Config/Env) so secrets are not in the zip.
- Required: `INSTA_USERNAME`, `INSTA_PASSWORD`, `BOT_USERNAME`,
  `OWNER_USERNAME`, `GROQ_API_KEY`.

### 5. View logs
- Dashboard → your app → **Logs**.
- Expect: `[BOT] Starting Instagram bot...` → `[ig] logged in as ...`.
- Login failures retry every 30s without crashing.

### 6. Test
1. Add the burner account to your Instagram group chat.
2. Send a message mentioning `@the_honered_`.
3. Bot replies with a sarcastic message.
4. From `kaustup.dhakal`, DM the burner `!health` / `!stats` / `!pause` / `!resume`.

## Notes

- Free tier RAM is 100MB (`RAM=100` in `discloud.config`). If you see OOM crashes,
  history is already capped at 5 msgs/thread; reduce further if needed.
- No 2FA handling — burner must have none.
- Owner ID resolved at startup via `user_id_from_username`; username fallback
  also works if resolution fails.
- Koyeb leftovers removed: no `Procfile`, no `runtime.txt`, no `uvicorn`,
  no `/health` endpoint, no `X-Admin-Token` logic.
