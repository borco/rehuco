<#
.SYNOPSIS
Gives a mapped network drive a Windows Recycle Bin.

.DESCRIPTION
Windows keeps a Recycle Bin for local volumes and for "known folders". A mapped network drive gets one when its root
is registered as a known folder, which takes two registry entries under one GUID:

  HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions\{GUID}
      Name, RelativePath = "<letter>:\", Category = 4            (machine-wide: needs administrator rights)
  HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\KnownFolder\{GUID}
      MaxCapacity (MB), NukeOnDelete = 0                          (this user's own: no elevation)

The script writes the HKCU half itself and relaunches only the HKLM half elevated, so the UAC prompt appears once,
and only when the folder definition is missing or its name changes. A drive letter that already has a definition
keeps its GUID. The bin follows the drive LETTER, not the share: remapping a letter to another share keeps the bin.

Deletions on the drive go to the bin in Explorer windows opened afterwards; restart Explorer, or sign out and in,
if an open window still deletes permanently.

.PARAMETER Drive
The drive letter, with or without the colon: T or T:

.PARAMETER Name
The known folder's name; the share the letter is mapped to (\\server\share as "server share") when not given.

.PARAMETER MaxCapacityMB
The bin's size in MB; 10% of the drive's size when not given, or 10240 when the size cannot be read.

.EXAMPLE
.\tools\add_recycle_bin.ps1 T

.EXAMPLE
.\tools\add_recycle_bin.ps1 -Drive T: -Name "Nas DATA_14T" -MaxCapacityMB 50000
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[A-Za-z]:?$')]
    [string]$Drive,

    [string]$Name,

    [ValidateRange(1, [int]::MaxValue)]
    [int]$MaxCapacityMB,

    # internal: the elevated relaunch writes the folder definition under this GUID and nothing else
    [string]$Guid,

    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'

$letter = $Drive.Substring(0, 1).ToUpperInvariant()
$root = "${letter}:\"
$descriptions = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions'
$bitBucket = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\KnownFolder'

function Set-RegistryValues([string]$Key, [hashtable]$Strings, [hashtable]$Dwords) {
    # never New-Item -Force on an existing key: it would be recreated empty
    if (-not (Test-Path $Key)) {
        New-Item -Path $Key | Out-Null
    }
    foreach ($entry in $Strings.GetEnumerator()) {
        New-ItemProperty -Path $Key -Name $entry.Key -Value $entry.Value -PropertyType String -Force | Out-Null
    }
    foreach ($entry in $Dwords.GetEnumerator()) {
        New-ItemProperty -Path $Key -Name $entry.Key -Value $entry.Value -PropertyType DWord -Force | Out-Null
    }
}

if ($Elevated) {
    Set-RegistryValues "$descriptions\$Guid" @{ Name = $Name; RelativePath = $root } @{ Category = 4 }
    exit 0
}

# --- what the letter is
$mapping = Get-SmbMapping -LocalPath "${letter}:" -ErrorAction SilentlyContinue
if ($null -eq $mapping) {
    throw "${letter}: is not a mapped network drive (Get-SmbMapping knows nothing of it). A local drive has a Recycle Bin already."
}
if (-not $Name) {
    $Name = ($mapping.RemotePath.Trim('\') -replace '\\', ' ')
}
if (-not $MaxCapacityMB) {
    $MaxCapacityMB = 10240
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID = '${letter}:'" -ErrorAction SilentlyContinue
    if ($null -ne $disk -and $disk.Size) {
        $MaxCapacityMB = [int][math]::Max(1, [math]::Floor($disk.Size / 1MB * 0.10))
    }
}

# --- the folder definition: reuse the letter's own if there is one
$existing = Get-ChildItem $descriptions | Where-Object {
    (Get-ItemProperty $_.PSPath -Name RelativePath -ErrorAction SilentlyContinue).RelativePath -eq $root
} | Select-Object -First 1

if ($null -ne $existing) {
    $Guid = $existing.PSChildName
    $current = (Get-ItemProperty $existing.PSPath -Name Name -ErrorAction SilentlyContinue).Name
    $needsElevation = $PSBoundParameters.ContainsKey('Name') -and $current -ne $Name
    if (-not $needsElevation) { $Name = $current }
    Write-Host "${letter}: is already the known folder $Guid ('$current')."
}
else {
    $Guid = '{' + [guid]::NewGuid().ToString().ToUpperInvariant() + '}'
    $needsElevation = $true
}

if ($needsElevation) {
    Write-Host "Registering ${letter}: as the known folder $Guid ('$Name') -- this needs administrator rights."
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
        '-Drive', $letter, '-Name', "`"$Name`"", '-Guid', $Guid, '-Elevated'
    )
    try {
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    }
    catch {
        throw "The elevation was refused, so nothing was changed: $($_.Exception.Message)"
    }
    if ($process.ExitCode -ne 0) {
        throw "The elevated part failed (exit code $($process.ExitCode)); nothing was changed for this user."
    }
}

# --- the bin itself, in this user's own hive
Set-RegistryValues "$bitBucket\$Guid" @{} @{ MaxCapacity = $MaxCapacityMB; NukeOnDelete = 0 }

Write-Host "${letter}: ($($mapping.RemotePath)) now has a Recycle Bin of $MaxCapacityMB MB."
Write-Host 'Explorer windows opened from now on use it; restart Explorer if an open one still deletes permanently.'
