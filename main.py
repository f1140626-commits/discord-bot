import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# 載入環境變數 (.env)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 設定機器人的權限 (Intents)
intents = discord.Intents.default()
# 啟動語音狀態權限，以偵測使用者是否在語音頻道
intents.voice_states = True    
# 收發訊息權限
intents.message_content = True 

class MusicBot(commands.Bot):
    def __init__(self):
        # 由於我們只使用斜線指令，這裡的前綴隨意設定甚至設為 None 無妨，這裡設為提及機器人
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None # 移除傳統的 help 指令
        )

    async def setup_hook(self):
        """bot 啟動前的設定：載入 cogs 並同步斜線指令"""
        # 確保 cogs 資料夾存在
        if not os.path.exists('./cogs'):
            os.makedirs('./cogs')

        # 讀取 /cogs 資料夾底下的所有 .py 檔案
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('__'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"📦 已載入模組: {filename}")
                except Exception as e:
                    print(f"⚠️ 無法載入模組 {filename}: {e}")

        # 將斜線指令同步至 Discord 伺服器
        try:
            synced = await self.tree.sync()
            print(f"🔄 成功同步了 {len(synced)} 個全域斜線指令。")
        except Exception as e:
            print(f"❌ 同步斜線指令時發生錯誤: {e}")

bot = MusicBot()

@bot.event
async def on_ready():
    """當機器人啟動並準備就緒時觸發的事件"""
    print(f'✅ 機器人 {bot.user} 已成功登入！')
    
    # 設定機器人的狀態與活動 (正在聽 /play)
    activity = discord.Activity(type=discord.ActivityType.listening, name="/play 音樂")
    await bot.change_presence(status=discord.Status.online, activity=activity)

if __name__ == "__main__":
    if not TOKEN or TOKEN == "your_discord_bot_token_here":
        print("❌ 錯誤: 找不到 DISCORD_TOKEN，請確認是否已設定 .env 檔案並填入正確的 Token。")
    else:
        bot.run(TOKEN)
