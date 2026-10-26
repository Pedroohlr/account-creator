@echo off
chcp 65001 >nul
title Account Creator
color 0A
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Criando ambiente virtual...
    python -m venv .venv || goto :erro
    ".venv\Scripts\python.exe" -m pip install -q -e . || goto :erro
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [setup] Arquivo .env criado. Abra-o e confira o AVD_NAME antes de continuar.
    notepad ".env"
)

".venv\Scripts\python.exe" -m automate_accounts %*
if errorlevel 1 pause
exit /b 0

:erro
echo.
echo Falha na instalacao. Verifique se o Python 3.11+ esta instalado e no PATH.
pause
exit /b 1
