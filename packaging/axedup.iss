; Inno Setup script for AxEdUp Windows installer.
;
; Build with:
;   ISCC.exe /DMyAppVersion=0.1.0 packaging\axedup.iss
; Or via build_windows.ps1 which injects the version automatically.
;
; Output: dist\AxEdUp-<version>-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppName=AxEdUp
AppVersion={#MyAppVersion}
AppVerName=AxEdUp {#MyAppVersion}
AppPublisher=Vinod KD
AppPublisherURL=https://github.com/vinodkd/axedup
AppSupportURL=https://github.com/vinodkd/axedup/issues
AppUpdatesURL=https://github.com/vinodkd/axedup/releases
DefaultDirName={autopf}\AxEdUp
DefaultGroupName=AxEdUp
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=AxEdUp-{#MyAppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Let the user choose per-user vs machine-wide at install time
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
; Icon — optional; installer proceeds without one if file is absent
#ifexist "packaging\axedup.ico"
  SetupIconFile=packaging\axedup.ico
  UninstallDisplayIcon={app}\axedup.exe
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Entire PyInstaller onedir output — recurse into _internal/ and any subdirs
Source: "dist\axedup\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AxEdUp";                       Filename: "{app}\axedup.exe"
Name: "{group}\{cm:UninstallProgram,AxEdUp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AxEdUp";                 Filename: "{app}\axedup.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\axedup.exe"; Description: "{cm:LaunchProgram,AxEdUp}"; Flags: nowait postinstall skipifsilent
