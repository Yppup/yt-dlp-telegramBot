# main.py
import os
import re
import time
import asyncio
import yaml
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified

from x_downloader import download_video_sync

# --- 读取配置 ---
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

API_ID = config['TELEGRAM']['API_ID']
API_HASH = config['TELEGRAM']['API_HASH']
BOT_TOKEN = config['TELEGRAM']['BOT_TOKEN']
WORK_DIR = config['SYSTEM']['WORK_DIR']

app = Client("xbot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workdir=WORK_DIR)
url_cache = {}  
active_downloads = {}  

# --- 进度条更新任务 ---
async def update_download_ui(message, msg_id):
    last_text = ""
    while msg_id in active_downloads:
        progress = active_downloads[msg_id]
        if progress:
            text = f"⬇️ 正在下载: {progress}"
            if text != last_text:
                try:
                    await message.edit_text(text)
                    last_text = text
                except MessageNotModified:
                    pass
                except Exception:
                    pass
        await asyncio.sleep(3)

async def upload_progress(current, total, message, start_time, state):
    now = time.time()
    if now - state.get('last_update', 0) > 3 or current == total:
        state['last_update'] = now
        
        percent = current * 100 / total
        speed_bps = current / (now - start_time) if now > start_time else 1
        eta_seconds = (total - current) / speed_bps if speed_bps > 0 else 0
        
        current_mb = current / 1024 / 1024
        total_mb = total / 1024 / 1024
        speed_mb = speed_bps / 1024 / 1024
        mins, secs = divmod(int(eta_seconds), 60)
        
        text = (
            f"⬆️ 正在直传至 Telegram:\n"
            f"📊 进度: {percent:.1f}% ({current_mb:.1f} MB / {total_mb:.1f} MB)\n"
            f"🚀 速度: {speed_mb:.2f} MB/s\n"
            f"⏳ 剩余: {mins}分 {secs}秒"
        )
        try:
            await message.edit_text(text)
        except MessageNotModified:
            pass
        except Exception:
            pass

# --- 消息拦截与按钮 ---
@app.on_message(filters.text & ~filters.command("start"))
async def handle_message(client, message):
    url_match = re.search(r'(https?://(?:www\.)?(?:twitter\.com|x\.com)/[^\s]+)', message.text)
    if not url_match:
        return
        
    url = url_match.group(1)
    msg_id = message.id
    url_cache[msg_id] = url
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 视频 (压缩/兼容好)", callback_data=f"video_{msg_id}"),
            InlineKeyboardButton("📄 文件 (无损/原画质)", callback_data=f"doc_{msg_id}")
        ]
    ])
    await message.reply_text('👇 成功解析，请选择接收方式：', reply_markup=keyboard, reply_to_message_id=msg_id)

@app.on_callback_query()
async def button_callback(client, query):
    data = query.data
    chat_id = query.message.chat.id
    
    mode, msg_id_str = data.split('_')
    original_msg_id = int(msg_id_str)
    url = url_cache.get(original_msg_id)
    
    if not url:
        await query.message.edit_text("❌ 链接已过期或丢失，请重新发送。")
        return

    post_id_match = re.search(r'status/(\d+)', url)
    post_id = post_id_match.group(1) if post_id_match else str(original_msg_id)
    
    file_prefix_path = os.path.join(WORK_DIR, f"x_video_{post_id}")
    expected_file_name = f"{file_prefix_path}.mp4"
    
    active_downloads[original_msg_id] = "初始化中..."
    dl_task = asyncio.create_task(update_download_ui(query.message, original_msg_id))
    
    try:
        video_metadata = await asyncio.to_thread(
            download_video_sync, url, file_prefix_path, original_msg_id, active_downloads
        )
        
        active_downloads.pop(original_msg_id, None)
        dl_task.cancel()
        
        if not os.path.exists(expected_file_name):
            raise Exception("yt-dlp 下载完成，但硬盘未找到文件。")

        start_time = time.time()
        state = {"last_update": 0}
        
        if mode == 'video':
            await client.send_video(
                chat_id=chat_id,
                video=expected_file_name,
                reply_to_message_id=original_msg_id,
                caption="✅ Down! 请查收视频！",
                supports_streaming=True,
                width=video_metadata.get('width'),
                height=video_metadata.get('height'),
                duration=video_metadata.get('duration'),
                progress=upload_progress,
                progress_args=(query.message, start_time, state)
            )
        else:
            await client.send_document(
                chat_id=chat_id,
                document=expected_file_name,
                reply_to_message_id=original_msg_id,
                caption="✅ Down! 请查收文件！",
                progress=upload_progress,
                progress_args=(query.message, start_time, state)
            )
            
        await query.message.delete()

    except Exception as e:
        active_downloads.pop(original_msg_id, None)
        if 'dl_task' in locals(): dl_task.cancel()
        await query.message.edit_text(f"❌ 处理失败: {str(e)}")
        
    finally:
        url_cache.pop(original_msg_id, None)
        if os.path.exists(expected_file_name):
            os.remove(expected_file_name)

if __name__ == '__main__':
    print("Main Pyrogram Bot is starting...")
    app.run()