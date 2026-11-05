@echo off
rem Run by Windows Task Scheduler (task "DSE Share Watch", Mon-Fri 08:00 = the Sun-Thu session just ended).
rem fetch new days -> rebuild clean data -> paper run as of yesterday -> watcher page. Output: data\watch\run.log
cd /d "%~dp0.."
if not exist data\watch mkdir data\watch
set PY=C:\Python315\python.exe
for /f %%d in ('%PY% -c "import datetime as d;print(d.date.today()-d.timedelta(days=1))"') do set YESTERDAY=%%d
if not defined YESTERDAY echo SESSION DATE LOOKUP FAILED: the paper run below will fail >> data\watch\run.log
echo ==== %date% %time% (session %YESTERDAY%) >> data\watch\run.log
%PY% scripts\fetch_dse_daily.py >> data\watch\run.log 2>&1 && ^
%PY% -W ignore scripts\build_clean.py > data\watch\build_clean.log 2>&1 && ^
%PY% -W ignore scripts\paper_run.py --asof %YESTERDAY% >> data\watch\run.log 2>&1 || echo DATA PIPELINE FAILED, see above and data\watch\build_clean.log >> data\watch\run.log
rem interest rates for the page's caution line; re-downloads from the IMF only when the copy is over 30 days old
%PY% -W ignore scripts\rates_vs_index.py --refresh-if-stale > data\watch\rates.log 2>&1 || echo RATES REFRESH FAILED, see data\watch\rates.log >> data\watch\run.log
%PY% scripts\watch_share.py >> data\watch\run.log 2>&1
rem weekly snapshot of every company page (sector comparison, screener); after the page so it never delays it
%PY% scripts\fundamentals_snapshot.py --if-older 6 > data\watch\snapshot.log 2>&1 || echo FUNDAMENTALS SNAPSHOT FAILED, see data\watch\snapshot.log >> data\watch\run.log
