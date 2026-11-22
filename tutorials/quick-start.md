# Claude Environment Sentinel 新手教程

> 这份教程假设你**没有打开过终端**。每一步都给出完整命令；看到命令时，复制整行到 Windows PowerShell 或 macOS“终端”里按回车即可。
>
> 先记住一句话：**先检测，再对齐，最后才安全启动。** 不要一上来就点“安全启动”。

---

## 1. 先确认电脑上有 Python 和 Node.js

### 1.1 Python 是什么？为什么需要它？

Sentinel 本身是一个 Python 程序。没有 Python，它无法运行。

- 下载地址：<https://www.python.org/downloads/>
- 版本要求：**3.10 或更新**；推荐 3.12/3.13/3.14。
- Windows 安装时务必勾选 **Add python.exe to PATH**（把 Python 加到 PATH）。如果忘了勾选，重新安装一次并勾选。

### 1.2 检查 Python 是否安装成功

打开 Windows 的“开始菜单”，搜索 **PowerShell**，打开后输入：

```powershell
python --version
```

你应该看到类似：

```text
Python 3.12.8
```

如果提示“不是内部或外部命令”，说明 Python 没装好或没加入 PATH。重新安装并勾选 Add to PATH。

### 1.3 Node.js 是什么？为什么需要它？

Node.js 是 Claude CLI 和很多 Electron 应用使用的运行时。Sentinel 会调用 Node 来观察 `Intl` 实际看到的时区和 locale（审计项 A4）。

- 下载地址：<https://nodejs.org/>
- 版本要求：**18 或更新**；推荐 LTS 版本。
- 安装时保持默认选项即可。

检查：

```powershell
node --version
```

看到 `v18.x`、`v20.x`、`v22.x` 或更高即可。

> 没有 Node 时 Sentinel 仍能运行，但 A4 会显示“警告”，而不是通过。安装 Node 后重新检测即可。

### 1.4 检查 Tkinter（Python 的图形界面库）

Windows 官方 Python 一般自带 Tkinter。检查：

```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
```

看到 `8.6` 或 `9.0` 即可。macOS 如果报错，通常需要安装 python.org 的官方 Python，而不是系统自带的旧版本。

---

## 2. 第一次打开 Sentinel

### 2.1 启动

在项目文件夹中双击：

```text
run_sentinel.bat
```

或者在 PowerShell 里：

```powershell
cd "C:\path\to\claude-environment-sentinel"
python -m sentinel
```

第一次启动不会自动修改任何设置。

### 2.2 第一件事：点“检测”

新手模式只有三个主要按钮：

1. **检测**
2. **一键对齐**
3. **安全启动**

先点 **检测**。它会读取：

- 系统时区、`TZ`/`LANG`/`LC_ALL`；
- Node 看到的 Intl 时区/locale；
- 出口 IP 国家、ASN、IP 类型；
- 代理变量、代理内核、TUN；
- DNS 出口、WebRTC、字体、浏览器语言/WebRTC 策略；
- Claude 客户端、系统时钟、与上次审计的漂移。

检测过程通常需要几秒到几十秒，取决于网络探测。结果会显示：

- 风险分 0–100；
- 通过/警告/失败数量；
- 每个失败项的原因；
- 安全启动是否被允许。

### 2.3 第二件事：读结果，不要急着安全启动

请先看“审计未通过/允许”的提示。**只要还有阻断级失败，安全启动按钮就是灰色或点击后会被拒绝。** 这不是 bug，而是设计目标：审计不通过，Claude 进程不得被拉起。

### 2.4 每个项目旁边的 `?`

新手模式每个审计项右侧都有 `?`。点击会显示：

- 这一项通俗解释；
- 本次采样的证据行；
- 原始 JSON；
- 修复建议。

专家模式还能点“修复此项”。

---

## 3. 审计项通俗解释：哪些必须修，哪些可以忽略

状态含义：

- **通过**：当前采样正常。
- **警告**：有风险或信息不足，通常不阻断安全启动，但会提高风险分。
- **失败**：关键冲突或异常，通常阻断安全启动，必须先处理。
- **采样异常**：Sentinel 内部执行某项时出错；结果不可信，需要查看证据/日志。

