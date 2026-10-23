@echo off
setlocal
set ELECTRON_RUN_AS_NODE=
start "" "%~dp0media-runtime\electron\electron.exe" "%~dp0freevideo-trial\studio-app"
