# 发行文件签名

当前发布程序未使用发布者证书签名（macOS 本地构建为 ad-hoc 签名）。Windows 使用 `sign-release.ps1`，macOS 使用 `sign-release-macos.sh`。两个脚本都只为持有正式代码签名证书的发布者提供检查和签名入口；没有证书时应保留未签名状态，不能把脚本存在当作发行文件已经签名。

## 证书与工具

脚本从 `CurrentUser\My` 或 `LocalMachine\My` 证书存储中按明确的 thumbprint 选择证书，检查代码签名 EKU、私钥、有效期及可信 X509 链，并使用在线吊销检查。`HasPrivateKey` 不保证当前账号或硬件令牌能够实际签名，真实调用失败仍须检查证书权限和签名服务。云端签名服务可能需要专有工具，不属于本脚本的证书存储流程。

需要 Windows SDK 的 `signtool.exe`；脚本可检测常见 SDK 安装位置，也支持明确指定路径。时间戳必须是发布者确认可用的 HTTPS RFC 3161 服务 URL。以下仅展示参数形式，替换证书指纹和 URL 后再运行：

```powershell
.\sign-release.ps1 -ExePath '.\dist\VvTalkStudio.exe' `
  -Thumbprint 'YOUR_CODE_SIGNING_CERTIFICATE_THUMBPRINT' `
  -StoreLocation CurrentUser `
  -TimestampUrl 'https://YOUR_RFC3161_TIMESTAMP_SERVICE'
```

源 EXE 保持不变，脚本默认写入唯一的新副本；如果使用 `-OutputPath`，其目标文件必须不存在，父目录应先创建。不要把当前运行的 EXE 或已发布附件作为覆盖目标。

## 验证与发布

签名使用 SHA-256 文件摘要和 SHA-256 RFC 3161 时间戳摘要。之后执行 SignTool `verify /pa /all /v /tw`，并检查 `Get-AuthenticodeSignature` 的状态为 `Valid`、签名证书与指定指纹一致且存在时间戳。任意步骤失败都不应把输出宣称为已验证签名。

确认有效后，重新记录签名前后文件摘要、签名者公开信息和时间戳，再生成发行包及 SHA-256 清单。公开记录中避免包含个人证书存储路径或机器用户名。签名不能替代依赖许可证、同版本完整对应源码、隐私清理和功能验收。

该脚本已做 PowerShell 5.1 语法解析、缺少工具和找不到证书时的安全失败检查，以及 SDK 检测检查。本轮没有正式证书、没有执行真实签名，也没有取得已签名程序的 SmartScreen 信任结果。

## macOS 签名与公证

macOS 发行包使用 `sign-release-macos.sh`。未提供证书时脚本使用 ad-hoc 签名，只适合本机测试；公开发行应传入 Developer ID Application 证书：

```bash
./sign-release-macos.sh dist/VvTalkStudio.app "Developer ID Application: Your Name (TEAMID)"
```

脚本会以 hardened runtime、时间戳和 `--deep` 签名整个 `.app`，随后执行 `codesign --verify --deep --strict`。`.app` 采用 onedir 结构，请先完成 `build.sh --web` 打包，不要只签名内部 Mach-O 可执行文件。

公证需要 Apple Developer 账号及已保存的 `notarytool` 凭据配置：

```bash
xcrun notarytool store-credentials vvtalk-notary \
  --apple-id 'YOUR_APPLE_ID' --team-id 'YOUR_TEAM_ID' --password 'APP_SPECIFIC_PASSWORD'
NOTARY_PROFILE=vvtalk-notary ./sign-release-macos.sh dist/VvTalkStudio.app "Developer ID Application: Your Name (TEAMID)"
```

脚本会创建临时 ZIP、提交公证、等待结果并执行 `xcrun stapler staple`。公证和装订都失败时不能宣称发行包已通过 Gatekeeper；用户仍可右键“打开”或按 [macOS 适配说明](macos.md) 移除 quarantine 属性，但这不应替代正式签名。公开记录中不要包含 Apple ID、团队密码、证书私钥或本机钥匙串路径。
