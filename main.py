# main.py
import os
import re
import time
import asyncio
import yaml
import json
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified

from cookie_manager import (
    cookie_manager,
    is_cookie_auth_error,
    normalize_platform,
    platform_from_url,
)
from video_downloader import download_video_sync, probe_video_entries

# --- 读取配置 ---
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

API_ID = config['TELEGRAM']['API_ID']
API_HASH = config['TELEGRAM']['API_HASH']
BOT_TOKEN = config['TELEGRAM']['BOT_TOKEN']
WORK_DIR = config['SYSTEM']['WORK_DIR']

app = Client("xbot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workdir=WORK_DIR)
url_cache = {}
entry_cache = {}
active_downloads = {}
processing_callbacks = set()
pending_cookie_uploads = {}

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
        
        item_text = f"📦 文件: {state['item']}\n" if state.get('item') else ""
        text = (
            f"⬆️ 正在直传至 Telegram:\n"
            f"{item_text}"
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

async def video_codec(file_path):
    """使用 ffprobe 检查视频文件的编码格式"""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name', '-of', 'json', file_path
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        info = json.loads(stdout)
        return info['streams'][0]['codec_name'].lower()
    except Exception as e:
        print(f"检查编码失败: {e}")
        return ""

def build_file_prefix_path(url, original_msg_id):
    if 'instagram.com' in url:
        ig_match = re.search(r'(?:reel|p)/([^/]+)', url)
        post_id = ig_match.group(1) if ig_match else str(original_msg_id)
        return os.path.join(WORK_DIR, f"ig_video_{post_id}")

    post_id_match = re.search(r'status/(\d+)', url)
    post_id = post_id_match.group(1) if post_id_match else str(original_msg_id)
    return os.path.join(WORK_DIR, f"x_video_{post_id}")

def is_instagram_url(url):
    return 'instagram.com' in url

def is_admin_message(message):
    user = getattr(message, "from_user", None)
    return bool(user and cookie_manager.is_admin(user.id))

def is_private_chat(message):
    chat_type = str(getattr(message.chat, "type", "")).lower()
    return chat_type.endswith("private") or chat_type == "private"

def platform_label(platform):
    return "X" if platform == "x" else "Instagram"

def format_cookie_status(status):
    state_labels = {
        "valid": "可用",
        "missing": "缺失",
        "expired": "过期",
        "invalid": "无效",
    }
    updated_at = ""
    if status.updated_at:
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(status.updated_at))
    else:
        updated_at = "未知"
    reason = f"\n  原因: {status.reason}" if status.reason else ""
    path = status.path or "未配置"
    return (
        f"{platform_label(status.platform)}: {state_labels.get(status.state, status.state)}\n"
        f"  来源: {status.source}\n"
        f"  文件: {path}\n"
        f"  更新: {updated_at}{reason}"
    )

async def notify_cookie_auth_failure(client, url, error):
    if not is_cookie_auth_error(error, url):
        return False

    platform = platform_from_url(url)
    if not platform:
        return False

    should_alert = cookie_manager.mark_auth_failure(platform)
    if not should_alert:
        return True

    label = platform_label(platform)
    error_summary = str(error).replace("\n", " ")[:500]
    text = (
        f"⚠️ {label} Cookie 可能已失效。\n\n"
        f"失败链接: {url}\n"
        f"错误摘要: {error_summary}\n\n"
        f"请在私聊中使用 /cookie_upload {platform} 后直接发送新的 cookies.txt 文件。"
    )
    for admin_id in cookie_manager.admin_user_ids:
        try:
            await client.send_message(admin_id, text)
        except Exception as send_error:
            print(f"发送 Cookie 管理提醒失败: {send_error}")
    return True

def build_entry_selection_keyboard(mode, original_msg_id, entry_count):
    rows = [[
        InlineKeyboardButton("全部下载", callback_data=f"pick_{mode}_{original_msg_id}_all")
    ]]

    row = []
    for index in range(1, entry_count + 1):
        row.append(InlineKeyboardButton(f"第 {index} 个", callback_data=f"pick_{mode}_{original_msg_id}_{index}"))
        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return InlineKeyboardMarkup(rows)

async def transcode_to_h264(message, file_path):
    codec = await video_codec(file_path)
    if codec not in ['vp9', 'vp09', 'av1', 'av01']:
        return

    await message.edit_text("⚙️ 检测到不受支持的视频编码 (VP9/AV1)\n正在自动转码为 H.264，这可能需要几分钟，请耐心等待...")

    file_root, _ = os.path.splitext(file_path)
    transcoded_file = f"{file_root}_h264.mp4"
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-i', file_path,
        '-c:v', 'libx264',
        '-preset', 'veryslow',
        '-crf', '22',
        '-c:a', 'aac',
        '-b:a', '320k',
        transcoded_file
    ]

    process = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await process.wait()

    if process.returncode == 0 and os.path.exists(transcoded_file):
        os.replace(transcoded_file, file_path)
    else:
        if os.path.exists(transcoded_file):
            os.remove(transcoded_file)
        raise Exception("FFmpeg 转码过程发生错误。")

