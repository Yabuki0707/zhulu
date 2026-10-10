@echo off
rem ---------------------------------------------------------------------------
rem  Zhulu terrain raster generator -- the ONE entry point.
rem
rem  Double-click    -> GUI (run.py with no args): parameters, stages, live log
rem  With arguments  -> straight to the CLI, e.g.
rem       ShengChengTu.bat --cell 0.0625
rem       ShengChengTu.bat --no-veg
rem       ShengChengTu.bat --river-min 50
rem
rem  This file is deliberately ASCII-only. After 'chcp 65001' takes effect,
rem  cmd.exe re-reads a batch file with a byte offset that desyncs on
rem  multi-byte characters and shreds the following lines. So every Chinese
rem  message is printed by Python (run.py sets PYTHONUTF8 below), and the two
rem  Chinese-named entry modules are reached through the ASCII name run.py.
rem
rem  Line endings must stay CRLF -- do not save this file as LF.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

%PY% "%~dp0run.py" %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo   [ERROR] the generator exited with a non-zero code.
echo           Read its message above. The two common causes:
echo             - JiChuDanYuan.json missing -> python toolsuild_editor.py --dump-units
echo             - a contract assert fired -> its message names the broken rule
echo           Re-running is safe: the .npy caches are reused and nothing is
echo           half-written (products are only written by the last stage).
echo   (press any key to close this window)
pause >nul
exit /b 1

:nopython
echo.
echo   [ERROR] Python 3 not found: neither "py -3" nor "python" could run.
echo   Install Python 3 from python.org, tick "Add python.exe to PATH",
echo   then double-click this file again.
echo   (press any key to close this window)
pause >nul
exit /b 1