### A1 系统时区

**是什么**：Windows 控制面板里的系统时区。

**怎么判断**：Sentinel 能否读到系统时区。

**必须修吗**：读不到才算失败。读得到但地区不对，由 A8 判断。

### A2 用户环境变量 TZ

**是什么**：只对当前用户生效的时区覆盖。

**怎么判断**：没设置 = 警告（程序会继承系统时区）；设置了但无效或与系统时区不一致 = 失败。

**必须修吗**：如果设置了冲突的 TZ，必须修，否则 Node/CLI 可能按另一个时区运行。

### A3 用户环境变量 LANG / LC_ALL

**是什么**：只对当前用户生效的语言环境。

**怎么判断**：两个都没设置 = 警告；格式非法或两者互相冲突 = 失败；有效且一致 = 通过。

**必须修吗**：冲突/非法必须修；未设置通常可以暂时忽略。

### A4 Node Intl 默认环境

**是什么**：真正启动一次 Node，看它看到的 locale 和时区。

**怎么判断**：Node 不存在 = 警告；Node 时区与系统/用户时区冲突 = 失败；locale 不跟随 = 警告（Windows 平台限制）。

**必须修吗**：时区冲突必须修。Windows 上 Node 的 locale 由系统决定，Sentinel 不会为了通过而改系统显示语言，也不会伪报通过。

### A5 出口 IP 国家/地区

**是什么**：网络实际从哪里出去。

**怎么判断**：ipinfo → ip-api → Cloudflare trace；都失败 = 失败；有 IP 没国家 = 警告；有国家 = 通过。

**必须修吗**：探测全失败时必须先修复网络/代理，否则无法判断地区一致性。

### A6 出口 IP 的 ASN 与类型

**是什么**：住宅、移动、机房、代理/Tor。

**怎么判断**：住宅/移动 = 通过；机房/未知 = 警告；代理/Tor 标记 = 失败。

**必须修吗**：代理/Tor 标记需要处理；机房 IP 是风险提示，Sentinel 不能“洗白”IP 质量。

### A7 出口 IP 与上次审计一致

**是什么**：这次出口和上次记录比。

**怎么判断**：首次 = 通过并建立基线；同国换 IP = 警告；换国 = 失败。

**必须修吗**：换国通常意味着你应该停下来确认，而不是继续切。

### A8 系统时区与出口地区偏移

**是什么**：系统时间告诉服务端你在哪个时区，网络又告诉它你在哪个地区。

**怎么判断**：系统 UTC 偏移与出口 IP 时区当前偏移差 ≤2 小时 = 通过；>2 小时 = 失败；出口时区未知 = 警告。

**通俗例子**：

> A8 失败 = 你的系统时间告诉 Claude 你在东八区，但你的网络出口在美国，这两件事对不上。

**必须修吗**：这是核心冲突，必须修。

### A9 系统语言与出口地区

**是什么**：系统和网络是否讲同一个地区故事。

**怎么判断**：中文系统 + 欧美 IP = 失败；中日韩与西方语言双向硬冲突 = 失败；一般不匹配 = 警告；匹配 = 通过。

**必须修吗**：硬冲突必须修。

### A10 代理环境变量

**是什么**：HTTP_PROXY / HTTPS_PROXY / ALL_PROXY。

**怎么判断**：没设置 = 警告（可能使用 TUN/系统代理）；格式非法 = 失败；有效 = 通过；不同变量指向不同出口 = 警告。

**必须修吗**：格式非法必须修。没有代理变量不一定是错误，取决于你的网络方案。

### A11 代理内核存活

**是什么**：Clash/mihomo、sing-box、v2ray/xray 等真正转发流量的程序。

**怎么判断**：配置了代理变量但内核没运行 = 失败；内核在但端口不通 = 警告；直连 = 警告。

**必须修吗**：配置了代理却不可用时必须修，否则流量可能直接泄漏。

### A12 TUN / 虚拟网卡

**是什么**：透明代理使用的虚拟网卡。

