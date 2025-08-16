from future import annotations
import os
import tempfile
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

from utils import setup_logging, load_env, get_env, human_exc
from audio_processing import is_url
from search_engine import identify_from_audio_input, identify_from_text

log = setup_logging()
load_env()

BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
MB_UA = get_env("MUSICBRAINZ_USER_AGENT", "MusicJoo/1.0 (contact@example.com)")
BOT_USERNAME = get_env("BOT_USERNAME", "").lower()  # for group mentions

if not BOT_TOKEN:
    raise SystemExit("Please set TELEGRAM_BOT_TOKEN in your .env")

WELCOME = (
    ":headphones: *MusicJoo* is ready!\n"
    "• Send *text* (song title or a bit of lyrics)\n"
    "• Send a *link* (IG, YT, ...)\n"
    "• Send *audio/voice/video*\n\n"
    "I’ll return official links, cover art, and a 30s preview when available."
)

HELP = (
    "Usage:\n"
    "• Text: title or part of the lyrics (best-effort)\n"
    "• Link: any media link with audio (IG/YT/...)\n"
    "• File: audio/voice/video\n\n"
    "Tip: For short clips, set ACOUSTID_API_KEY and install fpcalc (Chromaprint) to enable fingerprint matching."
)

def _mentioned_me(text: str) -> bool:
    """Return True if bot is explicitly mentioned in group text."""
    if not BOT_USERNAME:
        return False
    return f"@{BOT_USERNAME}" in (text or "").lower()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(WELCOME)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def _reply_with_result(update: Update, res: dict):
    """Send a nice result message with optional cover and links."""
    title = res.get("title") or "Unknown"
    artists = res.get("artists") or ""
    cover = res.get("cover_url")
    sp = res.get("spotify_link")
    prev = res.get("spotify_preview")
    lyr = res.get("lyrics_excerpt")

    caption = f":musical_note: *{title}* — {artists}".strip()
    if sp:
        caption += f"\nSpotify: {sp}"
    if prev:
        caption += f"\nPreview (30s): {prev}"
    if lyr:
        # keep compact
        caption += f"\n\n_lyrics (excerpt):_\n{lyr[:500]}"

    if cover:
        try:
            await update.message.reply_photo(cover, caption=caption, parse_mode="Markdown")
            return
        except Exception:
            pass

    await update.message.reply_markdown(caption)

async def handle_text_or_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = (update.message.text or "").strip()
        chat_type = update.message.chat.type

        # In groups, only react if mentioned; in private, always react
        if chat_type in ("group", "supergroup"):
            if not _mentioned_me(text):
                return

        # URL input -> treat as media link; else text search
        if is_url(text):
            res = identify_from_audio_input(text, MB_UA)
        else:
            res = identify_from_text(text, MB_UA)

        if res:
            await _reply_with_result(update, res)
        else:
            await update.message.reply_text("No match found. Try a clearer title, link, or a short audio clip :pray:")
    except Exception as e:
        log.exception("handle_text_or_link failed")
        await update.message.reply_text(f"Error: {human_exc(e)}")

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = None
        msg = update.message
        if msg.audio:
            file = await msg.audio.get_file()
        elif msg.voice:
            file = await msg.voice.get_file()
        elif msg.video:
            file = await msg.video.get_file()
        elif msg.video_note:
            file = await msg.video_note.get_file()
        elif msg.document:
            file = await msg.document.get_file()

        if not file:
            await msg.reply_text("Unsupported file.")
            return
with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            local_path = tmp.name

        res = identify_from_audio_input(local_path, MB_UA)
        if res:
            await _reply_with_result(update, res)
        else:
            await msg.reply_text("Couldn't identify from this clip. Try a slightly longer/clearer segment.")

        try:
            os.remove(local_path)
        except Exception:
            pass
    except Exception as e:
        log.exception("handle_media failed")
        await update.message.reply_text(f"Error: {human_exc(e)}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Private texts always handled; group texts handled only when mentioned (inside handler)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_or_link))

    # Any media is handled in all chats
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL,
        handle_media
    ))

    log.info("MusicJoo is running...")
    app.run_polling(close_loop=False)

if __name__ == "main":
    main()