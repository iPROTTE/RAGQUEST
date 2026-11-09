@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Ragquest Admin
if not exist .venv\Scripts\python.exe (
  echo Preparando o Ragquest Admin - so na primeira vez...
  python -m venv .venv
  .venv\Scripts\python -m pip install --disable-pip-version-check -q fastapi uvicorn
)
echo Ragquest Admin rodando em http://localhost:8766 - feche esta janela para sair.
.venv\Scripts\python admin.py
pause
