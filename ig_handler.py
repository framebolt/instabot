"""Instagram client, message listener, mention detection.

Pure background process — no HTTP, no FastAPI. Admin commands are typed
directly in any group chat the bot is part of, owner-only.
"""
import asyncio
import logging
import os
import time
from collections import defaultdict, deque

import config
from ai_handler import generate_reply
from image_handler import generate_image

log = logging.getLogger("ig_handler")

# Admin state (module-level, in memory)
PAUSED: bool = False
IMAGE_GEN_ENABLED: bool = config.IMAGE_ENABLED_DEFAULT

# Aliases kept for backwards compat (get_status / setters / old imports)
paused = PAUSED
image_enabled = IMAGE_GEN_ENABLED

start_time: float = time.time()
last_poll_ts: float = 0.0
last_reply_ts: float = 0.0
last_activity_ts: float = 0.0
stats = {"seen": 0, "replies": 0, "images": 0, "errors": 0}

_cl = None
_bot_user_id = None
_owner_user_id = None

_seen_ids: set = set()
_history: dict = defaultdict(lambda: deque(maxlen=5))
_first_poll_done = False

MIN_REPLY_GAP = 2.0


def _get_client():
    global _cl
    if _cl is None:
        from instagrapi import Client

        _cl = Client()
    return _cl


def is_mentioned(text: str) -> bool:
    if not text:
        return False
    return f"@{config.BOT_USERNAME.lower()}" in text.lower()


def is_admin(user_id, sender_username: str = "") -> bool:
    """Owner-only gate. Checks numeric ID first, falls back to username."""
    # 1) Resolved owner ID from login
    if _owner_user_id is not None and user_id is not None:
        try:
            if str(user_id) == str(_owner_user_id):
                return True
        except Exception:
            pass
    # 2) OWNER_USER_ID env (if user filled it in)
    if config.OWNER_USER_ID and config.OWNER_USER_ID != "0" and user_id is not None:
        try:
            if str(user_id) == str(config.OWNER_USER_ID):
                return True
        except Exception:
            pass
    # 3) Username fallback (sender name from thread users)
    if sender_username and config.OWNER_USERNAME:
        if sender_username.strip().lower().lstrip("@") == config.OWNER_USERNAME.strip().lower().lstrip("@"):
            return True
    return False


def _msg_text(msg) -> str:
    return (getattr(msg, "text", None) or "").strip()


def _msg_id(msg, thread_id) -> str:
    mid = getattr(msg, "id", None)
    return f"{thread_id}:{mid}" if mid else f"{thread_id}:{getattr(msg, 'user_id', '?')}:{_msg_text(msg)[:40]}"


def _username_for(thread, user_id) -> str:
    try:
        for u in getattr(thread, "users", []) or []:
            if str(getattr(u, "pk", "")) == str(user_id):
                return getattr(u, "username", str(user_id)) or str(user_id)
    except Exception:
        pass
    return str(user_id)


