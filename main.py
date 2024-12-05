import asyncio
import logging
import os
import yt_dlp
import json
import instaloader
import requests
import uuid
from telegram import InputMediaPhoto, Update
from telegram.ext import CommandHandler, MessageHandler, filters, CallbackContext, Application
from bs4 import BeautifulSoup
import instaloader
import shutil
import re

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Maintain a set of active chat IDs
active_chats = set()

# Function to handle new messages and register chat IDs
async def register_chat(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in active_chats:
        active_chats.add(chat_id)
        logger.info(f"Registered new chat: {chat_id}")

# Function to send a message to all registered chats
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

async def instaloader_dl(shortcode):
    L = instaloader.Instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode=shortcode)
    L.download_post(post, target=f'insta_{shortcode}')
    jpg_files = [f'insta_{shortcode}/{file}' for file in os.listdir(f'insta_{shortcode}') if file.endswith('.jpg')]
    print(jpg_files)
    return jpg_files

# Define a function to handle TikTok, Instagram, YouTube, and Twitter (X) links
async def download_content(update: Update, context: CallbackContext) -> None:
    message = update.message
    url = message.text
    # Extract URL from the message text using regex
    url = re.search(r'(https?://\S+)', message.text).group(0)
    if not url:
        url = message.text

    # Sending the 'typing' action to let users know the bot is processing
    await message.reply_chat_action(action="typing")

    # Check if the URL is valid for TikTok, Instagram, YouTube, or X
    if 'tiktok.com' in url:
        await download_tiktok(url, update, context)
    elif 'instagram.com' in url:
        await download_instagram(url, update, context)
    elif 'youtube.com' in url or 'youtu.be' in url:
        await download_youtube(url, update, context)
    elif 'twitter.com' in url or 'x.com' in url:
        await download_twitter(url, update, context)
    else:
        await context.bot.send_message(chat_id=message.chat_id, text="Sorry, I don't support this URL.")

import os
import subprocess
from moviepy.editor import AudioFileClip, VideoFileClip


def create_video_with_sliding_images(images, audio_path, output_video):
    # Generate the image slideshow video with a sliding effect using FFmpeg
    images_pattern = 'img%d.jpg'  # This pattern assumes images are named img1.jpg, img2.jpg, etc.
    
    # Copy images to temporary filenames img1.jpg, img2.jpg, ...
    for idx, image in enumerate(images, start=1):
        os.rename(image, f'img{idx}.jpg')
    
    # FFmpeg command to create sliding image video
    slideshow_command = [
        'ffmpeg',
        '-framerate', '1/2',  # 1 image every 2 seconds
        '-i', images_pattern,  # Input images (img1.jpg, img2.jpg, etc.)
        '-vf', "zoompan=z='if(lte(on,1),1,zoom-0.001)':x='w-(t/2)*w':d=125",  # Sliding effect from right to left
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-r', '30',  # Framerate
        'slideshow.mp4'  # Output video file
    ]
    
    # Run the FFmpeg command to generate the slideshow
    subprocess.run(slideshow_command, check=True)
    
    # Add the audio to the video using MoviePy
    video = VideoFileClip("slideshow.mp4")
    audio = AudioFileClip(audio_path)
    
    # Set the audio to the video
    final_video = video.set_audio(audio)
    
    # Write the final video to the output path
    final_video.write_videofile(output_video, codec="libx264", audio_codec="aac")
    
    # Cleanup temporary files
    video.close()
    audio.close()
    os.remove("slideshow.mp4")
    for idx in range(1, len(images) + 1):
        os.remove(f'img{idx}.jpg')

