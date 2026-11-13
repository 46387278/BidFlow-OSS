@echo off
chcp 936 >nul
cd /d "%~dp0"

rem 不能用 where python 判断。Win10/11 自带一个 WindowsApps\python.exe 占位别名，
rem where 会返回"找到"，但一执行就报"系统找不到文件"。必须真的跑一次才算数。
rem 同时试 py -3：有些机器只装了 py 启动器，python 不在 PATH 上。
set PYOK=0
set PYEXE=python
python -V >nul 2>nul
if not errorlevel 1 goto :py_found
py -3 -V >nul 2>nul
if not errorlevel 1 goto :py_launcher
goto :no_python

:py_launcher
set PYEXE=py -3
:py_found
set PYOK=1

if not exist "config\config.json" if exist "config\config.example.json" copy "config\config.example.json" "config\config.json" >nul
if not exist "output" md "output"

rem 端口从 config\config.json 读，读不到按 8080。
rem 旧版在命令行写死 --port 8080，把 config 里的 port 覆盖了 ——
rem 文档让人改 config 换端口，改了却不生效，属于自己骗自己。
set PORT=8080
for /f "usebackq delims=" %%p in (`%PYEXE% -c "import json;print(json.load(open('config/config.json',encoding='utf-8')).get('port',8080))" 2^>nul`) do set PORT=%%p

echo ============================================================
echo  投标工作台 正在启动
echo  地址  http://127.0.0.1:%PORT%/
echo  关闭本窗口即停止服务
echo ============================================================
start "" /min "%COMSPEC%" /c "timeout /t 2 >nul & start http://127.0.0.1:%PORT%/"
%PYEXE% src\app.py

echo.
echo 服务已停止。按任意键关闭窗口。
pause >nul
exit /b 0

:no_python
echo ============================================================
echo  [错误] 没有可用的 Python
echo  ERROR: Python not available
echo ------------------------------------------------------------
echo  请安装 Python 3.8 或更高版本：
echo    1. 打开 https://www.python.org/downloads/windows/
echo    2. 下载 Windows installer，选 64-bit 版本
echo    3. 安装时务必勾选最下面的 Add python.exe to PATH
echo    4. 装完关掉本窗口，重新双击 start.bat
echo.
echo  如果提示里出现 WindowsApps\python.exe，
echo  那是 Windows 自带的占位程序，不是真 Python，必须按上面装一次。
echo  详细步骤见 docs\安装部署手册.md 第三节
echo ============================================================
pause
exit /b 1
