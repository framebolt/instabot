"""Entry point — pure background process. No FastAPI, no HTTP port."""
import asyncio

import config
from ig_handler import start_listener

if __name__ == "__main__":
    missing = config.missing_required()
    if missing:
        print(f"[BOT] WARNING missing env: {missing} — will retry login until set", flush=True)
    print("[BOT] Starting Instagram bot...", flush=True)
    print(
        f"[BOT] user={config.INSTA_USERNAME} bot_mention=@{config.BOT_USERNAME} "
        f"owner={config.OWNER_USERNAME} poll={config.POLL_INTERVAL_SEC}s "
        f"images={'on' if config.IMAGE_ENABLED_DEFAULT else 'off'}",
        flush=True,
    )
    print("[BOT] admin commands via group chat from owner only: "
          "!health !stats !pause !resume !imagegenon !imagegenoff", flush=True)
    asyncio.run(start_listener())
