"""Telegram publishing module for blog-agent (Step 4: queued -> published).

Sends a post card and validated plain-text caption using Telegram Bot API sendPhoto
with token isolation and file permission checks (0600).
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from typing import Optional

import httpx

from src.image import generate_card
from src.logger import get_logger, redact_secrets
from src.paths import DATA_DIR
from src.validation import require_plain_text
import src.plan as plan

logger = get_logger("publish")

BASE_DIR: Path = DATA_DIR
ENV_FILE: Path = BASE_DIR / ".env"
TOKEN_PATHS: list[Path] = [
    Path.home() / ".config" / "blog-agent" / "bot_token",
    BASE_DIR / ".tg_bot_token",
]


def _read_token_from_env_file(env_path: Path) -> Optional[str]:
    """Parse .env file for TELEGRAM_BOT_TOKEN or BOT_TOKEN without third-party deps."""
    if not env_path.exists():
        return None
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN") and val:
                        return val
    except Exception as e:
        logger.warning(f"Failed to read .env file at {env_path}: {e}")
    return None


def get_bot_token() -> str:
    """Read Telegram bot token with priority:
    1. Environment variables TELEGRAM_BOT_TOKEN / BOT_TOKEN
    2. TELEGRAM_BOT_TOKEN_FILE (e.g. a read-only Docker secret)
    3. Local .env file and legacy dedicated token files
    """
    # 1. Check process environment (standard for Docker runtime --env-file .env)
    env_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if env_token and env_token.strip():
        logger.debug("Bot token loaded from environment variables")
        return env_token.strip()

    secret_file = os.getenv("TELEGRAM_BOT_TOKEN_FILE")
    if secret_file:
        token = Path(secret_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN_FILE is empty")
        return token

    # 2. Check local .env file
    file_env_token = _read_token_from_env_file(ENV_FILE)
    if file_env_token:
        logger.debug(f"Bot token loaded from {ENV_FILE}")
        return file_env_token

    # 3. Check isolated files with permission checks
    token_file: Optional[Path] = None
    for candidate in TOKEN_PATHS:
        if candidate.exists():
            token_file = candidate
            break

    if not token_file:
        paths_str = ", ".join(str(p) for p in TOKEN_PATHS)
        raise FileNotFoundError(
            f"Telegram bot token not found. Set TELEGRAM_BOT_TOKEN env var, add to .env, or create 0600 file at: {paths_str}"
        )

    file_stat = token_file.stat()
    file_mode = stat.S_IMODE(file_stat.st_mode)
    if file_mode not in (0o600, 0o400):
        os.chmod(token_file, 0o600)

    with open(token_file, "r", encoding="utf-8") as f:
        token = f.read().strip()

    if not token:
        raise ValueError(f"Telegram bot token file at {token_file} is empty.")

    logger.debug(f"Bot token loaded from file {token_file}")
    return token


def run_publish(post_id: Optional[str] = None, dry_run: bool = False) -> bool:
    """Publish queued post to Telegram channel.

    Transitions post: queued -> published.
    """
    post = plan.get_post(post_id) if post_id else plan.next_for("publish")
    if not post:
        return False

    draft_path = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft file for {post.id} not found at {draft_path}")

    with open(draft_path, "r", encoding="utf-8") as f:
        raw_draft = f.read().strip()
    require_plain_text(raw_draft)

    # Image preparation
    image_path = BASE_DIR / "out" / "images" / f"{post.id}.png"
    if not image_path.exists():
        image_path = generate_card(post.id)

    # Send the validated body literally, with no markup parser enabled.
    if len(raw_draft) > 1024:
        raise ValueError(
            f"Telegram caption limit exceeded: {len(raw_draft)} chars (max 1024 allowed for photo captions)."
        )

    # Channel configuration
    content_plan = plan.load()
    channel_id = str(content_plan.meta.get("channel", "@CHANGE_ME"))

    if dry_run:
        print(f"[DRY-RUN] Post: {post.id} ({post.title})")
        print(f"[DRY-RUN] Target Channel: {channel_id}")
        print(f"[DRY-RUN] Image: {image_path} ({image_path.stat().st_size} bytes)")
        print(f"[DRY-RUN] Caption Length: {len(raw_draft)} chars")
        print("[DRY-RUN] Caption Preview:\n" + raw_draft)
        return True

    # Real publication
    token = get_bot_token()
    api_url = f"https://api.telegram.org/bot{token}/sendPhoto"

    with open(image_path, "rb") as img_file:
        files = {"photo": (image_path.name, img_file, "image/png")}
        data = {
            "chat_id": channel_id,
            "caption": raw_draft,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(api_url, data=data, files=files)
                response.raise_for_status()
                res_json = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(redact_secrets(str(exc))) from None

    if not res_json.get("ok"):
        raise RuntimeError(f"Telegram API returned error: {res_json}")

    message_id = int(res_json["result"]["message_id"])
    now_iso = datetime.now(timezone.utc).isoformat()

    plan.advance(
        post.id,
        status="published",
        tg_message_id=message_id,
        published_at=now_iso,
    )
    return True
