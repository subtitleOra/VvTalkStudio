# Windows 发行文件签名

当前发布程序未签名。`sign-release.ps1` 为持有正式代码签名证书的发布者提供检查和签名入口，不生成自签名证书，不导入信任根，也不接受或记录 PFX 密码。没有证书时应保留未签名状态，不能把脚本存在当作发行文件已经签名。

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
