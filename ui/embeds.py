import discord
from ui.views import QueuePaginationView

def build_queue_response(player):
    """根據 player 狀態，建立播放清單的 embeds 與 view"""
    current_song = player.current_song
    mq = player.queue

    if not current_song and len(mq) == 0:
        embed = discord.Embed(title="📜 目前播放佇列", description="📭 目前沒有正在播放的音樂，佇列也是空的！", color=discord.Color.blue())
        return [embed], None

    # 計算總時間
    total_seconds = sum(song.get('duration', 0) for song in mq)
    total_mins, total_secs = divmod(int(total_seconds), 60)
    total_hours, total_mins = divmod(total_mins, 60)
    duration_str = f"{total_hours:02d}:{total_mins:02d}:{total_secs:02d}" if total_hours > 0 else f"{total_mins:02d}:{total_secs:02d}"

    # 目前播放資訊
    now_playing_text = ""
    if current_song:
        now_playing_text = f"**▶️ 正在播放:** [{current_song.get('title')}]({current_song.get('webpage_url', '')})\n"
        now_playing_text += f"---\n\n"

    songs_per_page = 10
    embeds = []
    
    # 若完全沒有接下來的歌
    if len(mq) == 0:
        embed = discord.Embed(title="📜 目前播放佇列", description=now_playing_text + "沒有接下來的歌曲了。", color=discord.Color.blue())
        loop_mode_str = {'off': '關閉', 'single': '🔂 單曲', 'all': '🔁 清單'}.get(player.loop_mode, '關閉')
        embed.set_footer(text=f"循環模式: {loop_mode_str}")
        embeds.append(embed)
    else:
        total_pages = (len(mq) - 1) // songs_per_page + 1
        for i in range(total_pages):
            start_idx = i * songs_per_page
            end_idx = start_idx + songs_per_page
            page_songs = mq[start_idx:end_idx]

            queue_list = ""
            for idx, song in enumerate(page_songs):
                s_min, s_sec = divmod(int(song.get('duration', 0)), 60)
                queue_list += f"`{start_idx + idx + 1}.` [{song['title']}]({song.get('webpage_url', '')}) `({s_min}:{s_sec:02d})`\n"

            description = f"{now_playing_text}**即將播放:**\n{queue_list}\n"
            embed = discord.Embed(
                title=f"📜 目前播放佇列 (第 {i+1}/{total_pages} 頁)", 
                description=description, 
                color=discord.Color.blue()
            )
            
            loop_mode_str = {'off': '關閉', 'single': '🔂 單曲', 'all': '🔁 清單'}.get(player.loop_mode, '關閉')
            embed.set_footer(text=f"共 {len(mq)} 首歌 | 總長: {duration_str} | 循環模式: {loop_mode_str}")
            embeds.append(embed)

    view = QueuePaginationView(embeds) if len(embeds) > 1 else None
    return embeds, view
