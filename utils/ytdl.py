import yt_dlp
import asyncio
import os

# yt-dlp 的抓取設定 (最佳音質、不下載影片、過濾廣告)
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False, # 允許解析播放清單 (後續處理)
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch', # 若輸入不是網址，預設在 YouTube 搜尋
    # 移除或更改 player_client，避免雲端主機觸發 YouTube Bot 防護 (Android client 常造成 format not available)
    'extractor_args': {'youtube': {'player_client': ['web']}},
}

# 判斷如果有匯出 cookies，就使用它來繞過 YouTube 官方的 Bot 機器人驗證 (特別是在雲端伺服器上)
if os.path.exists('cookies.txt'):
    YTDL_OPTIONS['cookiefile'] = 'cookies.txt'

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

async def extract_info(query: str):
    """非同步執行 yt-dlp 解析，避免阻塞機器人"""
    loop = asyncio.get_event_loop()
    try:
        # extract_info 如果 URL 不是清單但 noplaylist=False，可能回傳 playlist 格式（單一影片的 list）
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        return data
    except Exception as e:
        print(f"yt-dlp 解析失敗: {e}")
        return None

async def search_youtube(query: str, limit: int = 10):
    """快速搜尋 YouTube 取得候選單，不解析真實音訊網址 (extract_flat=True)"""
    loop = asyncio.get_event_loop()
    try:
        opts = YTDL_OPTIONS.copy()
        opts['extract_flat'] = True
        
        with yt_dlp.YoutubeDL(opts) as ytdl_search:
            data = await loop.run_in_executor(None, lambda: ytdl_search.extract_info(f"ytsearch{limit}:{query}", download=False))
            return data
    except Exception as e:
        print(f"yt-dlp 快速搜尋失敗: {e}")
        return None

async def extract_autoplay_info(current_url: str, played_urls: set = None):
    """取得 YouTube Mix 推薦的下一首歌"""
    if played_urls is None:
        played_urls = set()

    loop = asyncio.get_event_loop()
    try:
        # 只支援 YouTube 網址
        if current_url and ('youtube.com' in current_url or 'youtu.be' in current_url):
            video_id = None
            if 'v=' in current_url:
                video_id = current_url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in current_url:
                video_id = current_url.split('youtu.be/')[1].split('?')[0]
            
            if video_id:
                mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
                # 快速取得播放清單內的項目
                opts = YTDL_OPTIONS.copy()
                opts['playlistend'] = 25  # 多抓幾首以便過濾
                opts['extract_flat'] = 'in_playlist'
                
                with yt_dlp.YoutubeDL(opts) as ytdl_auto:
                    data = await loop.run_in_executor(None, lambda: ytdl_auto.extract_info(mix_url, download=False))
                    if 'entries' in data:
                        for entry in data['entries']:
                            if not entry:
                                continue
                            next_id = entry.get('url') or entry.get('id')
                            if not next_id:
                                continue
                            play_url = f"https://www.youtube.com/watch?v={next_id}" if len(next_id) == 11 else next_id

                            # 如果 URL 還沒被播過
                            if play_url not in played_urls and play_url != current_url:
                                return await extract_info(play_url)
    except Exception as e:
        print(f"自動播放擷取失敗: {e}")
    return None
