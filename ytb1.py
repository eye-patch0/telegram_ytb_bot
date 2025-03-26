import os
import yt_dlp
from datetime import timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

class YouTubeDownloader:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
        }
    
    def get_video_info(self, url):
        """Extract video information without downloading"""
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                print(f"Error getting video info: {e}")
                return None
    
    def get_available_formats(self, info):
        """Get available formats with proper sorting"""
        formats = info.get('formats', [])
        
        # Filter unique resolutions
        unique_resolutions = {}
        for f in formats:
            if f.get('vcodec') != 'none':  # Video formats only
                res = f.get('height', 'unknown')
                current_size = f.get('filesize', 0) or 0
                existing_size = unique_resolutions.get(res, {}).get('filesize', 0) or 0
                
                if res not in unique_resolutions or current_size > existing_size:
                    unique_resolutions[res] = f
        
        # Sort resolutions numerically (highest first)
        sorted_resolutions = dict(sorted(
            unique_resolutions.items(),
            key=lambda item: item[0] if isinstance(item[0], int) else 0,
            reverse=True
        ))
        
        return sorted_resolutions
    
    def download_video(self, url, resolution, output_path='.'):
        """Download video with selected resolution"""
        download_opts = self.ydl_opts.copy()
        download_opts.update({
            'format': f'b[height<={resolution}]',
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'progress_hooks': [self.progress_hook],
        })
        
        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return filename
        except Exception as e:
            print(f"Download failed: {e}")
            return None
    
    def progress_hook(self, d):
        """Progress callback function (not used directly in Telegram bot)"""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '?')
            speed = d.get('_speed_str', '?')
            eta = d.get('_eta_str', '?')
            print(f"\rDownloading: {percent} | Speed: {speed} | ETA: {eta}", end='')
        elif d['status'] == 'finished':
            print(f"\nDownload complete! Saved to: {d['filename']}")

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.downloader = YouTubeDownloader()
        self.app = Application.builder().token(token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Create temp directory if it doesn't exist
        os.makedirs("temp_downloads", exist_ok=True)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a welcome message when the command /start is issued"""
        welcome_text = """
        🎬 YouTube Video Downloader Bot
        
        Send me a YouTube URL and I'll download it for you!
        
        Commands:
        /start - Show this message
        /help - Show help information
        """
        await update.message.reply_text(welcome_text)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a help message when the command /help is issued"""
        help_text = """
        ℹ️ How to use this bot:
        
        1. Send me a YouTube URL (e.g., https://www.youtube.com/watch?v=...)
        2. I'll show you available resolutions
        3. Select your preferred quality
        4. Wait for the download to complete
        
        Note: Large videos may take time to download and may exceed Telegram's file size limits.
        """
        await update.message.reply_text(help_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming YouTube URLs"""
        url = update.message.text.strip()
        chat_id = update.message.chat_id
        
        # Check if it's a YouTube URL
        if not ("youtube.com" in url or "youtu.be" in url):
            await update.message.reply_text("Please send a valid YouTube URL.")
            return
        
        try:
            await update.message.reply_text("🔍 Getting video information...")
            
            # Get video info
            info = self.downloader.get_video_info(url)
            if not info:
                await update.message.reply_text("❌ Could not get video information. Please check the URL.")
                return
            
            # Prepare video info message
            duration = str(timedelta(seconds=info['duration']))
            info_text = (
                f"📽 <b>{info['title']}</b>\n"
                f"👤 Channel: {info['uploader']}\n"
                f"⏱ Duration: {duration}\n"
                f"📅 Upload date: {info.get('upload_date', 'N/A')}\n"
                f"👀 Views: {info.get('view_count', 'N/A')}"
            )
            
            # Get available formats
            formats = self.downloader.get_available_formats(info)
            if not formats:
                await update.message.reply_text("❌ No downloadable formats found.")
                return
            
            # Create quality selection buttons (top 3 resolutions)
            buttons = []
            for i, (res, fmt) in enumerate(list(formats.items())[:3]):
                file_size = fmt.get('filesize')
                size_str = f" ({round(file_size/(1024*1024), 1)}MB)" if file_size else ""
                buttons.append([
                    InlineKeyboardButton(
                        f"{res}p{size_str}",
                        callback_data=f"dl_{res}_{url}"
                    )
                ])
            
            # Add audio-only option
            buttons.append([
                InlineKeyboardButton(
                    "🎵 Audio Only (MP3)",
                    callback_data=f"dl_audio_{url}"
                )
            ])
            
            reply_markup = InlineKeyboardMarkup(buttons)
            
            # Send video info with quality options
            await update.message.reply_text(
                info_text,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quality selection button presses"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        chat_id = query.message.chat_id
        
        if data.startswith('dl_'):
            try:
                parts = data.split('_')
                quality = parts[1]
                url = '_'.join(parts[2:])  # Reconstruct URL which might contain underscores
                
                await query.edit_message_text("⏳ Starting download... Please wait.")
                
                if quality == "audio":
                    # Handle audio download
                    filename = await self.download_audio(url, chat_id)
                else:
                    # Handle video download
                    filename = await self.download_video(url, int(quality), chat_id)
                
                if not filename:
                    await query.edit_message_text("❌ Download failed. Please try again.")
                    return
                
                # Send the downloaded file
                try:
                    if quality == "audio":
                        with open(filename, 'rb') as audio_file:
                            await context.bot.send_audio(
                                chat_id=chat_id,
                                audio=audio_file,
                                caption="Here's your audio file!"
                            )
                    else:
                        with open(filename, 'rb') as video_file:
                            await context.bot.send_video(
                                chat_id=chat_id,
                                video=video_file,
                                caption=f"Here's your video in {quality}p quality!"
                            )
                    
                    # Clean up
                    os.remove(filename)
                    await query.delete_message()
                    
                except Exception as e:
                    await query.edit_message_text(f"❌ Error sending file: {str(e)}")
                    if os.path.exists(filename):
                        os.remove(filename)
            
            except Exception as e:
                await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def download_video(self, url, resolution, chat_id):
        """Download video and return filename"""
        try:
            message = await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"⬇️ Downloading {resolution}p video..."
            )
            
            # Custom progress hook for Telegram
            def progress_hook(d):
                if d['status'] == 'downloading':
                    percent = d.get('_percent_str', '?')
                    speed = d.get('_speed_str', '?')
                    eta = d.get('_eta_str', '?')
                    self.app.create_task(
                        message.edit_text(
                            f"⬇️ Downloading {resolution}p video...\n"
                            f"Progress: {percent}\n"
                            f"Speed: {speed}\n"
                            f"ETA: {eta}"
                        )
                    )
            
            # Configure download options
            download_opts = self.downloader.ydl_opts.copy()
            download_opts.update({
                'format': f'b[height<={resolution}]',
                'outtmpl': os.path.join("temp_downloads", '%(title)s.%(ext)s'),
                'progress_hooks': [progress_hook],
            })
            
            # Download the video
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Ensure the file has .mp4 extension
                if not filename.endswith('.mp4'):
                    new_filename = f"{os.path.splitext(filename)[0]}.mp4"
                    os.rename(filename, new_filename)
                    filename = new_filename
                
                return filename
        
        except Exception as e:
            print(f"Download error: {e}")
            return None
    
    async def download_audio(self, url, chat_id):
        """Download audio only and return filename"""
        try:
            message = await self.app.bot.send_message(
                chat_id=chat_id,
                text="⬇️ Downloading audio..."
            )
            
            # Custom progress hook for Telegram
            def progress_hook(d):
                if d['status'] == 'downloading':
                    percent = d.get('_percent_str', '?')
                    speed = d.get('_speed_str', '?')
                    eta = d.get('_eta_str', '?')
                    self.app.create_task(
                        message.edit_text(
                            f"⬇️ Downloading audio...\n"
                            f"Progress: {percent}\n"
                            f"Speed: {speed}\n"
                            f"ETA: {eta}"
                        )
                    )
            
            # Configure download options for audio
            download_opts = self.downloader.ydl_opts.copy()
            download_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': os.path.join("temp_downloads", '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'progress_hooks': [progress_hook],
            })
            
            # Download the audio
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                filename = f"{os.path.splitext(filename)[0]}.mp3"
                return filename
        
        except Exception as e:
            print(f"Audio download error: {e}")
            return None
    
    def run(self):
        """Run the bot"""
        print("Bot is running...")
        self.app.run_polling()

if __name__ == "__main__":
    # Replace with your bot token from @BotFather
    TOKEN = "replace token here"
    
    bot = TelegramBot(TOKEN)
    bot.run()
