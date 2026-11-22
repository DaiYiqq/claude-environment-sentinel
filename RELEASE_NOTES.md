# Claude Environment Sentinel v1.1.0

多语言、社区共治与 AGPL 许可证版本。

## 下载

`Claude-Sentinel-1.1.0-win64-portable.zip`

- Windows 10/11 x64；
- 内含 CPython + Tk 运行时，不需要预装 Python；
- 解压整个文件夹后双击 `ClaudeSentinel.exe`；
- 本构建未做代码签名，Windows SmartScreen 可能提示未知发布者。

## 能力

- 20 项本地环境审计与加权风险分；
- 时区 / 语言 / Chrome/Edge 策略一键对齐；
- 对齐前创建不可变快照，一键还原；
- 历史趋势、逐项对比、风险分解；
- 本地浏览器控制台，写接口需要 token 和二次确认；
- Kill-Switch 与安全启动（桌面版）。

## 安全边界

- 不读取或保存 Claude 登录凭证、Cookie、Token、会话文件；
- 不绕过服务端风控，不承诺账号结果；
- 不修改 hosts、内核或驱动；字体只提示，不删除；
- 写操作只在本地执行，控制台仅绑定 127.0.0.1。

## 许可证

v1.1.0 起使用 **AGPL-3.0-only**。首次发布的 v1.0.0 按 MIT 发布，旧副本继续适用
MIT；详见 `LICENSING.md`、`LICENSE`、`NOTICE` 与 `LICENSE-MIT`。

## 社区

- 开发者：戴亿（Dai Yi / DaiYiqq）
- 抖音：`daiyi091004`
- Twitter/X：[@daiyi_520](https://x.com/daiyi_520)
- QQ：`1703205607`
- Discussions / Issues / PR 欢迎参与。

使用前请阅读 `README.md`、`SECURITY.md` 和 `docs/anti-ban-guide.md`。
