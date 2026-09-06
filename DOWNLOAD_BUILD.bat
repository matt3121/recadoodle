@echo off

setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (

    ".venv\Scripts\python.exe" get_build.py

    goto :end

)

if exist "..\.venv\Scripts\python.exe" (

    "..\.venv\Scripts\python.exe" get_build.py

    goto :end

)

echo Python environment not found.

echo Run INSTALL_LOCAL_DEPENDENCIES.bat in this folder first.

echo Then run DOWNLOAD_BUILD.bat again.

echo.

pause

exit /b 1

:end

if errorlevel 1 pause