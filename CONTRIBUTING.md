# Contributing

## Ground rules

- 不提交真实凭据、Cookie、Token、会话文件、代理密码或账号身份材料。
- 不提交 `state/`、`backups/`、`logs/`、`profiles/` 中的运行时内容。
- 不增加绕过服务端风控的功能；项目只处理本地环境一致性。
- 修改写入类功能时，必须保持“快照先于写入”和“还原删除原本不存在的变量”不变。
- 新增浏览器写接口时，必须使用本地 token、显式确认和 loopback 限制。

## Development

```powershell
python -m unittest discover -s tests
node --check sentinel/webui/app.js
node --check docs/assets/site.js
python -m sentinel smoke-test
```

或：

```powershell
pwsh -File scripts/test.ps1
```

## Portable build

```powershell
pwsh -File scripts/build_portable.ps1
```

需要 Windows、.NET Framework `csc.exe` 和本机 CPython（含 Tkinter）。构建脚本会把 CPython 运行时复制到便携目录，不修改系统 Python。

## Pull requests

- 保持变更聚焦；
- 写明行为变化、风险边界和验证方式；
- UI 变化请同时检查深色/浅色和移动端宽度；
- 涉及写入的改动必须包含失败路径测试；
- 新增或修改文案时同步维护 `README.en.md` / `README.ja-JP.md`（至少更新对应章节）；
- 提交即表示同意以 **AGPL-3.0-only** 授权该贡献。

## Community

- 公共讨论：<https://github.com/DaiYiqq/claude-environment-sentinel/discussions>
- Issue：<https://github.com/DaiYiqq/claude-environment-sentinel/issues>
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 治理说明：[GOVERNANCE.md](GOVERNANCE.md)
- 维护者：戴亿（Dai Yi / DaiYiqq），联系方式见 [AUTHORS.md](AUTHORS.md)
- 安全问题请走私密 Security Advisory，不要发公开 Issue。

## License

从 v1.1.0 起贡献按 **AGPL-3.0-only** 授权；详见 [LICENSING.md](LICENSING.md)。
历史 v1.0.0 的 MIT 说明见 [LICENSE-MIT](LICENSE-MIT)。
