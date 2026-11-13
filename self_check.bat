@echo off
chcp 936 >nul
cd /d "%~dp0"
set FAILED=0

echo ============================================================
echo  BidFlow 自检 - 不联网、不启动服务
echo ============================================================
rem 不能用 where python：WindowsApps 占位别名会被误判为已安装
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
%PYEXE% -V

if not exist "output" md "output"
if not exist "config\config.json" if exist "config\config.example.json" copy "config\config.example.json" "config\config.json" >nul

echo.
echo [1/3] 拆标引擎
%PYEXE% tests\test_split.py
if errorlevel 1 set FAILED=1

echo.
echo [2/3] 写稿引擎
%PYEXE% tests\test_draft.py
if errorlevel 1 set FAILED=1

echo.
echo [3/3] 需求雷达
%PYEXE% tests\test_radar.py
if errorlevel 1 set FAILED=1

echo.
echo ============================================================
if "%FAILED%"=="1" goto :failed
echo  结果：全部通过 ALL PASS
echo ============================================================
pause
exit /b 0

:failed
echo  结果：有失败项，见上方提示
echo ============================================================
pause
exit /b 1

:no_python
echo [错误] 没有可用的 Python，请先看 docs\安装部署手册.md 第三节
echo 若提示 WindowsApps\python.exe，那是 Windows 占位程序，不是真 Python
pause
exit /b 1
