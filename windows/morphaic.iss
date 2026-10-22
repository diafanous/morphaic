#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\dist\morphaic-1.3.0.exe"
#endif

[Setup]
; Preserve the test installer identity so existing installations upgrade cleanly.
AppId=Diafanous.Morphaic.Test
AppName=Morphaic
AppVersion={#AppVersion}
AppPublisher=diafanous
DefaultDirName={localappdata}\Programs\Morphaic
DefaultGroupName=Morphaic
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=morphaic-{#AppVersion}-setup
SetupIconFile=..\assets\morphaic.ico
UninstallDisplayIcon={app}\morphaic.ico
UninstallDisplayName=Morphaic
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=1.3.0.0
VersionInfoDescription=Morphaic Test Setup
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

Name: "removeold"; Description: "Uninstall the previous Morphaic installation before installing"; GroupDescription: "Previous installation:"; Flags: unchecked; Check: HasPreviousInstallation

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "morphaic.exe"; Flags: ignoreversion
Source: "..\assets\morphaic.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Morphaic"; Filename: "{app}\morphaic.exe"; IconFilename: "{app}\morphaic.ico"; AppUserModelID: "Diafanous.Morphaic.Test"
Name: "{autodesktop}\Morphaic"; Filename: "{app}\morphaic.exe"; IconFilename: "{app}\morphaic.ico"; Tasks: desktopicon; AppUserModelID: "Diafanous.Morphaic.Test"

[Run]
Filename: "{app}\morphaic.exe"; Description: "Open Morphaic"; Flags: nowait postinstall skipifsilent

[Code]
function PreviousUninstaller(): String;
var
  Command: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\Diafanous.Morphaic.Test_is1',
    'UninstallString', Command) then
  begin
    Command := RemoveQuotes(Trim(Command));
    if FileExists(Command) and (CompareText(ExtractFileExt(Command), '.exe') = 0) and
      (CompareText(Copy(ExtractFileName(Command), 1, 5), 'unins') = 0) then
      Result := Command;
  end;
end;

function HasPreviousInstallation(): Boolean;
begin
  Result := PreviousUninstaller() <> '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Uninstaller: String;
  ExitCode: Integer;
begin
  Result := '';
  if not WizardIsTaskSelected('removeold') then Exit;
  Uninstaller := PreviousUninstaller();
  if Uninstaller = '' then Exit;
  if not Exec(Uninstaller, '/SILENT /SUPPRESSMSGBOXES /NORESTART', '',
    SW_SHOW, ewWaitUntilTerminated, ExitCode) then
    Result := 'Could not start the previous uninstaller. Uncheck the removal option to update in place.'
  else if ExitCode <> 0 then
    Result := 'The previous installation could not be removed. Close Morphaic and try again, or uncheck the removal option.';
end;
