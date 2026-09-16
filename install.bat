@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "SOURCE_DIR=%SCRIPT_DIR%lanebatchupdate"
set "PLUGIN_ROOT=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins"
set "TARGET_DIR=%PLUGIN_ROOT%\lanebatchupdate"
set "LOG_FILE=%TEMP%\lanebatchupdate_install.log"

>"%LOG_FILE%" echo Lane Batch Update installer
>>"%LOG_FILE%" echo Source: %SOURCE_DIR%
>>"%LOG_FILE%" echo Target: %TARGET_DIR%

if not exist "%SOURCE_DIR%\metadata.txt" goto :missing_source

cls
echo Lane Batch Update installer
echo.
echo Target folder:
echo %TARGET_DIR%
echo.
echo Close QGIS before continuing.
echo.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 goto :cancelled

if not exist "%PLUGIN_ROOT%" mkdir "%PLUGIN_ROOT%" >>"%LOG_FILE%" 2>&1
if not exist "%PLUGIN_ROOT%" goto :create_failed

robocopy "%SOURCE_DIR%" "%TARGET_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >>"%LOG_FILE%" 2>&1
set "COPY_RESULT=%ERRORLEVEL%"
if %COPY_RESULT% GEQ 8 goto :copy_failed

echo.
echo Installation completed successfully.
echo Restart QGIS, then enable Lane Batch Update in the Plugins manager.
echo.
echo Log file: %LOG_FILE%
pause
exit /b 0

:missing_source
echo.
echo ERROR: The lanebatchupdate folder was not found beside this script.
echo Extract the whole release folder before running install.bat.
echo.
echo Log file: %LOG_FILE%
pause
exit /b 1

:create_failed
echo.
echo ERROR: Cannot create the QGIS plugins folder.
echo %PLUGIN_ROOT%
echo Check your account permissions.
echo.
echo Log file: %LOG_FILE%
pause
exit /b 1

:copy_failed
echo.
echo ERROR: Installation failed. Copy error code: %COPY_RESULT%
echo Close QGIS and run install.bat again.
echo.
echo Log file: %LOG_FILE%
pause
exit /b %COPY_RESULT%

:cancelled
echo Installation cancelled.
pause
exit /b 0
