; Instalador do Ragquest (Inno Setup 6) — gerado pelo Ragquest Admin
#ifndef Versao
  #define Versao "1.0.0"
#endif
#ifndef Fonte
  #define Fonte "build\Ragquest"
#endif
#ifndef Saida
  #define Saida "saida"
#endif

[Setup]
AppId={{9B406FA0-DB28-40E0-BECB-8A8C163A5C25}
AppName=Ragquest
AppVersion={#Versao}
AppVerName=Ragquest {#Versao}
AppPublisher=Protti
DefaultDirName={localappdata}\Ragquest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=lowest
OutputDir={#Saida}
OutputBaseFilename=Ragquest-Instalador-{#Versao}
SetupIconFile={#Fonte}\app\static\ragquest.ico
UninstallDisplayIcon={app}\app\static\ragquest.ico
WizardSmallImageFile={#Fonte}\app\static\wizard-58.bmp,{#Fonte}\app\static\wizard-116.bmp
UninstallDisplayName=Ragquest - Assistente de conhecimento
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#Versao}
VersionInfoDescription=Ragquest - Assistente de conhecimento

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
ptbr.WelcomeLabel2=Este assistente vai instalar o Ragquest no seu computador.%n%nSe o motor de IA (Ollama) não estiver instalado, ele será baixado e instalado automaticamente (cerca de 1 GB).%n%nNa primeira abertura, o Ragquest baixa os modelos de IA (3 a 6 GB) e depois pede a chave de licença.

[Tasks]
Name: "desktopicon"; Description: "Criar atalhos na Área de Trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#Fonte}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Fonte}\_LEIA-ME.txt"; DestDir: "{userdocs}\Ragquest - Conhecimento"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{userdocs}\Ragquest - Conhecimento\pop"; Flags: uninsneveruninstall
Name: "{userdocs}\Ragquest - Conhecimento\manual"; Flags: uninsneveruninstall
Name: "{userdocs}\Ragquest - Conhecimento\diretriz"; Flags: uninsneveruninstall
Name: "{userdocs}\Ragquest - Conhecimento\outros"; Flags: uninsneveruninstall

[Icons]
Name: "{autoprograms}\Ragquest\Ragquest"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\iniciar.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\static\ragquest.ico"
Name: "{autoprograms}\Ragquest\Parar Ragquest"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\parar.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\static\ragquest.ico"
Name: "{autoprograms}\Ragquest\Pasta de conhecimento"; Filename: "{userdocs}\Ragquest - Conhecimento"
Name: "{autoprograms}\Ragquest\Desinstalar Ragquest"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Ragquest"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\iniciar.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\static\ragquest.ico"; Tasks: desktopicon
Name: "{autodesktop}\Ragquest - Conhecimento"; Filename: "{userdocs}\Ragquest - Conhecimento"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ragquest"; ValueData: """{app}\python\pythonw.exe"" ""{app}\iniciar.pyw"" --sem-navegador"; Flags: uninsdeletevalue; Check: ModoServidor

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\iniciar.pyw"""; WorkingDir: "{app}"; Description: "Abrir o Ragquest agora"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ModoPage: TInputOptionWizardPage;
  Servidor: Boolean;

function JaConfigurado: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Ragquest\config.env'));
end;

function ModoServidor: Boolean;
begin
  Result := Servidor;   { decidido na pagina "Como o Ragquest vai ser usado?" }
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (ModoPage <> nil) and (PageID = ModoPage.ID) and JaConfigurado;
end;

procedure LiberarFirewall;
var
  ResultCode: Integer;
begin
  ShellExec('runas', ExpandConstant('{sys}\netsh.exe'),
    'advfirewall firewall add rule name="Ragquest" dir=in action=allow protocol=TCP localport=8765 program="' +
    ExpandConstant('{app}\python\pythonw.exe') + '" profile=any description="Acesso dos funcionarios ao Ragquest (login e senha obrigatorios)"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function OllamaInstalado: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

procedure DesligarRagquest;
var
  Http: Variant;
begin
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(1000, 1000, 1000, 2000);
    Http.Open('POST', 'http://127.0.0.1:8765/desligar', False);
    Http.Send('');
    Sleep(1500);
  except
  end;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  ModoPage := CreateInputOptionPage(wpSelectTasks, 'Como o Ragquest vai ser usado?',
    'Escolha quem vai acessar o Ragquest instalado neste computador.',
    'Você pode mudar isso depois, no Ragquest, em Usuários > Acesso dos funcionários.', True, False);
  ModoPage.Add('Só neste computador');
  ModoPage.Add('Servidor da empresa: os funcionários acessam pela rede, no computador ou no celular (o Windows vai pedir permissão para liberar o firewall)');
  ModoPage.Values[0] := True;
  DownloadPage := CreateDownloadPage('Baixando o motor de IA', 'Baixando o Ollama (cerca de 1 GB). Aguarde...', @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (ModoPage <> nil) and (CurPageID = ModoPage.ID) then
    Servidor := ModoPage.Values[1] and (not JaConfigurado);
  if (CurPageID = wpReady) and (not OllamaInstalado) then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('https://ollama.com/download/OllamaSetup.exe', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        Result := True;
      except
        if not DownloadPage.AbortedByUser then
          SuppressibleMsgBox('Não foi possível baixar o Ollama: ' + AddPeriod(GetExceptionMessage) + #13#10 +
            'Verifique a conexão com a internet e tente novamente.', mbCriticalError, MB_OK, IDOK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  DesligarRagquest;
  // reinicia o motor de IA: versoes antigas o ligavam de um jeito que abria telas pretas de terminal
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ollama.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ollama_llama_server.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Cfg, Kn: String;
  L: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    if (not OllamaInstalado) and FileExists(ExpandConstant('{tmp}\OllamaSetup.exe')) then
    begin
      WizardForm.StatusLabel.Caption := 'Instalando o motor de IA (Ollama)... isso pode levar alguns minutos.';
      Exec(ExpandConstant('{tmp}\OllamaSetup.exe'), '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      // o Ollama abre a propria janela ao terminar; fecha (o Ragquest liga o motor em segundo plano)
      Sleep(3000);
      Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "ollama app.exe"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
    Cfg := ExpandConstant('{app}\config.env');
    if not FileExists(Cfg) then
    begin
      Kn := ExpandConstant('{userdocs}\Ragquest - Conhecimento');
      SetArrayLength(L, 11);
      L[0] := '# Configuracao do Ragquest';
      L[1] := 'PORTA=8765';
      L[2] := '# Acesso pela rede (1 = funcionarios acessam por http://IP-do-servidor:8765 com login e senha)';
      if ModoServidor then
        L[3] := 'ACESSO_REDE=1'
      else
        L[3] := 'ACESSO_REDE=0';
      L[4] := 'EMBED_MODEL=bge-m3';
      L[5] := 'PASTA_CONHECIMENTO=' + Kn;
      L[6] := 'SCAN_SEGUNDOS=30';
      L[7] := '# Buscar na internet quando nao achar nos documentos (1 = sim, 0 = nao)';
      L[8] := 'BUSCA_WEB=1';
      L[9] := 'SIMILARIDADE_MINIMA=0.35';
      L[10] := 'RECRAWL_HOUR=3';
      SaveStringsToUTF8File(Cfg, L, False);
      if ModoServidor then
      begin
        WizardForm.StatusLabel.Caption := 'Liberando o acesso pela rede (o Windows vai pedir permissão)...';
        LiberarFirewall;
      end;
    end;
  end;
end;

function InitializeUninstall: Boolean;
begin
  DesligarRagquest;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Ragquest');
    if Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="Ragquest"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
      ShellExec('runas', ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall delete rule name="Ragquest"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
