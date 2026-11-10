@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 停止脚本
REM  停止 star.cmd 启动的服务（运行记录在 .run\service.json）。
REM ============================================================

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" goto :not_initialized

"%PYTHON%" "%~dp0scripts\launcher.py" stop
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto :msg_done

echo 停止失败，请按上面的提示处理后重试。按任意键关闭窗口。
goto :pause_done

:msg_done
echo 已处理完毕。按任意键关闭窗口。

:pause_done
pause >nul
exit /b %RC%

:not_initialized
echo.
echo 服务没有在运行：这台电脑上还没有创建虚拟环境 .venv。
echo 直接双击 star.cmd 开始使用即可，它会自动完成环境准备。
echo.
pause
exit /b 0
