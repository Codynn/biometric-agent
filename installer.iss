; installer.iss
; Inno Setup script for Biometric Attendance Agent
; Requires Inno Setup 6+ — https://jrsoftware.org/isinfo.php

#define AppName      "Biometric Attendance Agent"
#define AppVersion   "1.0.0"
#define AppPublisher "Biometric"
#define AppExeName   "BiometricAgent.exe"
#define AppId        "{{A3F2C1D0-8B4E-4F7A-9C2D-1E5B6A3F8D9C}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://Biometric.app
AppSupportURL=https://Biometric.app
AppUpdatesURL=https://Biometric.app
; Install to Program Files
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Allow user to choose whether to create Start Menu folder
AllowNoIcons=yes
; Output
OutputDir=installer_output
OutputBaseFilename=BiometricAgentSetup
; Icon
SetupIconFile=assets\icon.ico
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Require admin so we can write to Program Files and HKLM
PrivilegesRequired=admin
; Minimum Windows version: Windows 10 (10.0)
MinVersion=10.0
; Wizard style
WizardStyle=modern
; Uninstaller
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; "Start on login" checkbox — ticked by default
Name: "autostart"; Description: "Start {#AppName} automatically when Windows starts"; GroupDescription: "Startup:"; Flags: checkedonce

[Files]
; Copy everything from the PyInstaller output folder
Source: "dist\BiometricAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\{#AppName}";        Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Registry]
; Auto-start on Windows login (HKCU so it runs as the logged-in user — correct for tray apps)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExeName}"""; \
  Flags: uninsdeletevalue; \
  Tasks: autostart

[Run]
; Launch the app after install finishes (without waiting for it)
Filename: "{app}\{#AppExeName}"; \
  Description: "Launch {#AppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill the running process before uninstall so files can be deleted
Filename: "taskkill"; Parameters: "/f /im {#AppExeName}"; Flags: runhidden; RunOnceId: "KillAgent"

[Code]
// Kill any running instance before upgrading/reinstalling
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    Exec('taskkill', '/f /im {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000); // give it a moment to die
  end;
end;
