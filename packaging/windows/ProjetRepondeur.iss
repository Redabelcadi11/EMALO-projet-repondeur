#define AppName "Projet Repondeur"
#define AppVersion "0.1.0"
#define AppPublisher "EMALO"
#define AppExeName "ProjetRepondeur.exe"
#define AppDistDir "..\..\dist\windows\ProjetRepondeur"

[Setup]
AppId={{B55F5207-2A8E-4F81-8C2A-6D810B1D9C20}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\ProjetRepondeur
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=ProjetRepondeur-Setup
PrivilegesRequired=admin

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "{#AppDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Projet Repondeur"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Projet Repondeur - Diagnostic"; Filename: "{app}\{#AppExeName}"; Parameters: "doctor"
Name: "{group}\Projet Repondeur - Installer runtime"; Filename: "{app}\{#AppExeName}"; Parameters: "install-runtime"
Name: "{group}\Projet Repondeur - Pipeline"; Filename: "{app}\{#AppExeName}"; Parameters: "pipeline"
Name: "{group}\Projet Repondeur - Copilote"; Filename: "{app}\{#AppExeName}"; Parameters: "copilote-order"
Name: "{commondesktop}\Projet Repondeur"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Projet Repondeur"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: taskbaricon

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "taskbaricon"; Description: "Ajouter un raccourci dans la zone utilisateur barre des tâches (best effort)"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "repairruntime"; Description: "Réparer / réinstaller le runtime navigateur après installation"; GroupDescription: "Composants optionnels :"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: "install-runtime"; Description: "Réparer / installer le runtime Playwright"; Flags: postinstall skipifsilent waituntilterminated; Tasks: repairruntime
Filename: "{app}\{#AppExeName}"; Parameters: "doctor"; Description: "Vérifier l'installation"; Flags: postinstall skipifsilent nowait
