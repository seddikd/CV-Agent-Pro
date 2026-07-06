; Installeur Inno Setup pour CV Agent (application desktop Windows).
; Compilation : build_installer.ps1  (ou : ISCC.exe installer.iss)
; Produit : dist\CV-Agent-Setup.exe

#define AppName "CV Agent"
#define AppVersion "1.0.0"
#define AppPublisher "CLab Labs"
#define AppExe "CV-Agent.exe"

[Setup]
AppId={{7C1B2E4A-9D3F-4E88-B6A1-CV0AGENT0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\CV-Agent
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installation par utilisateur : pas de prompt UAC (les données vont déjà dans %LOCALAPPDATA%).
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=CV-Agent-Setup
SetupIconFile=static\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Ferme l'app si elle tourne pendant une mise à jour.
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
; Tout le dossier autonome produit par PyInstaller (CV-Agent.exe + _internal\).
Source: "dist\CV-Agent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  AdminPage: TInputQueryWizardPage;

procedure InitializeWizard();
begin
  { Page de saisie du compte administrateur (après le choix du dossier). }
  AdminPage := CreateInputQueryPage(wpSelectDir,
    'Compte administrateur',
    'Identifiants d''accès à CV Agent',
    'Ces identifiants vous serviront à vous connecter à l''application après l''installation.');
  AdminPage.Add('Nom complet :', False);
  AdminPage.Add('Email :', False);
  AdminPage.Add('Mot de passe (8 caractères minimum) :', True);
  AdminPage.Add('Confirmer le mot de passe :', True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (AdminPage <> nil) and (CurPageID = AdminPage.ID) then
  begin
    if Trim(AdminPage.Values[1]) = '' then
    begin
      MsgBox('Veuillez saisir un email.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Length(AdminPage.Values[2]) < 8 then
    begin
      MsgBox('Le mot de passe doit contenir au moins 8 caractères.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if AdminPage.Values[2] <> AdminPage.Values[3] then
    begin
      MsgBox('Les mots de passe ne correspondent pas.', mbError, MB_OK);
      Result := False; Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  tmpFile, content: string;
  rc: Integer;
begin
  { Après l'installation des fichiers : créer le compte admin via l'application. }
  if CurStep = ssPostInstall then
  begin
    if (AdminPage <> nil) and (Trim(AdminPage.Values[1]) <> '') then
    begin
      tmpFile := ExpandConstant('{tmp}\cvadmin.txt');
      { email / nom / mot de passe sur 3 lignes }
      content := AdminPage.Values[1] + #13#10 + AdminPage.Values[0] + #13#10 + AdminPage.Values[2];
      if SaveStringToFile(tmpFile, content, False) then
      begin
        Exec(ExpandConstant('{app}\{#AppExe}'), '--create-admin "' + tmpFile + '"',
             '', SW_HIDE, ewWaitUntilTerminated, rc);
        DeleteFile(tmpFile);
      end;
    end;
  end;
end;
