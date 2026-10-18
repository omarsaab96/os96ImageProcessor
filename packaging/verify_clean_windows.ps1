param(
    [Parameter(Mandatory=$true)][string]$ArtifactDirectory,
    [Parameter(Mandatory=$true)][string]$ResultDirectory,
    [string]$Version = '1.0.0rc2'
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $ResultDirectory -Force | Out-Null
$ResultDirectory = (Resolve-Path -LiteralPath $ResultDirectory).Path
$result = [ordered]@{ passed=$false; version=$Version; machine=$env:COMPUTERNAME; checks=@(); error=$null }
$work = Join-Path $env:TEMP ('OS96-release-check-' + [guid]::NewGuid().ToString('N'))
$install = Join-Path $work 'installed-é'
New-Item -ItemType Directory -Path $work | Out-Null
function Run-Checked([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Process failed ($($process.ExitCode)): $File" }
}
try {
    $ArtifactDirectory = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
    $zip = Join-Path $ArtifactDirectory "OS96ImageOptimizer-$Version-portable.zip"
    $setup = Join-Path $ArtifactDirectory "OS96ImageOptimizer-$Version-Setup.exe"
    foreach ($file in @($zip, $setup)) {
        $expected = (Get-Content -LiteralPath ($file + '.sha256') -Raw).Split(' ')[0].Trim()
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $expected) { throw "Checksum mismatch: $file" }
    }
    $result.checks += 'Archive and installer SHA-256'
    $registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OS96.ImageOptimizer_is1'
    if (Test-Path -LiteralPath $registry) { throw 'An existing OS96 installation is present; run in a clean VM/Sandbox.' }
    $portable = Join-Path $work 'portable'
    Expand-Archive -LiteralPath $zip -DestinationPath $portable
    $app = Join-Path $portable 'OS96ImageOptimizer\OS96ImageOptimizer.exe'
    $env:PATH = "$env:WINDIR\System32;$env:WINDIR"
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    $env:QT_QPA_PLATFORM = 'windows'
    Set-Location -LiteralPath $work
    Run-Checked $app @('--self-test', ('"' + (Join-Path $ResultDirectory 'portable-selftest.json') + '"'))
    $portableResult = Get-Content -LiteralPath (Join-Path $ResultDirectory 'portable-selftest.json') -Raw | ConvertFrom-Json
    if (-not $portableResult.passed -or $portableResult.version -ne $Version) { throw 'Portable self-test failed.' }
    $result.checks += 'Portable executable without Python on PATH'
    Run-Checked $setup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', ('/DIR="' + $install + '"'))
    $installedApp = Join-Path $install 'OS96ImageOptimizer.exe'
    Run-Checked $installedApp @('--self-test', ('"' + (Join-Path $ResultDirectory 'installed-selftest.json') + '"'))
    $installedResult = Get-Content -LiteralPath (Join-Path $ResultDirectory 'installed-selftest.json') -Raw | ConvertFrom-Json
    if (-not $installedResult.passed -or $installedResult.version -ne $Version) { throw 'Installed self-test failed.' }
    $result.checks += 'Installed app, codecs, native helpers, Unicode path, corrupt input'
    $result.signature = (Get-AuthenticodeSignature -LiteralPath $installedApp).Status.ToString()
    $result.checks += 'Signature status recorded (unsigned candidate is expected)'
    $result.passed = $true
} catch {
    $result.error = $_.Exception.ToString()
} finally {
    $uninstaller = Join-Path $install 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller) {
        if (-not ([IO.Path]::GetFullPath($install).StartsWith([IO.Path]::GetFullPath($work) + [IO.Path]::DirectorySeparatorChar))) {
            throw 'Installation target escaped the test workspace.'
        }
        try {
            Run-Checked $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
            for ($i=0; $i -lt 50 -and (Test-Path -LiteralPath $install); $i++) { Start-Sleep -Milliseconds 100 }
            if (Test-Path -LiteralPath $install) { throw 'Uninstaller left the installation directory.' }
            $result.checks += 'Uninstaller removed its target directory'
        } catch { $result.passed=$false; $result.error=$_.Exception.ToString() }
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ResultDirectory 'clean-windows-verification.json') -Encoding UTF8
    Set-Location -LiteralPath $ResultDirectory
    $resolvedWork = [IO.Path]::GetFullPath($work)
    $temporaryRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if ($resolvedWork.StartsWith($temporaryRoot) -and (Split-Path -Leaf $resolvedWork).StartsWith('OS96-release-check-')) {
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
    } else { throw 'Refusing to clean a directory outside the generated test workspace.' }
}
if (-not $result.passed) { exit 1 }
