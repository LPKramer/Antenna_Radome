@echo off
rem ============================================================
rem  antfdm - editor grafico
rem
rem  De um duplo clique neste arquivo para abrir o editor.
rem  Voce tambem pode arrastar um arquivo .yaml para cima dele
rem  para abrir direto naquela antena.
rem ============================================================
setlocal
cd /d "%~dp0"
title antfdm

rem python.exe e nao pythonw.exe de proposito: a janela de console fica junto e
rem mostra a mensagem quando algo da errado.  Com pythonw um erro sumiria e o
rem duplo clique pareceria nao ter feito nada.
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo.
  echo   Ambiente virtual nao encontrado em:
  echo   %~dp0.venv
  echo.
  echo   Crie com estes dois comandos, nesta pasta:
  echo.
  echo       python -m venv .venv
  echo       .venv\Scripts\python.exe -m pip install -e .[gui]
  echo.
  pause
  exit /b 1
)

"%PY%" -c "import PySide6" 2>nul
if errorlevel 1 (
  echo.
  echo   O editor grafico precisa do PySide6, que nao esta instalado.
  echo.
  echo       .venv\Scripts\python.exe -m pip install PySide6-Essentials
  echo.
  pause
  exit /b 1
)

set "SPEC=%~1"
if "%SPEC%"=="" set "SPEC=%~dp0antfdm\recipes\dipolo_y.yaml"

echo.
echo   Abrindo: %SPEC%
echo   Pode fechar esta janela preta depois que o editor aparecer.
echo.

"%PY%" -m antfdm.cli gui "%SPEC%"

if errorlevel 1 (
  echo.
  echo   O editor terminou com erro. O motivo esta na mensagem acima.
  echo.
  pause
)
endlocal
