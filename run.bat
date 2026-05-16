@echo off
cd /d "%~dp0"
"%USERPROFILE%\.venv\Scripts\python.exe" manage.py runserver
