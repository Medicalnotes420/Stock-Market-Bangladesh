@echo off
rem Run by Windows Task Scheduler (task "DSE Rates Check", every 1 August 09:00): re-download the IMF bond yields,
rem rebuild the bonds-vs-shares tables, re-run the pre-registered rising-yields test and its fresh-months tally.
rem Output appended to data\rates\rates_check.log. Uses DSEX from data\clean (kept current by "DSE Share Watch").
cd /d "%~dp0.."
if not exist data\rates mkdir data\rates
set PY=C:\Python315\python.exe
echo ==== %date% %time% >> data\rates\rates_check.log
%PY% -W ignore scripts\rates_vs_index.py --refresh >> data\rates\rates_check.log 2>&1 && ^
%PY% -W ignore scripts\rates_signal.py >> data\rates\rates_check.log 2>&1 || echo RATES CHECK FAILED, see above >> data\rates\rates_check.log
