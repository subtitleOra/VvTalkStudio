#Requires -Version 5.1
<#
.SYNOPSIS
使用已安装且受信任的正式代码签名证书，创建 EXE 签名副本。
.EXAMPLE
.\sign-release.ps1 -ExePath '.\dist\1.1.1\VvTalkStudio.exe' -Thumbprint '40位证书指纹' -TimestampUrl '证书机构提供的HTTPS时间戳地址'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$Thumbprint,
    [Parameter(Mandatory = $true)][string]$TimestampUrl,
    [ValidateSet('CurrentUser', 'LocalMachine')][string]$StoreLocation = 'CurrentUser',
    [string]$SignToolPath,
    [string]$OutputPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Find-SignTool([string]$ExplicitPath) {
    if ($ExplicitPath) {
        $resolvedTool = (Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop).ProviderPath
        if (-not (Test-Path -LiteralPath $resolvedTool -PathType Leaf) -or
            [IO.Path]::GetFileName($resolvedTool) -ine 'signtool.exe') {
            throw 'SignToolPath 必须指向现有的 signtool.exe。'
        }
        return $resolvedTool
    }
    $command = Get-Command signtool.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $sdkRoots = @()
    $installed = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue
    if ($installed -and $installed.PSObject.Properties['KitsRoot10']) { $sdkRoots += $installed.KitsRoot10 }
    if (${env:ProgramFiles(x86)}) { $sdkRoots += (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10') }
    foreach ($sdkRoot in ($sdkRoots | Select-Object -Unique)) {
        foreach ($architecture in @('x64', 'arm64', 'x86')) {
            $found = Get-ChildItem -Path (Join-Path $sdkRoot "bin\*\$architecture\signtool.exe") -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    throw '未找到 SignTool。请安装 Windows SDK 的 Signing Tools，或明确传入 -SignToolPath；本脚本不会安装工具。'
}

function Get-PublicCertificate($Certificate) {
    return [ordered]@{
        subject = $Certificate.Subject
        issuer = $Certificate.Issuer
        thumbprint = $Certificate.Thumbprint
        serialNumber = $Certificate.SerialNumber
        notBeforeUtc = $Certificate.NotBefore.ToUniversalTime().ToString('o')
        notAfterUtc = $Certificate.NotAfter.ToUniversalTime().ToString('o')
    }
}

function Get-StreamSha256([IO.FileStream]$Stream) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $Stream.Position = 0
        $digest = $hasher.ComputeHash($Stream)
        $Stream.Position = 0
        return ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    } finally { $hasher.Dispose() }
}

function Invoke-SignTool([string]$Tool, [string[]]$Arguments) {
    # Windows PowerShell 5.1 将原生 stderr 转成 ErrorRecord；按实际退出码判定结果。
    $ErrorActionPreference = 'Continue'
    $LASTEXITCODE = 1
    $lines = @(& $Tool @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    return @{ exitCode = $LASTEXITCODE; output = $lines }
}

$sourceStream = $null
$reportStream = $null
$certificateStore = $null
$chain = $null
$report = $null
$exitStatus = 1
$targetPath = $null
$reportPath = $null

try {
    $sourcePath = (Resolve-Path -LiteralPath $ExePath -ErrorAction Stop).ProviderPath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or [IO.Path]::GetExtension($sourcePath) -ine '.exe') {
        throw 'ExePath 必须指向现有的 EXE 文件。'
    }
    # 原文件全程只读锁定：不允许其他进程写入或删除，签名只作用于新副本。
    $sourceStream = [IO.File]::Open($sourcePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sourceHash = Get-StreamSha256 $sourceStream
    $normalizedThumbprint = ($Thumbprint -replace '\s', '').ToUpperInvariant()
    if ($normalizedThumbprint -notmatch '^[0-9A-F]{40}$') { throw 'Thumbprint 必须是 40 位十六进制证书指纹。' }
    $timestampUri = $null
    if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$timestampUri) -or
        $timestampUri.Scheme -ine 'https' -or -not $timestampUri.Host -or $timestampUri.UserInfo -or $timestampUri.Fragment) {
        throw 'TimestampUrl 必须是明确提供的 HTTPS RFC 3161 服务地址，且不包含用户名、密码或片段。'
    }
    if ($OutputPath) {
        $targetPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
    } else {
        $newName = '{0}.signed-{1}-{2}.exe' -f [IO.Path]::GetFileNameWithoutExtension($sourcePath),
            (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 8))
        $targetPath = Join-Path ([IO.Path]::GetDirectoryName($sourcePath)) $newName
    }
    $targetPath = [IO.Path]::GetFullPath($targetPath)
    $reportPath = $targetPath + '.signing.json'
    if ($targetPath -ieq $sourcePath -or [IO.Path]::GetExtension($targetPath) -ine '.exe') {
        throw 'OutputPath 必须是与原文件不同的新 EXE 路径，禁止覆盖原 EXE。'
    }
    if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($targetPath)) -PathType Container)) {
        throw '输出文件夹必须已经存在。'
    }
    if ((Test-Path -LiteralPath $targetPath) -or (Test-Path -LiteralPath $reportPath)) {
        throw '输出 EXE 或签名记录已存在；请指定新的输出路径，脚本不会覆盖。'
    }
    $toolPath = Find-SignTool $SignToolPath
    $location = [Security.Cryptography.X509Certificates.StoreLocation]::$StoreLocation
    $certificateStore = New-Object Security.Cryptography.X509Certificates.X509Store('My', $location)
    $certificateStore.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
    $matches = @($certificateStore.Certificates | Where-Object { $_.Thumbprint -eq $normalizedThumbprint })
    if ($matches.Count -ne 1) { throw "在 $StoreLocation\My 中没有找到唯一的指定证书。当前未签名；请先申领并安装正式代码签名证书。" }
    $certificate = $matches[0]
    $now = Get-Date
    if ($now -lt $certificate.NotBefore -or $now -gt $certificate.NotAfter) { throw '代码签名证书尚未生效或已经过期。' }
    if (-not $certificate.HasPrivateKey) { throw '证书没有关联的可用私钥。请使用证书机构提供的密钥设备或提供程序完成配置。' }
    $codeSigningOid = '1.3.6.1.5.5.7.3.3'
    $hasCodeSigningEku = $false
    foreach ($extension in $certificate.Extensions) {
        if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($usage in $extension.EnhancedKeyUsages) {
                if ($usage.Value -eq $codeSigningOid) { $hasCodeSigningEku = $true }
            }
        }
    }
    if (-not $hasCodeSigningEku) { throw '证书没有 Code Signing EKU，不能用于本流程。' }
    $chain = New-Object Security.Cryptography.X509Certificates.X509Chain
    $chain.ChainPolicy.VerificationFlags = [Security.Cryptography.X509Certificates.X509VerificationFlags]::NoFlag
    $chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::Online
    $chain.ChainPolicy.RevocationFlag = [Security.Cryptography.X509Certificates.X509RevocationFlag]::ExcludeRoot
    $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(15)
    [void]$chain.ChainPolicy.ApplicationPolicy.Add((New-Object Security.Cryptography.Oid($codeSigningOid)))
    if (-not $chain.Build($certificate)) {
        $chainErrors = @($chain.ChainStatus | ForEach-Object { "$($_.Status): $($_.StatusInformation.Trim())" }) -join '; '
        throw "证书信任链或吊销检查失败：$chainErrors。脚本不会导入根证书或降低信任要求。"
    }
    $report = [ordered]@{
        schema = 1; status = 'pending'; startedUtc = [DateTime]::UtcNow.ToString('o'); finishedUtc = $null
        original = @{ path = $sourcePath; sha256Before = $sourceHash; sha256After = $null }
        output = @{ path = $targetPath; sha256BeforeSigning = $null; sha256AfterSigning = $null }
        certificate = (Get-PublicCertificate $certificate)
        storeLocation = $StoreLocation
        chain = @($chain.ChainElements | ForEach-Object { Get-PublicCertificate $_.Certificate })
        digestAlgorithm = 'SHA256'
        timestamp = @{ url = $timestampUri.GetLeftPart([UriPartial]::Path); queryOmitted = [bool]$timestampUri.Query; protocol = 'RFC3161'; digestAlgorithm = 'SHA256'; certificate = $null }
        signTool = @{ path = $toolPath; sign = $null; verify = $null }
        authenticode = $null; error = $null
    }
    # 两个目标都以 CreateNew 创建，避免检查之后的竞态覆盖。
    $reportStream = [IO.File]::Open($reportPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $destinationStream = [IO.File]::Open($targetPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $sourceStream.CopyTo($destinationStream) } finally { $destinationStream.Dispose() }
    $report['output']['sha256BeforeSigning'] = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($report['output']['sha256BeforeSigning'] -ne $sourceHash) { throw '副本哈希与原 EXE 不一致，停止签名。' }
    $signArguments = @('sign', '/v', '/s', 'My', '/sha1', $normalizedThumbprint, '/fd', 'SHA256', '/tr', $timestampUri.AbsoluteUri, '/td', 'SHA256')
    if ($StoreLocation -eq 'LocalMachine') { $signArguments += '/sm' }
    $signArguments += $targetPath
    $report['signTool']['sign'] = Invoke-SignTool $toolPath $signArguments
    if ($report['signTool']['sign']['exitCode'] -ne 0) { throw "SignTool 签名失败或产生警告，退出码 $($report['signTool']['sign']['exitCode'])。请查看旁边的 JSON；副本不能作为已验证签名发行。" }
    $report['signTool']['verify'] = Invoke-SignTool $toolPath @('verify', '/pa', '/all', '/v', '/tw', $targetPath)
    $signature = Get-AuthenticodeSignature -LiteralPath $targetPath
    $report['authenticode'] = @{ status = $signature.Status.ToString(); statusMessage = $signature.StatusMessage; signer = $null }
    if ($signature.SignerCertificate) { $report['authenticode']['signer'] = Get-PublicCertificate $signature.SignerCertificate }
    if ($signature.TimeStamperCertificate) { $report['timestamp']['certificate'] = Get-PublicCertificate $signature.TimeStamperCertificate }
    if ($report['signTool']['verify']['exitCode'] -ne 0 -or $signature.Status -ne 'Valid') { throw '签名验证没有完全通过；要求 SignTool verify 成功且 Authenticode Status=Valid。' }
    if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $normalizedThumbprint) { throw '验证得到的签名证书与指定指纹不一致。' }
    if (-not $signature.TimeStamperCertificate) { throw '签名缺少已验证的时间戳证书，不能将本次操作视为成功。' }
    $report['status'] = 'verified'
    $exitStatus = 0
} catch {
    if ($report) { $report['status'] = 'failed'; $report['error'] = $_.Exception.Message }
    [Console]::Error.WriteLine('签名未完成：' + $_.Exception.Message)
    $exitStatus = 1
} finally {
    if ($report) {
        try {
            $report['original']['sha256After'] = Get-StreamSha256 $sourceStream
            if ($report['original']['sha256After'] -ne $report['original']['sha256Before']) {
                throw '原 EXE 哈希发生变化，不能宣布签名成功。'
            }
            if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
                $report['output']['sha256AfterSigning'] = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        } catch {
            $report['status'] = 'failed'; $report['error'] = $_.Exception.Message; $exitStatus = 1
            [Console]::Error.WriteLine($_.Exception.Message)
        }
        $report['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
        if ($reportStream) {
            try {
                $encoding = New-Object Text.UTF8Encoding($false)
                $bytes = $encoding.GetBytes(($report | ConvertTo-Json -Depth 12))
                $reportStream.Write($bytes, 0, $bytes.Length)
                $reportStream.Flush()
            } catch {
                $exitStatus = 1
                [Console]::Error.WriteLine('签名记录写入失败，不能宣布交付成功：' + $_.Exception.Message)
            } finally { $reportStream.Dispose() }
        }
    }
    if ($sourceStream) { $sourceStream.Dispose() }
    if ($chain) { $chain.Dispose() }
    if ($certificateStore) { $certificateStore.Close() }
}
if ($exitStatus -eq 0) {
    Write-Output "已生成并验证签名副本：$targetPath"
    Write-Output "公共签名记录：$reportPath"
} else {
    if ($reportStream) { Write-Output "失败记录：$reportPath；副本仅供排错，不应发行。" }
}
exit $exitStatus
