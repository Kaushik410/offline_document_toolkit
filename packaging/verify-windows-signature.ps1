param(
    [Parameter(Mandatory=$true)][string]$ArtifactPath,
    [string]$ExpectedThumbprint = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$signature = Get-AuthenticodeSignature -LiteralPath $ArtifactPath
if ($signature.Status -ne 'Valid') {
    throw "Authenticode signature verification failed: $($signature.Status) — $($signature.StatusMessage)"
}
if (!$signature.TimeStamperCertificate) { throw 'A trusted timestamp is required.' }
if ($ExpectedThumbprint -and $signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint) {
    throw 'The signing certificate does not match the configured publisher identity.'
}
@{
    subject = $signature.SignerCertificate.Subject
    thumbprint = $signature.SignerCertificate.Thumbprint
    timestamp_subject = $signature.TimeStamperCertificate.Subject
    authenticode_status = $signature.Status.ToString()
} | ConvertTo-Json -Compress