async def process_download(client, query, mode, original_msg_id, url, selection, entries=None):
    chat_id = query.message.chat.id
    file_prefix_path = build_file_prefix_path(url, original_msg_id)
    downloaded_paths = []
    dl_task = None

    active_downloads[original_msg_id] = "初始化中..."
    dl_task = asyncio.create_task(update_download_ui(query.message, original_msg_id))

    try:
        video_results = await asyncio.to_thread(
            download_video_sync, url, file_prefix_path, original_msg_id, active_downloads, selection, entries
        )

        active_downloads.pop(original_msg_id, None)
        dl_task.cancel()

        if not video_results:
            raise Exception("yt-dlp 未返回任何下载结果。")

        downloaded_paths = [video_metadata['path'] for video_metadata in video_results]
        total_videos = len(video_results)
        for ordinal, video_metadata in enumerate(video_results, start=1):
            file_path = video_metadata['path']

            if not os.path.exists(file_path):
                raise Exception(f"yt-dlp 下载完成，但硬盘未找到文件: {os.path.basename(file_path)}")

            if mode == 'video':
                await transcode_to_h264(query.message, file_path)

            start_time = time.time()
            item_label = f"{ordinal}/{total_videos}" if total_videos > 1 else ""
            state = {"last_update": 0, "item": item_label}
            caption_suffix = f" ({ordinal}/{total_videos})" if total_videos > 1 else ""

            if mode == 'video':
                await client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    reply_to_message_id=original_msg_id,
                    caption=f"✅ Down! 请查收视频！{caption_suffix}",
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
                    document=file_path,
                    reply_to_message_id=original_msg_id,
                    caption=f"✅ Down! 请查收文件！{caption_suffix}",
                    progress=upload_progress,
                    progress_args=(query.message, start_time, state)
                )

        await query.message.delete()

    except Exception as e:
        active_downloads.pop(original_msg_id, None)
        if dl_task:
            dl_task.cancel()
        cookie_issue = await notify_cookie_auth_failure(client, url, e)
        if cookie_issue:
            await query.message.edit_text("❌ 下载失败：平台登录态可能已失效，请联系管理员更新 Cookie。")
        else:
            await query.message.edit_text(f"❌ 处理失败: {str(e)}")

    finally:
        url_cache.pop(original_msg_id, None)
        entry_cache.pop(original_msg_id, None)
        for file_path in downloaded_paths:
            if os.path.exists(file_path):
                os.remove(file_path)

# --- Cookie 管理命令 ---
@app.on_message(filters.command("cookie_status"))
async def cookie_status_command(client, message):
    if not is_admin_message(message):
        await message.reply_text("❌ 你没有权限使用此命令。")
        return

    statuses = cookie_manager.status()
    text = "🍪 Cookie 状态\n\n" + "\n\n".join(
        format_cookie_status(status) for status in statuses.values()
    )
    await message.reply_text(text)

@app.on_message(filters.command("reload_cookies"))
async def reload_cookies_command(client, message):
    if not is_admin_message(message):
        await message.reply_text("❌ 你没有权限使用此命令。")
        return

    try:
        cookie_manager.reload()
    except Exception as e:
        await message.reply_text(f"❌ 重新加载 Cookie 失败: {str(e)}")
        return

    statuses = cookie_manager.status()
    text = "✅ Cookie 配置已重新加载\n\n" + "\n\n".join(
        format_cookie_status(status) for status in statuses.values()
    )
    await message.reply_text(text)

@app.on_message(filters.command("cookie_upload"))
async def cookie_upload_command(client, message):
    if not is_admin_message(message):
        await message.reply_text("❌ 你没有权限使用此命令。")
        return
    if not is_private_chat(message):
        await message.reply_text("❌ Cookie 文件只能在管理员私聊中上传，请私聊机器人使用此命令。")
        return

    if len(message.command) < 2:
        await message.reply_text("用法: /cookie_upload x 或 /cookie_upload instagram")
        return

    platform = normalize_platform(message.command[1])
    if not platform:
        await message.reply_text("❌ 只支持 x 或 instagram。")
        return

    expires_at = time.time() + cookie_manager.upload_session_ttl
    pending_cookie_uploads[message.from_user.id] = {
        "platform": platform,
        "expires_at": expires_at,
    }
    expires_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))
    await message.reply_text(
        f"🍪 请在 {expires_text} 前直接发送 {platform_label(platform)} 的 Netscape cookies.txt 文件。\n\n"
        "上传必须在当前管理员私聊中完成。"
    )

