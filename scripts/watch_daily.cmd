@echo off
rem Run by Windows Task Scheduler (task "DSE Share Watch"). Appends output to data\watch\run.log.
cd /d "%~dp0.."
if not exist data\watch mkdir data\watch
echo ==== %date% %time% >> data\watch\run.log
"C:\Python315\python.exe" scripts\watch_share.py >> data\watch\run.log 2>&1
