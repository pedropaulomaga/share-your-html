@echo off
title Share Your HTML
echo.
echo  =========================================
echo    Share Your HTML - Iniciando...
echo  =========================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] Python nao encontrado. Instale em python.org
    pause
    exit /b 1
)

pip show flask >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias...
    pip install -r requirements.txt -q
)

echo  Abrindo navegador em http://localhost:5050
echo  Para encerrar: feche esta janela ou pressione CTRL+C
echo.

start "" http://localhost:5050
python app.py

pause
