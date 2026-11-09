# Instalador do Ragquest (executado pelo Ragquest-Instalador.exe)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'Instalando o Ragquest'
$src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $env:LOCALAPPDATA 'Ragquest'
$kn   = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Ragquest - Conhecimento'
$oll  = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
$ollApp = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
try { Start-Transcript -Path (Join-Path $dest 'instalacao.log') -Force | Out-Null } catch {}

function Passo($n, $t) { Write-Host ''; Write-Host "  [$n/6] $t" -ForegroundColor Cyan }
function Falha($t) {
  Write-Host ''; Write-Host "  ERRO: $t" -ForegroundColor Red
  Write-Host "  Envie ao suporte o arquivo: $dest\instalacao.log"
  try { Stop-Transcript | Out-Null } catch {}
  try { Read-Host '  Pressione Enter para sair' | Out-Null } catch { Start-Sleep 60 }
  exit 1
}
Clear-Host
Write-Host ''
Write-Host '  ==============================================' -ForegroundColor Magenta
Write-Host '     RAGQUEST  -  Assistente de conhecimento' -ForegroundColor Magenta
Write-Host '  ==============================================' -ForegroundColor Magenta
Write-Host ''
Write-Host '  A instalacao leva de 10 a 40 minutos (baixa ~6 GB de modelos de IA).'
Write-Host '  Nao feche esta janela.'

