@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 重启脚本
REM  先停掉正在运行的服务，再按 start.cmd 的配置重新启动。
REM  APP_PORT / APP_HOST 在 start.cmd 开头修改。
REM ============================================================

call "%~dp0scripts\env.cmd"
if errorlevel 1 goto :prepare_failed

set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" "%~dp0scripts\launcher.py" restart
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

echo.
if "%RC%"=="4" goto :msg_running
if "%RC%"=="3" goto :msg_failed
goto :msg_ended

:msg_running
echo 重启没有完成，旧服务可能还在运行中。可以关闭本窗口。
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
echo 环境准备没有完成，请按上面的提示处理后重新双击 restart.cmd。
echo.
pause
exit /b 1
