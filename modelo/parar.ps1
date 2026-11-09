$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and $_.ExecutablePath.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
