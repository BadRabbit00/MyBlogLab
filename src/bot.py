"""Interactive Telegram Bot for blog-agent.

Features:
- /generate: Generates next post from content-plan.yaml using RAG (docs/ + history).
- Review flow: Approve or reject drafts with inline buttons.
- Rejection feedback loop: Model regenerates incorporating user critique.
- Approval & Publishing: Bot accepts user-uploaded header photo (or auto card) and publishes to channel.
"""

import asyncio
from datetime import datetime, timezone
import html
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.generate import generate_post_content
from src.image import generate_card
import src.plan as plan
from src.publish import get_bot_token, markdown_to_telegram_html

BASE_DIR: Path = Path(__file__).resolve().parent.parent
OUT_DRAFTS_DIR: Path = BASE_DIR / "out" / "drafts"
OUT_IMAGES_DIR: Path = BASE_DIR / "out" / "images"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("blog-bot")

router = Router()


class PostReviewStates(StatesGroup):
    waiting_for_reject_comment = State()
    waiting_for_header_photo = State()


def make_review_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for post evaluation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{post_id}"),
            ],
            [
                InlineKeyboardButton(text="🎨 Показать обложку", callback_data=f"card:{post_id}"),
            ],
        ]
    )


def make_photo_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Build keyboard for approved post awaiting photo."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Опубликовать со сгенерированной карточкой",
                    callback_data=f"pubcard:{post_id}",
                ),
            ]
        ]
    )


STATUS_ICONS: dict[str, str] = {
    "pending": "⏳",
    "drafted": "📝",
    "queued": "📥",
    "published": "🚀",
    "killed": "💀",
}


