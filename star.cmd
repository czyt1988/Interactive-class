@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 启动脚本
REM  端口：改下面 APP_PORT，默认 8081
REM  绑定：改下面 APP_HOST
REM        0.0.0.0   = 本机和局域网都能访问（默认）
REM        127.0.0.1 = 只有本机能访问
REM  改完保存，双击本文件即可。已在运行时可双击 restart.cmd。
REM ============================================================
set "APP_PORT=8081"
set "APP_HOST=0.0.0.0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" goto :missing_venv

"%PYTHON%" "%~dp0scripts\launcher.py" start
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

echo.
if "%RC%"=="4" goto :msg_running
if "%RC%"=="3" goto :msg_failed
goto :msg_ended

:msg_running
echo 服务已经在运行。按任意键关闭窗口。
goto :pause_done

:msg_failed
echo 启动失败，请按上面的提示处理后重试。按任意键关闭窗口。
goto :pause_done

:msg_ended
echo 服务已结束。按任意键关闭窗口。

:pause_done
pause >nul
exit /b %RC%

:missing_venv
echo.
echo [错误] 没有找到虚拟环境：.venv\Scripts\python.exe
echo.
echo 请先在项目根目录执行：
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
echo.
pause
exit /b 1
