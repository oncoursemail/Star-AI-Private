#ifndef StarVersion
  #define StarVersion "1.0.1"
#endif
#define STARName "STAR Intelligence"
#define STARExe "STAR.exe"
[Setup]
AppId={{E2B5518B-30A1-409D-AF44-6F773BF05C97}
AppName={#STARName}
AppVerName={#STARName} {#StarVersion}
AppVersion={#StarVersion}
AppPublisher=STAR Intelligence
AppPublisherURL=https://github.com/oncoursemail/Star-AI
AppSupportURL=https://github.com/oncoursemail/Star-AI/issues
AppUpdatesURL=https://github.com/oncoursemail/Star-AI/releases
DefaultDirName={localappdata}\Programs\STAR
DefaultGroupName=STAR Intelligence
UninstallDisplayIcon={app}\{#STARExe}
OutputDir=..\dist
OutputBaseFilename=STAR-Setup-v{#StarVersion}
SetupIconFile=..\assets\star.ico
Compression=lzma2
SolidCompression=yes
; Multi-threaded LZMA2 (CI runners have 4 cores): same files, ~2-3x faster compile, slightly larger Setup.
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Manual Setup preserves an existing install's scope; the in-app updater passes
; /CURRENTUSER or /ALLUSERS when it can identify the running copy's registration.
UsePreviousPrivileges=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no

; The old *application runtime* ({app}\_internal and STAR.exe) is replaced as a whole, so no stale DLL or
; Python module survives an upgrade: [Code] below moves it aside first and restores it if Setup fails.
; NEVER delete {userappdata}\STAR (chats, models, memory) or arbitrary {app} files.

[Files]
Source: "..\dist\STAR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\STAR Intelligence"; Filename: "{app}\{#STARExe}"
Name: "{autodesktop}\STAR Intelligence"; Filename: "{app}\{#STARExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#STARExe}"; Description: "Launch STAR Intelligence"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\{#STARExe}"; Flags: nowait skipifnotsilent runasoriginaluser

; Issue 120: never leave a half-replaced STAR. Setup's own rollback does not undo [InstallDelete], so the
; old runtime ({app}\_internal and {app}\STAR.exe) is moved aside before the new files are copied, put back
; if the installation does not finish, and deleted only after it has finished. Leftovers from a Setup that
; was killed are preserved for recovery; the next Setup refuses to overwrite them.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal.star-previous"
Type: files; Name: "{app}\{#STARExe}.star-previous"

[Code]
const
  RuntimeDir = '_internal';
  KeptSuffix = '.star-previous';

var
  AppFolder: String;
  RuntimeMoved: Boolean;
  ExeMoved: Boolean;
  InstallFinished: Boolean;

function KeptPath(const Name: String): String;
begin
  Result := AppFolder + '\' + Name + KeptSuffix;
end;

{ A previous interrupted Setup may have left the only working runtime here. }
procedure CheckLeftover(const Name: String);
var
  Path: String;
begin
  Path := KeptPath(Name);
  if DirExists(Path) or FileExists(Path) then
  begin
    SuppressibleMsgBox('A previous STAR upgrade left a recovery copy at ' + Path + '.' + #13#10 +
      'Setup has not changed it. Close STAR and recover the previous installation ' +
      'before trying again. Keep both .star-previous items together.', mbError, MB_OK, IDOK);
    Abort;
  end;
end;

{ Opening an existing file for exclusive read/write does not modify it, but fails for a
  loaded executable even on Windows versions that allow renaming that executable. }
function RuntimeAvailable(const Path: String): Boolean;
var
  Stream: TFileStream;
  Found: TFindRec;
begin
  Result := False;
  if DirExists(Path) then
  begin
    if not FindFirst(Path + '\*', Found) then
      Exit;
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then
        begin
          { Do not follow junctions or symbolic links outside the installed runtime. }
          if (Found.Attributes and $400) <> 0 then
            Exit;
          if not RuntimeAvailable(Path + '\' + Found.Name) then
            Exit;
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
    Result := True;
  end
  else if FileExists(Path) then
  begin
    try
      Stream := TFileStream.Create(Path, $0012); { fmOpenReadWrite or fmShareExclusive }
      Stream.Free;
      Result := True;
    except
      Log('Runtime file is unavailable: ' + Path);
    end;
  end
  else
    Result := True; { Fresh installation. }
end;

{ Retry transient rename failures after the open-file preflight; never delete live files here. }
function MoveAside(const Name: String): Boolean;
var
  Attempt: Integer;
begin
  Result := False;
  for Attempt := 1 to 8 do
  begin
    Result := RenameFile(AppFolder + '\' + Name, KeptPath(Name));
    if Result then
      Exit;
    Sleep(500);
  end;
end;

{ Replaces whatever a failed installation left with the kept old copy. }
function PutBack(const Name: String): Boolean;
var
  Live: String;
begin
  Live := AppFolder + '\' + Name;
  if DirExists(Live) then
    DelTree(Live, True, True, True)
  else if FileExists(Live) then
    DeleteFile(Live);
  Result := RenameFile(KeptPath(Name), Live);
  if not Result then
    Log('Could not put back ' + Live + '; the previous copy is kept at ' + KeptPath(Name));
end;

procedure RefuseWhileRunning;
begin
  SuppressibleMsgBox('STAR Intelligence is still running, or one of its files is open in another program, ' +
    'so Setup cannot replace it.' + #13#10 + #13#10 +
    'Setup stopped before copying new files. Your chats and settings were not changed. ' +
    'Close every STAR window (also one started with "Run as administrator") and run Setup again.',
    mbError, MB_OK, IDOK);
  Abort;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    { Restart Manager has already been asked to close STAR (CloseApplications=yes). }
    AppFolder := ExpandConstant('{app}');
    CheckLeftover(RuntimeDir);
    CheckLeftover('{#STARExe}');
    if not RuntimeAvailable(AppFolder + '\{#STARExe}') then
      RefuseWhileRunning;
    if not RuntimeAvailable(AppFolder + '\' + RuntimeDir) then
      RefuseWhileRunning;
    if DirExists(AppFolder + '\' + RuntimeDir) then
    begin
      if not MoveAside(RuntimeDir) then
        RefuseWhileRunning;
      RuntimeMoved := True;
    end;
    if FileExists(AppFolder + '\{#STARExe}') then
    begin
      if not MoveAside('{#STARExe}') then
      begin
        if RuntimeMoved then
          RuntimeMoved := not PutBack(RuntimeDir);
        RefuseWhileRunning;
      end;
      ExeMoved := True;
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    InstallFinished := True;
    if RuntimeMoved then
      DelTree(KeptPath(RuntimeDir), True, True, True);
    if ExeMoved then
      DeleteFile(KeptPath('{#STARExe}'));
  end;
end;

{ Runs when Setup ends for any reason, after its own rollback of the files it copied. }
procedure DeinitializeSetup;
begin
  if InstallFinished then
    Exit;
  if RuntimeMoved then
    RuntimeMoved := not PutBack(RuntimeDir);
  if ExeMoved then
    ExeMoved := not PutBack('{#STARExe}');
  if RuntimeMoved or ExeMoved then
    SuppressibleMsgBox('Setup could not restore all of the previous STAR runtime. ' +
      'Keep the .star-previous recovery copies in ' + AppFolder + ' and close STAR before recovery.',
      mbError, MB_OK, IDOK);
end;
