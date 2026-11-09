$ErrorActionPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'Desinstalar Ragquest'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host ''
Write-Host '  Desinstalar o Ragquest' -ForegroundColor Magenta
Write-Host '  A pasta de conhecimento (seus documentos) NAO sera apagada.'
Write-Host ''
$r = Read-Host '  Confirma a desinstalacao? (S/N)'
if ($r -notmatch '^[sS]') { exit }
& (Join-Path $base 'parar.ps1')
Start-Sleep 2
$desk = [Environment]::GetFolderPath('Desktop')
$prog = Join-Path ([Environment]::GetFolderPath('Programs')) 'Ragquest'
Remove-Item (Join-Path $desk 'Ragquest.lnk'), (Join-Path $desk 'Ragquest - Conhecimento.lnk') -Force
Remove-Item $prog -Recurse -Force
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Ragquest' -Recurse -Force
Set-Location $env:TEMP
Remove-Item $base -Recurse -Force
Write-Host ''
Write-Host '  Ragquest removido. Os modelos de IA continuam no Ollama (pode remover pelo Ollama se quiser).'
Start-Sleep 5
