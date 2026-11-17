@echo off
rem SPDX-License-Identifier: MIT
rem Copyright (c) 2026 adanglingpointer
setlocal EnableExtensions
title PS5 Movie Converter
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  PS5 Movie Converter - Windows launcher
rem  * Drag and drop movie files (or folders) onto this file, or
rem  * double-click it to convert every movie in this folder.
rem  Output: "<name>.PS5.mp4" next to each original.
rem ------------------------------------------------------------------

rem ---- find Python -------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3 is not installed.
  choice /m "Install it now with winget"
  if errorlevel 2 goto :nopy
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Python installed. Close this window and run "PS5 Convert" again.
  pause
  exit /b 0
)

rem ---- find FFmpeg -------------------------------------------------
where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" if not exist "%~dp0ffmpeg.exe" if not exist "%~dp0bin\ffmpeg.exe" (
  echo FFmpeg is not installed.
  choice /m "Install it now with winget"
  if errorlevel 2 goto :noff
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo.
  echo FFmpeg installed. Close this window and run "PS5 Convert" again.
  pause
  exit /b 0
)

rem ---- run ---------------------------------------------------------
if "%~1"=="" (
  %PY% "%~dp0ps5_convert.py" "%~dp0."
) else (
  %PY% "%~dp0ps5_convert.py" %*
)
echo.
pause
exit /b

:nopy
echo Install Python 3 from https://www.python.org/downloads/ and try again.
pause
exit /b 1

:noff
echo Install FFmpeg (https://www.gyan.dev/ffmpeg/builds/) and try again.
pause
exit /b 1
