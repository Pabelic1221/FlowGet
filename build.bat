@echo off
REM Builds FlowGet.exe, the installer, and the SHA-256 file the auto-updater verifies.
REM Requires Python 3.10+ and Inno Setup 6.
py -m pip install -r requirements.txt || goto :err
py -m PyInstaller --noconfirm --onefile --windowed --name FlowGet app.py || goto :err
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer.iss || goto :err
powershell -NoProfile -Command "$h=(Get-FileHash 'dist\FlowGet-Setup.exe' -Algorithm SHA256).Hash.ToLower(); \"$h  FlowGet-Setup.exe\" | Out-File -Encoding ascii 'dist\FlowGet-Setup.exe.sha256'" || goto :err
echo.
echo Done. Upload BOTH files to your GitHub Release:
echo   dist\FlowGet-Setup.exe
echo   dist\FlowGet-Setup.exe.sha256
pause & exit /b 0
:err
echo Build failed. & pause & exit /b 1
