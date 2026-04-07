@echo off
setlocal
title Warzone Audio Enhancer - Build Tool

echo =======================================
echo   WARZONE AUDIO ENHANCER - Build Tool
echo =======================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ y agrega al PATH.
    pause & exit /b 1
)

echo [1/4] Instalando / actualizando dependencias...
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] Fallo al instalar requirements. & pause & exit /b 1 )

echo [2/4] Instalando PyInstaller...
pip install "pyinstaller>=6.0" --quiet
if errorlevel 1 ( echo [ERROR] Fallo al instalar PyInstaller. & pause & exit /b 1 )

echo [3/4] Compilando ejecutable (esto puede tardar 2-5 minutos)...
pyinstaller warzone_audio.spec --clean --noconfirm
if errorlevel 1 ( echo [ERROR] Fallo la compilacion. Revisa los mensajes arriba. & pause & exit /b 1 )

echo [4/4] Listo.
echo.
echo ===================================================
echo   EXE generado en:  dist\WarzoneAudioEnhancer.exe
echo ===================================================
echo.
echo Sube dist\WarzoneAudioEnhancer.exe a tu GitHub Release.
echo El archivo data\ (modelos ML) se creara junto al .exe al ejecutarlo.
echo.
pause