try {
  Passo 1 'Copiando arquivos...'
  $parar = Join-Path $dest 'parar.ps1'
  if (Test-Path $parar) {          # atualizacao: para a versao em execucao
    $ErrorActionPreference = 'Continue'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $parar
    $ErrorActionPreference = 'Stop'
    Start-Sleep 2
  }
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  foreach ($d in 'app', 'python') { if (Test-Path (Join-Path $dest $d)) { Remove-Item (Join-Path $dest $d) -Recurse -Force } }
  $ErrorActionPreference = 'Continue'
  & tar.exe -xf (Join-Path $src 'ragquest.zip') -C $dest
  if ($LASTEXITCODE -ne 0) { Expand-Archive -Path (Join-Path $src 'ragquest.zip') -DestinationPath $dest -Force }
  $ErrorActionPreference = 'Stop'

  Passo 2 'Criando a pasta de conhecimento...'
  foreach ($s in 'pop', 'manual', 'diretriz', 'outros') { New-Item -ItemType Directory -Force -Path (Join-Path $kn $s) | Out-Null }
  Copy-Item (Join-Path $dest '_LEIA-ME.txt') (Join-Path $kn '_LEIA-ME.txt') -Force
  Write-Host "      $kn"

  Passo 3 'Verificando o computador...'
  $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
  $nvidia = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
  if ($nvidia -and $ramGB -ge 12) { $modelo = 'qwen2.5:7b' } else { $modelo = 'qwen2.5:3b' }
  Write-Host "      Memoria: $ramGB GB | Placa NVIDIA: $(if($nvidia){'sim'}else{'nao'}) | Modelo: $modelo"
  $cfg = Join-Path $dest 'config.env'
  if (-not (Test-Path $cfg)) {
@"
# Configuracao do Ragquest
PORTA=8765
# Senha de acesso (vazio = sem senha; o Ragquest so aceita acesso deste computador)
SENHA=
# Acesso pela rede da empresa (1 = outros computadores acessam por http://IP:8765; exige SENHA)
ACESSO_REDE=0
OLLAMA_MODEL=$modelo
EMBED_MODEL=bge-m3
PASTA_CONHECIMENTO=$kn
SCAN_SEGUNDOS=30
# Buscar na internet quando nao achar nos documentos (1 = sim, 0 = nao)
BUSCA_WEB=1
SIMILARIDADE_MINIMA=0.35
RECRAWL_HOUR=3
"@ | Set-Content -Path $cfg -Encoding UTF8
  } else {
    $modelo = ((Get-Content $cfg | Where-Object { $_ -like 'OLLAMA_MODEL=*' }) -split '=', 2)[1]
  }

  Passo 4 'Instalando o motor de IA (Ollama)...'
  if (Test-Path $oll) { Write-Host '      Ja instalado.' } else {
    $tmp = Join-Path $env:TEMP 'OllamaSetup.exe'
    $ErrorActionPreference = 'Continue'
    & curl.exe -L --fail -o $tmp 'https://ollama.com/download/OllamaSetup.exe'
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { Falha 'Nao foi possivel baixar o Ollama. Verifique a internet.' }
    Write-Host '      Instalando o Ollama...'
    $p = Start-Process -FilePath $tmp -ArgumentList '/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES' -PassThru
    $p.WaitForExit()                 # espera so o instalador (nao o app que ele abre)
    for ($i = 0; $i -lt 30 -and -not (Test-Path $oll); $i++) { Start-Sleep 2 }
    if (-not (Test-Path $oll)) { Falha 'A instalacao do Ollama nao terminou.' }
  }
  function OllamaOk { try { $c = New-Object Net.Sockets.TcpClient; $r = $c.ConnectAsync('127.0.0.1', 11434).Wait(1500); $c.Close(); return $r } catch { return $false } }
  $ok = OllamaOk
  if (-not $ok) { Start-Process $ollApp; for ($i = 0; $i -lt 60 -and -not $ok; $i++) { Start-Sleep 2; $ok = OllamaOk } }
  if (-not $ok) { Falha 'O Ollama nao iniciou.' }

  Passo 5 "Baixando os modelos de IA (bge-m3 e $modelo)..."
  $ErrorActionPreference = 'Continue'
  & $oll pull bge-m3;  if ($LASTEXITCODE -ne 0) { Falha 'Falha ao baixar o modelo bge-m3.' }
  & $oll pull $modelo; if ($LASTEXITCODE -ne 0) { Falha "Falha ao baixar o modelo $modelo." }
  $ErrorActionPreference = 'Stop'

  Passo 6 'Criando atalhos...'
  $sh = New-Object -ComObject WScript.Shell
  $ico = Join-Path $dest 'app\static\ragquest.ico'
  $pyw = Join-Path $dest 'python\pythonw.exe'
  function Atalho($path, $target, $argumentos, $icon) {
    $l = $sh.CreateShortcut($path); $l.TargetPath = $target; $l.Arguments = $argumentos
    $l.WorkingDirectory = $dest; if ($icon) { $l.IconLocation = $icon }; $l.Save()
  }
  $desk = [Environment]::GetFolderPath('Desktop')
  $prog = Join-Path ([Environment]::GetFolderPath('Programs')) 'Ragquest'
  New-Item -ItemType Directory -Force -Path $prog | Out-Null
  $ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  Atalho (Join-Path $desk 'Ragquest.lnk') $pyw "`"$dest\iniciar.pyw`"" $ico
  Atalho (Join-Path $prog 'Ragquest.lnk') $pyw "`"$dest\iniciar.pyw`"" $ico
  Atalho (Join-Path $desk 'Ragquest - Conhecimento.lnk') $kn '' "$env:WINDIR\System32\shell32.dll,4"
  Atalho (Join-Path $prog 'Parar Ragquest.lnk') $ps "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dest\parar.ps1`"" $ico
  Atalho (Join-Path $prog 'Desinstalar Ragquest.lnk') $ps "-NoProfile -ExecutionPolicy Bypass -File `"$dest\desinstalar.ps1`"" $ico
  Atalho (Join-Path $prog 'Pasta de conhecimento.lnk') $kn '' "$env:WINDIR\System32\shell32.dll,4"
  $ver = (Get-Content (Join-Path $dest 'versao.txt') -ErrorAction SilentlyContinue)
  $u = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Ragquest'
  New-Item -Path $u -Force | Out-Null
  Set-ItemProperty $u DisplayName 'Ragquest - Assistente de conhecimento'
  Set-ItemProperty $u DisplayVersion "$ver"
  Set-ItemProperty $u Publisher 'Protti'
  Set-ItemProperty $u DisplayIcon $ico
  Set-ItemProperty $u InstallLocation $dest
  Set-ItemProperty $u UninstallString "$ps -NoProfile -ExecutionPolicy Bypass -File `"$dest\desinstalar.ps1`""
  Set-ItemProperty $u NoModify 1 -Type DWord; Set-ItemProperty $u NoRepair 1 -Type DWord
} catch { Falha $_.Exception.Message }

Write-Host ''
Write-Host '  Instalacao concluida!' -ForegroundColor Green
Write-Host '  Atalhos "Ragquest" e "Ragquest - Conhecimento" criados na Area de Trabalho.'
Write-Host '  O Ragquest vai abrir no navegador e mostrar o CODIGO DA MAQUINA para ativacao.'
Start-Process -FilePath $pyw -ArgumentList "`"$dest\iniciar.pyw`"" -WorkingDirectory $dest
try { Stop-Transcript | Out-Null } catch {}
Start-Sleep 8
