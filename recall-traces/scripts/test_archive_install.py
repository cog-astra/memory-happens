import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parent
POWERSHELL = shutil.which('powershell.exe')
HARNESS = r'''
param($Installer, $Options, $Result, $Python)
$ErrorActionPreference = 'Stop'
$global:action = $null
$global:registered = $false
$global:started = $false
function Get-Command { param($Name) @{Source=$Python} }
function New-ScheduledTaskAction {
    param($Execute, $Argument, $WorkingDirectory)
    $global:action = @{execute=$Execute; arguments=$Argument; cwd=$WorkingDirectory}
    $global:action
}
function New-ScheduledTaskTrigger { param([switch]$Once, $At, $RepetitionInterval, [switch]$AtLogOn, $User) 'trigger' }
function New-ScheduledTaskSettingsSet {
    param([switch]$StartWhenAvailable, $MultipleInstances, [switch]$AllowStartIfOnBatteries,
          [switch]$DontStopIfGoingOnBatteries, $ExecutionTimeLimit)
    'settings'
}
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Settings, $Description, [switch]$Force) $global:registered=$true }
function Start-ScheduledTask { param($TaskName) $global:started=$true }
$settings = @{}
(Get-Content -LiteralPath $Options -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $settings[$_.Name]=$_.Value }
$failure = $null
try { & $Installer @settings } catch { $failure=$_.Exception.Message }
@{action=$global:action; registered=$global:registered; started=$global:started; error=$failure} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Result -Encoding UTF8
'''


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Windows PowerShell installers')
class ArchiveInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.harness = self.root / 'capture.ps1'
        self.harness.write_text(HARNESS, encoding='utf-8')
        (self.root / 'pythonw.exe').touch()

    def install(self, client, **options):
        config = self.root / 'options.json'
        result = self.root / 'result.json'
        config.write_text(json.dumps(options), encoding='utf-8')
        subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(self.harness), str(SCRIPTS / f'install-{client}-archive.ps1'),
                        str(config), str(result), str(self.root / 'python.exe')],
                       check=True, capture_output=True, timeout=30)
        return json.loads(result.read_text(encoding='utf-8-sig'))

    def test_missing_paths_leave_existing_schedule_untouched(self):
        for client in ('claude', 'codex'):
            for options in ({}, {'Source': 'raw'}, {'Destination': 'archive'}):
                with self.subTest(client=client, options=options):
                    result = self.install(client, **options)
                    self.assertIsNotNone(result['error'])
                    self.assertIn('Specify -Source', result['error'])
                    self.assertFalse(result['registered'])
                    self.assertFalse(result['started'])
                    self.assertIsNone(result['action'])

    def test_scheduled_command_exports_to_chosen_corpus_after_reinstall(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                source = self.root / f'{client} raw сессии'
                archive = self.root / f'{client} archive архив'
                folder = source / ('sessions' if client == 'codex' else 'project')
                folder.mkdir(parents=True)
                message = {'role': 'user', 'content': [{'type': 'input_text', 'text': 'installer witness'}]}
                if client == 'codex':
                    data = {'type': 'response_item', 'payload': {'type': 'message', **message}}
                else:
                    data = {'type': 'user', 'sessionId': 'fixture', 'message': {'role': 'user', 'content': 'installer witness'}}
                (folder / 'fixture.jsonl').write_text(json.dumps(data) + '\n', encoding='utf-8')
                first = self.install(client, Source=str(source) + '\\', Destination=str(archive) + '\\')
                second = self.install(client, Source=str(source), Destination=str(archive))
                for result in (first, second):
                    self.assertIsNone(result['error'])
                    self.assertTrue(result['registered'])
                    self.assertTrue(result['started'])
                    action = result['action']
                    self.assertIn(source.as_posix(), action['arguments'])
                    self.assertIn(archive.as_posix(), action['arguments'])
                    subprocess.run(f'"{sys.executable}" {action["arguments"]}', cwd=action['cwd'],
                                   check=True, capture_output=True, timeout=30)
                passages = list((archive / 'sessions-corpus').rglob('*.md'))
                self.assertEqual(len(passages), 1)
                self.assertIn('installer witness', passages[0].read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