**怎么判断**：活动 TUN = 通过；配置代理但没有 TUN = 警告（CLI 可能绕过浏览器代理）；明确要求 TUN 但缺失 = 失败；直连 = 警告。

**必须修吗**：只有你开启了“要求 TUN”时才阻断；否则是可忽略的警告。

### A13 DNS 出口

**是什么**：DNS 查询实际从哪里出去。

**怎么判断**：用 Cloudflare 和 Google 的 DoH 查询各自出口 IP，再查 ASN；不一致 = 警告；样本不足 = 警告。

**必须修吗**：通常是警告；先确认你的代理 DNS 设置。

### A14 WebRTC 地址泄漏

**是什么**：WebRTC 是否暴露了非出口的公网地址。

**怎么判断**：STUN 映射或 ICE 候选出现非出口公网 IP = 失败；覆盖不足 = 警告；一致 = 通过/警告（取决于覆盖）。

**必须修吗**：发现公网泄漏必须修。仅有 RFC1918 地址或覆盖不足时是警告。

### A15 字体地区特征

**是什么**：SimSun、微软雅黑、文泉驿、方正等典型中文办公字体。

**怎么判断**：命中 = 警告；未命中 = 通过。

**必须修吗**：**不必须，也绝不自动删除。** 删字体会影响其他软件。Sentinel 只做标记。

### A16 浏览器 Accept-Language 策略

**是什么**：Chrome/Edge 发给网站的 `Accept-Language`。

**怎么判断**：策略与出口地区匹配 = 通过；只有用户偏好、没有策略锁定 = 警告；缺失/不匹配 = 失败；没有浏览器 = 警告。

**必须修吗**：缺失/不匹配会阻断安全启动；写入后通常需要重启浏览器。

### A17 浏览器 WebRTC 策略

**是什么**：Chrome/Edge 的 `WebRtcIPHandling`。

**怎么判断**：`disable_non_proxied_udp` = 通过；`default_public_interface_only` = 警告；缺失/default = 失败。

**必须修吗**：缺失会阻断安全启动；写入后重启浏览器。

### A18 Claude 客户端类型与版本

**是什么**：CLI、桌面客户端或浏览器是否安装，以及版本。

**怎么判断**：检测到且版本可读 = 通过；检测到但版本读不到 = 警告；未检测到 = 警告。

**必须修吗**：不阻断审计，但安全启动需要可执行命令；可在专家模式“设置”里指定路径。

**隐私**：这一项不读取登录态、Cookie、Token 或会话文件，只检测程序和版本。

### A19 系统时钟偏差

**是什么**：本机时间与网络时间差。

**怎么判断**：≤30 秒 = 通过；30 秒–5 分钟 = 警告；>5 分钟 = 失败；无法采样 = 警告。

**必须修吗**：超过 5 分钟必须修（开启系统自动时间同步）。

### A20 关键配置漂移

**是什么**：和上一次审计相比，关键项有没有变化。

**怎么判断**：0 项 = 通过；1–2 项 = 警告；≥3 项 = 警告（风险分提高）；首次 = 通过并建立基线。

**必须修吗**：不直接阻断，但频繁变化本身是风险信号。请确认变化是不是你主动做的。

---

## 4. 一键对齐

### 4.1 什么时候点

当你看完审计，确认：

- 出口地区是你想要的；
- 你愿意让 Sentinel 修改用户级时区/语言/浏览器策略；
- 你理解系统时区修改需要管理员权限。

再点 **一键对齐**。

### 4.2 确认对话框会告诉你什么

- 目标国家/地区；
- 目标时区（来自出口 IP 的 IANA 时区）；
- 目标 locale；
- 浏览器 Accept-Language；
- 是否同时修改系统时区；
- “我理解这会修改用户级设置”的确认框。

### 4.3 快照

点“创建快照并应用”后，Sentinel **先**在 `backups/` 生成一个 JSON 快照，包含：

- 系统时区原始值；
- `TZ`/`LANG`/`LC_ALL` 的原始值，明确区分“不存在”和“存在但为空”；
- Chrome/Edge 被修改策略键的原始值；
- POSIX 环境文件原始内容（macOS/Linux）；
- SHA-256 校验和。

