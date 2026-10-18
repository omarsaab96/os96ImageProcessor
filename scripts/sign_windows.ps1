param(
    [Parameter(Mandatory=$true)][string]$Thumbprint,
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string]$TimestampUrl = 'http://timestamp.digicert.com'
)
$ErrorActionPreference = 'Stop'
$certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$Thumbprint"
if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -lt (Get-Date)) {
    throw 'A valid code-signing certificate with a private key is required.'
}
if (-not ($certificate.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.3')) {
    throw 'The selected certificate does not have the Code Signing usage.'
}
$tool = Get-ChildItem -LiteralPath "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse |
    Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $tool) { throw 'Windows SDK SignTool was not found.' }
$resolvedFile = (Resolve-Path -LiteralPath $FilePath).Path
& $tool.FullName sign /sha1 $Thumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $resolvedFile
if ($LASTEXITCODE -ne 0) { throw 'Code signing failed.' }
& $tool.FullName verify /pa /all /tw $resolvedFile
if ($LASTEXITCODE -ne 0) { throw 'Authenticode signature verification failed.' }
