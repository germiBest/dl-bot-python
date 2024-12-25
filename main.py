import asyncio
import logging
import os
import json
import requests
import uuid
import re
from telegram import InputMediaPhoto, InputMediaVideo, Update
from telegram.ext import CommandHandler, MessageHandler, filters, CallbackContext, Application
import yt_dlp
from bs4 import BeautifulSoup
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

active_chats = set()

async def register_chat(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in active_chats:
        active_chats.add(chat_id)
        logger.info(f"Registered new chat: {chat_id}")

async def say_all(update: Update, context: CallbackContext) -> None:
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /sayall <message>")
        return

    message = " ".join(context.args)
    if not active_chats:
        await update.message.reply_text("No active chats to send the message to.")
        return

    for chat_id in active_chats:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send message to chat {chat_id}: {e}")

async def snapsave(input_url: str) -> dict:
    """
    Uses Playwright to open a real Chromium browser, navigate to snapsave.app,
    submit an Instagram or Facebook URL, and scrape the resulting download links.
    Returns a dict with status and data.
    """

    is_facebook_link = re.search(r'(?:https?:\/\/(web\.|www\.|m\.)?(facebook|fb)\.(com|watch)\S+)?$', input_url)
    is_instagram_link = re.search(r'(https|http):\/\/www.instagram.com\/(p|reel|tv|stories)', input_url, re.IGNORECASE)

    if not (is_facebook_link or is_instagram_link):
        return {
            "status": False,
            "msg": "Link URL not valid",
        }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", '--enable-webgl', '--use-gl=swiftshader', '--enable-accelerated-2d-canvas'])
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                device_scale_factor=1,
            )
            page = await context.new_page()

            await page.goto("https://snapsave.app/")

            await page.fill("input[name='url']", input_url)

            await page.click("button.is-download")

            await page.wait_for_selector("#download-section", timeout=30000)

            download_section_html = await page.inner_html("#download-section")

            await browser.close()

    except Exception as exc:
        return {
            "status": False,
            "msg": f"Browser error: {exc}",
        }

    soup = BeautifulSoup(download_section_html, "html.parser")
    results = []

    table_found = soup.select("table.table")
    article_found = soup.select("article.media > figure")

    if table_found or article_found:

        figure_img = soup.select_one("article.media > figure img")
        first_thumbnail = figure_img.get("src") if figure_img else None

        for row in soup.select("tbody > tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            resolution_text = cells[0].get_text(strip=True)

            anchor = cells[2].find("a")
            button = cells[2].find("button")

            link = anchor["href"] if anchor else None
            if not link and button and button.has_attr("onclick"):
                link = button["onclick"]

            needs_progress_api = bool(re.search(r"get_progressApi", link or "", re.IGNORECASE))
            if needs_progress_api:
                match = re.search(r"get_progressApi\('(.*?)'\)", link or "")
                if match:
                    link = match.group(1)

            results.append({
                "resolution": resolution_text,
                "thumbnail": first_thumbnail,
                "url": link,
                "shouldRender": needs_progress_api,
            })
    else:

        thumb_divs = soup.select("div.download-items__thumb")
        btn_divs = soup.select("div.download-items__btn")

        for thumb_div in thumb_divs:
            img_tag = thumb_div.find("img")
            thumbnail_url = img_tag["src"] if img_tag else None

            for btn_div in btn_divs:
                anchor = btn_div.find("a")
                download_url = anchor["href"] if anchor else None
                if download_url and not re.match(r"https?://", download_url):
                    download_url = f"https://snapsave.app{download_url}"

                if download_url:
                    results.append({
                        "thumbnail": thumbnail_url,
                        "url": download_url,
                    })

    if not results:
        return {
            "status": False,
            "msg": "Blank data",
        }

    return {
        "status": True,
        "data": results,
    }

async def download_instagram(url: str, update: Update, context: CallbackContext):
    """
    Reworked Instagram downloader that downloads media from SnapSave URLs,
    saves them locally, and sends them as a Telegram media group.
    """
    message = update.message
    final_data = await snapsave(url)  

    if not final_data["status"]:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=f"Failed to download from SnapSave: {final_data.get('msg', 'Unknown error')}"
        )
        return

    def remove_duplicates(dict_list, keys):
        seen = set()
        unique_list = []
        for d in dict_list:
            identifier = tuple(d[key] for key in keys)
            if identifier not in seen:
                seen.add(identifier)
                unique_list.append(d)
        return unique_list

    results = remove_duplicates(final_data.get("data", []), keys=["url"])

    if not results:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="No downloadable media found."
        )
        return

    media_group = []
    temp_files = []  

    try:
        for item in results:
            media_url = item.get("url")
            if not media_url:
                continue

            file_extension = "mp4" if ("reel" in url or "tv" in url) else "jpg"
            is_video = file_extension == "mp4"
            file_path = f"downloads/ig_{uuid.uuid4().hex}.{file_extension}"

            download_file(media_url, file_path)
            temp_files.append(file_path)

            if is_video:
                media_group.append(InputMediaVideo(media=open(file_path, 'rb')))
            else:
                media_group.append(InputMediaPhoto(media=open(file_path, 'rb')))

        if media_group:
            await context.bot.send_media_group(
                chat_id=message.chat_id,
                media=media_group,
                reply_to_message_id=message.message_id
            )

    finally:

        for temp_file in temp_files:
            os.remove(temp_file)

