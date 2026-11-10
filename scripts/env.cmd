@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"

REM ============================================================
REM  AI Learning 环境准备（由 star.cmd / restart.cmd 调用）
REM  已经就绪时什么都不做；缺什么补什么：
REM    虚拟环境 .venv、项目依赖、播放器资源、课程构建、数据库表结构
REM  成功返回 0，失败返回 1；具体原因由 bootstrap.py 打印。
REM ============================================================

if exist "%VENV_PY%" goto :prepare_existing

echo.
echo 首次使用，正在准备运行环境。需要联网，可能要几分钟，只需做一次。
echo.
call :find_python
if not defined SYS_PY goto :no_python
%SYS_PY% "%~dp0bootstrap.py"
if errorlevel 1 exit /b 1
exit /b 0

:prepare_existing
"%VENV_PY%" "%~dp0bootstrap.py" --quiet
if errorlevel 1 exit /b 1
exit /b 0

:no_python
echo.
echo [错误] 没有找到 Python 3.11 或更高版本。
echo.
echo 请先安装 Python：
echo   https://www.python.org/downloads/
echo 安装时勾选 "Add python.exe to PATH"，装好后重新双击 star.cmd。
echo.
exit /b 1

:find_python
REM 依次尝试系统里的 Python，第一个版本不低于 3.11 的胜出。
set "SYS_PY="
call :check_python py -3.13
if defined SYS_PY goto :eof
call :check_python py -3.12
if defined SYS_PY goto :eof
call :check_python py -3.11
if defined SYS_PY goto :eof
call :check_python python
if defined SYS_PY goto :eof
call :check_python python3
if defined SYS_PY goto :eof
call :check_python py -3
goto :eof

:check_python
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 set "SYS_PY=%*"
goto :eof
