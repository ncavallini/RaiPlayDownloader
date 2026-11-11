; Inno Setup script for the Windows installer. Built by .github/workflows/release.yml:
;   iscc /DAppVersion=1.2.3 installer.iss   (expects RaiPlayDownloader-windows.exe next to this file)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; never change AppId: it's how upgrades and the uninstaller find the existing install
AppId={{E5A785AC-7E96-4F03-B300-B24494EAD852}
AppName=RaiPlay Downloader
AppVersion={#AppVersion}
AppPublisher=ncavallini
AppPublisherURL=https://github.com/ncavallini/RaiPlayDownloader
DefaultDirName={autopf}\RaiPlay Downloader
DefaultGroupName=RaiPlay Downloader
DisableProgramGroupPage=yes
; installs per-user without admin by default; the dialog lets users pick "all users" instead
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\RaiPlayDownloader.exe
OutputDir=.
OutputBaseFilename=RaiPlayDownloader-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "RaiPlayDownloader-windows.exe"; DestDir: "{app}"; DestName: "RaiPlayDownloader.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\RaiPlay Downloader"; Filename: "{app}\RaiPlayDownloader.exe"
Name: "{group}\{cm:UninstallProgram,RaiPlay Downloader}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RaiPlay Downloader"; Filename: "{app}\RaiPlayDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RaiPlayDownloader.exe"; Description: "{cm:LaunchProgram,RaiPlay Downloader}"; Flags: nowait postinstall skipifsilent
