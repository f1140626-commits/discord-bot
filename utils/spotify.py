import asyncio
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv
import re
import aiohttp

load_dotenv()

# 初始化 Spotify 用戶端
# 請在 .env 檔案中加入 SPOTIPY_CLIENT_ID 和 SPOTIPY_CLIENT_SECRET
client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")

sp = None
if client_id and client_secret and len(client_id) > 10:
    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    sp = spotipy.Spotify(auth_manager=auth_manager)
else:
    print("提示: 未偵測到有效的 SPOTIPY 金鑰，將直接使用網頁爬蟲模式處理 Spotify 網址。")

def _fetch_spotify_api_data(url: str) -> list:
    """使用 spotipy 查詢函數"""
    queries = []
    if '/track/' in url:
        track = sp.track(url)
        queries.append(f"{track['name']} {track['artists'][0]['name']}")    
    elif '/playlist/' in url:
        results = sp.playlist_items(url, limit=30)
        for item in results.get('items', []):
            track = item.get('track')
            if track:
                queries.append(f"{track['name']} {track['artists'][0]['name']}")
    elif '/album/' in url:
        results = sp.album_tracks(url, limit=30)
        for track in results.get('items', []):
            queries.append(f"{track['name']} {track['artists'][0]['name']}")
    return queries

async def _fetch_spotify_html(url: str) -> str:
    """備用方法：直接爬取 Spotify 網頁"""
    async with aiohttp.ClientSession() as session:
        # Disable SSL verification in case of strict local network
        async with session.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, ssl=False) as response:
            if response.status == 200:
                return await response.text()
            return ""

async def _fetch_spotify_scrape_data(url: str) -> list:
    """自動備援的網頁爬取邏輯"""
    html = await _fetch_spotify_html(url)
    if not html:
        return []

    queries = []
    if '/track/' in url:
        title_match = re.search(r'<meta property="og:title" content="(.*?)"', html)
        desc_match = re.search(r'<meta property="og:description" content="(.*?)"', html)
        if title_match and desc_match:
            title = title_match.group(1).replace('&#39;', "'").replace('&amp;', '&').replace('&quot;', '"')
            desc = desc_match.group(1).replace('&#39;', "'").replace('&amp;', '&').replace('&quot;', '"')
            artist = desc.split('')[0].strip()
            queries.append(f"{title} {artist}")

    elif '/playlist/' in url or '/album/' in url:
        track_urls = re.findall(r'<meta name="music:song" content="(.*?)"', html)
        track_urls = track_urls[:30]

        async def fetch_track_query(t_url):
            try:
                t_html = await _fetch_spotify_html(t_url)
                t_match = re.search(r'<meta property="og:title" content="(.*?)"', t_html)
                d_match = re.search(r'<meta property="og:description" content="(.*?)"', t_html)
                if t_match and d_match:
                    t_title = t_match.group(1).replace('&#39;', "'").replace('&amp;', '&').replace('&quot;', '"')
                    t_desc = d_match.group(1).replace('&#39;', "'").replace('&amp;', '&').replace('&quot;', '"')
                    t_artist = t_desc.split('')[0].strip()
                    return f"{t_title} {t_artist}"
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[fetch_track_query(u) for u in track_urls])
        for r in results:
            if r:
                queries.append(r)
    return queries

async def extract_spotify_queries(url: str) -> list:
    """
    解析 Spotify 網址，優先使用官方 API，若無金鑰或遇到 403 權限問題自動切換為免金鑰網頁爬蟲。
    """
    # 嘗試使用 API (如果有設定金鑰)
    if sp:
        try:
            loop = asyncio.get_event_loop()
            queries = await loop.run_in_executor(None, _fetch_spotify_api_data, url)
            if queries:
                return queries
        except spotipy.SpotifyException as e:
            print(f"[Spotify] API 回傳錯誤 ({e.http_status}): {e.msg}")
            print("[Spotify] 將自動回退(Fallback)至免金鑰網頁爬蟲模式處理...")
        except Exception as e:
            print(f"[Spotify] API 發生預期外錯誤: {e}")
            print("[Spotify] 將自動回退(Fallback)至免金鑰網頁爬蟲模式處理...")
            
    # 沒有設定 sp 或 API 報錯時，執行備用網頁爬蟲邏輯
    print(f"[Spotify] 正在使用網頁爬蟲解析: {url}")
    return await _fetch_spotify_scrape_data(url)
    return await _fetch_spotify_scrape_data(url)
