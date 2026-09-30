import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import Forbidden, BadRequest
from storage import get_broadcasts, add_broadcast, delete_broadcast, get_all_user_ids
from keyboards import broadcast_history_menu, broadcast_item_menu, back_button

logger = logging.getLogger(__name__)

BCAST_MESSAGE, BCAST_CUSTOM_TARGETS = range(2)

# ── helpers ───────────────────────────────────────────────────────────────────

def _confirm_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Send to All Users", callback_data="bcast_confirm", style="success")],
        [InlineKeyboardButton("❌ Cancel",            callback_data="main_menu",     style="danger")],
    ])

def _msg_type_label(msg) -> str:
    if msg.sticker:       return "🎭 Sticker"
    if msg.photo:         return "🖼 Photo"
    if msg.video:         return "🎬 Video"
    if msg.animation:     return "🎞 GIF"
    if msg.audio:         return "🎵 Audio"
    if msg.voice:         return "🎤 Voice"
    if msg.video_note:    return "📹 Video Note"
    if msg.document:      return "📎 Document"
    if msg.text:          return "✉️ Text"
    return "📨 Message"


# ── conversation steps ────────────────────────────────────────────────────────

async def broadcast_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from storage import is_owner
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    user_ids = get_all_user_ids()
    await query.edit_message_text(
        "📢 *BROADCAST*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 *Bot users:* {len(user_ids)}\n\n"
        "Send the message you want to broadcast.\n"
        "Any format is supported — text, emoji, stickers, photos, videos, etc.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger")
        ]]),
        parse_mode="Markdown",
    )
    return BCAST_MESSAGE


