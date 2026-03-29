import discord

# FFmpeg 播放設定 (在 Discord 播放前重新連接避免斷線)
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# --- 讀取音訊串流的包裝器 (用來追蹤時間進度) ---
class ProgressAudioSource(discord.AudioSource):
    def __init__(self, original_source):
        self.original = original_source
        self.frames_read = 0
            
    def read(self):
        ret = self.original.read()
        if ret:
            # 每讀取一個 frame 代表 20 毫秒
            self.frames_read += 1
        return ret
            
    def cleanup(self):
        self.original.cleanup()
            
    @property
    def elapsed_seconds(self):
        return self.frames_read * 0.02
