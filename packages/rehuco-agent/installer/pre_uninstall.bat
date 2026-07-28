@echo off
REM Removes what post_install.bat registered, before the uninstall deletes the files it points at.
REM Without this, every registration written at install time would survive as a handler for a
REM removed Rehuco.exe -- the "no association pointing at a removed path" failure #206 calls out.
REM
REM The MSI sequences this After="InstallInitialize" on REMOVE="ALL", so the exe is still present
REM when it runs. Same layout and same exit-code contract as post_install.bat: run from
REM [INSTALLFOLDER]\_installer\, and never fail the uninstall.
"%~dp0..\Rehuco.exe" --unregister
exit /b 0
