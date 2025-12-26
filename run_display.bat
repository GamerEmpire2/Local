@echo off
REM YouTube Music Display - Task Scheduler Runner
REM This batch file launches the YT Music display overlay.

setlocal enabledelayedexpansion

set ROOT=%~dp0
cd /d "%ROOT%"

REM Prefer packaged EXE in dist\, fallback to local EXE, then to venv Python
set DIST=%ROOT%dist\
set GUI=%DIST%YT_Music_Display.exe
if not exist "%GUI%" set GUI=%ROOT%YT_Music_Display.exe

if exist "%GUI%" (
	echo Launching GUI: "%GUI%"
	start "" "%GUI%"
	endlocal
	exit /b 0
)

REM No EXE found — try venv Python
set PY=C:\Users\1724j\OneDrive\Documents\YTMusic\.venv\Scripts\python.exe
if exist "%PY%" (
	if exist "%ROOT%YT_Music_display_local.py" (
		echo Launching with venv Python: "%PY%"
		start "" "%PY%" "%ROOT%YT_Music_display_local.py"
		endlocal
		exit /b 0
	) else (
		echo ERROR: %ROOT%YT_Music_display.py not found.
		pause
		endlocal
		exit /b 1
	)
)

echo ERROR: No GUI executable or Python venv runner found. Place the EXE in "%DIST%" or ensure the venv exists.
pause
endlocal
exit /b 1
