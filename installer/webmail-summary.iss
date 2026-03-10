#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif

#define MyAppName "webmail-summary"
#define MyAppPublisher "webmail-summary"
#define MyAppExeName "webmail-summary.exe"
#define MyAppVersionInfo MyAppVersion + ".0"

[Setup]
AppId={{7E4E6D1D-4F21-4A0B-9B4A-2E5C8D1C9A67}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersionInfo}
AppPublisher={#MyAppPublisher}
SetupIconFile=..\landing\app\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousTasks=no
CloseApplications=yes
ForceCloseApplications=yes
RestartApplications=no
OutputDir=..\release
OutputBaseFilename=webmail-summary-setup-windows-x64
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업"; Flags: checked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\landing\app\favicon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\favicon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\favicon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} 실행"; Flags: nowait postinstall skipifsilent

[Code]
procedure KillRunningAppProcesses();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "{#MyAppExeName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunningAppProcesses();
  Result := '';
end;
