@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  AI Learning 构建脚本
REM  改完课程、设计令牌、站点代码或数据库迁移后，双击本文件重建整个项目，
REM  完成后再双击 start.cmd，看到的就是最新版本。
REM  构建内容：后端导入检查、运行时/字体/令牌同步、数据库迁移、全部课程包。
REM  环境缺失时会先调用 scripts\env.cmd 自动准备，所以第一次也能直接用。
REM ============================================================

call "%~dp0scripts\env.cmd"
if errorlevel 1 goto :prepare_failed

set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" "%~dp0scripts\build.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto :build_done

echo 构建没有完成：请按上面的提示处理后重新双击 build.cmd。
echo 按任意键关闭本窗口。
pause >nul
exit /b %RC%

:build_done
echo 构建完成：现在双击 start.cmd 启动最新版本；站点正在运行时双击 restart.cmd。
echo 按任意键关闭本窗口。
pause >nul
exit /b 0

:prepare_failed
echo.
echo 环境准备没有完成：请按上面的提示处理后重新双击 build.cmd。
echo.
pause
exit /b 1
