@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title CardFactory

where uv >nul 2>nul
if errorlevel 1 (
  echo O gerenciador "uv" nao foi encontrado.
  echo Instale abrindo o PowerShell e rodando:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
  echo Depois feche e abra esta janela de novo.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

echo Iniciando o CardFactory (a primeira vez pode demorar alguns minutos)...
uv run --project backend cardfactory serve --open
pause