快照创建失败时，Sentinel 不会写入任何设置。

### 4.4 对齐后会发生什么

- B1：写用户级 `TZ`；只有你勾选并确认后才改系统时区；
- B2：写用户级 `LANG`/`LC_ALL`；
- B3：写 Chrome/Edge 用户级策略；
- B4：字体只提示，不删除；
- 自动重新采样 A1–A4、A16–A17；
- 如果 Node locale 在 Windows 上没有跟随，B2 会列为未完成项，A4 显示警告，不会假装通过。

浏览器正在运行时，策略通常要重启浏览器才完全生效；GUI 会提示。

### 4.5 在浏览器控制台一键对齐

本地控制台（`127.0.0.1:8790`）的“操作”页也可以一键对齐：

1. 先运行检测；
2. 点击“创建快照并一键对齐”；
3. 在确认对话框中检查目标国家、时区、locale、Accept-Language；
4. 勾选 B1 时区、B2 语言、B3 浏览器策略；
5. 管理员可选择“同时修改系统时区”；
6. 勾选“我理解会修改本机环境设置”，确认执行。

写操作受一次性 token、二次确认和 Host/Origin 校验保护；对齐前仍会先创建快照。
如果只想查看，可使用 `python -m sentinel web-preview --read-only` 启动只读模式。

---

## 5. 一键还原

### 5.1 在 GUI 中还原

1. 切到专家模式；
2. 打开“快照”标签；
3. 选择快照；
4. 点“还原选中快照”，或点“还原最近快照”；
5. 确认后，Sentinel 逐项写回原始值；
6. 自动重新审计，并列出“未能还原的项”。

### 5.2 还原规则

- 原本存在的变量：写回原值和原类型；
- 原本不存在的变量：**删除**，不是设成空字符串；
- 原本不存在的浏览器策略值：删除；
- 原本不存在的策略键：如果 Sentinel 创建后变空，会清理该键；
- 系统时区：优先写回原始 Windows ID；需要管理员权限。

### 5.3 还原后如何验证

看还原结果对话框里的“逐项验证”：

- `[OK]`：当前值和快照原始值一致；
- `[MISMATCH]`：当前值仍不一致，通常会附原因和手动命令。

再点一次“检测”，确认关键项回到你熟悉的状态。

### 5.4 CLI 还原

如果 GUI 卡住，可以在 PowerShell 中：

```powershell
python -m sentinel snapshots list
python -m sentinel restore --latest --yes
```

或指定 ID：

```powershell
python -m sentinel restore --id 20261122T071144Z-abcdef12 --yes
```

`--yes` 表示你已明确知情；不要在不清楚快照内容时使用。

### 5.5 在浏览器控制台一键还原

“操作”页的还原卡提供三种方式：

- **撤销上次对齐**：使用上一次对齐前创建的快照；
- **还原最近快照**：使用 `backups/` 中最新的快照；
- **还原所选快照**：从下拉列表中选择。

确认后会逐项写回原始值，原本不存在的 `TZ/LANG/LC_ALL` 会被删除，而不是设为空字符串。完成后会自动复检，并列出未还原项和手动命令。

---

## 5.6 主题、控制台、历史与国家锁定

### 昼夜模式

- 桌面版右上角有“浅色模式 / 深色模式”开关；切换会重新打开 Sentinel 窗口，让整个界面使用新配色。
- 浏览器控制台顶部也有主题按钮，点击即时切换，刷新后仍记得你的选择。
- 主题只影响界面显示，不修改系统设置、不修改环境变量。

### 控制台

桌面版专家模式新增“控制台”标签，显示最近审计历史、Kill-Switch 状态和建议下一步。命令行也可以用：

```powershell
python -m sentinel console
python -m sentinel console --verbose
python -m sentinel console --no-color
```

默认输出风险分、出口、状态统计、完整 20 项摘要和建议下一步；`--verbose` 才展开每项证据行，避免默认输出过于嘈杂。

### 风险趋势

每次桌面版完整检测会向 `state/audit_history.jsonl` 追加一条摘要。浏览器控制台“概览”页会把最近记录画成趋势图。它记录的是风险分、门禁、出口国家/地区等摘要，不保存凭证。

