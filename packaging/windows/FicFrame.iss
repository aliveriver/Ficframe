#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\package\windows\dist\FicFrame"
#endif
#ifndef ArtifactDir
  #define ArtifactDir "..\..\release"
#endif

[Setup]
AppId={{A2D946AF-2AE1-48EE-89F7-A2B11BB61B29}
AppName=FicFrame
AppVersion={#AppVersion}
AppPublisher=FicFrame
DefaultDirName={code:GetDefaultInstallDir}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ArtifactDir}
OutputBaseFilename=FicFrame-{#AppVersion}-windows-x64-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\FicFrame.exe
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data"

[Icons]
Name: "{autoprograms}\FicFrame"; Filename: "{app}\FicFrame.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\FicFrame"; Filename: "{app}\FicFrame.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FicFrame.exe"; Description: "启动 FicFrame"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
function GetDefaultInstallDir(Param: String): String;
begin
  { Default beside the downloaded installer. The directory page remains visible, }
  { so users can select any writable folder or non-system drive. }
  Result := AddBackslash(ExpandConstant('{src}')) + 'FicFrame';
end;