async def bcast_compose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept any message type and ask for confirmation."""
    msg = update.message
    user_ids = get_all_user_ids()
    kind = _msg_type_label(msg)

    # Store the content needed to re-send (file_ids survive restarts; text is plain)
    content: dict = {"caption": msg.caption or ""}
    if msg.sticker:
        content["sticker"] = msg.sticker.file_id
    elif msg.photo:
        content["photo"] = msg.photo[-1].file_id
    elif msg.video:
        content["video"] = msg.video.file_id
    elif msg.animation:
        content["animation"] = msg.animation.file_id
    elif msg.audio:
        content["audio"] = msg.audio.file_id
    elif msg.voice:
        content["voice"] = msg.voice.file_id
    elif msg.video_note:
        content["video_note"] = msg.video_note.file_id
    elif msg.document:
        content["document"] = msg.document.file_id
    elif msg.text:
        content["text"] = msg.text
    else:
        content["text"] = msg.text or ""

    context.user_data["bcast_content"] = content
    context.user_data["bcast_kind"]    = kind

    await msg.reply_text(
        "📢 *BROADCAST PREVIEW*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 *Type:* {kind}\n"
        f"👥 *Recipients:* {len(user_ids)} bot users\n\n"
        "The message above is exactly what will be sent.\n"
        "Ready to send?",
        reply_markup=_confirm_kb(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def _send_content(bot, chat_id: int, content: dict) -> None:
    """Send a single message to one chat_id using the stored content dict."""
    caption = content.get("caption") or None
    if "sticker" in content:
        await bot.send_sticker(chat_id=chat_id, sticker=content["sticker"])
    elif "photo" in content:
        await bot.send_photo(chat_id=chat_id, photo=content["photo"], caption=caption)
    elif "video" in content:
        await bot.send_video(chat_id=chat_id, video=content["video"], caption=caption)
    elif "animation" in content:
        await bot.send_animation(chat_id=chat_id, animation=content["animation"], caption=caption)
    elif "audio" in content:
        await bot.send_audio(chat_id=chat_id, audio=content["audio"], caption=caption)
    elif "voice" in content:
        await bot.send_voice(chat_id=chat_id, voice=content["voice"], caption=caption)
    elif "video_note" in content:
        await bot.send_video_note(chat_id=chat_id, video_note=content["video_note"])
    elif "document" in content:
        await bot.send_document(chat_id=chat_id, document=content["document"], caption=caption)
    else:
        text = content.get("text") or caption or ""
        await bot.send_message(chat_id=chat_id, text=text)


async def bcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    content = context.user_data.get("bcast_content")

    if not content:
        await query.edit_message_text(
            "⚠️ No message found. Please start again.",
            reply_markup=back_button("main_menu"),
        )
        return

    user_ids = get_all_user_ids()
    total    = len(user_ids)

    # Progress message
    prog = await query.edit_message_text(
        f"📤 Sending broadcast…\n\n"
        f"0 / {total} sent",
    )

    sent = failed = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            await _send_content(context.bot, int(uid), content)
            sent += 1
        except (Forbidden, BadRequest) as e:
            logger.warning("Broadcast to %s failed (Forbidden/BadRequest): %s", uid, e)
            failed += 1
        except Exception as e:
            logger.warning("Broadcast to %s failed (%s): %s", uid, type(e).__name__, e)
            failed += 1

        # Update progress every 10 users or on the last one
        if i % 10 == 0 or i == total:
            try:
                await prog.edit_text(
                    f"📤 Sending broadcast…\n\n"
                    f"{i} / {total} sent",
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)   # ~20 msg/s — stay well within Telegram limits

    # Log to broadcast history
    add_broadcast(update.effective_user.id, {
        "date":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target_label": f"All Bot Users ({total})",
        "targets":      user_ids,
        "sent_to":      sent,
        "failed":       failed,
        "status":       "sent",
    })

    for key in ["bcast_content", "bcast_kind"]:
        context.user_data.pop(key, None)

    await prog.edit_text(
        "✅ *BROADCAST COMPLETE!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ *Delivered:* {sent}\n"
        f"❌ *Failed:* {failed}  _(blocked / deleted)_\n"
        f"👥 *Total:* {total}\n"
        f"📅 *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        reply_markup=back_button("main_menu"),
        parse_mode="Markdown",
    )


# ── history handlers (unchanged) ──────────────────────────────────────────────

async def broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    broadcasts = get_broadcasts(user_id)

    if not broadcasts:
        await query.edit_message_text(
            "📜 *BROADCAST HISTORY*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No broadcasts sent yet.",
            reply_markup=back_button("main_menu"),
            parse_mode="Markdown",
        )
        return

    total_sent = sum(b.get("sent_to", 0) for b in broadcasts)
    await query.edit_message_text(
        "📜 *BROADCAST HISTORY*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Total broadcasts: *{len(broadcasts)}*\n"
        f"👥 Total delivered: *{total_sent}*\n\n"
        "Select a broadcast to view details:",
        reply_markup=broadcast_history_menu(broadcasts),
        parse_mode="Markdown",
    )


async def bcast_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    broadcasts = get_broadcasts(user_id)

    if index >= len(broadcasts):
        await query.edit_message_text("Broadcast not found.", reply_markup=back_button("broadcast_history"))
        return

    b = broadcasts[index]
    await query.edit_message_text(
        "📢 *BROADCAST DETAILS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Date:* {b.get('date', 'N/A')}\n"
        f"📌 *Target:* {b.get('target_label', 'N/A')}\n"
        f"✅ *Delivered:* {b.get('sent_to', 0)}\n"
        f"❌ *Failed:* {b.get('failed', 0)}\n",
        reply_markup=broadcast_item_menu(index),
        parse_mode="Markdown",
    )


async def bcast_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    delete_broadcast(user_id, index)
    await query.answer("🗑 Broadcast record deleted", show_alert=True)
    await broadcast_history(update, context)


async def bcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for key in ["bcast_from_chat", "bcast_msg_id", "bcast_targets", "bcast_label", "bcast_message"]:
        context.user_data.pop(key, None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END


# ── stubs kept so existing bot.py imports don't break ─────────────────────────
async def bcast_pick_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await broadcast_home(update, context)

async def bcast_custom_targets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await bcast_compose(update, context)