趋势只用于观察稳定性，不是账号评分，也不能预测账号结果。

### 历史对比与风险分解

浏览器控制台新增“历史”页：

- 先运行桌面版或 `python -m sentinel console` 完整检测，历史页才会积累记录；
- 点击任意历史记录，可以和当前审计逐项对比，看到哪些项改善、恶化、新增或缺失；
- 旧版本历史如果没有逐项状态，页面会明确提示“无法逐项对比”，不会伪造结果；
- 历史页可以导出历史 JSON。

概览页的“风险分解”会按时区、语言、网络、浏览器、客户端、字体六组，显示未通过项的权重贡献。它用于解释风险来自哪里，不是账号安全评分。

审计页支持按 ID、标题、摘要搜索，并可以导出当前 JSON、打印或保存 PDF。导出和打印都只使用当前缓存报告，不会写回系统设置。

### 国家锁定

如果你希望 Claude 只在一个国家/地区使用，可在专家模式“设置”中开启“锁定出口国家”，填写如 `US`、`JP`、`CN`。当出口国家不一致或无法确认时，安全启动会被门禁阻止。这个功能是额外保险，不会让 IP 本身变干净。

---

## 6. Sentinel 报错或卡住时的手动恢复

### 6.1 先关闭 Sentinel

- 点窗口右上角关闭；
- 如果界面卡死，用任务管理器结束 **Sentinel 的 python.exe**（注意不要结束你其他的 Python 程序），或：

```powershell
Get-Process python | Select-Object Id, Path
taskkill /PID <确认后的 PID> /F
```

只结束你确认属于 Sentinel 的进程。

### 6.2 手动改回 Windows 系统时区

查看当前：

```powershell
tzutil /g
```

改回中国标准时间（需要管理员 PowerShell）：

```powershell
tzutil /s "China Standard Time"
```

常用值：
- 中国：`China Standard Time`
- 日本：`Tokyo Standard Time`
- 美国太平洋：`Pacific Standard Time`
- 美国东部：`Eastern Standard Time`
- 英国：`GMT Standard Time`

### 6.3 手动删除 Windows 用户环境变量

先查看：

```powershell
reg query "HKCU\Environment" /v TZ
reg query "HKCU\Environment" /v LANG
reg query "HKCU\Environment" /v LC_ALL
```

删除（不存在也没关系）：

```powershell
reg delete "HKCU\Environment" /v TZ /f
reg delete "HKCU\Environment" /v LANG /f
reg delete "HKCU\Environment" /v LC_ALL /f
```

**不要用 `setx TZ ""` 来“删除”**：`setx` 会把变量设成空字符串，而不是删除。用上面的 `reg delete`，或：

```powershell
[Environment]::SetEnvironmentVariable("TZ", $null, "User")
[Environment]::SetEnvironmentVariable("LANG", $null, "User")
[Environment]::SetEnvironmentVariable("LC_ALL", $null, "User")
```

### 6.4 手动删除 Windows 浏览器策略

Chrome：

```powershell
reg delete "HKCU\Software\Policies\Google\Chrome" /v IntlAcceptLanguages /f
reg delete "HKCU\Software\Policies\Google\Chrome" /v WebRtcIPHandling /f
```

Edge：

```powershell
reg delete "HKCU\Software\Policies\Microsoft\Edge" /v DefinePreferredLanguages /f
reg delete "HKCU\Software\Policies\Microsoft\Edge" /v WebRtcIPHandling /f
```

删完重启浏览器。

### 6.5 手动清理 Sentinel 防火墙规则

先看：

```powershell
Get-NetFirewallRule -DisplayName "ClaudeSentinel-*" | Select-Object DisplayName, Enabled, Direction, Action
```

确认这些都是 Sentinel 创建的（名称以 `ClaudeSentinel-Block-` 开头），再删除：

```powershell
Remove-NetFirewallRule -DisplayName "ClaudeSentinel-*"
```

这需要管理员 PowerShell。优先在 Sentinel 的 Kill-Switch 页面点“解除锁定并删除规则”，不要手动删；手动命令只用于 GUI 无法启动的恢复场景。

