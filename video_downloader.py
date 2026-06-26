# x_downloader.py
import os
import re
import yaml
import yt_dlp

from cookie_manager import get_ydl_cookie_opts

# --- 读取配置 ---
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

WORK_DIR = config['SYSTEM'].get('WORK_DIR','./')

def _is_instagram_url(url):
    return 'instagram.com' in url

def _clean_ansi(value):
    return re.sub(r'\x1b\[[0-9;]*m', '', value or '').strip()

def _video_metadata(video_info, file_path, index=1):
    return {
        'path': file_path,
        'index': index,
        'width': int(video_info.get('width') or 0),
        'height': int(video_info.get('height') or 0),
        'duration': int(video_info.get('duration') or 0)
    }

def probe_video_entries(url: str):
    """
    探测链接内包含的视频条目数量，不下载文件。
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    ydl_opts.update(get_ydl_cookie_opts(url))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = [entry for entry in info.get('entries', []) if entry] if isinstance(info, dict) else []
    if not entries:
        entries = [info]

    return [
        {
            'index': index,
            'width': int((entry or {}).get('width') or 0),
            'height': int((entry or {}).get('height') or 0),
            'duration': int((entry or {}).get('duration') or 0)
        }
        for index, entry in enumerate(entries, start=1)
    ]

def download_video_sync(url: str, file_prefix_path: str, msg_id: int, active_downloads: dict, selection='all', known_entries=None):
    """
    独立的视频下载模块
    """
    selected_indexes = None
    if selection != 'all':
        selected_indexes = [int(selection)]

    if known_entries:
        probe_entries = known_entries
    elif _is_instagram_url(url):
        probe_entries = [{'index': 1, 'width': 0, 'height': 0, 'duration': 0}]
    else:
        probe_entries = probe_video_entries(url)
    total_count = len(probe_entries)
    if selected_indexes is None:
        selected_indexes = [entry['index'] for entry in probe_entries]

    downloaded_videos = []

    def download_one(entry_index, ordinal, total_selected):
        if total_count == 1:
            output_prefix = file_prefix_path
        else:
            output_prefix = f"{file_prefix_path}_{entry_index:03d}"

        expected_file_name = f"{output_prefix}.mp4"

        def progress_hook(d):
            if d['status'] == 'downloading':
                percent = _clean_ansi(d.get('_percent_str', '0.0%'))
                speed = _clean_ansi(d.get('_speed_str', '0B/s'))
                eta = _clean_ansi(d.get('_eta_str', '未知'))

                if total_selected > 1:
                    prefix = f"第 {ordinal}/{total_selected} 个 "
                else:
                    prefix = ""

                active_downloads[msg_id] = f"{prefix}{percent} | {speed} | 剩余: {eta}"

        ydl_opts = {
            'outtmpl': f"{output_prefix}.%(ext)s",
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [progress_hook],
        }
        ydl_opts.update(get_ydl_cookie_opts(url))

        if total_count > 1:
            ydl_opts['playlist_items'] = str(entry_index)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        entries = [entry for entry in info.get('entries', []) if entry] if isinstance(info, dict) else []
        video_info = entries[0] if entries else info

        return _video_metadata(video_info, expected_file_name, entry_index)

    for ordinal, entry_index in enumerate(selected_indexes, start=1):
        active_downloads[msg_id] = f"准备下载第 {ordinal}/{len(selected_indexes)} 个..."
        downloaded_videos.append(download_one(entry_index, ordinal, len(selected_indexes)))

    return downloaded_videos
