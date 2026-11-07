@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 重启脚本
REM  会先停掉正在运行的服务，再按 star.cmd 开头的
REM  APP_PORT / APP_HOST 重新启动。
REM  端口不在这里改，改 star.cmd。
REM ============================================================

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" goto :missing_venv

"%PYTHON%" "%~dp0scripts\launcher.py" restart
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

echo.
if "%RC%"=="4" goto :msg_running
if "%RC%"=="3" goto :msg_failed
goto :msg_ended

:msg_running
echo 重启没有完成，服务仍在运行。按任意键关闭窗口。
goto :pause_done

:msg_failed
echo 重启失败，请按上面的提示处理后重试。按任意键关闭窗口。
goto :pause_done

:msg_ended
echo 重启未完成，服务可能已停止。按任意键关闭窗口。

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
