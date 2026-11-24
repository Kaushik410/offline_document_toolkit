#ifndef AppVersion
#define AppVersion "0.4.1"
#endif
[Setup]
AppId={{30C87873-B1E6-42EC-888D-CF13F0B89AF9}
AppName=Offline Document Toolkit
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\OfflineDocumentToolkit
DefaultGroupName=Offline Document Toolkit
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=OfflineDocumentToolkit-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\OfflineDocumentToolkit.exe
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\Offline Document Toolkit"; Filename: "{app}\OfflineDocumentToolkit.exe"
Name: "{autodesktop}\Offline Document Toolkit"; Filename: "{app}\OfflineDocumentToolkit.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\OfflineDocumentToolkit.exe"; Description: "Open Offline Document Toolkit"; Flags: nowait postinstall skipifsilent
