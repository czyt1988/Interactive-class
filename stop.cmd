@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 停止脚本
REM  结束 star.cmd 启动的服务。运行记录在 .run\service.json。
REM ============================================================

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" goto :missing_venv

"%PYTHON%" "%~dp0scripts\launcher.py" stop
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto :msg_done

echo 停止失败，请按上面的提示处理。按任意键关闭窗口。
goto :pause_done

:msg_done
echo 已处理完毕。按任意键关闭窗口。

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
