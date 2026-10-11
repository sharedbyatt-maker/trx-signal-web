@echo off
setlocal
cd /d "%~dp0"
echo This launcher enables manual REAL orders, not demo orders.
echo Every order still requires confirmation in the admin dashboard.
set TRX_LOCAL_REAL_ORDERS=1
call run_local.bat
endlocal
