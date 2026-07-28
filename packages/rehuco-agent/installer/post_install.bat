@echo off
REM Registers .rehu/.tc, the folder and folder-background verbs, and the archive verb (#43) by
REM calling the app's own --register, so the installer and the app share one registration identity
REM ([[appendices.briefcase-packaging#windows]]). The MSI deliberately declares no document_type on
REM Windows -- it would write a second, competing ProgID covering only .rehu, which the app's own
REM Registry settings page (#47) could never recognise as its own.
REM
REM Invoked by the MSI's generated run_post_install.bat, which sets ALLUSERS, INSTALLER_PATH and
REM INSTALLER_UNATTENDED in the environment and calls this with no arguments. It runs from
REM [INSTALLFOLDER]\_installer\, so the exe is one directory up; the name follows `formal_name`.
REM
REM Exits 0 unconditionally. The WiX custom action is Return="check", so a non-zero exit rolls the
REM entire installation back -- and an unregistered file association is not worth failing an
REM install over. The app stays fully usable, and the Registry settings page can register it later.
"%~dp0..\Rehuco.exe" --register
exit /b 0
