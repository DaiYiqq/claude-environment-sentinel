# Claude Environment Sentinel

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja-JP.md)

**先审计，再对齐，最后才安全启动。**

[![GitHub](https://img.shields.io/badge/GitHub-DaiYiqq%2Fclaude--environment--sentinel-181717?logo=github)](https://github.com/DaiYiqq/claude-environment-sentinel)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-2ea44f.svg)](LICENSE)
[![Windows portable](https://img.shields.io/badge/Download-Windows%20portable-0f766e)](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest)

**下载：** [Windows 便携版](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest) · **推广站：** <https://daiyiqq.github.io/claude-environment-sentinel/> · **源码：** <https://github.com/DaiYiqq/claude-environment-sentinel>

Windows 便携版包含 CPython/Tk 运行时，解压后双击 `ClaudeSentinel.exe` 即可使用，不需要预装 Python。构建未签名，SmartScreen 可能提示未知发布者。

Claude Environment Sentinel（下称 Sentinel）是一个本地桌面辅助工具：它在启动 Claude 之前检查系统时区、用户语言、Node/Electron 可见环境、出口地区、代理/TUN、DNS、WebRTC、浏览器策略等 20 项信号；对可逆的用户级设置提供“一键对齐”；在安全启动后提供 Kill-Switch 监控。

> **边界声明**
>
> Sentinel 的目标是降低“本地环境画像与账号注册/使用地区冲突”这一层风险。它不承诺任何账号结果，也不是服务端风控的绕过工具，不能替代对 Anthropic 服务条款和地区可用性政策的遵守。Anthropic 没有公开完整的账号风控评分细节，任何声称能决定结果的说法都不应被信任。

---

## 1. 功能一览

- **模块 A：20 项审计**（A1–A20），每项包含“通过/警告/失败/采样异常”、证据行、原始采样值和通俗解释；可导出 JSON。
- **加权风险分 0–100**：权重和理由集中在 `sentinel/audit/risk.py`。风险分 ≥ 60 或存在阻断级失败时，安全启动不可执行。
- **模块 B：可逆对齐**：用户级 `TZ`/`LANG`/`LC_ALL`、Windows/macOS/Linux 用户级浏览器策略、按确认修改系统时区；字体只标记不删除。
- **模块 C：不可变快照与一键还原**：写入前先备份；文件带 SHA-256 校验和，使用 `O_EXCL` 创建且不会被后续快照覆盖；原本不存在的变量在还原时被删除，而不是置空。
- **模块 D：Kill-Switch**：安全启动后每 5 秒检查出口国家/IP、代理内核、TUN；异常时终止 Claude 进程树、创建出站阻断规则、写日志并锁定，直到手动解除。支持全局快捷键（Windows 内置 `Ctrl+Shift+K`）。
- **模块 E：多环境配置包**：按账号场景保存/切换时区、语言、浏览器策略和代理标签/端点。**不保存任何登录凭证、Cookie、Token、会话文件或账号身份。**
- **模块 F/G：教程与风险指南**：`tutorials/quick-start.md` 在 GUI 内嵌；`docs/anti-ban-guide.md` 独立讲解风险模型。
- **CLI/无头模式**：便于排障和自动化；仍有同样的门禁和快照逻辑。
- **桌面启动器 + 浏览器控制台**：`ClaudeSentinel.exe` 双击打开桌面版；`run_sentinel_web.bat` 打开本地控制台（`127.0.0.1:8790`），支持一键对齐与一键还原。
- **昼夜模式**：桌面版右上角切换浅色/深色；浏览器控制台支持即时切换并记住选择。
- **控制台**：`python -m sentinel console` 提供简洁摘要、完整列表与 `--verbose` 证据；Web 控制台展示事件流、趋势和下一步建议。
- **国家锁定**：可选设置期望出口国家；不一致时安全启动门禁直接阻断。
- **审计历史与趋势**：桌面检测记录摘要到 `state/audit_history.jsonl`，Web 概览显示风险趋势。
- **推荐处置**：从失败/警告自动生成有优先级的下一步建议，不自动修改任何设置。

---

## 2. 运行要求

### 必需

- Windows 便携版：**无需安装 Python**，解压即用。
- 从源码运行：Python **3.10+**（推荐 3.12/3.13/3.14）和 Tkinter。
- Windows 10/11 为完整支持平台；macOS/Linux 的审计、用户级环境变量、快照与配置包可用，但系统级断网/严格安全启动能力有限（见 §8）。

### 可选

- **Node.js 18+**：用于 A4 的 `Intl.DateTimeFormat().resolvedOptions()` 采样；没有 Node 时 A4 为警告。
- **Chrome / Edge**：用于 A16/A17 浏览器策略检查与写入；没有浏览器时这两项为警告。
- **可选 `aiortc`**：安装后会进一步收集 WebRTC ICE 候选；未安装时 Sentinel 仍会做 STUN 绑定和本地接口枚举，但会在 A14 标记覆盖有限。
- **非 Windows 全局热键**：需要可选依赖 `pynput`。

Sentinel 的强制运行时依赖为 **零第三方包**。GUI 使用 Python 自带的 Tkinter；PySide6 是可选偏好，但会让首次运行多一步依赖安装，因此本项目优先做到“下载后可直接运行”。

---

## 3. 安装与启动

### Windows（最简单）

1. 安装 Python 3.10+：<https://www.python.org/downloads/>，安装时勾选 **Add python.exe to PATH**。
2. 双击项目根目录的 `run_sentinel.bat`。
   或在 PowerShell 中执行：

```powershell
cd "C:\path\to\claude-environment-sentinel"
python -m sentinel
```

建议以管理员身份启动，以便：
- 在“一键对齐”中修改系统时区；
- 在 Kill-Switch 触发时创建 Windows 出站防火墙规则。

没有管理员权限时，Sentinel 仍可审计、备份、修改用户级环境变量；但系统时区与安全启动会被明确阻止，不会静默降级。

### 双击桌面版

项目根目录已经生成：

```text
ClaudeSentinel.exe
```

双击它即可打开桌面版（无控制台窗口）。桌面快捷方式也已创建：

```text
%USERPROFILE%\Desktop\Claude Environment Sentinel.lnk
```

`ClaudeSentinel.exe` 是原生 Windows 启动器，会查找项目目录和本机 `pythonw.exe`，再启动 `python -m sentinel`。它依赖本机 Python 3.10+，不是把 Python 运行时打进单文件的独立安装包；如果移动了项目目录，请保持 exe 与 `sentinel/` 文件夹相对位置不变。

如果 exe 丢失或需要重新构建：

```powershell
build_desktop_exe.bat
powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
```

### 浏览器控制台

双击：

```text
run_sentinel_web.bat
```

它会启动一个仅绑定 `127.0.0.1` 的本地控制台，并自动用默认浏览器打开：

```text
http://127.0.0.1:8790/
```

也可以手动启动：

```bash
python -m sentinel web-preview --port 8790 --open
python -m sentinel web-preview --port 8790 --read-only
```

控制台展示真实的 20 项审计、证据详情、历史与对比、风险分解、快照、环境配置包、教程和风险指南，并提供：

- **一键对齐**：B1 时区、B2 语言、B3 Chrome/Edge 策略；
- **一键还原**：撤销上一次对齐、还原最近快照或选择指定快照；
- 控制台事件流、建议下一步、导出 JSON、打印/PDF、昼夜主题。

写操作的安全边界：

- 只接受 127.0.0.1/localhost/::1 的 Host；
- 每个服务进程生成一次性控制 token，写请求必须携带；
- 必须由页面二次确认，并要求 `confirm: true`；
- 对齐前自动创建不可变快照；还原逐项验证；
- 不提供启动 Claude、停止 Claude 或解除 Kill-Switch 的网页接口。

Web 端审计自身仍然不写 `state/last_audit.json`、不写历史、不创建快照；只有明确执行对齐/还原才会写设置和快照。`--read-only` 可恢复旧的只读预览行为。

### 昼夜模式

- 桌面版：右上角“浅色模式 / 深色模式”切换。Tk 控件颜色在创建时固定，切换会重新打开 Sentinel 窗口；不会修改系统设置、快照或 Kill-Switch 规则。
- 浏览器控制台：顶部主题按钮即时切换，并保存在 `localStorage`；没有保存值时跟随系统 `prefers-color-scheme`。
- 主题偏好保存在 `state/config.json` 的 `theme` 字段，不写入系统环境变量。

### 国家锁定与历史

- 专家模式“设置”中可以开启“锁定出口国家”，例如 `US`、`JP`、`CN`；出口不一致或无法确认时，安全启动门禁会直接阻断。
- 桌面版每次完整检测会追加一条摘要到 `state/audit_history.jsonl`（不保存凭证）；Web 概览用最近记录绘制风险趋势。
- Web 新增“历史”页：可筛选历史记录，选择任意一条与当前审计做**历史对比**，查看改善、恶化、新增和缺失项。
- Web 概览新增**风险分解**：按时区、语言、网络、浏览器、客户端、字体分组展示未通过项的权重贡献；只用于解释风险结构，不改变审计分。
- 审计页支持按 ID/标题/摘要搜索，并可**导出**当前 JSON、打印/保存 PDF；历史页可导出历史 JSON。
- 历史与推荐只用于复盘和下一步决策，不自动修改设置，也不承诺账号结果。

### macOS / Linux

```bash
cd /path/to/claude-environment-sentinel
python3 -m sentinel
```

macOS 系统时区修改可能触发系统管理员授权对话框。Linux 的 `timedatectl` 可能需要 polkit。

### 可选安装为命令

```bash
python -m pip install -e .
sentinel
```

（安装本身不是必需的；`python -m sentinel` 可以直接运行。）

---

## 4. 第一次使用

1. **先点“检测”**。这一步只读，不修改系统设置。
2. 阅读审计结果。先看“必须修复”的阻断项，再看警告。
3. 如果决定对齐，点“一键对齐”。确认对话框会告诉你目标时区、locale、浏览器策略，以及是否会修改系统时区。
4. 对齐前 Sentinel 自动创建 `backups/` 快照；失败会直接中止，绝不先写后备份。
5. 对齐完成后会重新采样关键项；仍然失败的项会列出来，不会伪报成功。
6. **只有审计通过后，“安全启动”才会启用。** 安全启动内部还会重新审计一次，不信任界面上的旧结果。

新手教程见 [`tutorials/quick-start.md`](tutorials/quick-start.md)。GUI 新手模式的每个审计项旁有 `?`，点击即可看到同一份通俗解释。

---

## 5. 数据与目录

```text
sentinel/       主程序（含 webui/ 本地浏览器控制台静态资源）
launcher/       ClaudeSentinel.exe 的原生 C# 启动器源码
dist/           可选的构建输出目录
tutorials/      教程（GUI 内嵌）
docs/           防封/风险指南
backups/        不可变快照（运行时生成，不入版本控制）
logs/           JSONL 日志（运行时生成）
state/          配置、审计基线、Kill-Switch 锁定状态（运行时生成）
profiles/       多环境配置包（运行时生成，不含身份材料）
ClaudeSentinel.exe  Windows 原生启动器（构建产物）
```

设置文件：`state/config.json`。它不保存代理密码、Claude Token、Cookie 或登录信息。

快照文件名：`backups/sentinel-snapshot-<UTC时间>-<随机>.json`。每个文件包含：
- 系统时区的原生 Windows ID / IANA 名 / 偏移；
- `TZ`/`LANG`/`LC_ALL` 的“是否存在/值/注册表类型”；
- 将被修改的 Chrome/Edge 用户级策略键；
- POSIX 环境文件的原始内容；
- SHA-256 校验和。

日志：
- `logs/sentinel.jsonl`：检测、对齐、安全启动/停止；
- `logs/killswitch.jsonl`：Kill-Switch 触发/解除；
- `logs/restore.jsonl`：还原与逐项验证；
- `logs/profiles.jsonl`：配置包创建/切换。

---

## 6. CLI

```bash
python -m sentinel                       # 打开 GUI
python -m sentinel audit --json out.json # 审计并导出
python -m sentinel audit --offline       # 不联网的离线诊断
python -m sentinel align --timezone --language --browser
python -m sentinel align --confirm-system-timezone   # 显式确认系统时区修改
python -m sentinel restore --latest --yes
python -m sentinel restore --id <snapshot_id>
python -m sentinel snapshots list
python -m sentinel snapshots show --id <snapshot_id>
python -m sentinel snapshots delete --id <snapshot_id>
python -m sentinel profiles list
python -m sentinel profiles create --name "账号 A / 美西" --country US --proxy-label US-LA-01
python -m sentinel profiles activate --id <profile_id>
python -m sentinel profiles export --id <profile_id> --path profile.json
python -m sentinel profiles import --path profile.json
python -m sentinel doctor
python -m sentinel smoke-test            # 只做 GUI 构造/销毁，不执行审计
python -m sentinel console              # 简洁控制台摘要
python -m sentinel console --verbose    # 展开每项证据
python -m sentinel console --no-color
python -m sentinel web-preview --open    # 本地控制台，默认 8790
python -m sentinel web-preview --open --read-only
python -m sentinel web-preview --no-open --port 8791
```

`restore` 默认要求输入 `YES`；`--yes` 仅用于你已明确知情的手动恢复。`snapshots delete` 不可撤销。

---

## 7. 风险分与门禁

权重和理由在 [`sentinel/audit/risk.py`](sentinel/audit/risk.py) 顶部注释中逐项写明。摘要：

- 高风险：A8=9、A9=8、A5=7、A11=7、A1=6、A12=6。
- 中风险：A2/A4/A6/A7/A10/A16/A17=5。
- 较低：A3/A13/A14/A18/A19=4，A15/A20=3。
- 总计 104。

```text
PASS = 0
WARN = 0.35 × 权重
FAIL/ERROR = 1.0 × 权重
风险分 = round(100 × 加权和 / 104)
```

安全启动同时要求：

1. 风险分 < 60；
2. 不存在“阻断项且状态为失败/异常”；
3. 已配置可执行的 Claude 命令（显式设置或自动探测到）；
4. Kill-Switch 后端可用（Windows：管理员 + 防火墙命令；其他平台需明确支持）。

门禁不通过时，[`sentinel/launcher.py`](sentinel/launcher.py) 会在调用 `Popen` 之前返回，不会拉起 Claude。

---

## 8. 安全设计与已知限制

### 明确不承诺

- 不承诺账号处理结果（包括限制、封禁或审查）；
- 不承诺“环境对齐”能改变服务端评分；
- 不承诺脏 IP、共享 IP、批量注册等根因问题能被本地工具解决；
- 不应用于规避地区服务限制或违反 Anthropic 服务条款。

### 只做可回滚的用户级/系统级设置

- 不修改 Hosts 文件；
- 不修改内核参数；
- 不安装驱动；
- 不持久化后台守护进程（只有应用打开期间的监控线程和热键线程）；
- 不修改浏览器可执行文件；
- 不删除字体。

### 快照与还原

- 快照创建失败 → 不写入任何设置；
- 还原逐项写回，并重新审计；
- 无法还原的项（例如缺少管理员权限）会明确列出，不会静默失败；
- 快照文件不会被后续操作覆盖；删除动作只由用户显式触发。

### Kill-Switch

- Windows：`taskkill /T /F` 终止 Claude 进程树，随后用 `New-NetFirewallRule` 为相关可执行文件创建出站阻断规则；规则名形如 `ClaudeSentinel-Block-<session>-<n>`。
- 如果防火墙规则创建失败，Sentinel 会记录 `firewall_ok=false`，不会谎称已阻断重连。
- 如果 Claude CLI 通过批处理/Node 运行时启动，能定位到的可执行文件可能是 `node.exe` 等共享运行时；规则会按程序路径阻断，可能暂时影响其他使用同一运行时的程序，解除时删除。触发日志会记录实际规则路径。
- 锁定状态持久化到 `state/killswitch.json`；重新打开 Sentinel 仍会显示锁定，必须手动解除。
- 非 Windows 平台尚未提供可验证的进程级出站隔离；为避免虚假安全感，安全启动被禁用，审计/对齐/快照仍可用。

### Node/Electron locale 的平台限制

在 Windows 上，Node 的 ICU 默认 locale 由系统环境决定，`LANG`/`LC_ALL` 通常 **不会**改变 `Intl.DateTimeFormat().resolvedOptions().locale`（`TZ` 会跟随）。Sentinel 不会为了通过检查而修改系统显示语言，也不会注入运行时 shim。B2 对齐后会重新采样 A4；如果 locale 未跟随，A4 显示警告，B2 标记为未完成项，绝不伪报通过。相关背景可参考 [nodejs/node#28099](https://github.com/nodejs/node/issues/28099)。

### 自动化测试不会修改真实系统

测试使用 Fake 平台/网络/进程对象，覆盖快照顺序、还原删除语义、门禁、Kill-Switch 和配置包凭证拒绝；不会在测试中修改你的时区、浏览器策略或防火墙。

---

## 9. 测试与自检

```bash
python -m unittest discover -s tests -v
python -m compileall sentinel
python -m sentinel doctor
python -m sentinel audit --json state/audit-smoke.json --offline
python -m sentinel smoke-test
```

`doctor` 只读，会显示：
- 平台、Python、Tkinter；
- Node/浏览器/Claude 检测；
- 管理员权限；
- Kill-Switch 与全局热键能力；
- 快照数量与数据目录。

---

## 10. 故障排查

### 安全启动按钮一直是灰色

这是设计行为。查看“门禁阻止”的原因：
- 风险分 ≥ 60；
- 某个阻断项失败；
- 未找到 Claude 命令；
- Kill-Switch 后端不可用（例如未以管理员身份运行）；
- Kill-Switch 处于锁定状态。

### 修改系统时区失败

Windows 需要管理员权限；`tzutil /s` 会返回系统错误。Sentinel 不会自动提权。可以：
1. 以管理员身份重新打开 Sentinel；或
2. 只写用户级 `TZ`，并在专家模式接受 A1/A8 仍然失败。

### 浏览器策略写完但审计仍失败

策略通常需要重启浏览器；如果机器策略（HKLM）覆盖了 HKCU，用户级写入不会生效。Sentinel 会读取有效来源并在证据中显示 `effective_hive`。

### 应用卡住/报错

手动恢复命令见 [`tutorials/quick-start.md`](tutorials/quick-start.md) 第 6 节。核心思路：
1. 关闭 Sentinel；
2. 用 `restore --latest --yes` 或 `--id` 还原快照；
3. 检查 `backups/`、`logs/restore.jsonl`；
4. 必要时手动删除环境变量/浏览器策略/`ClaudeSentinel-*` 防火墙规则。

### 想完全移除

1. 在专家模式解除 Kill-Switch 并删除 Sentinel 规则；
2. 用快照还原环境；
3. 关闭 Sentinel；
4. 删除本项目目录（或至少删除 `state/`、`backups/`、`logs/`、`profiles/`）。

---

## 11. 隐私

- Sentinel 不读取 Claude 登录态、Cookie、Token、会话文件或浏览器账号资料；
- 浏览器 Preferences 只提取 `intl.accept_languages`，不导出 `account_info`；
- 代理 URL 中的用户名/密码在证据和日志中脱敏；
- 进程信息只保留名称/PID/路径，不导出命令行，避免会话参数泄漏；
- 网络请求只用于 IP/地区/DoH/时间/STUN 探测，不向 Claude 提交账号数据；
- 所有报告和日志都在本地。

---

## 12. 构建 Windows 便携版

需要 Windows、.NET Framework `csc.exe` 和本机 CPython（含 Tkinter）：

```powershell
pwsh -File scripts/build_portable.ps1
```

输出：

```text
dist/Claude-Sentinel-1.1.0-win64-portable/
dist/Claude-Sentinel-1.1.0-win64-portable.zip
```

便携包把 CPython 运行时放在 `python/`，启动器优先使用它，不依赖系统 Python。

## 13. 目录与测试索引

- 审计项实现：[`sentinel/audit/checks.py`](sentinel/audit/checks.py)
- 风险/门禁：[`sentinel/audit/risk.py`](sentinel/audit/risk.py)
- 快照/还原：[`sentinel/snapshots.py`](sentinel/snapshots.py)
- 对齐：[`sentinel/align/engine.py`](sentinel/align/engine.py)
- Kill-Switch：[`sentinel/killswitch.py`](sentinel/killswitch.py)
- 安全启动：[`sentinel/launcher.py`](sentinel/launcher.py)
- 多环境配置包：[`sentinel/profiles.py`](sentinel/profiles.py)
- GUI：[`sentinel/gui/main_window.py`](sentinel/gui/main_window.py)
- 教程：[`tutorials/quick-start.md`](tutorials/quick-start.md)
- 风险指南：[`docs/anti-ban-guide.md`](docs/anti-ban-guide.md)

模块 H 在原始需求消息中被截断，因此本版本先交付 A–G，并把 H 实现为低风险增强：CLI/doctor、审计历史基线、配置包导入导出基础、报告导出。没有实现后台常驻守护或服务端风控绕过。

---

## 14. 开发者 / Maintainer

- **开发者：戴亿**（Dai Yi / DaiYiqq）
- **GitHub**：[@DaiYiqq](https://github.com/DaiYiqq)
- **抖音**：`daiyi091004`
- **Twitter / X**：[@daiyi_520](https://x.com/daiyi_520)
- **QQ**：`1703205607`

这是一个非官方项目。联系开发者时请不要发送真实账号密码、Cookie、Token、
完整环境快照或代理凭据。

## 15. 社区共同维护

Sentinel 欢迎社区共同维护：

- **GitHub Discussions**：<https://github.com/DaiYiqq/claude-environment-sentinel/discussions>
- **Issues**：<https://github.com/DaiYiqq/claude-environment-sentinel/issues>
- **Pull Requests**：<https://github.com/DaiYiqq/claude-environment-sentinel/pulls>
- **贡献指南**：[CONTRIBUTING.md](CONTRIBUTING.md)
- **治理说明**：[GOVERNANCE.md](GOVERNANCE.md)
- **行为准则**：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **安全报告**：[SECURITY.md](SECURITY.md) / GitHub Security Advisories
- **翻译**：欢迎维护 English / 日本語 README 与文档翻译；请保留安全边界原文含义。

社区贡献不会改变项目边界：不接收绕过服务端风控的功能，不接收真实账号凭据，
不承诺账号结果。

## 16. 许可证与历史版本

从 **v1.1.0** 开始，项目使用 **GNU Affero General Public License v3.0 only
（AGPL-3.0-only）**。这是保守型强 copyleft 许可证：修改和分发需要继续开源，
通过网络服务提供修改版也需要向用户提供对应源码。

- 完整许可证：[LICENSE](LICENSE)
- 版权/保证声明：[NOTICE](NOTICE)
- 历史版本说明：[LICENSING.md](LICENSING.md)
- v1.0.0 曾按 MIT 发布：[LICENSE-MIT](LICENSE-MIT)

v1.0.0 已经授予的 MIT 权利不可撤销；v1.1.0 起的新代码和新贡献使用 AGPL-3.0-only。
第三方组件仍遵循各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