# Function to download TikTok video
async def download_tiktok(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        api_url = "https://ttsave.app/download"
        payload = json.dumps({
            "query": url,
            "language_id": "1"
        })
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9,ru-RU;q=0.8,ru;q=0.7,uk;q=0.6,pl;q=0.5,be;q=0.4',
            'content-type': 'application/json',
            'dnt': '1',
            'origin': 'https://ttsave.app',
            'priority': 'u=1, i',
            'referer': 'https://ttsave.app/en',
            'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Cookie': 'XSRF-TOKEN=eyJpdiI6ImMwRHNEMGc3UXJXVzcrdkFrYmRJcEE9PSIsInZhbHVlIjoiYVNxWE4xMTNWK2JSSk5DUkZDN1Z3MTh5RVN4bzJmVzN5d2RyQXk2UGs4R1BMU3MxaTNHL0V1UjBRQVh3ckxyaUR1eXpOSzVEOWxDNlpITFU1eE1kNFdISER4Q25Icmg1ekFPUHV4WHVLd2hmbTMrN2lDMldEVVlLcE1kL2ZmL0QiLCJtYWMiOiJjZjY0MjVkOTU3MzcyZDU1ODNiYmYwNGJlZjhiMmY2ZDViYmI1N2ZlZWViNWUyY2I5ZGQ4YzNhOTdiYWFlODBmIiwidGFnIjoiIn0%3D; ttsaveapp_session=eyJpdiI6IkdOcXVOZWxKQTIrTVljZ3YxMUZSMmc9PSIsInZhbHVlIjoiY3M1UWdWdWdETGJheGhPTUN4akU1aGovL1lDRWMxcWp6OXorcERTdU5sMmtGU0FMZVpmVVNTbmtJU2tSeGt6aUViZzVBSG15TjlFdjZpaFkwMTBDREdzdDdTb0tBcEREcjRCZERmVjJPNGlSYWJwVjBYMWxuMEV6Uy8reldqOFgiLCJtYWMiOiJjYjQ0YjQ2OGY4NDU2MDdkZTc3YzA3ZjdkZGFiZjI1NzBiMmU5MzI5MTA5Y2NjYjY4YjA5MmUyNTUyMTBiNTM5IiwidGFnIjoiIn0%3D'
        }

        response = requests.post(api_url, headers=headers, data=payload)
        response.raise_for_status()

        # Parse the response to find the direct video URL
        soup = BeautifulSoup(response.text, 'html.parser')
        download_button = soup.find('div', id='button-download-ready')
        if download_button:
            # Try to find an image first
            img_tags = download_button.find_all('img')
            if img_tags:
                media_group = []
                for img_tag in img_tags:
                    if 'src' in img_tag.attrs:
                        # If img tag is found, download the image
                        img_url = img_tag['src']
                        img_response = requests.get(img_url)
                        img_file = f'downloads/tiktok_image_{img_tags.index(img_tag)}.jpg'
                        with open(img_file, 'wb') as f:
                            f.write(img_response.content)
                        
                        media_group.append(img_file)

                # Send all images as a media group
                media = [InputMediaPhoto(open(img, 'rb')) for img in media_group]
                await context.bot.send_media_group(chat_id=message.chat_id, media=media, reply_to_message_id=message.message_id)

                # Clean up downloaded images
                for img in media_group:
                    os.remove(img)

                # Try to find an audio file with .mp3 extension
                audio_tag = download_button.find('a', href=lambda href: href and href.endswith('.mp3'))
                if audio_tag:
                    audio_url = audio_tag['href']
                    audio_response = requests.get(audio_url)
                    audio_file = f'downloads/tiktok_audio_{uuid.uuid4().hex}.mp3'
                    with open(audio_file, 'wb') as f:
                        f.write(audio_response.content)

                    await context.bot.send_audio(chat_id=message.chat_id, audio=open(audio_file, 'rb'), reply_to_message_id=message.message_id)
                    os.remove(audio_file)
            else:
                # If no img tag found, try to find the video URL
                video_url = download_button.find('a')['href']
                if video_url:
                    video_response = requests.get(video_url)
                    video_file = f'downloads/tiktok_{uuid.uuid4().hex}.mp4'
                    with open(video_file, 'wb') as f:
                        f.write(video_response.content)

                    await context.bot.send_video(chat_id=message.chat_id, video=open(video_file, 'rb'), reply_to_message_id=message.message_id)
                    os.remove(video_file)
                else:
                    raise Exception("Failed to find the download link in the response.")
        else:
            raise Exception("Failed to find the download link in the response.")
    except Exception as e:
        logger.error(e)
        logger.error("Exception occurred", exc_info=True)
        await context.bot.send_message(chat_id=message.chat_id, text="Failed to download TikTok video.")

