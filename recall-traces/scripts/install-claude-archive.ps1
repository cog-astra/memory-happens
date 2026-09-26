$ErrorActionPreference = 'Stop'
$python = (Get-Command python.exe).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe not found' }
$script = Join-Path $PSScriptRoot 'archive_claude.py'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}"' -f $script) -WorkingDirectory $PSScriptRoot
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'claude-session-archive' -Action $action -Trigger @($periodic, $logon) -Settings $settings -Description 'Preserve Claude Code JSONL and update a local searchable conversation corpus.' -Force | Out-Null
Start-ScheduledTask -TaskName 'claude-session-archive'
