@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 启动脚本
REM  双击即可启动。第一次会自动准备运行环境（需要联网），之后直接打开。
REM  端口：改下面的 APP_PORT，默认 8081
REM  绑定：改下面的 APP_HOST
REM        0.0.0.0   = 本机和局域网都能访问（默认）
REM        127.0.0.1 = 只有本机能访问
REM  改完端口后用 restart.cmd 重启；停止服务用 stop.cmd。
REM ============================================================
set "APP_PORT=8081"
set "APP_HOST=0.0.0.0"

call "%~dp0scripts\env.cmd"
if errorlevel 1 goto :prepare_failed

set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" "%~dp0scripts\launcher.py" start
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

echo.
if "%RC%"=="4" goto :msg_running
if "%RC%"=="3" goto :msg_failed
goto :msg_ended

:msg_running
echo 服务已经在运行中。可以关闭本窗口。
goto :pause_done

:msg_failed
echo 启动失败，请按上面的提示处理后重试。按任意键关闭窗口。
goto :pause_done

:msg_ended
echo 服务已结束。按任意键关闭窗口。

:pause_done
pause >nul
exit /b %RC%

:prepare_failed
echo.
echo 环境准备没有完成，请按上面的提示处理后重新双击 start.cmd。
echo.
pause
exit /b 1
