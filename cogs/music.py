import discord
from discord.ext import commands
import asyncio
import os

from utils.ytdl import extract_info, extract_autoplay_info, search_youtube
from utils.audio import ProgressAudioSource, FFMPEG_OPTIONS
from ui.views import MusicPlayerView, SearchResultView
from ui.embeds import build_queue_response
from core.player import GuildPlayer

class MusicCog(commands.Cog, name="音樂功能"):
    def __init__(self, bot):
        self.bot = bot
        # 使用 GuildPlayer 管理每個伺服器的狀態
        self.players = {}
        
    def get_player(self, guild_id):
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer(guild_id)
        return self.players[guild_id]

    async def _send_play_message(self, guild, current_song, progress_source):
        guild_id = guild.id
        player = self.get_player(guild_id)

        print(f"[_send_play_message] Initiated for {current_song.get('title')}, channel: {player.message_channel}")

        if not player.message_channel:
            print("[_send_play_message] No message channel found.")
            return
            
        channel = player.message_channel
        
        # 將秒數轉換為 分:秒
        duration_seconds = current_song.get('duration', 0)
        if duration_seconds:
            mins, secs = divmod(int(duration_seconds), 60)
            duration_str = f"{mins}:{secs:02d}"
        else:
            duration_str = "未知"

        embed = discord.Embed(
            title="🎶 正在播放",
            description=f"**[{current_song['title']}]({current_song['webpage_url']})**\n\n`0:00` 🔘▬▬▬▬▬▬▬▬▬ ` {duration_str} `",
            color=discord.Color.brand_green()
        )
        
        # 新增縮圖 (如果 yt-dlp 有抓到)
        thumbnail = current_song.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        try:
            from ui.views import MusicPlayerView
            view = MusicPlayerView(self, guild_id)
            print("[_send_play_message] Sending message...")
            message = await channel.send(embed=embed, view=view)
            print(f"[_send_play_message] Message sent successfully: {message.id}")

            # 開啟背景任務，每 5 秒動態更新一次進度條
            player.update_task = self.bot.loop.create_task(
                self._update_progress_bar(guild, message, current_song, progress_source)
            )
        except Exception as e:
            print(f"[_send_play_message] Error: {e}")

    async def _update_progress_bar(self, guild, message, current_song, progress_source):
        """背景任務：定期修改訊息內的文字進度條"""
        try:
            total_seconds = current_song.get('duration', 0)
            if not total_seconds:
                return # 若長度未知則不更新進度條
                
            tot_str = f"{int(total_seconds//60)}:{int(total_seconds%60):02d}"
            
            # 使用 getattr 安全地取得 voice_client
            while getattr(guild, 'voice_client', None) and (guild.voice_client.is_playing() or guild.voice_client.is_paused()):
                await asyncio.sleep(5) # 每 5 秒更新一次
                
                if guild.voice_client.is_paused():
                    continue # 暫停時不更新時間
                    
                cur_sec = progress_source.elapsed_seconds
                curr_str = f"{int(cur_sec//60)}:{int(cur_sec%60):02d}"
                
                # 計算進度條 (總長15等分)
                fraction = min(cur_sec / total_seconds, 1.0)
                pos = int(15 * fraction)
                bar = "▬" * pos + "🔘" + "▬" * (15 - pos)
                
                embed = message.embeds[0]
                embed.description = f"**[{current_song['title']}]({current_song['webpage_url']})**\n\n`{curr_str}` {bar} ` {tot_str} `"
                
                await message.edit(embed=embed)
        except asyncio.CancelledError:
            pass # 歌曲結束或被手動切歌時撤銷任務
        except Exception as e:
            print(f"更新進度條失敗: {e}")

    def after_play(self, err, guild):
        """播放完畢後的回呼"""
        if err:
            print(f"播放發生錯誤: {err}")
        
        player = self.get_player(guild.id)
        
        # 撤銷動態更新任務
        if player.update_task:
            player.update_task.cancel()
            
        loop_status = player.loop_mode
        last_song = player.current_song
        
        # 處理循環邏輯
        if last_song and loop_status != 'off':
            if loop_status == 'single':
                # 單曲循環：加回佇列最前方 (因為等一下 play_next 會從最前方 pop)
                player.queue.insert(0, last_song)
            elif loop_status == 'all':
                # 清單循環：加到佇列最後方
                player.queue.append(last_song)
            
        self.bot.loop.call_soon_threadsafe(self.play_next, guild)

    def play_next(self, guild):
        guild_id = guild.id
        voice_client = guild.voice_client
        player = self.get_player(guild_id)

        # 準備播放下一首歌時清空跳過投票
        player.skip_votes.clear()

        if len(player.queue) > 0:
            player.is_playing = True
            current_song = player.queue.pop(0)

            # --- 將現在正在播放的歌存起來，給歌詞功能用 ---
            player.current_song = current_song
            
            # --- 把這首歌記為已播 (防重複) ---
            url = current_song.get('webpage_url') or current_song.get('original_url')
            if url:
                player.played_urls.add(url)

            audio_source = discord.FFmpegPCMAudio(current_song['url'], **FFMPEG_OPTIONS)
            # 包裝一層以計算已播放時間
            progress_source = ProgressAudioSource(audio_source)

            voice_client.play(progress_source, after=lambda e: self.after_play(e, guild))

            # --- 非同步發送播放訊息與控制面板 ---
            # 改用 create_task 取代 run_coroutine_threadsafe，並加入錯誤處理以防萬一
            async def send_task():
                try:
                    await self._send_play_message(guild, current_song, progress_source)
                except Exception as e:
                    print(f"Error in _send_play_message task: {e}")
            
            self.bot.loop.create_task(send_task())

            # 如果開啟自動播放，且後面沒有歌了，就預先抓一首補在清單後面
            if player.autoplay and len(player.queue) == 0:
                asyncio.run_coroutine_threadsafe(self._handle_autoplay(guild), self.bot.loop)
                
        else:
            player.is_playing = False

    async def _handle_autoplay(self, guild):
        """處理自動播放邏輯：尋找下一首關聯歌曲並預先加入隊列"""
        player = self.get_player(guild.id)
        
        # 以隊列最後一首歌或是正在播的歌為基準
        if len(player.queue) > 0:
            ref_song = player.queue[-1]
        else:
            ref_song = player.current_song
            
        if not ref_song:
            return

        current_url = ref_song.get('webpage_url') or ref_song.get('original_url')
        
        info = await extract_autoplay_info(current_url, player.played_urls)

        if info:
            # 處理可能回傳的單筆列表資訊
            song = info['entries'][0] if 'entries' in info else info
            
            url = song.get('webpage_url') or song.get('original_url')
            if url:
                player.played_urls.add(url)
                
            player.queue.append({
                'title': song.get('title'),
                'url': song.get('url'),
                'webpage_url': url,
                'duration': song.get('duration'),
                'thumbnail': song.get('thumbnail')
            })
            
            # 提示已加入推薦歌曲
            if player.message_channel:
                embed = discord.Embed(
                    title="🤖 自動推薦已加入",
                    description=f"**[{song.get('title')}]({url})** 已加入到播放清單末尾！",
                    color=discord.Color.blurple()
                )
                if song.get('thumbnail'):
                    embed.set_thumbnail(url=song.get('thumbnail'))
                await player.message_channel.send(embed=embed)
            
            # 如果發現語音已經停止，就要喚醒播放
            voice_client = guild.voice_client
            if voice_client and not voice_client.is_playing() and not player.is_playing:
                self.bot.loop.call_soon_threadsafe(self.play_next, guild)
        else:
            if player.message_channel:
                embed = discord.Embed(title="❌ 自動播放", description="無法找到不重複的推薦歌曲。", color=discord.Color.red())
                await player.message_channel.send(embed=embed)

    @discord.app_commands.command(name="play", description="播放影片或將歌曲加入待播清單")
    @discord.app_commands.describe(query="輸入 YouTube 連結或想搜尋的歌曲關鍵字")
    async def play(self, interaction: discord.Interaction, query: str):
        """核心播放指令"""
        try:
            await interaction.response.defer() # 延遲回覆，機器人正在思考中（因為 yt-dlp 抓取需要時間）
        except discord.errors.NotFound:
            # 忽略因為網路延遲或機器人剛啟動時導致互動過期 (超過3秒) 的錯誤
            pass

        guild_id = interaction.guild_id
        player = self.get_player(guild_id)

        # 紀錄使用者是在哪個文字頻道下指令的，之後面板要發在那裡
        player.message_channel = interaction.channel

        # 1. 檢查使用者與機器人的語音頻道狀態
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send("❌ **請先加入一個語音頻道！**")

        user_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if not voice_client:
            try:
                voice_client = await user_channel.connect()
            except Exception as e:
                return await interaction.followup.send(f"❌ 無法連接到語音頻道: {e}")
        elif voice_client.channel != user_channel:
            return await interaction.followup.send("❌ **我已經在另一個語音頻道了，請來到我的頻道！**")

        # 2. 解析使用者的查詢
        import re
        is_url = re.match(r'^https?://', query)
        
        if is_url and 'spotify.com' in query:
            from utils.spotify import extract_spotify_queries
            spotify_queries = await extract_spotify_queries(query)
            
            if not spotify_queries:
                return await interaction.followup.send("❌ **無法解析該 Spotify 連結或歌單為空。**")
            
            info = await extract_info(spotify_queries[0])
            if not info:
                return await interaction.followup.send("❌ **無法在 YouTube 找到該 Spotify 音樂。**")
                
            song = info['entries'][0] if 'entries' in info else info
            url = song.get('webpage_url') or song.get('original_url')
            
            player.queue.append({
                'title': song.get('title'),
                'url': song.get('url'),
                'webpage_url': url,
                'duration': song.get('duration'),
                'thumbnail': song.get('thumbnail')
            })
            if url:
                player.played_urls.add(url)
                
            # 提供回應
            embed = discord.Embed(
                title="✅ 已加入佇列", 
                description=f"**[{song.get('title')}]({url})**\n*(Spotify 來源{ '，若為清單其餘歌曲將於背景陸續加入' if len(spotify_queries) > 1 else '' })*", 
                color=discord.Color.green()
            )
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song.get('thumbnail'))
            await interaction.followup.send(embed=embed)
            
            # 從背景繼續解析其他的歌曲
            if len(spotify_queries) > 1:
                async def fetch_background(queries):
                    for q in queries:
                        try:
                            # 加入延遲避免發送過多 YouTube 搜尋導致被列入黑名單
                            await asyncio.sleep(2)
                            bg_info = await extract_info(q)
                            if bg_info:
                                bg_song = bg_info['entries'][0] if 'entries' in bg_info else bg_info
                                bg_url = bg_song.get('webpage_url') or bg_song.get('original_url')
                                player.queue.append({
                                    'title': bg_song.get('title'),
                                    'url': bg_song.get('url'),
                                    'webpage_url': bg_url,
                                    'duration': bg_song.get('duration'),
                                    'thumbnail': bg_song.get('thumbnail')
                                })
                                if bg_url:
                                    player.played_urls.add(bg_url)
                        except Exception as e:
                            print(f"背景解析 Spotify 歌曲失敗 ({q}): {e}")

                # 留下除了第一首以外的放入背景任務
                self.bot.loop.create_task(fetch_background(spotify_queries[1:]))

            # 檢查是否需要啟動播放
            if not player.is_playing and not voice_client.is_playing():
                self.play_next(interaction.guild)
                
            return
        
        if not is_url:
            # 使用快速搜尋，取得前 10 筆結果
            info = await search_youtube(query, limit=10)
            if not info or not info.get('entries'):
                return await interaction.followup.send("❌ **找不到任何搜尋結果，請更換關鍵字。**")
            
            entries = [e for e in info['entries'] if e]
            if len(entries) > 0:
                view = SearchResultView(self, guild_id, entries)
                embed = discord.Embed(
                    title="🔍 搜尋結果",
                    description=f"找到關於 **{query}** 的結果。請使用下方選單選擇您要播放的版本：",
                    color=discord.Color.blurple()
                )
                return await interaction.followup.send(embed=embed, view=view)
        
        # 如果是網址，或剛好只搜到 1 筆等（上面已 return，這裡主要是網址處理）
        info = await extract_info(query)

        if not info:
            return await interaction.followup.send("❌ **找不到該歌曲或解析失敗，請更換關鍵字或網址。**")

        queue = player.queue
        added_songs = []

        # 處理資料結構 (有時回傳列表，有時回傳單一影片)
        if 'entries' in info:
            # 這是播放清單
            for song in info['entries']:
                if song: # 確保有資料
                    url = song.get('webpage_url') or song.get('original_url')
                    queue.append({
                        'title': song.get('title'),
                        'url': song.get('url'),
                        'webpage_url': url,
                        'duration': song.get('duration'),
                        'thumbnail': song.get('thumbnail')
                    })
                    added_songs.append(song)
                    if url:
                        player.played_urls.add(url)
        else:
            # 單一影片
            url = info.get('webpage_url') or info.get('original_url')
            queue.append({
                'title': info.get('title'),
                'url': info.get('url'),
                'webpage_url': url,
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail')
            })
            added_songs.append(info)
            if url:
                player.played_urls.add(url)

        # 3. 回覆訊息並開始播放
        if len(added_songs) == 1:
            song_info = added_songs[0]
            title = song_info.get('title') or "未知標題"
            url = song_info.get('webpage_url') or song_info.get('original_url') or ""
            embed = discord.Embed(title="✅ 已加入佇列", description=f"[{title}]({url})" if url else title, color=discord.Color.green())
            if song_info.get('thumbnail'):
                embed.set_thumbnail(url=song_info.get('thumbnail'))
            await interaction.followup.send(embed=embed)
        elif len(added_songs) > 1:
            embed = discord.Embed(title="✅ 已加入播放清單", description=f"共 **{len(added_songs)}** 首歌曲已加入佇列。", color=discord.Color.green())
            await interaction.followup.send(embed=embed)

        # 檢查是否需要啟動播放 (如果不是正在播放中，就呼叫 play_next)
        if not player.is_playing and not voice_client.is_playing():
            self.play_next(interaction.guild)


    @discord.app_commands.command(name="queue", description="查看目前的待播清單與播放狀態")
    async def queue(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        player = self.get_player(guild_id)
        
        embeds, view = build_queue_response(player)
        
        if view:
            await interaction.response.send_message(embed=embeds[0], view=view)
        else:
            await interaction.response.send_message(embed=embeds[0])

    @discord.app_commands.command(name="loop", description="設定循環播放模式")
    @discord.app_commands.choices(mode=[
        discord.app_commands.Choice(name="關閉 (Off)", value="off"),
        discord.app_commands.Choice(name="單曲循環 (Single)", value="single"),
        discord.app_commands.Choice(name="清單循環 (All)", value="all"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str):
        player = self.get_player(interaction.guild_id)
        player.loop_mode = mode
        mode_text = {"off": "關閉", "single": "🔂 單曲循環", "all": "🔁 清單循環"}[mode]
        embed = discord.Embed(title="🔁 循環設定", description=f"循環模式已設為：**{mode_text}**", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="remove", description="移除待播清單中的指定歌曲")
    @discord.app_commands.describe(index="輸入使用 /queue 查看的歌曲編號")
    async def remove(self, interaction: discord.Interaction, index: int):
        player = self.get_player(interaction.guild_id)
        if 1 <= index <= len(player.queue):
            removed = player.queue.pop(index - 1)
            embed = discord.Embed(title="🗑️ 移除歌曲", description=f"已從隊列中移除：**{removed['title']}**", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="❌ 錯誤", description="無效的歌曲編號。", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="clear", description="清空所有待播歌曲")
    async def clear(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild_id)
        if len(player.queue) > 0:
            player.queue.clear()
            embed = discord.Embed(title="🧹 清空清單", description="**已清空所有待播清單！**", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="ℹ️ 提示", description="隊列已經是空的了。", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="leave", description="使機器人離開語音頻道並清空清單")
    async def leave(self, interaction: discord.Interaction):
        """離開語音頻道指令"""
        voice_client = interaction.guild.voice_client

        if voice_client is not None:
            player = self.get_player(interaction.guild_id)
            player.clear() # 利用建立好的 clear 方法一次清空狀態

            await voice_client.disconnect()
            embed = discord.Embed(title="👋 離開頻道", description="**已停止播放，並離開語音頻道。**", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="❌ 錯誤", description="**我目前不在任何語音頻道。**", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
