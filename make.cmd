@echo off
rem SIA Norm Intelligence – Make-Wrapper fuer Windows (REQ-000).
rem Aufruf: make <target>  mit target = setup | check | eval | run | package
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo make: Python nicht im PATH gefunden. 1>&2
  exit /b 1
)
python "%~dp0scripts\make.py" %*
