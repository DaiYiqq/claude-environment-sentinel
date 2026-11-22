# Claude Environment Sentinel

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja-JP.md)

**Audit first. Align second. Start safely last.**

[![GitHub](https://img.shields.io/badge/GitHub-DaiYiqq%2Fclaude--environment--sentinel-181717?logo=github)](https://github.com/DaiYiqq/claude-environment-sentinel)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-2ea44f.svg)](LICENSE)
[![Windows portable](https://img.shields.io/badge/Download-Windows%20portable-0f766e)](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest)

**Download:** [Windows portable](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest) ·
**Website:** <https://daiyiqq.github.io/claude-environment-sentinel/> ·
**Source:** <https://github.com/DaiYiqq/claude-environment-sentinel>

The Windows portable build bundles CPython and Tk. Extract it and double-click
`ClaudeSentinel.exe`; no system Python installation is required. The build is
unsigned, so Windows SmartScreen may warn.

## What it is

Claude Environment Sentinel is a local-first desktop companion for people who
use Claude. Before starting Claude, it audits up to 20 environment signals:
system timezone, language, Node/Electron-visible environment, network exit
region, proxy/TUN, DNS, WebRTC, browser policies, clock skew and drift.

It can reversibly align user-level settings, take immutable snapshots, restore
them item by item, and run a Kill-Switch while a supervised Claude process is
running.

> **Boundary:** Sentinel reduces avoidable local environment inconsistencies.
> It does not guarantee account outcomes, does not bypass server-side risk
> controls, and does not replace compliance with Anthropic's terms and regional
> availability policies.

## Download

- **Windows 10/11 x64 portable ZIP**: [latest release](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest)
- Includes CPython/Tk runtime; no Python required.
- Extract the whole folder; do not copy only the EXE.
- Optional: Node.js and Chrome/Edge improve the locale and browser checks.

## Core capabilities

- **20-item audit and weighted risk score** with evidence, raw samples and
  human-readable explanations.
- **Reversible alignment** for user-level `TZ`, `LANG`, `LC_ALL`, Chrome/Edge
  language and WebRTC policies, with explicit confirmation for system timezone.
- **Immutable snapshots** created before writes, SHA-256 checksummed, with
  item-by-item restore. Variables that did not exist before are deleted, not
  set to empty strings.
- **Kill-Switch** after safe start: checks exit country/IP, proxy core and TUN;
  on violation it terminates the supervised Claude process tree and creates an
  outbound firewall rule.
- **Local browser console** with history, diff, risk breakdown, recommendations,
  one-click align/restore, token-protected write actions, export and print.
- **Dark/light themes** and a local-only design with no telemetry.
- **Environment profiles** that never store credentials, cookies, tokens,
  session files or account identities.

## Safety boundaries

- No reading or storing Claude login state, cookies, tokens or session files.
- No hosts/kernel/driver modifications; fonts are only flagged, never deleted.
- No server-side risk-control bypass.
- No guarantee that an account will not be limited.
- Write actions require explicit confirmation and create a snapshot first.
- The browser console binds to `127.0.0.1`; write requests require a per-process
  token, valid Host/Origin and `confirm: true`.
- Start Claude and release Kill-Switch from the desktop app, not the browser.

## Quick start

1. Download the Windows portable ZIP and extract all files.
2. Double-click `ClaudeSentinel.exe`.
3. Run **Audit** and review the findings and gate reasons.
4. If needed, use **One-click align**; it creates a snapshot first.
5. Use **One-click restore** to undo the alignment.
6. For the local browser console, run `run_sentinel_web.bat`.

From source:

```powershell
python -m sentinel
python -m sentinel web-preview --open
python -m unittest discover -s tests
powershell -File scripts/build_portable.ps1
```

The detailed tutorial and risk guide are currently written in Chinese:

- [Quick start (Chinese)](tutorials/quick-start.md)
- [Risk guide (Chinese)](docs/anti-ban-guide.md)

## Developer / Maintainer

- **Developer: 戴亿 (Dai Yi / DaiYiqq)**
- **GitHub:** [@DaiYiqq](https://github.com/DaiYiqq)
- **Douyin:** `daiyi091004`
- **Twitter / X:** [@daiyi_520](https://x.com/daiyi_520)
- **QQ:** `1703205607`

This is an unofficial project. Please do not send real passwords, cookies,
tokens, complete environment snapshots or proxy credentials.

## Community

Sentinel is maintained with the community:

- [GitHub Discussions](https://github.com/DaiYiqq/claude-environment-sentinel/discussions)
- [Issues](https://github.com/DaiYiqq/claude-environment-sentinel/issues)
- [Pull Requests](https://github.com/DaiYiqq/claude-environment-sentinel/pulls)
- [Contributing](CONTRIBUTING.md) · [Governance](GOVERNANCE.md) · [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md) / GitHub Security Advisories
- Translations for English and Japanese README are welcome. Keep the safety
  boundary accurate when translating.

Contributions must not add server-side risk-control bypasses, credential
collection or claims that the project can guarantee account outcomes.

## License and version history

Starting with **v1.1.0**, this project is licensed under the
**GNU Affero General Public License v3.0 only (AGPL-3.0-only)**.

- [LICENSE](LICENSE) — full AGPL-3.0 text
- [NOTICE](NOTICE) — copyright and warranty notice
- [LICENSING.md](LICENSING.md) — version history and contribution terms
- [LICENSE-MIT](LICENSE-MIT) — historical v1.0.0 MIT license
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

v1.0.0 was published under MIT and those copies remain under MIT. New code and
new releases use AGPL-3.0-only.
