@echo off
rem ---------------------------------------------------------------------------
rem Build the DLL and install DLL + vpp, then verify what is on disk is what
rem was just built.
rem
rem Why this exists: doing these steps by hand fails silently. Skip one and the
rem game just behaves like the previous build, so you go hunting for a bug that
rem is not there. That cost us three debugging rounds.
rem
rem IMPORTANT: this script does NOT run build_all.py.
rem   build_all.py subsets the Chinese font from Noto Sans CJK, and the source
rem   .ttc files only exist on the Linux side. Run it on Windows and it silently
rem   SKIPS the fonts -- the vpp still builds, just without any Chinese glyphs,
rem   and every Chinese character in the game vanishes. Been there.
rem   rfcn.vpp is built on the Linux side; this script only installs it, and
rem   refuses to run if it looks like a fontless build.
rem
rem TWO THINGS THIS FILE MUST NEVER DO:
rem   1. Contain non-ASCII bytes. cmd reads it with the system OEM code page
rem      (932 here) and UTF-8 Chinese breaks line parsing outright.
rem   2. Expand a path containing ")" inside a parenthesised if(...) block.
rem      Every path here goes through "Program Files (x86)", and that ")" closes
rem      the block early -- a parse error, so the window just blinks and dies.
rem      That is why this script uses goto labels instead of if(...) bodies.
rem
rem Right-click -> Run as administrator.
rem ---------------------------------------------------------------------------

setlocal
set "SRC=<ALPINE_SRC>"
set "BUILD=build13"
set "RFCN=<RF_CN>"
set "GAME=<GAME_DIR>"
set "AFDIR=<ALPINE_DIR>"
set "VCVARS=<VS_BUILDTOOLS>\VC\Auxiliary\Build\vcvarsall.bat"
set "VPPSIZE=0"

net session >nul 2>&1
if errorlevel 1 goto :noadmin

echo === 1/4 patch state ===
python "%RFCN%\patches\apply_patch.py" "%SRC%" --check
if errorlevel 1 goto :fail

echo.
echo === 2/4 sanity-check the prebuilt vpp ===
if not exist "%RFCN%\build\rfcn.vpp" goto :novpp
for %%F in ("%RFCN%\build\rfcn.vpp") do set "VPPSIZE=%%~zF"
rem A complete vpp is ~1.7 MB. A fontless one is ~0.5 MB, loads fine, and makes
rem every Chinese character disappear -- so treat "too small" as fatal.
if %VPPSIZE% LSS 1200000 goto :nofonts
echo vpp looks complete, %VPPSIZE% bytes

echo.
echo === 3/4 build DLL ===
call "%VCVARS%" x86 >nul
if errorlevel 1 goto :novcvars
cd /d "%SRC%"
cmake --build %BUILD% --config Release > build.log 2>&1
findstr /n /c:"error" build.log
if not errorlevel 1 goto :builderr
echo build ok

echo.
echo === 4/4 install and verify ===
copy /Y "%SRC%\%BUILD%\bin\AlpineFaction.dll" "%AFDIR%\AlpineFaction.dll" >nul
if errorlevel 1 goto :dllwrite
copy /Y "%RFCN%\build\rfcn.vpp" "%GAME%\client_mods\rfcn.vpp" >nul
if errorlevel 1 goto :vppwrite

fc /b "%SRC%\%BUILD%\bin\AlpineFaction.dll" "%AFDIR%\AlpineFaction.dll" >nul
if errorlevel 1 goto :dllmismatch
fc /b "%RFCN%\build\rfcn.vpp" "%GAME%\client_mods\rfcn.vpp" >nul
if errorlevel 1 goto :vppmismatch

echo.
echo ALL OK - the game now runs exactly what was just built.
pause
exit /b 0

:noadmin
echo [ERROR] Not running as administrator.
echo Right-click deploy.bat and choose "Run as administrator".
goto :fail

:novpp
echo [ERROR] rfcn.vpp not found under the rf_cn\build folder.
echo It has to be built on the Linux side - build_all.py cannot make a
echo usable one on Windows because the source fonts are not there.
goto :fail

:nofonts
echo [ERROR] rfcn.vpp is only %VPPSIZE% bytes - the fonts are missing.
echo Rebuild it on the Linux side. Do not run build_all.py here.
goto :fail

:novcvars
echo [ERROR] vcvarsall.bat failed.
goto :fail

:builderr
echo [ERROR] compile errors above. Full log: build.log in the source folder.
goto :fail

:dllwrite
echo [ERROR] cannot write AlpineFaction.dll - is the game running?
goto :fail

:vppwrite
echo [ERROR] cannot write rfcn.vpp - is the game running?
goto :fail

:dllmismatch
echo [ERROR] installed DLL differs from the one just built.
goto :fail

:vppmismatch
echo [ERROR] installed vpp differs from the source.
goto :fail

:fail
echo.
echo FAILED - files in the game folder may still be the old version.
pause
exit /b 1
