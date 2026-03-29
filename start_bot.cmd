@echo off
echo 正在啟用虛擬環境 (venv)...
call venv\Scripts\activate.bat

:: 啟動機器人
echo.
echo 正在啟動機器人 (python bot.py)...
echo --------------------------------------------------
python bot.py

:: 如果機器人關閉或遇到錯誤，暫停以顯示錯誤訊息
echo --------------------------------------------------
echo 機器人已成功關閉或遇到錯誤中止。
pause
