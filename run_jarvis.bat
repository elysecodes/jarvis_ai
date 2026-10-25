@echo off
title JARVIS
cd /d "%~dp0"

echo.
echo ========================================
echo  JARVIS - local voice assistant
echo ========================================
echo.

REM --- Check Python is available ---
python --version >nul 2>&1
if errorlevel 1 goto no_python

REM --- Check Python version is 3.10+ ---
for /f "tokens=2 delims=. " %%a in ('python --version 2^>nul') do set PYVER=%%a
if "%PYVER%" LSS "10" goto old_python

REM --- Set up virtual environment if needed ---
if not exist ".venv\Scripts\python.exe" goto make_env
if not exist ".venv\Lib\site-packages\pyttsx3" goto make_env
goto run

:make_env
echo Setting up JARVIS one time - creating virtual environment...
python -m venv .venv
if errorlevel 1 goto failed
echo Installing required packages (this may take a minute)...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run
REM --- Check Ollama (warning only - rule commands still work) ---
.venv\Scripts\python.exe -c "from modules import ai_engine; ok,_ = ai_engine.ping(2); print('Ollama: ready' if ok else 'Ollama: not running (AI answers unavailable, rule commands still work)')" 2>nul

echo Starting JARVIS.
echo Say "hey jarvis" then your command. Stop with "stop listening" or Ctrl+C.
echo Tip: use "python main.py --text" for keyboard mode without a microphone.
echo.
.venv\Scripts\python.exe -u main.py %*
goto end

:no_python
echo.
echo ERROR: Python is not installed or not on your PATH.
echo Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
goto end

:old_python
echo.
echo ERROR: JARVIS needs Python 3.10 or newer. You have Python %PYVER%.
echo Install Python 3.10+ from python.org.
goto end

:failed
echo.
echo Setup failed. Open a Command Prompt here and run:
echo     .venv\Scripts\python.exe -m pip install -r requirements.txt

:end
