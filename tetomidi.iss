#define MyAppName "tetomidi"
#define MyAppVersion "1.0.0"
#define MyAppExe "tetomidi.exe"

[Setup]
AppId={{B7C3E9A2-5D41-4E7B-9F26-3A1C8D5E7F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=tetomidi
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=tetomidi-setup
SetupIconFile=assets\tetomidi.ico
UninstallDisplayIcon={app}\tetomidi.ico
Compression=lzma2
SolidCompression=no
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\tetomidi\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs
Source: "assets\tetomidi.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "tetomidi.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\tetomidi.ico"
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\tetomidi.ico"

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Open tetomidi"; Flags: nowait postinstall skipifsilent
