@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==================================================
echo   Sistema Mae - Instalacao para Windows
echo ==================================================
echo.

REM ---------------------------------------------------------------
REM  0) Localiza o Python 3.10 ou superior
REM ---------------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [ERRO] Python nao foi encontrado.
    echo        Instale o Python 3.10 ou superior em https://www.python.org/downloads/
    echo        e marque a opcao "Add python.exe to PATH" durante a instalacao.
    goto :erro
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo [ERRO] E necessario Python 3.10 ou superior.
    goto :erro
)

REM ---------------------------------------------------------------
REM  1) Cria o ambiente virtual
REM ---------------------------------------------------------------
echo [1/5] Criando o ambiente virtual (venv)...
if exist "venv\Scripts\python.exe" (
    echo        Ambiente virtual ja existe, reaproveitando.
) else (
    %PY% -m venv venv
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel criar o ambiente virtual.
        goto :erro
    )
)

REM ---------------------------------------------------------------
REM  2) Ativa o ambiente virtual
REM ---------------------------------------------------------------
echo [2/5] Ativando o ambiente virtual...
call "venv\Scripts\activate.bat"

REM ---------------------------------------------------------------
REM  3) Instala as dependencias
REM ---------------------------------------------------------------
echo [3/5] Instalando as dependencias (requer internet)...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias. Verifique a conexao com a internet.
    goto :erro
)

REM ---------------------------------------------------------------
REM  4) Banco de dados
REM     makemigrations garante que o esquema esteja sincronizado com os
REM     models; se nada mudou, apenas informa "No changes detected".
REM ---------------------------------------------------------------
echo [4/5] Preparando o banco de dados...
python manage.py makemigrations accounts gestao
if errorlevel 1 goto :erro_manage
python manage.py migrate
if errorlevel 1 goto :erro_manage

REM ---------------------------------------------------------------
REM  5) Primeiro Administrador (opcional)
REM ---------------------------------------------------------------
echo.
echo [5/5] Conta de Administrador
echo        O Administrador aprova os cadastros dos demais usuarios.
choice /c SN /n /m "Deseja criar o primeiro Administrador agora? [S/N] "
if errorlevel 2 goto :sem_admin
echo.
python manage.py createsuperuser
:sem_admin

REM ---------------------------------------------------------------
REM  Cria o atalho de inicializacao rapida (run.bat) se nao existir
REM ---------------------------------------------------------------
if exist "run.bat" goto :run_ok
> run.bat echo @echo off
>> run.bat echo setlocal
>> run.bat echo cd /d "%%~dp0"
>> run.bat echo REM Troque para 0 para nao abrir o navegador automaticamente.
>> run.bat echo set "ABRIR_NAVEGADOR=1"
>> run.bat echo if not exist "venv\Scripts\activate.bat" goto :sem_venv
>> run.bat echo call "venv\Scripts\activate.bat"
>> run.bat echo echo Sistema Mae em http://127.0.0.1:8000/ - pressione Ctrl+C para encerrar.
>> run.bat echo if "%%ABRIR_NAVEGADOR%%"=="1" start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000/'"
>> run.bat echo python manage.py runserver 127.0.0.1:8000 --noreload
>> run.bat echo pause
>> run.bat echo exit /b 0
>> run.bat echo :sem_venv
>> run.bat echo echo Ambiente virtual nao encontrado. Execute install.bat primeiro.
>> run.bat echo pause
>> run.bat echo exit /b 1
echo        Criado o atalho run.bat.
:run_ok

echo.
echo ==================================================
echo   Instalacao concluida!
echo   Para iniciar o sistema, de dois cliques em run.bat
echo ==================================================
echo.
choice /c SN /n /m "Deseja iniciar o sistema agora? [S/N] "
if errorlevel 2 goto :fim
call run.bat

:fim
echo.
pause
exit /b 0

:erro_manage
echo [ERRO] Falha ao preparar o banco de dados. Veja as mensagens acima.
:erro
echo.
pause
exit /b 1