# Function to download Instagram content
async def download_instagram(url: str, update: Update, context: CallbackContext):
    message = update.message
    if 'p/' in url:
        try:
            shortcode = url.split('/p/')[1].split('/')[0]
            files_list = await instaloader_dl(shortcode)
            

            if len(files_list) > 1:
                media = [InputMediaPhoto(open(file, 'rb')) for file in files_list]
                await context.bot.send_media_group(chat_id=message.chat_id, media=media, reply_to_message_id=message.message_id)
            else:
                await context.bot.send_document(chat_id=message.chat_id, document=open(files_list[0], 'rb'), reply_to_message_id=message.message_id)
            for file in files_list:
                os.remove(file)
            shutil.rmtree(f'insta_{shortcode}')
        except Exception as e:
            logger.error(e)
            await context.bot.send_message(chat_id=message.chat_id, text="Failed to download Instagram content.")
    else:
        try:
            api_url = "https://app.publer.io/hooks/media"
            payload = json.dumps({
                "url": url
            })
            headers = {
                'accept': '*/*',
                'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8,uk;q=0.7',
                'content-type': 'application/json;',
                'origin': 'https://publer.io',
                'priority': 'u=1, i',
                'referer': 'https://publer.io/',
                'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site'
            }
            logger.info(f"Sending request to {api_url} with payload: {payload}")
            response = requests.post(api_url, headers=headers, data=payload)
            response.raise_for_status()
            logger.info(f"Received response: {response.json()}")
            job_id = response.json()['job_id']
            job_status = 'working'
            while job_status == 'working':
                logger.info(f"Checking job status for job_id: {job_id}")
                await asyncio.sleep(2)
                response = requests.get(f'https://app.publer.io/api/v1/job_status/{job_id}')
                response.raise_for_status()
                job_status = response.json()['status']
                logger.info(f"Job status: {job_status}")
            if job_status == 'failed':
                raise Exception('Failed to download Instagram content')
            if job_status == 'complete':
                path = response.json()['payload'][0]['path']
                logger.info(f"Downloading video from path: {path}")
                video_response = requests.get(path)
                video_file = f'downloads/instagram_{uuid.uuid4().hex}.mp4'
                with open(video_file, 'wb') as f:
                    f.write(video_response.content)
                logger.info(f"Video downloaded to {video_file}")

                await context.bot.send_video(chat_id=message.chat_id, video=open(video_file, 'rb'), reply_to_message_id=message.message_id)
                os.remove(video_file)
                logger.info(f"Video file {video_file} removed after sending")
        except Exception as e:
            logger.error(e)
            await context.bot.send_message(chat_id=message.chat_id, text="Failed to download Instagram content.")

async def download_youtube(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'format': 'best',
            'noplaylist': True,
            'max_filesize': 200000000  # Limit to 200MB
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            video_file = ydl.prepare_filename(info_dict)
            await context.bot.send_video(chat_id=message.chat_id, video=open(video_file, 'rb'), reply_to_message_id=message.message_id)
            os.remove(video_file)
    except Exception as e:
        logger.error(e)
        await context.bot.send_message(chat_id=message.chat_id, text="Failed to download YouTube video or file is too large.")

# Function to download X (Twitter) content
async def download_twitter(url: str, update: Update, context: CallbackContext):
    message = update.message
    try:
        ydl_opts = {'outtmpl': 'downloads/%(title)s.%(ext)s'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            media_file = ydl.prepare_filename(info_dict)
            await context.bot.send_video(chat_id=message.chat_id, video=open(media_file, 'rb'), reply_to_message_id=message.message_id)
            os.remove(media_file)
    except Exception as e:
        logger.error(e)
        await context.bot.send_message(chat_id=message.chat_id, text="Failed to download Twitter video.")

# Error handler function
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f'Update "{update}" caused error "{context.error}"')

# Main function to start the bot
def main() -> None:
    TOKEN = ""
    application = Application.builder().token(TOKEN).build()

    application.add_handler(MessageHandler(filters.TEXT & (filters.Entity("url") | filters.Entity("text_link")), download_content))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, register_chat))
    application.add_handler(CommandHandler("sayall", say_all))

    # Log all errors
    application.add_error_handler(error)

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
