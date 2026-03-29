class GuildPlayer:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        # 待播放的音樂佇列
        self.queue = []
        # 是否正在播放
        self.is_playing = False
        # 目前正在播放的歌曲資訊
        self.current_song = None
        # 用來發送播放訊息的文字頻道
        self.message_channel = None
        # 動態更新進度條的非同步任務
        self.update_task = None
        # 循環模式: 'off', 'single', 'all'
        self.loop_mode = 'off'
        # 投票跳過的名單
        self.skip_votes = set()
        # 是否開啟自動播放
        self.autoplay = False
        # 紀錄已播放或已排入隊列的歌曲 URL，用於自動播放防止重複
        self.played_urls = set()

    def clear(self):
        """清空狀態"""
        self.queue.clear()
        self.is_playing = False
        self.current_song = None
        if self.update_task:
            self.update_task.cancel()
            self.update_task = None
        self.loop_mode = 'off'
        self.skip_votes.clear()
        self.played_urls.clear()