def render_list_page(page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Render a 5-item paginated view of content-plan.yaml with navigation buttons."""
    content_plan = plan.load()
    posts = content_plan.posts
    total_posts = len(posts)
    page_size = 5
    total_pages = max(1, (total_posts + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_posts)
    current_posts = posts[start_idx:end_idx]

    lines = [
        f"📋 <b>Контент-план</b> (Стр. {page + 1} из {total_pages})",
        f"Всего постов: {total_posts}\n",
    ]

    for p in current_posts:
        icon = STATUS_ICONS.get(p.status, "❓")
        prefix_str = f" <code>[{p.doc_prefix}]</code>" if p.doc_prefix else ""
        lines.append(
            f"{icon} <b>#{p.id.upper()}</b> | {p.date} ({p.slot}) | <i>{p.rubric}</i>{prefix_str}\n"
            f"<b>{html.escape(p.title)}</b>\n"
            f"Тезис: {html.escape(p.thesis[:100])}{'...' if len(p.thesis) > 100 else ''}\n"
            f"Статус: <code>{p.status}</code>" + (" (⚠️ needs review)" if p.needs_review else "") + "\n"
        )

    # Navigation buttons: Prev / Page info / Next
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"list_page:{page - 1}"))
    else:
        nav_row.append(InlineKeyboardButton(text="⏹️", callback_data="noop"))

    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))

    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"list_page:{page + 1}"))
    else:
        nav_row.append(InlineKeyboardButton(text="⏹️", callback_data="noop"))

    # Action row: quick generate triggers for non-diary posts on this page
    action_row: list[InlineKeyboardButton] = []
    for p in current_posts:
        if p.rubric != "dnevnik":
            action_row.append(
                InlineKeyboardButton(
                    text=f"⚡ {p.id}",
                    callback_data=f"gen_req:{p.id}",
                )
            )

    keyboard_rows: list[list[InlineKeyboardButton]] = [nav_row]
    if action_row:
        keyboard_rows.append(action_row[:3])
        if len(action_row) > 3:
            keyboard_rows.append(action_row[3:])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    return "\n".join(lines), keyboard


@router.message(CommandStart())
async def cmd_start_handler(message: Message) -> None:
    """Handle /start command."""
    welcome_text = (
        "🤖 <b>Blog-Agent Bot активен.</b>\n\n"
        "Доступные команды:\n"
        "• /list — постраничный просмотр контент-плана по 5 постов с кнопками (⬅️/➡️)\n"
        "• /generate [ID] — сгенерировать следующий пост по плану (или конкретный ID, например <code>/generate w1-01</code>)\n"
        "• /status — текущее состояние плана и очередей\n"
        "• /review — список постов, ожидающих публикации\n"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


@router.message(Command("list"))
async def cmd_list_handler(message: Message) -> None:
    """Show paginated content plan."""
    text, markup = render_list_page(0)
    await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("list_page:"))
async def callback_list_page_handler(callback: CallbackQuery) -> None:
    """Handle pagination page change."""
    page_str = callback.data.split(":", 1)[1]
    page = int(page_str)
    text, markup = render_list_page(page)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def callback_noop_handler(callback: CallbackQuery) -> None:
    """No-op callback for informational buttons."""
    await callback.answer()


@router.callback_query(F.data.startswith("gen_req:"))
async def callback_gen_req_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle quick generation request from /list buttons."""
    target_id = callback.data.split(":", 1)[1]
    post = plan.get_post(target_id)
    if not post:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return

    await callback.answer(f"Генерирую {target_id}...")
    status_msg = await callback.message.answer(
        f"⏳ <b>Генерирую черновик</b>: [{post.id}] «{html.escape(post.title)}»...\n"
        f"<i>Считываю историю канала и статьи из ./docs/{post.doc_prefix or ''}*...</i>",
        parse_mode=ParseMode.HTML,
    )

    loop = asyncio.get_running_loop()
    draft_text, lint_res = await loop.run_in_executor(
        None, generate_post_content, post, None, None, 2
    )

    badge = "✅ Линтер пройден" if lint_res.passed else f"⚠️ Замечания ({'; '.join(lint_res.errors)})"

    response_text = (
        f"📝 <b>Черновик готов: #{post.id.upper()}</b>\n"
        f"<b>Тема:</b> {html.escape(post.title)}\n"
        f"<b>Рубрика:</b> {post.rubric} | <b>Символов:</b> {len(draft_text)}\n"
        f"<b>Статус:</b> {badge}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{html.escape(draft_text)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Одобрить или отправить на доработку с комментарием?"
    )

    await status_msg.delete()
    await callback.message.answer(
        response_text,
        reply_markup=make_review_keyboard(post.id),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("status"))
async def cmd_status_handler(message: Message) -> None:
    """Show plan statistics."""
    stats = plan.get_stats()
    content_plan = plan.load()
    channel = content_plan.meta.get("channel", "не указан")

    text = (
        f"📊 <b>Статус канала</b>: <code>{channel}</code>\n"
        f"Всего постов: {stats.get('total', 0)}\n"
        f"• Pending: {stats.get('pending', 0)}\n"
        f"• Drafted: {stats.get('drafted', 0)}\n"
        f"• Queued: {stats.get('queued', 0)} (требуют ревью: {stats.get('needs_review', 0)})\n"
        f"• Published: {stats.get('published', 0)}\n"
        f"• Killed: {stats.get('killed', 0)}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("review"))
async def cmd_review_handler(message: Message) -> None:
    """List queued posts."""
    queued_posts = plan.all_for("publish")
    if not queued_posts:
        await message.answer("В очереди публикации пока нет постов.")
        return

    for post in queued_posts[:5]:
        draft_file = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
        content = draft_file.read_text(encoding="utf-8") if draft_file.exists() else "файл не найден"
        review_flag = "⚠️ ТРЕБУЕТ ВНИМАНИЯ" if post.needs_review else "✅ ГОТОВ"
        msg = (
            f"<b>#{post.id.upper()}</b> | {post.rubric.upper()} | {review_flag}\n"
            f"<b>{html.escape(post.title)}</b>\n\n"
            f"{html.escape(content)}"
        )
        await message.answer(msg, reply_markup=make_review_keyboard(post.id), parse_mode=ParseMode.HTML)


@router.message(Command("generate"))
async def cmd_generate_handler(message: Message, state: FSMContext) -> None:
    """Generate draft for next or specified post."""
    args = message.text.split(maxsplit=1) if message.text else []
    target_id: Optional[str] = args[1].strip() if len(args) > 1 else None

    post = plan.get_post(target_id) if target_id else (plan.next_for("draft") or plan.next_for("critique"))
    if not post:
        await message.answer("❌ Нет доступных постов для генерации в контент-плане.")
        return

    status_msg = await message.answer(
        f"⏳ <b>Генерирую черновик</b>: [{post.id}] «{html.escape(post.title)}»...\n"
        f"<i>Считываю историю канала и статьи из ./docs/{post.doc_prefix or ''}*...</i>",
        parse_mode=ParseMode.HTML,
    )

    # Run LLM generation in worker thread to avoid blocking asyncio loop
    loop = asyncio.get_running_loop()
    draft_text, lint_res = await loop.run_in_executor(
        None, generate_post_content, post, None, None, 2
    )

    badge = "✅ Линтер пройден" if lint_res.passed else f"⚠️ Замечания ({'; '.join(lint_res.errors)})"

    response_text = (
        f"📝 <b>Черновик готов: #{post.id.upper()}</b>\n"
        f"<b>Тема:</b> {html.escape(post.title)}\n"
        f"<b>Рубрика:</b> {post.rubric} | <b>Символов:</b> {len(draft_text)}\n"
        f"<b>Статус:</b> {badge}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{html.escape(draft_text)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Одобрить или отправить на доработку с комментарием?"
    )

    await status_msg.delete()
    await message.answer(
        response_text,
        reply_markup=make_review_keyboard(post.id),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("card:"))
async def callback_card_handler(callback: CallbackQuery) -> None:
    """Render and send SVG social card preview."""
    post_id = callback.data.split(":", 1)[1]
    await callback.answer("Рендерю карточку...")

    loop = asyncio.get_running_loop()
    png_path = await loop.run_in_executor(None, generate_card, post_id)

    if png_path.exists():
        photo_file = FSInputFile(str(png_path))
        await callback.message.answer_photo(
            photo=photo_file,
            caption=f"🎨 Фирменная обложка для поста #{post_id.upper()}",
        )
    else:
        await callback.message.answer("❌ Ошибка при генерации карточки.")


@router.callback_query(F.data.startswith("reject:"))
async def callback_reject_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt user for rejection feedback."""
    post_id = callback.data.split(":", 1)[1]
    await state.set_state(PostReviewStates.waiting_for_reject_comment)
    await state.update_data(post_id=post_id)

    await callback.answer()
    await callback.message.answer(
        f"❌ <b>Пост #{post_id.upper()} отклонен.</b>\n\n"
        "Напиши в ответ, что именно не понравилось или что нужно изменить/добавить.\n"
        "Модель перегенерирует текст с учетом твоего комментария.",
        parse_mode=ParseMode.HTML,
    )


@router.message(PostReviewStates.waiting_for_reject_comment)
async def process_reject_comment(message: Message, state: FSMContext) -> None:
    """Process user rejection critique and trigger LLM regeneration."""
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await message.answer("❌ Ошибка контекста. Начни заново через /generate.")
        await state.clear()
        return

    post = plan.get_post(post_id)
    if not post:
        await message.answer(f"❌ Пост {post_id} не найден в плане.")
        await state.clear()
        return

    user_comment = message.text or ""
    draft_file = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
    prev_draft = draft_file.read_text(encoding="utf-8") if draft_file.exists() else ""

    status_msg = await message.answer(
        f"🔄 <b>Перегенерирую пост #{post.id.upper()}</b> с твоим комментарием:\n"
        f"<i>«{html.escape(user_comment)}»</i>...",
        parse_mode=ParseMode.HTML,
    )

    loop = asyncio.get_running_loop()
    new_text, lint_res = await loop.run_in_executor(
        None, generate_post_content, post, user_comment, prev_draft, 2
    )

    await state.clear()
    await status_msg.delete()

    badge = "✅ Линтер пройден" if lint_res.passed else f"⚠️ Замечания ({'; '.join(lint_res.errors)})"
    response_text = (
        f"📝 <b>Обновленный черновик: #{post.id.upper()}</b>\n"
        f"<b>Тема:</b> {html.escape(post.title)}\n"
        f"<b>Символов:</b> {len(new_text)} | <b>Статус:</b> {badge}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{html.escape(new_text)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Принять этот вариант?"
    )

    await message.answer(
        response_text,
        reply_markup=make_review_keyboard(post.id),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("approve:"))
async def callback_approve_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Accept draft and wait for post header image."""
    post_id = callback.data.split(":", 1)[1]
    plan.advance(post_id, status="queued")

    await state.set_state(PostReviewStates.waiting_for_header_photo)
    await state.update_data(post_id=post_id)

    await callback.answer()
    await callback.message.answer(
        f"✅ <b>Черновик #{post_id.upper()} одобрен!</b>\n\n"
        "📸 <b>Отправь фотографию</b> в этот чат, которая будет прикреплена к посту при публикации в канал.\n\n"
        "Либо нажми кнопку ниже, чтобы опубликовать с автоматически созданной векторной обложкой:",
        reply_markup=make_photo_keyboard(post_id),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("pubcard:"))
async def callback_publish_card_handler(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Publish to Telegram channel using the generated card."""
    post_id = callback.data.split(":", 1)[1]
    await state.clear()
    await callback.answer("Публикую в канал...")

    # Ensure card is generated
    png_path = generate_card(post_id)
    await _publish_to_channel(bot, callback.message, post_id, png_path)


@router.message(PostReviewStates.waiting_for_header_photo, F.photo)
async def process_header_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    """Download user-provided photo and publish post to channel."""
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await message.answer("❌ Ошибка контекста. Начни заново через /generate.")
        await state.clear()
        return

    await state.clear()
    status_msg = await message.answer("⏳ Сохраняю фотографию и отправляю пост в канал...")

    # Highest resolution photo is last item
    photo = message.photo[-1]
    OUT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    image_path = OUT_IMAGES_DIR / f"{post_id}_custom.jpg"

    await bot.download(photo.file_id, destination=image_path)
    await status_msg.delete()

    await _publish_to_channel(bot, message, post_id, image_path)


async def _publish_to_channel(
    bot: Bot, user_message: Message, post_id: str, image_path: Path
) -> None:
    """Internal helper to push photo and formatted caption to target channel."""
    post = plan.get_post(post_id)
    if not post:
        await user_message.answer(f"❌ Пост {post_id} не найден в плане.")
        return

    draft_file = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
    if not draft_file.exists():
        await user_message.answer(f"❌ Файл черновика {draft_file} отсутствует.")
        return

    raw_text = draft_file.read_text(encoding="utf-8").strip()
    caption_html = markdown_to_telegram_html(raw_text)

    if len(caption_html) > 1024:
        await user_message.answer(
            f"❌ Текст поста превышает лимит подписи Telegram: {len(caption_html)} знаков (максимум 1024)."
        )
        return

    content_plan = plan.load()
    channel = str(content_plan.meta.get("channel", "@CHANGE_ME"))

    try:
        photo_file = FSInputFile(str(image_path))
        published_msg = await bot.send_photo(
            chat_id=channel,
            photo=photo_file,
            caption=caption_html,
            parse_mode=ParseMode.HTML,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        plan.advance(
            post.id,
            status="published",
            tg_message_id=published_msg.message_id,
            published_at=now_iso,
        )

        await user_message.answer(
            f"🚀 <b>Пост #{post.id.upper()} успешно опубликован в канале {channel}!</b>\n"
            f"Message ID: <code>{published_msg.message_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error(f"Error publishing to channel: {exc}", exc_info=True)
        await user_message.answer(
            f"❌ Ошибка публикации в канал {channel}: <code>{html.escape(str(exc))}</code>\n"
            f"<i>Убедись, что бот добавлен в канал администратором с правом публикации.</i>",
            parse_mode=ParseMode.HTML,
        )


async def run_bot() -> None:
    """Initialize and run the Telegram bot polling."""
    token = get_bot_token()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Starting blog-agent Telegram bot polling...")
    await dp.start_polling(bot)


def main() -> None:
    """Bot entrypoint."""
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
