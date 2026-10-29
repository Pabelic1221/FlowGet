@echo off
REM Builds FlowGet.exe, the installer, and the SHA-256 file the auto-updater verifies.
REM Requires Python 3.10+. Inno Setup 6 is downloaded and installed automatically if it is missing.
py -m pip install -r requirements.txt || goto :err

REM Find the icon folder (files-logo or assets) and embed the icons into icon_data.py
set ICODIR=
for /f "delims=" %%d in ('py embed_icons.py') do set ICODIR=%%d
if not defined ICODIR goto :err
echo Using icons from: %ICODIR%

py -m PyInstaller --noconfirm --onefile --windowed --noupx --name FlowGet --icon "%ICODIR%\icon.ico" app.py || goto :err

call :findiscc
if not defined ISCC call :getinno
if not defined ISCC call :findiscc
if not defined ISCC goto :noinno
echo Using Inno Setup: %ISCC%

"%ISCC%" "/DIconDir=%ICODIR%" installer.iss || goto :err
powershell -NoProfile -Command "$h=(Get-FileHash 'dist\FlowGet-Setup.exe' -Algorithm SHA256).Hash.ToLower(); \"$h  FlowGet-Setup.exe\" | Out-File -Encoding ascii 'dist\FlowGet-Setup.exe.sha256'" || goto :err
echo.
echo Done. Upload BOTH files to your GitHub Release:
echo   dist\FlowGet-Setup.exe
echo   dist\FlowGet-Setup.exe.sha256
pause & exit /b 0

:noinno
echo.
echo Inno Setup could not be found or installed automatically.
echo Install it by hand from https://jrsoftware.org/isdl.php and run this again.
echo dist\FlowGet.exe was built, but the installer was not.
goto :err

:findiscc
REM Looks for Inno Setup 6 or 7: system-wide, per-user, or on PATH
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if not defined ISCC for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%i"
exit /b 0

:getinno
echo.
echo Inno Setup not found. Downloading and installing it for the current user, no admin needed...
set "ISSETUP=%TEMP%\innosetup-6.7.3.exe"
if exist "%ISSETUP%" del "%ISSETUP%"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -UseBasicParsing 'https://files.jrsoftware.org/is/6/innosetup-6.7.3.exe' -OutFile '%ISSETUP%' } catch { exit 1 }"
if exist "%ISSETUP%" start /wait "" "%ISSETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER
if exist "%ISSETUP%" del "%ISSETUP%"
call :findiscc
if defined ISCC exit /b 0
echo Direct download did not work, trying winget...
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
exit /b 0

:err
echo Build failed. & pause & exit /b 1