async def send_photo(photo_url: str, message: Update, context: CallbackContext):
    """
    Download a single photo and send it.
    """
    photo_file = f"downloads/ig_{uuid.uuid4().hex}.jpg"
    download_file(photo_url, photo_file)

    await context.bot.send_photo(
        chat_id=message.chat_id,
        photo=open(photo_file, 'rb'),
        reply_to_message_id=message.message_id
    )
    os.remove(photo_file)

async def send_video(video_url: str, message: Update, context: CallbackContext):
    """
    Download a single video and send it.
    """
    video_file = f"downloads/ig_{uuid.uuid4().hex}.mp4"
    download_file(video_url, video_file)

    await context.bot.send_video(
        chat_id=message.chat_id,
        video=open(video_file, 'rb'),
        reply_to_message_id=message.message_id
    )
    os.remove(video_file)

def download_file(url: str, path: str):
    """
    Simple file downloader, saves to 'path'.
    """
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

async def download_tiktok(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        api_url = "https://ttsave.app/download"
        payload = json.dumps({"query": url, "language_id": "1"})
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://ttsave.app',
            'referer': 'https://ttsave.app/en',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }

        response = requests.post(api_url, headers=headers, data=payload)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        download_button = soup.find('div', id='button-download-ready')
        if download_button:
            video_link = download_button.find('a')
            if video_link and video_link.has_attr('href'):
                video_url = video_link['href']
                video_file = f'downloads/tiktok_{uuid.uuid4().hex}.mp4'
                download_file(video_url, video_file)

                await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=open(video_file, 'rb'),
                    reply_to_message_id=message.message_id
                )
                os.remove(video_file)
            else:
                raise Exception("No downloadable video link found.")
        else:
            raise Exception("Failed to find the download link in the response.")

    except Exception as e:
        logger.error(e, exc_info=True)
        await context.bot.send_message(
            chat_id=message.chat_id, 
            text="Failed to download TikTok video."
        )

async def download_youtube(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'format': 'best',
            'noplaylist': True,
            'max_filesize': 200_000_000  
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            video_file = ydl.prepare_filename(info_dict)
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=open(video_file, 'rb'),
                reply_to_message_id=message.message_id
            )
            os.remove(video_file)
    except Exception as e:
        logger.error(e, exc_info=True)
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="Failed to download YouTube video or file is too large."
        )

async def download_twitter(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'format': 'best'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            media_file = ydl.prepare_filename(info_dict)
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=open(media_file, 'rb'),
                reply_to_message_id=message.message_id
            )
            os.remove(media_file)
    except Exception as e:
        logger.error(e, exc_info=True)
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="Failed to download Twitter (X) video."
        )

async def download_content(update: Update, context: CallbackContext) -> None:
    """
    Check incoming message for a link. If it's recognized as TikTok/Instagram/
    YouTube/Twitter, route to the appropriate downloader.
    """
    message = update.message

    match = re.search(r'(https?://\S+)', message.text)
    if match:
        url = match.group(0)
    else:

        return

    await message.reply_chat_action(action="typing")

    if 'tiktok.com' in url:
        await download_tiktok(url, update, context)
    elif 'instagram.com' in url:
        await download_instagram(url, update, context)
    elif 'youtu.be' in url or 'youtube.com' in url:
        await download_youtube(url, update, context)
    elif 'twitter.com' in url or 'x.com' in url:
        await download_twitter(url, update, context)
    else:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text="Sorry, I don't support this URL."
        )


async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update "{update}" caused error "{context.error}"')

def main() -> None:
    TOKEN = ""
    application = Application.builder().token(TOKEN).build()

    application.add_handler(MessageHandler(
        filters.TEXT & (filters.Entity("url") | filters.Entity("text_link")),
        download_content
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, register_chat))
    application.add_handler(CommandHandler("sayall", say_all))

    application.add_error_handler(error)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()