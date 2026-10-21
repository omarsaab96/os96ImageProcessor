#ifndef AppVersion
#define AppVersion "1.0.0rc24"
#endif
#ifndef DistributionDir
#define DistributionDir "..\dist\OS96ImageOptimizer"
#endif
[Setup]
AppId=OS96.ImageOptimizer
AppName=OS96 Image Optimizer
AppVersion={#AppVersion}
AppPublisher=OS96
DefaultDirName={localappdata}\Programs\OS96ImageOptimizer
DefaultGroupName=OS96 Image Optimizer
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OS96ImageOptimizer-{#AppVersion}-Setup
UninstallDisplayIcon={app}\OS96ImageOptimizer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
[Files]
Source: "{#DistributionDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\OS96 Image Optimizer"; Filename: "{app}\OS96ImageOptimizer.exe"
[Run]
Filename: "{app}\OS96ImageOptimizer.exe"; Description: "Launch OS96 Image Optimizer"; Flags: nowait postinstall skipifsilent
