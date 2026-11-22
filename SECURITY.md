# Security Policy

## Reporting

请通过 GitHub Security Advisories 私下报告安全问题：

<https://github.com/DaiYiqq/claude-environment-sentinel/security/advisories/new>

不要在公开 Issue 中粘贴真实的代理凭据、Cookie、Token、账号信息或完整环境快照。

## Local-first design

- Sentinel 不包含遥测、账号登录或远程控制服务。
- 审计、报告、快照、日志都写入本地项目目录。
- 浏览器控制台只绑定 `127.0.0.1`，写接口使用每进程一次性 token、显式确认和 Host/Origin 校验。
- Sentinel 不读取 Claude 登录态、Cookie、Token、会话文件或浏览器账号资料。
- `state/`、`backups/`、`logs/`、`profiles/` 中的运行时数据不应提交到 Git。

## Privileges

- 系统时区修改、Windows 防火墙 Kill-Switch 需要管理员权限。
- 没有管理员权限时，Sentinel 不应该假装成功；失败和未完成项会明确显示。
- 便携版不包含代码签名证书。Windows SmartScreen 可能提示未知发布者。

## Scope

Sentinel 是本地环境一致性工具，不是安全沙箱，也不是服务器端风控绕过工具。
它不承诺账号结果，不修改 hosts、内核或驱动，不读取或保存账号凭证。

## Supported versions

当前维护 `1.x`。安全修复会发布在 GitHub Releases。
