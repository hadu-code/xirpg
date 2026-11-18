# Puts an "XIRPG" shortcut on your desktop that opens the launcher window (no console).
# It points at "XIRPG.exe" when that is here (players), else at launcher_gui.pyw with Python (the dev copy).
# (a GitHub download is named XIRPG.exe: either name works)
$exe = Get-ChildItem $PSScriptRoot -Filter "XIRPG.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if ($exe) {
  $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "XIRPG.lnk"
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $s.TargetPath = $exe
  $s.WorkingDirectory = $PSScriptRoot
  $s.IconLocation = $exe
  $s.Save()
  Write-Host "Created: $lnk" -ForegroundColor Green
  exit 0
}
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe" }
if (-not (Test-Path $pyw)) { Write-Host "Could not find pythonw.exe. Is Python installed?" -ForegroundColor Red; exit 1 }

python -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Your Python does not include tkinter (the window toolkit). Re-run the Python installer, choose Modify, and tick 'tcl/tk and IDLE'." -ForegroundColor Yellow
}

$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "XIRPG.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$PSScriptRoot\launcher_gui.pyw`""
$s.WorkingDirectory = $PSScriptRoot
$ico = Join-Path $PSScriptRoot "assets\ui\icon.ico"
if (Test-Path $ico) { $s.IconLocation = $ico }
$s.Save()
Write-Host "Created: $lnk" -ForegroundColor Green
