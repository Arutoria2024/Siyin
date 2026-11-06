#define AppName "祀音"
#ifndef SourceRoot
#define SourceRoot AddBackslash(SourcePath) + ".."
#endif
[Setup]
AppId={{915D14F5-22F0-4D1F-9D3D-A5B12301E180}
AppName={#AppName}
AppVersion=1.0.0
AppPublisher=Si Voice Workbench
DefaultDirName={localappdata}\Programs\SiVoiceWorkbench
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
OutputDir={#SourceRoot}\release\祀音-1.0.0
OutputBaseFilename=祀音安装包-1.0.0
SetupIconFile={#SourceRoot}\app\monitor\si-voice.ico
UninstallDisplayIcon={app}\app\monitor\si-voice.ico
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=1500000000
WizardStyle=modern
CloseApplications=no
RestartApplications=no
[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
[Files]
Source: "{#SourceRoot}\祀音.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\祀音.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\app\engine\*"; DestDir: "{app}\app\engine"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\python\*"; DestDir: "{app}\app\python"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\models\*"; DestDir: "{app}\app\models"; Excludes: "manifest.json,*.bak*"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\frontend\*"; DestDir: "{app}\app\frontend"; Excludes: "__pycache__\*,*.pyc,*.bak*"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\desktop\*.py"; DestDir: "{app}\app\desktop"; Flags: ignoreversion
Source: "{#SourceRoot}\app\services\*.py"; DestDir: "{app}\app\services"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\monitor\monitor.py"; DestDir: "{app}\app\monitor"; Flags: ignoreversion
Source: "{#SourceRoot}\app\monitor\*.ico"; DestDir: "{app}\app\monitor"; Flags: ignoreversion
Source: "{#SourceRoot}\app\ui\dist\*"; DestDir: "{app}\app\ui\dist"; Flags: ignoreversion recursesubdirs
Source: "{#SourceRoot}\app\ui\public\assets\character.jpg"; DestDir: "{app}\app\ui\public\assets"; Flags: ignoreversion
Source: "{#SourceRoot}\app\tools\ffmpeg\*"; DestDir: "{app}\app\tools\ffmpeg"; Flags: ignoreversion
Source: "{#SourceRoot}\app\config\gsv.env"; DestDir: "{app}\app\config"; Flags: ignoreversion
Source: "{#SourceRoot}\app\start*.bat"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#SourceRoot}\app\start_monitor.vbs"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#SourceRoot}\app\stop_all.bat"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#SourceRoot}\app\LICENSE"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#SourceRoot}\packaging\staging\*"; DestDir: "{app}"; Flags: onlyifdoesntexist recursesubdirs
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\祀音.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app\monitor\si-voice.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\祀音.exe"; WorkingDir: "{app}"; IconFilename: "{app}\app\monitor\si-voice.ico"
[Run]
Filename: "{app}\app\python\python.exe"; Parameters: """{app}\app\desktop\bootstrap.py"""; Flags: runhidden waituntilterminated
[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not RegKeyExists(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') and
     not RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') and
     not RegKeyExists(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') then
    MsgBox('本应用需要 Microsoft Edge WebView2 Runtime。如未安装，请先从微软官网下载并安装。', mbInformation, MB_OK);
end;
