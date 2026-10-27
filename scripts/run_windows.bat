@echo off
setlocal
cd /d "%~dp0.."
if defined FILE_INTEL_PYTHON (
  "%FILE_INTEL_PYTHON%" scripts\run.py %*
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    python scripts\run.py %*
  ) else (
    py -3.12 scripts\run.py %*
  )
)
if errorlevel 1 pause
