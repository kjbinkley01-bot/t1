; Clicker's Windows installer (Inno Setup 6). Build the app first (python -m PyInstaller Clicker.spec), then:
;   iscc /DAppVersion=2.11.0 installer\clicker.iss      ->  dist\Clicker-Setup.exe
;
; It installs for just you by default (no admin prompt, into %LOCALAPPDATA%\Programs\Clicker); the first
; page lets you install for everyone on the PC instead (Program Files, asks for admin). Clicker's in-app
; updater runs this same installer silently over the installed copy and it reopens Clicker at the end.
; Your scripts, rules and settings live in your user folder, so updating or uninstalling never touches them.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{3C85BEA0-9619-44E2-8C3E-8DBF56D24B4C}
AppName=Clicker
AppVersion={#AppVersion}
AppVerName=Clicker {#AppVersion}
AppPublisher=Clicker
AppPublisherURL=https://github.com/kjbinkley01-bot/t1
AppSupportURL=https://github.com/kjbinkley01-bot/t1/issues
AppUpdatesURL=https://github.com/kjbinkley01-bot/t1/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Clicker
DefaultDirName={autopf}\Clicker
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Clicker-Setup
SetupIconFile=..\assets\clicker.ico
UninstallDisplayIcon={app}\Clicker.exe
UninstallDisplayName=Clicker
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Clicker shortcut on the desktop"; Flags: unchecked

[InstallDelete]
; libraries from the previous version, so nothing stale is left behind after an update
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Clicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Clicker"; Filename: "{app}\Clicker.exe"
Name: "{autodesktop}\Clicker"; Filename: "{app}\Clicker.exe"; Tasks: desktopicon

[Run]
; after a normal install: a ticked "Open Clicker" box on the last page
Filename: "{app}\Clicker.exe"; Description: "Open Clicker"; Flags: nowait postinstall skipifsilent runasoriginaluser
; after an in-app update (a silent install): open the new version straight away
Filename: "{app}\Clicker.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent
