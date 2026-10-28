import os
import json
import io
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))


def get_drive():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        info = json.loads(token_json)
    else:
        with open("token.json", "r") as f:
            info = json.load(f)

    creds = Credentials.from_authorized_user_info(
        info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def allowed(update):
    return (
        OWNER_ID != 0
        and update.effective_user
        and update.effective_user.id == OWNER_ID
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "Send or forward a file here, and I'll ask where to upload it."
    )


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("Access denied.")
        return

    msg = update.message
    media = msg.document or msg.video or msg.audio or msg.animation

    if msg.photo:
        media = msg.photo[-1]
        filename = f"photo_{media.file_unique_id}.jpg"
    elif media:
        filename = getattr(media, "file_name", None)
        if not filename:
            filename = f"file_{media.file_unique_id}"
    elif msg.voice:
        media = msg.voice
        filename = f"voice_{media.file_unique_id}.ogg"
    else:
        await msg.reply_text("Please send a document, photo, video, audio, or voice message.")
        return

    if media.file_size and media.file_size > 20 * 1024 * 1024:
        await msg.reply_text("This file exceeds the bot's 20 MB download limit.")
        return

    context.user_data["pending_file"] = {
        "file_id": media.file_id,
        "filename": filename,
    }

    await show_folders(update, context, "root", edit=False)


async def show_folders(update, context, folder_id, edit=True):
    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()

    drive = get_drive()
    result = await asyncio.to_thread(
        lambda: drive.files().list(
            q=f"'{folder_id}' in parents and "
              "mimeType='application/vnd.google-apps.folder' "
              "and trashed=false",
            fields="files(id,name)",
            pageSize=50,
            orderBy="name"
        ).execute()
    )

    keyboard = [
        [InlineKeyboardButton("📁 " + f["name"],
                              callback_data="browse:" + f["id"])]
        for f in result.get("files", [])
    ]
    keyboard.append([
        InlineKeyboardButton("⬆️ Upload here",
                             callback_data="choose:" + folder_id)
    ])

    if folder_id != "root":
        parents = await asyncio.to_thread(
            lambda: drive.files().get(
                fileId=folder_id, fields="parents"
            ).execute()
        )
        parent = parents.get("parents", ["root"])[0]
        keyboard.append([
            InlineKeyboardButton("⬅️ Back",
                                 callback_data="browse:" + parent),
            InlineKeyboardButton("🏠 Root",
                                 callback_data="browse:root")
        ])

    markup = InlineKeyboardMarkup(keyboard)
    text = "Choose a folder to open, or tap Upload here."

    if query:
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def folder_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not allowed(update):
        await query.answer("Access denied.", show_alert=True)
        return

    action, folder_id = query.data.split(":", 1)

    if action == "browse":
        await show_folders(update, context, folder_id)
        return

    pending = context.user_data.get("pending_file")
    if not pending:
        await query.answer("Please send the file again.", show_alert=True)
        return

    await query.answer("Uploading...")
    await query.edit_message_text("Uploading your file to Google Drive...")

    try:
        tg_file = await context.bot.get_file(pending["file_id"])
        buffer = io.BytesIO()
        await tg_file.download_to_memory(out=buffer)
        buffer.seek(0)

        drive = get_drive()
        media = MediaIoBaseUpload(
            buffer, mimetype="application/octet-stream",
            resumable=False
        )

        uploaded = await asyncio.to_thread(
            lambda: drive.files().create(
                body={
                    "name": pending["filename"],
                    "parents": [folder_id]
                },
                media_body=media,
                fields="id,name"
            ).execute()
        )

        context.user_data.pop("pending_file", None)
        await query.edit_message_text(
            "✅ Upload complete!\n"
            f"File: {uploaded['name']}\n"
            f"Drive file ID: {uploaded['id']}"
        )
    except Exception as e:
        await query.edit_message_text(
            "Upload failed. Please check your Google authorization "
            "and try again.\n"
            f"Error: {str(e)[:500]}"
        )


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN first.")
    if OWNER_ID == 0:
        raise RuntimeError("Set OWNER_TELEGRAM_ID first.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(folder_button))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO |
        filters.AUDIO | filters.VOICE | filters.ANIMATION,
        receive_file
    ))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
