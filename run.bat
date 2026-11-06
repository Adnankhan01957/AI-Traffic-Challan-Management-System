@echo off
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it, paste your GROQ_API_KEY, save, then run this file again.
  notepad .env
  exit /b
)
streamlit run app.py
