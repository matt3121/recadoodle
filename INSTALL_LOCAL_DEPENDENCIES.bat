@echo off
setlocal
cd /d "%~dp0"

echo =====================================================
echo   Recadoodle Local Server - Dependency Installer
echo =====================================================
echo.

rem This local project is documented and tested with Python 3.12.
py -3.12 -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_COMMAND=py -3.12"
    goto :python_found
)

python -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_COMMAND=python"
    goto :python_found
)

echo ERROR: Python 3.12 or newer was not found.
echo.
echo Download Python from:
echo https://www.python.org/downloads/
echo.
echo During installation, select "Add Python to PATH".
goto :failed

:python_found
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating the local Python environment...
    %PYTHON_COMMAND% -m venv .venv
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Using the existing local Python environment...
    ".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>&1
    if errorlevel 1 (
        echo ERROR: The existing .venv uses an unsupported Python version.
        echo Delete the .venv folder, then run this installer again.
        goto :failed
    )
)

echo [2/4] Updating pip and packaging tools...
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :failed

echo [3/4] Installing all server and development dependencies...
".venv\Scripts\python.exe" -m pip install --editable ".[dev]"
if errorlevel 1 goto :failed

echo [4/4] Preparing the local configuration...
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo Created .env from .env.example.
    )
) else (
    echo Keeping the existing .env file.
)

echo.
echo SUCCESS: All local server dependencies are installed.
echo You can now run START_LOCAL_SERVER.bat.
echo.
pause
exit /b 0

:failed
echo.
echo INSTALLATION FAILED. Read the error above, then try again.
echo If pip could not download a package, check the internet connection.
echo.
pause
exit /b 1