def _admin_command(text: str) -> str | None:
    """Return admin command token if text starts with '!', else None.

    Handles optional leading @bot mention (e.g. '@bot !pause' still counts).
    """
    if not text:
        return None
    t = text.strip().lower()
    # strip a leading bot mention so '@bot !pause' works like '!pause'
    for prefix in (f"@{config.BOT_USERNAME.lower()} ", f"@{config.BOT_USERNAME.lower()}:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if not t.startswith("!"):
        return None
    token = t.split()[0]  # '!pause', '!imagegenon', ...
    if token in ("!health", "!status", "!pause", "!resume", "!stats", "!imagegenon", "!imagegenoff"):
        return token
    return None


def login_sync():
    """Blocking login. Session persisted to CWD session.json."""
    global _bot_user_id, _owner_user_id
    cl = _get_client()
    if os.path.exists(config.SESSION_PATH):
        try:
            cl.load_settings(config.SESSION_PATH)
            print(f"[ig] loaded session from {config.SESSION_PATH}", flush=True)
        except Exception as e:
            print(f"[ig] load_settings failed: {e}", flush=True)
    else:
        print(f"[ig] no session file at {config.SESSION_PATH}, fresh login", flush=True)
    cl.login(config.INSTA_USERNAME, config.INSTA_PASSWORD)
    try:
        cl.dump_settings(config.SESSION_PATH)
        print(f"[ig] session saved to {config.SESSION_PATH}", flush=True)
    except Exception as e:
        print(f"[ig] dump_settings failed: {e}", flush=True)
    try:
        _bot_user_id = int(cl.user_id)
    except Exception:
        _bot_user_id = None
    try:
        _owner_user_id = int(cl.user_id_from_username(config.OWNER_USERNAME))
        print(f"[ig] owner {config.OWNER_USERNAME} -> {_owner_user_id}", flush=True)
    except Exception as e:
        print(f"[ig] owner resolve failed: {e}", flush=True)
        _owner_user_id = None
    print(f"[ig] logged in as {config.INSTA_USERNAME} bot_id={_bot_user_id}", flush=True)
    return cl


def _poll_once_sync():
    """Blocking single poll. Returns list of (thread_id, msg, text, user_id, sender)."""
    global last_poll_ts
    cl = _get_client()
    out = []
    threads = cl.direct_threads(amount=10)
    last_poll_ts = time.time()
    for th in threads:
        tid = str(getattr(th, "id", ""))
        if not tid:
            continue
        try:
            msgs = cl.direct_messages(tid, amount=5)
        except Exception as e:
            print(f"[ig] direct_messages failed {tid}: {e}", flush=True)
            continue
        for m in reversed(msgs or []):  # oldest first
            mid = _msg_id(m, tid)
            if mid in _seen_ids:
                continue
            _seen_ids.add(mid)
            if len(_seen_ids) > 2000:
                _seen_ids.clear()
                _seen_ids.add(mid)
            stats["seen"] += 1
            text = _msg_text(m)
            if not text:
                continue
            uid = getattr(m, "user_id", None)
            sender = _username_for(th, uid)
            out.append((tid, m, text, str(uid), sender))
            try:
                _history[tid].append({"sender": sender, "text": text})
            except Exception:
                pass
    return out


async def _handle_item(thread_id, text, user_id, sender):
    """Group-chat message handler. Admin commands first, then @mentions."""
    global last_reply_ts, last_activity_ts, PAUSED, IMAGE_GEN_ENABLED, paused, image_enabled
    last_activity_ts = time.time()
    low = text.lower()

    # --- 1) admin commands in group chat: must start with '!' + owner-only ---
    cmd = _admin_command(text)
    if cmd is not None:
        if not is_admin(user_id, sender):
            return  # non-owner !command: ignore completely, no reply
        if cmd == "!pause":
            PAUSED = True
            paused = True
            await _send_text(thread_id, "paused. touch grass while im gone.")
            return
        if cmd == "!resume":
            PAUSED = False
            paused = False
            await _send_text(thread_id, "im back. unfortunately for you.")
            return
        if cmd == "!imagegenoff":
            IMAGE_GEN_ENABLED = False
            image_enabled = False
            await _send_text(thread_id, "image gen off. words only, try to keep up.")
            return
        if cmd == "!imagegenon":
            IMAGE_GEN_ENABLED = True
            image_enabled = True
            await _send_text(thread_id, "image gen on. prepare to be disappointed visually.")
            return
        if cmd == "!stats":
            await _send_text(thread_id, _stats_text())
            return
        if cmd in ("!health", "!status"):
            await _send_text(thread_id, _health_text())
            return

    # --- 2) paused: skip all @mention responses, admin already handled above ---
    if PAUSED:
        return

    # --- 3) public: only on mention, never self-reply ---
    if not is_mentioned(text):
        return
    if _bot_user_id is not None and str(user_id) == str(_bot_user_id):
        return

    # rate limit
    now = time.time()
    gap = now - last_reply_ts
    if gap < MIN_REPLY_GAP:
        await asyncio.sleep(MIN_REPLY_GAP - gap)

    # image path
    if "!image" in low:
        if not IMAGE_GEN_ENABLED:
            await _send_text(thread_id, "image gen is off, cry about it.")
            return
        prompt = _extract_image_prompt(text)
        if not prompt:
            await _send_text(thread_id, "give me a prompt after !image, genius.")
            return
        try:
            path = await generate_image(prompt)
            await _send_photo(thread_id, path)
            stats["images"] += 1
            last_reply_ts = time.time()
        except Exception as e:
            print(f"[ig] image fail: {e}", flush=True)
            stats["errors"] += 1
            await _send_text(thread_id, "image gen failed, just like your ideas.")
        return

    # ai reply (run blocking groq call in thread)
    clean = _strip_mention(text)
    hist = list(_history.get(thread_id, []))[:-1]  # exclude current
    try:
        reply = await asyncio.to_thread(generate_reply, clean, sender, hist)
    except Exception as e:
        print(f"[ig] ai fail: {e}", flush=True)
        stats["errors"] += 1
        reply = "lol brain lag, try again."
    await _send_text(thread_id, reply)
    stats["replies"] += 1
    last_reply_ts = time.time()


def _extract_image_prompt(text: str) -> str:
    low = text.lower()
    idx = low.find("!image")
    prompt = text[idx + len("!image"):].strip()
    # strip bot mention if present
    prompt = prompt.replace(f"@{config.BOT_USERNAME}", "").strip()
    return prompt


def _strip_mention(text: str) -> str:
    return text.replace(f"@{config.BOT_USERNAME}", "").replace(f"@{config.BOT_USERNAME.lower()}", "").strip() or text


async def _send_text(thread_id, text: str):
    cl = _get_client()
    try:
        await asyncio.to_thread(cl.direct_send, text, thread_ids=[thread_id])
    except Exception as e:
        print(f"[ig] send failed: {e}", flush=True)
        stats["errors"] += 1


async def _send_photo(thread_id, path: str):
    cl = _get_client()
    try:
        await asyncio.to_thread(cl.direct_send_photo, path, thread_ids=[thread_id])
    except Exception as e:
        print(f"[ig] send_photo failed: {e}", flush=True)
        stats["errors"] += 1
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _health_text() -> str:
    up = int(time.time() - start_time)
    poll_ago = int(time.time() - last_poll_ts) if last_poll_ts else -1
    return f"ok. up {up}s. paused={PAUSED} images={'on' if IMAGE_GEN_ENABLED else 'off'} last_poll={poll_ago}s ago."


def _stats_text() -> str:
    up = int(time.time() - start_time)
    act_ago = int(time.time() - last_activity_ts) if last_activity_ts else -1
    return (
        f"seen={stats['seen']} replies={stats['replies']} images={stats['images']} "
        f"errors={stats['errors']} up={up}s paused={PAUSED} last_activity={act_ago}s ago."
    )


def get_status() -> dict:
    return {
        "paused": PAUSED,
        "image_enabled": IMAGE_GEN_ENABLED,
        "uptime_sec": int(time.time() - start_time),
        "last_poll_sec_ago": int(time.time() - last_poll_ts) if last_poll_ts else -1,
        "last_activity_sec_ago": int(time.time() - last_activity_ts) if last_activity_ts else -1,
        "owner_resolved": _owner_user_id is not None,
        "bot_user_id": _bot_user_id,
        **stats,
    }


def set_paused(v: bool):
    global PAUSED, paused
    PAUSED = v
    paused = v


def set_image_enabled(v: bool):
    global IMAGE_GEN_ENABLED, image_enabled
    IMAGE_GEN_ENABLED = v
    image_enabled = v


async def poll_loop():
    global _first_poll_done
    # initial login with retries, never crash the process
    while True:
        try:
            if not config.INSTA_USERNAME or not config.INSTA_PASSWORD:
                print(f"[ig] missing INSTA creds, retry in 30s: {config.missing_required()}", flush=True)
                await asyncio.sleep(30)
                continue
            await asyncio.to_thread(login_sync)
            break
        except Exception as e:
            print(f"[ig] login failed: {e}", flush=True)
            stats["errors"] += 1
            await asyncio.sleep(30)

    while True:
        try:
            items = await asyncio.to_thread(_poll_once_sync)
            if not _first_poll_done:
                # cold start: mark existing as seen, reply nothing
                _first_poll_done = True
                print(f"[ig] cold start, marked {len(items)} existing msgs seen", flush=True)
            else:
                for thread_id, _m, text, uid, sender in items:
                    try:
                        await _handle_item(thread_id, text, uid, sender)
                    except Exception as e:
                        print(f"[ig] handle error: {e}", flush=True)
                        stats["errors"] += 1
        except Exception as e:
            print(f"[ig] poll error: {e}", flush=True)
            stats["errors"] += 1
            # session may be dead — try re-login
            try:
                await asyncio.to_thread(login_sync)
            except Exception as le:
                print(f"[ig] relogin failed: {le}", flush=True)
        await asyncio.sleep(max(5, config.POLL_INTERVAL_SEC))


async def start_listener():
    """Entry point for main.py — runs the poll loop forever."""
    print("[ig] listener starting...", flush=True)
    await poll_loop()
