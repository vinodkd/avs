; Inno Setup script for aVs Windows installer.
;
; Build with:
;   ISCC.exe /DMyAppVersion=0.1.0 packaging\avs.iss
; Or via build_windows.ps1 which injects the version automatically.
;
; Output: dist\aVs-<version>-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppName=aVs
AppVersion={#MyAppVersion}
AppVerName=aVs {#MyAppVersion}
AppPublisher=Vinod KD
AppPublisherURL=https://github.com/vinodkd/avs
AppSupportURL=https://github.com/vinodkd/avs/issues
AppUpdatesURL=https://github.com/vinodkd/avs/releases
DefaultDirName={autopf}\aVs
DefaultGroupName=aVs
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=aVs-{#MyAppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Let the user choose per-user vs machine-wide at install time
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
; Icon — optional; installer proceeds without one if file is absent
#ifexist "packaging\avs.ico"
  SetupIconFile=packaging\avs.ico
  UninstallDisplayIcon={app}\avs.exe
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Entire PyInstaller onedir output — recurse into _internal/ and any subdirs
Source: "..\dist\avs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\aVs";                       Filename: "{app}\avs.exe"
Name: "{group}\{cm:UninstallProgram,aVs}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\aVs";                 Filename: "{app}\avs.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\avs.exe"; Description: "{cm:LaunchProgram,aVs}"; Flags: nowait postinstall skipifsilent
