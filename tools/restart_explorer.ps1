<#
.SYNOPSIS
Restarts Windows Explorer -- the taskbar, the desktop and every File Explorer window.

.DESCRIPTION
What a registry change to the shell needs before open windows see it -- a Recycle Bin added to a mapped drive by
add_recycle_bin.ps1, for one. Every open File Explorer window closes; the taskbar and desktop come back in a moment.

Windows restarts the shell by itself when it ends (the AutoRestartShell setting); this starts it only if that did not
happen within a few seconds.

.EXAMPLE
.\tools\restart_explorer.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

Get-Process -Name explorer -ErrorAction SilentlyContinue | Stop-Process -Force

$deadline = (Get-Date).AddSeconds(5)
while ((Get-Date) -lt $deadline -and -not (Get-Process -Name explorer -ErrorAction SilentlyContinue)) {
    Start-Sleep -Milliseconds 250
}
if (-not (Get-Process -Name explorer -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "$env:WINDIR\explorer.exe"
}

Write-Host 'Explorer restarted.'