@app.on_message(filters.document)
async def cookie_document_upload(client, message):
    if not is_admin_message(message):
        return
    if not is_private_chat(message):
        await message.reply_text("❌ Cookie 文件只能在管理员私聊中上传。")
        return

    user_id = message.from_user.id
    pending = pending_cookie_uploads.get(user_id)
    if not pending:
        return
    if pending["expires_at"] < time.time():
        pending_cookie_uploads.pop(user_id, None)
        await message.reply_text("❌ Cookie 上传会话已过期，请重新发送 /cookie_upload x 或 /cookie_upload instagram。")
        return

    document = message.document
    if document.file_size and document.file_size > 2 * 1024 * 1024:
        pending_cookie_uploads.pop(user_id, None)
        await message.reply_text("❌ Cookie 文件超过 2MB，请确认上传的是 Netscape cookies.txt。")
        return

    temp_path = os.path.join(WORK_DIR, f".cookie_upload_{user_id}_{int(time.time())}.txt")
    try:
        downloaded_path = await message.download(file_name=temp_path)
        try:
            await message.delete()
        except Exception:
            pass

        with open(downloaded_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        platform = pending["platform"]
        ok, result = cookie_manager.save_uploaded_cookie(platform, content)
        pending_cookie_uploads.pop(user_id, None)

        if not ok:
            await client.send_message(message.chat.id, f"❌ {platform_label(platform)} Cookie 更新失败: {result}")
            return

        status = cookie_manager.status(platform)
        await client.send_message(
            message.chat.id,
            f"✅ {platform_label(platform)} Cookie 已更新\n\n{format_cookie_status(status)}",
        )
    except Exception as e:
        pending_cookie_uploads.pop(user_id, None)
        await message.reply_text(f"❌ Cookie 上传处理失败: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- 消息拦截与按钮 ---
@app.on_message(filters.text & ~filters.command("start"))
async def handle_message(client, message):
    # 匹配 X 和 Instagram 链接
    url_match = re.search(r'(https?://(?:www\.)?(?:twitter\.com|x\.com|instagram\.com)/[^\s]+)', message.text)
    if not url_match:
        return
        
    raw_url = url_match.group(1)
    
    # 直接截断问号及后面的所有跟踪参数（如 ?s=46 或 ?igsh=...）
    clean_url = raw_url.split('?')[0] 
    
    msg_id = message.id
    url_cache[msg_id] = clean_url  # 存入缓存的是“干净”的链接
    
    reply_text = (
        "👇 **成功解析，请选择接收方式：**\n\n"
        "🎬 **视频模式**：可直接预览或保存到相册（VP9 或 AV1 编码会自动触发转码）。\n"
        "📄 **文件模式**：不会损失画质，不触发转码（不支持的编码需要使用第三方播放器）。"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 视频模式", callback_data=f"video_{msg_id}"),
        ],
        [
            InlineKeyboardButton("📄 文件模式", callback_data=f"doc_{msg_id}")
        ]
    ])
    await message.reply_text(reply_text, reply_markup=keyboard, reply_to_message_id=msg_id)

@app.on_callback_query()
async def button_callback(client, query):
    data = query.data
    parts = data.split('_')

    if parts[0] == 'pick':
        _, mode, msg_id_str, selection = parts
    else:
        mode, msg_id_str = parts
        selection = None

    original_msg_id = int(msg_id_str)
    url = url_cache.get(original_msg_id)
    
    if not url:
        await query.message.edit_text("❌ 链接已过期或丢失，请重新发送。")
        return

    if original_msg_id in processing_callbacks:
        await query.answer("正在处理，请勿重复点击。", show_alert=False)
        return

    processing_callbacks.add(original_msg_id)
    if selection is not None:
        try:
            cached = entry_cache.get(original_msg_id, {})
            await process_download(client, query, mode, original_msg_id, url, selection, cached.get('entries'))
        finally:
            processing_callbacks.discard(original_msg_id)
        return

    if is_instagram_url(url):
        try:
            await process_download(client, query, mode, original_msg_id, url, 'all')
        finally:
            processing_callbacks.discard(original_msg_id)
        return

    try:
        try:
            cached = entry_cache.get(original_msg_id)
            if cached:
                entries = cached['entries']
            else:
                await query.message.edit_text("🔎 正在检测此链接包含的视频数量...")
                entries = await asyncio.to_thread(probe_video_entries, url)
                entry_cache[original_msg_id] = {
                    'url': url,
                    'mode': mode,
                    'entries': entries,
                    'entry_count': len(entries),
                }
        except Exception as e:
            cookie_issue = await notify_cookie_auth_failure(client, url, e)
            if cookie_issue:
                await query.message.edit_text("❌ 解析失败：平台登录态可能已失效，请联系管理员更新 Cookie。")
            else:
                await query.message.edit_text(f"❌ 解析失败: {str(e)}")
            url_cache.pop(original_msg_id, None)
            entry_cache.pop(original_msg_id, None)
            return

        if len(entries) <= 1:
            await process_download(client, query, mode, original_msg_id, url, 'all', entries)
            return

        await query.message.edit_text(
            f"检测到此 Post 包含 {len(entries)} 个视频，请选择下载范围：",
            reply_markup=build_entry_selection_keyboard(mode, original_msg_id, len(entries))
        )
    finally:
        processing_callbacks.discard(original_msg_id)

if __name__ == '__main__':
    print("Main Pyrogram Bot is starting...")
    app.run()
