@echo off
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
set PYTHON_CMD=

echo.
echo ===========================
echo   AI Lab Launcher
echo ===========================
echo.

if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set PYTHON_CMD=%SCRIPT_DIR%venv\Scripts\python.exe
    echo [OK] Using virtual environment: "%SCRIPT_DIR%venv\"
    goto :check_wsl
)

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set PYTHON_CMD=%SCRIPT_DIR%.venv\Scripts\python.exe
    echo [OK] Using virtual environment: "%SCRIPT_DIR%.venv\"
    goto :check_wsl
)

where python >nul 2>nul
if !errorlevel! equ 0 (
    set PYTHON_CMD=python
    echo [OK] Using system Python
) else (
    echo [FAIL] Python not found.
    pause
    exit /b 1
)

:check_wsl
wsl --status >nul 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] WSL2 not installed.
    pause
    exit /b 1
)
echo [OK] WSL2 is available

wsl -d Ubuntu-24.04 -- which tmux >nul 2>nul
if !errorlevel! neq 0 (
    echo [WARN] tmux not found in Ubuntu-24.04 distro.
) else (
    echo [OK] tmux is available in WSL2
)

echo.
echo Checking Python dependencies...
"!PYTHON_CMD!" -c "import customtkinter; import psutil" >nul 2>nul
if !errorlevel! neq 0 (
    echo [WARN] Missing dependencies. Installing from requirements.txt...
    if exist "%SCRIPT_DIR%requirements.txt" (
        "!PYTHON_CMD!" -m pip install -r "%SCRIPT_DIR%requirements.txt" --quiet
        if !errorlevel! neq 0 (
            echo [FAIL] Failed to install dependencies.
            pause
            exit /b 1
        )
    ) else (
        echo [WARN] requirements.txt not found.
        set /p CONTINUE=Continue? 
        if /i not !CONTINUE!==y (
            exit /b 1
        )
    )
) else (
    echo [OK] All dependencies available (customtkinter, psutil)
)

if not exist "%SCRIPT_DIR%launcher.py" (
    echo [FAIL] launcher.py not found in %SCRIPT_DIR%
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%services.json" (
    echo [WARN] services.json not found.
) else (
    echo [OK] services.json found
)

echo.
echo ===========================
echo   Starting AI Lab Launcher...
echo ===========================
echo.
"!PYTHON_CMD!" "!SCRIPT_DIR!launcher.py"

if !errorlevel! neq 0 (
    echo [ERR] Launcher exited with code !errorlevel!
    pause
)
