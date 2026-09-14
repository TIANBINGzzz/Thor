param(
    [string]$SshHost = '103.236.98.149',
    [string]$RollbackRelease = '',
    [string]$RemoteReleaseScript = $env:CCSDK_DOCS_RELEASE_SCRIPT,
    [string]$RemoteIncomingDirectory = $env:CCSDK_DOCS_INCOMING_DIRECTORY
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# Validate before Git, SSH or filesystem writes; these values enter a remote shell.
foreach ($remotePath in @($RemoteReleaseScript, $RemoteIncomingDirectory)) {
    if ($remotePath -notmatch '^/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$' -or ($remotePath -split '/') -contains '..' -or ($remotePath -split '/') -contains '.') {
        throw 'Set RemoteReleaseScript and RemoteIncomingDirectory (or CCSDK_DOCS_RELEASE_SCRIPT and CCSDK_DOCS_INCOMING_DIRECTORY) to normalized remote paths without shell characters.'
    }
}
$repo = Split-Path $PSScriptRoot -Parent
$url = 'https://cp.stringedu.com/ccsdkscribe/python-api.html'
$sshOptions = @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15')
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('ccsdkscribe-docs-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
try {
    if ($RollbackRelease) {
        if ($RollbackRelease -notmatch '^\d{8}T\d{6}Z-[a-f0-9]{12}-[a-f0-9]{8}$') { throw 'Invalid release ID.' }
        $result = & ssh @sshOptions $SshHost "'$RemoteReleaseScript' --rollback '$RollbackRelease'"
        if ($LASTEXITCODE -ne 0) { throw 'Remote rollback failed.' }
    } else {
        # Commit only this document; leave unrelated staged changes intact.
        $status = & git -C $repo status --porcelain -- doc/python-api.html
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the source Git repository.' }
        if ($status) {
            & git -C $repo add -- doc/python-api.html
            if ($LASTEXITCODE -ne 0) { throw 'Cannot stage the HTML.' }
            & git -C $repo commit --only -m 'docs: update published Python API reference' -- doc/python-api.html
            if ($LASTEXITCODE -ne 0) { throw 'Cannot commit the HTML.' }
        }
        $revision = (& git -C $repo rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[a-f0-9]{40}$') { throw 'Invalid Git revision.' }
        # Publish immutable committed bytes, independent of Windows line endings.
        & git -C $repo archive --format=zip "--output=$scratch/source.zip" $revision -- doc/python-api.html
        if ($LASTEXITCODE -ne 0) { throw 'Cannot export the committed HTML.' }
        Expand-Archive -LiteralPath "$scratch/source.zip" -DestinationPath $scratch
        $html = Join-Path $scratch 'doc/python-api.html'
        $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $html).Hash.ToLowerInvariant()
        $stage = (& ssh @sshOptions $SshHost "mktemp -d '$RemoteIncomingDirectory/upload.XXXXXXXX'").Trim()
        $stagePattern = '^' + [regex]::Escape($RemoteIncomingDirectory) + '/upload\.[a-zA-Z0-9]+$'
        if ($LASTEXITCODE -ne 0 -or $stage -notmatch $stagePattern) { throw 'Cannot create remote staging directory.' }
        try {
            & scp @sshOptions $html "${SshHost}:$stage/python-api.html"
            if ($LASTEXITCODE -ne 0) { throw 'HTML upload failed.' }
            $result = & ssh @sshOptions $SshHost "'$RemoteReleaseScript' '$stage' '$sha' '$revision'"
            if ($LASTEXITCODE -ne 0) { throw 'Remote release failed; inspect server output.' }
        } finally {
            & ssh @sshOptions $SshHost "if test -d '$stage'; then rm -f '$stage/python-api.html'; rmdir '$stage'; fi"
            if ($LASTEXITCODE -ne 0) { Write-Warning "Remote staging cleanup failed: $stage" }
        }
    }
    $release = ($result -join "`n") | ConvertFrom-Json
    & curl.exe --fail --silent --show-error --connect-timeout 10 --max-time 30 "${url}?release=$($release.release)" --output "$scratch/public.html"
    if ($LASTEXITCODE -ne 0) { throw "Public verification failed. Server release: $($release.release); previous: $($release.previous)" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath "$scratch/public.html").Hash.ToLowerInvariant()
    if ($actual -ne $release.sha256) { throw "Public SHA256 mismatch. Previous release: $($release.previous)" }
    Write-Host "Published and verified: $url"
    Write-Host "Release: $($release.release)"
    Write-Host "Previous: $($release.previous)"
    Write-Host "SHA256: $actual"
} finally {
    # Delete only the uniquely created local publishing directory.
    Remove-Item -LiteralPath $scratch -Recurse -Force
}
