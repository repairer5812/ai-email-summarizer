param(
  [int]$ParentPid,
  [int]$UiPid = 0,
  [string]$InstallerPath,
  [string]$RelaunchExe,
  [string]$RelaunchArgsJson,
  [string]$InstallLogPath,
  [string]$StatusPath,
  [string]$InstalledExePath,
  [string]$ExpectedVersion
)
$ErrorActionPreference = 'Stop'
Start-Sleep -Seconds 2

function Write-UpdateStatus([string]$Stage, [string]$Message, [int]$Code = 0) {
  try {
    $obj = [ordered]@{
      stage = $Stage
      message = $Message
      code = $Code
      updated_at = (Get-Date).ToString('o')
    }
    ($obj | ConvertTo-Json -Compress) | Set-Content -Path $StatusPath -Encoding UTF8 -Force
  } catch {}
}

function Stop-PidIfRunning([int]$TargetPid) {
  if ($TargetPid -le 0) { return }
  try {
    Wait-Process -Id $TargetPid -Timeout 10 -ErrorAction SilentlyContinue | Out-Null
  } catch {}
  try {
    if (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) {
      Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {}
}

function Stop-ImageIfRunning([string]$ImageName) {
  if ([string]::IsNullOrWhiteSpace($ImageName)) { return }
  try {
    $procs = Get-Process -Name $ImageName -ErrorAction SilentlyContinue
    foreach ($pp in $procs) {
      try {
        Stop-Process -Id $pp.Id -Force -ErrorAction SilentlyContinue
      } catch {}
    }
  } catch {}
}

function Reset-PyInstallerEnv() {
  try { $env:PYINSTALLER_RESET_ENVIRONMENT = '1' } catch {}
  try {
    $vars = Get-ChildItem Env: -ErrorAction SilentlyContinue
    foreach ($vv in $vars) {
      if ($vv.Name -like '_PYI_*' -or $vv.Name -eq '_MEIPASS2') {
        try { Remove-Item -Path ('Env:' + $vv.Name) -ErrorAction SilentlyContinue } catch {}
      }
    }
  } catch {}
}

Write-UpdateStatus 'script_started' 'update handoff started'

if (!(Test-Path $InstallerPath)) {
  Write-UpdateStatus 'error' 'installer file not found' 1001
  exit 1001
}

try {
  Stop-PidIfRunning $UiPid
  try {
    Wait-Process -Id $ParentPid -Timeout 90 -ErrorAction SilentlyContinue | Out-Null
  } catch {}
  try {
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
      Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {}

  Stop-ImageIfRunning 'webmail-summary'
  Stop-ImageIfRunning 'llama-server'
  Start-Sleep -Seconds 2

  # Retry kill in case processes respawned or were slow to stop.
  Stop-ImageIfRunning 'webmail-summary'
  Stop-ImageIfRunning 'llama-server'
  Start-Sleep -Seconds 1

  # Clean stale _MEI temp dirs that block PyInstaller bootstrapper.
  try {
    $meiDirs = Get-ChildItem -Path $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue
    foreach ($d in $meiDirs) {
      try { Remove-Item -Path $d.FullName -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    }
  } catch {}

  Write-UpdateStatus 'installer_launching' 'installer launching'
  $args = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', '/FORCECLOSEAPPLICATIONS', '/LOGCLOSEAPPLICATIONS', ('/LOG=' + $InstallLogPath))
  $p = Start-Process -FilePath $InstallerPath -ArgumentList $args -Wait -PassThru -ErrorAction Stop
  $code = 0
  if ($null -ne $p) { $code = [int]$p.ExitCode }

  if ($code -ne 0) {
    Write-UpdateStatus 'error' ('installer exit code: ' + $code) $code
    exit $code
  }

  Write-UpdateStatus 'installer_succeeded' 'installer completed' $code

  $targetExe = $RelaunchExe
  if (!( [string]::IsNullOrWhiteSpace($InstalledExePath) ) -and (Test-Path $InstalledExePath)) {
    $targetExe = $InstalledExePath
  }

  if (!( [string]::IsNullOrWhiteSpace($ExpectedVersion) ) -and (Test-Path $targetExe)) {
    try {
      $expected = [string]$ExpectedVersion
      $expected = $expected.Trim()
      if ($expected.StartsWith('v')) {
        $expected = $expected.Substring(1)
      }
      if ($expected -match '^([0-9]+(?:\.[0-9]+){1,3})') {
        $expected = $matches[1]
      }

      $vi = (Get-Item $targetExe).VersionInfo
      $pv = [string]$vi.ProductVersion
      if ([string]::IsNullOrWhiteSpace($pv)) {
        $pv = [string]$vi.FileVersion
      }
      $pv = $pv.Trim()
      if ($pv.StartsWith('v')) {
        $pv = $pv.Substring(1)
      }
      if ($pv -match '^([0-9]+(?:\.[0-9]+){1,3})') {
        $pv = $matches[1]
      }

      $expParts = @($expected.Split('.') | ForEach-Object { [int]$_ })
      $actParts = @($pv.Split('.') | ForEach-Object { [int]$_ })
      $verOk = $true
      for ($i = 0; $i -lt $expParts.Count; $i++) {
        if ($i -ge $actParts.Count -or $actParts[$i] -ne $expParts[$i]) {
          $verOk = $false
          break
        }
      }
      if (-not $verOk) {
        Write-UpdateStatus 'error' ('installed version mismatch: expected ' + $expected + ', actual ' + $pv) 1003
        exit 1003
      }
    } catch {
      $msgv = ''
      try { $msgv = $_.Exception.Message } catch { $msgv = 'unknown version check error' }
      Write-UpdateStatus 'error' ('installed version check failed: ' + $msgv) 1004
      exit 1004
    }
  }

  if (Test-Path $targetExe) {
    Reset-PyInstallerEnv
    $argsList = @()
    if (![string]::IsNullOrWhiteSpace($RelaunchArgsJson)) {
      try {
        $tmp = ConvertFrom-Json $RelaunchArgsJson
        if ($tmp -is [System.Array]) { $argsList = $tmp }
        elseif ($null -ne $tmp) { $argsList = @($tmp) }
      } catch {
        $argsList = @($RelaunchArgsJson)
      }
    }
    if ($argsList.Count -eq 0) {
      Start-Process -FilePath $targetExe -ErrorAction SilentlyContinue | Out-Null
    } else {
      Start-Process -FilePath $targetExe -ArgumentList $argsList -ErrorAction SilentlyContinue | Out-Null
    }
  }
  Write-UpdateStatus 'done' 'update install completed' $code
  exit $code
} catch {
  $msg = ''
  try { $msg = $_.Exception.Message } catch { $msg = 'unknown error' }
  Write-UpdateStatus 'error' ('update execution failed: ' + $msg) 1999
  exit 1999
}
