; Inno Setup — Ncurity F5 Big-IP Managing Tool (Windows installer)
; Prerequisite: scripts\build_windows.ps1 (dist\NcurityF5Tool\)
; Compile: ISCC.exe packaging\NcurityF5Tool.iss  (or scripts\build_windows.ps1 -Installer)

#define MyAppName "Ncurity F5 Big-IP Managing Tool"
#define MyAppExeName "NcurityF5Tool.exe"
#define MyAppPublisher "Ncurity"
#define MyAppURL "https://www.ncurity.co.kr"

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{A8F3C2E1-9B4D-4F5A-8C3E-010203040506}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\Ncurity\F5 Big-IP Managing Tool
DefaultGroupName=Ncurity F5 Tool
AllowNoIcons=yes
LicenseFile=
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=NcurityF5Tool-Setup-{#MyAppVersion}
SetupIconFile=..\app\resources\ncurity_app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=no
UninstallDisplayName={#MyAppName}
InfoBeforeFile=release_notes_before.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\NcurityF5Tool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\RELEASE_NOTES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\release-notes\1.0.0.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion
Source: "..\docs\release-notes\1.1.0.md"; DestDir: "{app}\docs\release-notes"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Release Notes"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\docs\RELEASE_NOTES.md"""
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
