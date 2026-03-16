# x_downloader.py
import os
import re
import yaml
import yt_dlp

# --- 读取配置 ---
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

WORK_DIR = config['SYSTEM'].get('WORK_DIR','./')
COOKIE_PATH = os.path.join(WORK_DIR, config['SYSTEM'].get('COOKIE_FILE','cookies.txt'))

def download_video_sync(url: str, file_prefix_path: str, msg_id: int, active_downloads: dict):
    """
    独立的视频下载模块
    """
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0.0%')
            speed = d.get('_speed_str', '0B/s')
            eta = d.get('_eta_str', '未知')
            
            percent = re.sub(r'\x1b\[[0-9;]*m', '', percent).strip()
            speed = re.sub(r'\x1b\[[0-9;]*m', '', speed).strip()
            eta = re.sub(r'\x1b\[[0-9;]*m', '', eta).strip()
            
            active_downloads[msg_id] = f"{percent} | {speed} | 剩余: {eta}"

    ydl_opts = {
        'outtmpl': f"{file_prefix_path}.%(ext)s", 
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH, 
        'progress_hooks': [progress_hook],
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        if 'entries' in info and len(info['entries']) > 0:
            video_info = info['entries'][0]
        else:
            video_info = info

        return {
            'width': int(video_info.get('width') or 0),
            'height': int(video_info.get('height') or 0),
            'duration': int(video_info.get('duration') or 0)
        }