### 6.6 手动改回 macOS 系统时区

查看：

```bash
sudo systemsetup -gettimezone
```

改回：

```bash
sudo systemsetup -settimezone Asia/Shanghai
```

### 6.7 手动删除 macOS 用户环境变量

查看当前 shell 中的：

```bash
echo "$TZ"
echo "$LANG"
echo "$LC_ALL"
```

临时删除（当前终端会话）：

```bash
unset TZ
unset LANG
unset LC_ALL
```

持久化设置可能写在 `~/.zshrc`、`~/.zprofile` 或 `~/.config/environment.d/` 中。打开对应文件，删除 Sentinel 新增的 `TZ=`/`LANG=`/`LC_ALL=` 行；不要删除其他内容。

macOS 的 launchd 会话变量：

```bash
launchctl unsetenv TZ
launchctl unsetenv LANG
launchctl unsetenv LC_ALL
```

### 6.8 手动删除 macOS 浏览器策略

```bash
defaults delete com.google.Chrome IntlAcceptLanguages
defaults delete com.google.Chrome WebRtcIPHandling
defaults delete com.microsoft.Edge DefinePreferredLanguages
defaults delete com.microsoft.Edge WebRtcIPHandling
```

### 6.9 最后手段：从快照恢复

如果还能运行 CLI：

```powershell
python -m sentinel restore --latest --yes
```

如果 Python 启动不了，快照文件仍在 `backups/sentinel-snapshot-*.json`。用文本编辑器打开，按里面的 `system_timezone`、`user_env`、`browser_policies` 记录手动写回。**不要修改快照文件本身**；先复制一份再操作。

---

## 7. 常见问题

### 为什么“安全启动”是灰色的？

可能原因：

- 还没检测；
- 风险分 ≥ 60；
- 有阻断项失败；
- 没有配置 Claude 命令；
- Kill-Switch 后端不可用（如未以管理员身份运行）；
- Kill-Switch 处于锁定状态。

把鼠标移到/查看按钮下方的原因说明，或切到专家模式看完整审计。

### 为什么 A8 失败了？

见上面的例子：系统时区和网络出口不在同一个时区范围。先确认出口 IP 是你想要的，再用 B1 对齐；只改程序时区而系统时区不变，A8 仍会失败。

### 为什么 A4 是警告，而不是失败？

Windows 上 Node 的 ICU 默认 locale 由系统决定，`LANG`/`LC_ALL` 可能不生效。Sentinel 不会修改系统显示语言来“凑通过”，所以把它标为警告并给出原始采样。这是透明处理，不是漏检。

### 为什么浏览器策略写完了 A16/A17 还失败？

- 浏览器没重启；
- 机器策略（HKLM）覆盖了用户策略；
- 浏览器不在 Sentinel 识别的安装路径；
- 策略名/值被其他管理软件改回。

看审计证据里的 `effective_hive`。如果是 `HKLM`，用户级写入不会覆盖它。

### 为什么 Kill-Switch 说“没有受管会话”？

Kill-Switch 只保护由 Sentinel 在“安全启动”中拉起的 Claude。你自己在其他终端/桌面快捷方式启动的 Claude 不受它监控。这是范围限制，不是故障。

### 我需要一直开着 Sentinel 吗？

安全启动后的监控线程只在 Sentinel 打开期间运行。关闭 Sentinel 会停止受管会话（正常关闭时）或保留锁定/防火墙规则（已触发时）。它不是后台守护进程。

---

## 8. 使用边界

Sentinel 只降低“本地环境画像和网络出口地区不一致”这一层风险。它：

- 不承诺账号处理结果；
- 不能把脏 IP 变成干净 IP；
- 不能替代对服务条款和地区可用性政策的遵守；
- 不适合用于规避地区服务限制；
- 不修改 Claude 客户端、不处理登录凭证、不管理 Cookie/Token。

请把这份教程当作“减少不一致”的工具说明，而不是账号安全承诺。更完整的风险模型见 [`docs/anti-ban-guide.md`](../docs/anti-ban-guide.md)。
