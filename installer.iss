#define MyAppName "FlowGet"
#define MyAppVersion "1.4.0"
#ifndef IconDir
  #define IconDir "files-logo"
#endif

[Setup]
AppId={{6F1D2C3B-8A47-4E59-B0C2-1A9E5D7F3B42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=FlowGet
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=FlowGet-Setup
SetupIconFile={#IconDir}\icon.ico
UninstallDisplayIcon={app}\FlowGet.exe
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\FlowGet.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\FlowGet.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\FlowGet.exe"; Tasks: desktopicon

[Run]
; Install the VC++ runtime silently only when it is not already installed.
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ Runtime..."; Flags: waituntilterminated; Check: not IsVCRedistInstalled
Filename: "{app}\FlowGet.exe"; Description: "Launch FlowGet"; Flags: nowait postinstall skipifsilent
Filename: "{app}\FlowGet.exe"; Flags: nowait; Check: WizardSilent

[Code]
function IsVCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result :=
    RegQueryDWordValue(
      HKLM64,
      'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
      'Installed',
      Installed
    ) and (Installed = 1);
end;
