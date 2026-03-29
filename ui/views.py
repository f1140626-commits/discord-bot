import discord
import re
import math
from utils.scraper import fetch_lyrics
# 為了避免互相 importing 的問題，在函數內引入或是利用動態引入
# 不過 ui.embeds 需要 QueuePaginationView，這裡不互相匯入會比較安全

# --- 定義控制面板 UI (Buttons) ---
class SearchResultSelect(discord.ui.Select):
    def __init__(self, cog, guild_id, results):
        self.cog = cog
        self.guild_id = guild_id
        self.results = results # list of song dicts
        
        options = []
        for i, song in enumerate(results[:10]):
            title = song.get('title', '未知標題')
            if len(title) > 90:
                title = title[:87] + "..."
            
            duration = song.get('duration', 0)
            if duration:
                mins, secs = divmod(int(duration), 60)
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = "未知長度"
                
            channel = song.get('uploader', '未知頻道')
            if len(channel) > 40:
                channel = channel[:37] + "..."
                
            desc = f"⏱️ {dur_str} | 📺 {channel}"
            
            options.append(discord.SelectOption(
                label=title,
                description=desc,
                value=str(i),
                emoji="🎵"
            ))
            
        super().__init__(placeholder="請選擇一首歌曲來播放...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        selected_index = int(self.values[0])
        song_flat = self.results[selected_index]
        
        url_target = song_flat.get('url') or song_flat.get('webpage_url')
        if not url_target.startswith('http'):
            url_target = f"https://www.youtube.com/watch?v={url_target}"

        # 這裡的 url 尚未被解析成可用於 ffmpeg 的 stream url，我們需要解析一次
        from utils.ytdl import extract_info
        song = await extract_info(url_target)
        
        if not song:
            embed = discord.Embed(title="❌ 解析失敗", description="無法解析該影片，請重新搜尋！", color=discord.Color.red())
            return await interaction.edit_original_response(embed=embed, view=None)

        player = self.cog.get_player(self.guild_id)
        queue = player.queue
        
        url = song.get('webpage_url') or song.get('original_url') or song.get('url')
        
        queue.append({
            'title': song.get('title'),
            'url': song.get('url'),
            'webpage_url': url,
            'duration': song.get('duration'),
            'thumbnail': song.get('thumbnail')
        })
        
        if url:
            player.played_urls.add(url)
            
        embed = discord.Embed(
            title="✅ 已加入佇列", 
            description=f"**[{song.get('title')}]({url})**", 
            color=discord.Color.green()
        )
        if song.get('thumbnail'):
            embed.set_thumbnail(url=song.get('thumbnail'))
            
        # 替換掉原本的選擇選單，顯示已選結果
        await interaction.edit_original_response(embed=embed, view=None)
        
        voice_client = interaction.guild.voice_client
        if not player.is_playing and voice_client and not voice_client.is_playing():
            self.cog.play_next(interaction.guild)

class SearchResultView(discord.ui.View):
    def __init__(self, cog, guild_id, results):
        super().__init__(timeout=60)
        self.add_item(SearchResultSelect(cog, guild_id, results))

class MusicPlayerView(discord.ui.View):
    def __init__(self, cog, guild_id):
        # timeout=None 讓按鈕永久有效，直到我們主動移除
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    # 當沒有 DJ 權限時，要判斷是否發起投票 (未來實作，目前簡單版先直接跳過)
    async def check_permissions(self, interaction: discord.Interaction) -> bool:
        # 這裡未來可以加入權限判斷 (例如需有 DJ 身份組或是投票系統)
        return True

    @discord.ui.button(label="暫停 / 播放", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            embed = discord.Embed(title="❌ 錯誤", description="機器人不在語音頻道中。", color=discord.Color.red())
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if voice_client.is_paused():
            voice_client.resume()
            embed = discord.Embed(title="▶️ 繼續播放", description="音樂已繼續播放！", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif voice_client.is_playing():
            voice_client.pause()
            embed = discord.Embed(title="⏸️ 暫停播放", description="音樂已暫停！", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title="❌ 狀態錯誤", description="目前沒有音樂正在播放。", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="跳過 (Skip)", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(title="❌ 錯誤", description="目前沒有音樂可以跳過。", color=discord.Color.red())
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        player = self.cog.get_player(self.guild_id)

        # 判斷是否擁有 "DJ" 身分組，或是具有管理員權限
        is_dj = any(role.name.lower() == 'dj' for role in interaction.user.roles) or interaction.user.guild_permissions.manage_channels
        
        if is_dj:
            # 停止當前音樂，就會自動觸發 after 的 play_next 邏輯
            voice_client.stop()
            embed = discord.Embed(title="⏭️ 強制跳過", description=f"DJ {interaction.user.mention} 強制跳過了目前歌曲！", color=discord.Color.gold())
            await interaction.response.send_message(embed=embed)
        else:
            # 一般使用者，發起投票跳過 (1/3 同意)
            channel = voice_client.channel
            # 計算該頻道內的非機器人使用者數量
            members = [m for m in channel.members if not m.bot]
            # 至少需要 1 票，然後以人數的三分之一無條件進位 (例: 1~3人=1票, 4~6人=2票)
            required_votes = max(1, math.ceil(len(members) / 3))

            if interaction.user.id in player.skip_votes:
                embed = discord.Embed(title="🗳️ 投票跳過", description="你已經投過跳過票了喔！", color=discord.Color.orange())
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            player.skip_votes.add(interaction.user.id)
            current_votes = len(player.skip_votes)

            if current_votes >= required_votes:
                voice_client.stop()
                embed = discord.Embed(title="⏭️ 投票通過", description=f"({current_votes}/{required_votes})！已跳過歌曲。", color=discord.Color.green())
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(title="🗳️ 投票跳過", description=f"{interaction.user.mention} 投票跳過歌曲 ({current_votes}/{required_votes} 票)。", color=discord.Color.blurple())
                await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="停止 (Stop)", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client:
            # 清空該伺服器的隊列並停止
            player = self.cog.get_player(self.guild_id)
            player.queue.clear()
            voice_client.stop()
            embed = discord.Embed(title="⏹️ 停止播放", description="音樂已停止，隊列已清空。", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="❌ 錯誤", description="目前沒有在播放音樂。", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="顯示歌詞", style=discord.ButtonStyle.success, emoji="📜")
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) # 先延遲回覆，避免抓歌詞太久導致超時報錯

        player = self.cog.get_player(self.guild_id)
        current_song = player.current_song

        if not current_song:
            embed = discord.Embed(title="❌ 錯誤", description="找不到目前播放的歌曲資訊。", color=discord.Color.red())
            return await interaction.followup.send(embed=embed, ephemeral=True)

        title = current_song.get('title')

        # 簡單過濾掉標題中常見的 YouTube 雜訊 (如 "Official Video", "Lyric Video") 以提高歌詞命中率
        search_title = re.sub(r'\(.*?\)|\[.*?\]|【.*?】|Official Video|Lyrics?|MV', '', title, flags=re.IGNORECASE).strip()

        # 這裡我們使用 genius 的輕量爬蟲，若有 Genius API Token 可以設定
        # (為求穩定，此處我們撰寫一個 async func 在 utils.scraper 內)
        lyrics = await fetch_lyrics(search_title)

        if not lyrics:
            embed = discord.Embed(
                title="❌ 找不到歌詞", 
                description=f"很抱歉，透過 Genius 和 YouTube Data API 都找不到 **{search_title}** 的歌詞。", 
                color=discord.Color.red()
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Discord 限制 Embed description 最大 4096 字元，若過長需切分
        if len(lyrics) > 4000:
            lyrics = lyrics[:4000] + "\n...(歌詞過長遭截斷)..."

        embed = discord.Embed(title=f"📜 {search_title} 歌詞", description=lyrics, color=discord.Color.gold())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="循環模式", style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.cog.get_player(self.guild_id)
        if player.loop_mode == 'off':
            player.loop_mode = 'single'
            mode_text = "🔂 單曲循環"
        elif player.loop_mode == 'single':
            player.loop_mode = 'all'
            mode_text = "🔁 清單循環"
        else:
            player.loop_mode = 'off'
            mode_text = "關閉"
        
        embed = discord.Embed(title="🔁 循環模式", description=f"循環模式已切換為：**{mode_text}**", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="自動播放", style=discord.ButtonStyle.secondary, emoji="🤖", row=1)
    async def autoplay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.cog.get_player(self.guild_id)
        player.autoplay = not player.autoplay
        state_text = "開啟" if player.autoplay else "關閉"
        
        embed = discord.Embed(title="🤖 自動播放", description=f"自動播放已**{state_text}**！", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # 如果開啟，且目前播放清單為空，直接去找一首
        if player.autoplay and len(player.queue) == 0:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.cog._handle_autoplay(interaction.guild), self.cog.bot.loop)

    @discord.ui.button(label="播放清單", style=discord.ButtonStyle.secondary, emoji="📜", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from ui.embeds import build_queue_response
        player = self.cog.get_player(self.guild_id)
        
        embeds, view = build_queue_response(player)
        
        if view:
            await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embeds[0], ephemeral=True)


class QueuePaginationView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.primary, emoji="◀️", disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.primary, emoji="▶️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
