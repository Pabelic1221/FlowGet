#define MyAppName "FlowGet"
#define MyAppVersion "1.3.0"

[Setup]
AppId={{6F1D2C3B-8A47-4E59-B0C2-1A9E5D7F3B42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=FlowGet-Setup
Compression=lzma
SetupIconFile=assets\icon.ico
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\FlowGet.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\FlowGet.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\FlowGet.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\FlowGet.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlowGet.exe"; Description: "Launch FlowGet"; Flags: nowait postinstall skipifsilent
Filename: "{app}\FlowGet.exe"; Flags: nowait; Check: WizardSilent
