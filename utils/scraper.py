import aiohttp
from bs4 import BeautifulSoup
import urllib.parse
import os
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

async def fetch_youtube_lyrics(song_title: str) -> str:
    """利用 YouTube Data API v3 搜尋該首歌的歌詞影片，並擷取影片說明欄作為歌詞"""
    if not YOUTUBE_API_KEY:
        print("未設定 YOUTUBE_API_KEY，跳過 YouTube 歌詞搜尋")
        return None
        
    try:
        async with aiohttp.ClientSession() as session:
            # 1. 搜尋包含 lyrics 的影片
            search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={urllib.parse.quote(song_title + ' lyrics')}&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
            async with session.get(search_url) as resp:
                search_data = await resp.json()
                
            if not search_data.get("items"):
                return None
                
            video_id = search_data["items"][0]["id"]["videoId"]
            
            # 2. 獲取該影片的詳細資訊 (Description)
            video_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_API_KEY}"
            async with session.get(video_url) as resp:
                video_data = await resp.json()
                
            if not video_data.get("items"):
                return None
                
            description = video_data["items"][0]["snippet"]["description"]
            
            # 3. 簡單清理說明欄，過濾掉網址連結，試圖讓它看起來更像純歌詞
            lines = description.split('\n')
            lyric_lines = [line.strip() for line in lines if "http://" not in line and "https://" not in line]
            
            cleaned_lyrics = '\n'.join(lyric_lines).strip()
            
            # 如果清理後的說明欄夠長，假設它含有歌詞
            if len(cleaned_lyrics) > 50:
                return cleaned_lyrics + "\n\n*(此歌詞擷取自 YouTube 影片說明欄)*"
            
            return None
    except Exception as e:
        print(f"YouTube 歌詞抓取失敗: {e}")
        return None

async def fetch_lyrics(song_title: str):
    """利用 DuckDuckGo 簡單爬蟲或 YouTube Data API v3 捕捉歌詞"""
    # 注意：我們使用 bs4 與 aiohttp 來做一個簡單的免 Token 爬蟲，以防沒有 Genius Token
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(song_title + ' lyrics genius')}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')
                
                # 找尋第一個 Genius 的連結
                for a in soup.find_all('a', class_='result__url'):
                    href = a.get('href')
                    if href and 'genius.com' in href:
                        # 找到了！進入該頁面抓歌詞
                        async with session.get(href) as lyric_resp:
                            lyric_html = await lyric_resp.text()
                            lyric_soup = BeautifulSoup(lyric_html, 'html.parser')
                            
                            # Genius 網站結構中，歌詞大多放在這幾個 class 中
                            lyrics_divs = lyric_soup.find_all('div', attrs={'data-lyrics-container': 'true'})
                            if not lyrics_divs:
                                continue # 如果這個 Genius 網頁沒抓到，繼續試

                            # 取出文字，並用 '\n' 取代原本的 <br> 標籤
                            lyrics_text = ""
                            for div in lyrics_divs:
                                # Beautiful Soup 的 get_text 支援自訂分隔符號
                                lyrics_text += div.get_text(separator="\n").strip() + "\n\n"
                            return lyrics_text.strip()
                            
    except Exception as e:
        print(f"抓取歌詞發生錯誤: {e}")
        
    # 如果 Genius 抓不到，改用 YouTube Data API v3
    print("Genius 無法取得歌詞，嘗試使用 YouTube Data API v3...")
    return await fetch_youtube_lyrics(song_title)
