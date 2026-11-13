@echo off
setlocal
cd /d "%~dp0"

REM Troque para 0 para nao abrir o navegador automaticamente.
set "ABRIR_NAVEGADOR=1"

if not exist "venv\Scripts\activate.bat" goto :sem_venv
call "venv\Scripts\activate.bat"

echo ==================================================
echo   Sistema Mae rodando em http://127.0.0.1:8000/
echo   Pressione Ctrl+C (ou feche esta janela) para encerrar.
echo ==================================================

REM Abre o navegador padrao apos 3 segundos (tempo do servidor subir).
if "%ABRIR_NAVEGADOR%"=="1" start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000/'"

python manage.py runserver 127.0.0.1:8000 --noreload
pause
exit /b 0

:sem_venv
echo Ambiente virtual nao encontrado. Execute install.bat primeiro.
pause
exit /b 1
