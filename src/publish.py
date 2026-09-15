"""Telegram publishing module for blog-agent (Step 4: queued -> published).

Sends post card and caption using Telegram Bot API sendPhoto with strict token isolation,
file permission checks (0600), and HTML entity sanitization.
"""

from datetime import datetime, timezone
import html
import os
from pathlib import Path
import re
import stat
from typing import Optional

import httpx

from src.image import generate_card
from src.logger import get_logger
import src.plan as plan

logger = get_logger("publish")

BASE_DIR: Path = Path(__file__).resolve().parent.parent
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
    2. Local .env file
    3. Dedicated token files (~/.config/blog-agent/bot_token, .tg_bot_token) with 0600 permissions
    """
    # 1. Check process environment (standard for Docker runtime --env-file .env)
    env_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if env_token and env_token.strip():
        logger.debug("Bot token loaded from environment variables")
        return env_token.strip()

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


def markdown_to_telegram_html(text: str) -> str:
    """Convert basic markdown in draft (code, bold, italic) to valid Telegram HTML.

    Properly escapes raw HTML entities &, <, > while preserving tags.
    """
    # 1. Protect code blocks and inline code
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    def save_code_block(m: re.Match[str]) -> str:
        code = m.group(1)
        escaped = html.escape(code)
        code_blocks.append(f"<pre><code>{escaped}</code></pre>")
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"

    def save_inline_code(m: re.Match[str]) -> str:
        code = m.group(1)
        escaped = html.escape(code)
        inline_codes.append(f"<code>{escaped}</code>")
        return f"__INLINE_CODE_{len(inline_codes)-1}__"

    processed = re.sub(r"```(?:\w+)?\n?(.*?)\n?```", save_code_block, text, flags=re.DOTALL)
    processed = re.sub(r"`([^`\n]+)`", save_inline_code, processed)

    # 2. Escape raw HTML entities in regular text
    processed = html.escape(processed)

    # 3. Convert bold (**text** or __text__)
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed)

    # 4. Convert italic (*text*)
    processed = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", processed)

    # 5. Restore code tokens
    for idx, snippet in enumerate(code_blocks):
        processed = processed.replace(f"__CODE_BLOCK_{idx}__", snippet)
    for idx, snippet in enumerate(inline_codes):
        processed = processed.replace(f"__INLINE_CODE_{idx}__", snippet)

    return processed.strip()


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

    # Image preparation
    image_path = BASE_DIR / "out" / "images" / f"{post.id}.png"
    if not image_path.exists():
        image_path = generate_card(post.id)

    # Prepare HTML caption
    caption_html = markdown_to_telegram_html(raw_draft)
    if len(caption_html) > 1024:
        raise ValueError(
            f"Telegram caption limit exceeded: {len(caption_html)} chars (max 1024 allowed for photo captions)."
        )

    # Channel configuration
    content_plan = plan.load()
    channel_id = str(content_plan.meta.get("channel", "@CHANGE_ME"))

    if dry_run:
        print(f"[DRY-RUN] Post: {post.id} ({post.title})")
        print(f"[DRY-RUN] Target Channel: {channel_id}")
        print(f"[DRY-RUN] Image: {image_path} ({image_path.stat().st_size} bytes)")
        print(f"[DRY-RUN] Caption Length: {len(caption_html)} chars")
        print("[DRY-RUN] Caption Preview:\n" + caption_html)
        return True

    # Real publication
    token = get_bot_token()
    api_url = f"https://api.telegram.org/bot{token}/sendPhoto"

    with open(image_path, "rb") as img_file:
        files = {"photo": (image_path.name, img_file, "image/png")}
        data = {
            "chat_id": channel_id,
            "caption": caption_html,
            "parse_mode": "HTML",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url, data=data, files=files)
            response.raise_for_status()
            res_json = response.json()

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
