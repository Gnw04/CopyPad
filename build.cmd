@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0src"

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: python not found in PATH. Install Python 3.10+ first.
  pause
  exit /b 1
)

echo [1/2] Generating icon and version resource...
python gen_assets.py
if errorlevel 1 goto :err

echo [2/2] Building single-file exe (this takes a while)...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name CopyPad --icon app.ico --add-data "app.ico;." --version-file version.txt CopyPadApp.py
if errorlevel 1 goto :err

echo.
echo BUILD OK -^> src\dist\CopyPad.exe
goto :end

:err
echo BUILD FAILED. See output above.
exit /b 1

:end
endlocal
