# Claude Environment Sentinel

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja-JP.md)

**まず監査、次に整合、最後に安全な起動。**

[![GitHub](https://img.shields.io/badge/GitHub-DaiYiqq%2Fclaude--environment--sentinel-181717?logo=github)](https://github.com/DaiYiqq/claude-environment-sentinel)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-2ea44f.svg)](LICENSE)
[![Windows portable](https://img.shields.io/badge/Download-Windows%20portable-0f766e)](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest)

**ダウンロード：** [Windows ポータブル版](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest) ·
**紹介サイト：** <https://daiyiqq.github.io/claude-environment-sentinel/> ·
**ソース：** <https://github.com/DaiYiqq/claude-environment-sentinel>

Windows ポータブル版には CPython と Tk のランタイムが含まれています。展開して
`ClaudeSentinel.exe` をダブルクリックすれば起動でき、Python のインストールは不要です。
ビルドは未署名のため、Windows SmartScreen の警告が表示される場合があります。

## 概要

Claude Environment Sentinel は、Claude を利用する人のためのローカル優先デスクトップ
ツールです。Claude 起動前に、システムタイムゾーン、言語、Node/Electron から見える
環境、出口地域、プロキシ/TUN、DNS、WebRTC、ブラウザーポリシー、時計のずれなど最大
20 項目を監査します。

ユーザーレベルの設定を可逆的に整合し、書き込み前に不変スナップショットを作成し、
項目ごとに復元できます。監視対象の Claude 起動後には Kill-Switch も利用できます。

> **境界：** Sentinel はローカル環境の不要な不一致を減らすためのものです。
> アカウントの結果を保証せず、サーバー側のリスク管理を回避するものでもありません。
> Anthropic の利用規約・地域提供ポリシーへの遵守を代替しません。

## ダウンロード

- **Windows 10/11 x64 ポータブル ZIP**：[最新リリース](https://github.com/DaiYiqq/claude-environment-sentinel/releases/latest)
- CPython/Tk ランタイム同梱。Python の事前インストールは不要です。
- フォルダ全体を展開してください。EXE だけをコピーしないでください。
- Node.js と Chrome/Edge があると、locale とブラウザー検査の精度が上がります。

## 主な機能

- **20 項目の監査と重み付きリスクスコア**：証拠、生データ、わかりやすい説明付き。
- **可逆な整合**：ユーザーレベルの `TZ`、`LANG`、`LC_ALL`、Chrome/Edge の言語・
  WebRTC ポリシー。システムタイムゾーンは明示確認が必要です。
- **不変スナップショット**：書き込み前に SHA-256 付きで作成。項目ごとに復元し、
  元々存在しなかった環境変数は空文字ではなく削除します。
- **Kill-Switch**：安全起動後、出口国/IP、プロキシコア、TUN を確認。違反時は
  監視対象の Claude プロセスツリーを終了し、送信ブロック用ファイアウォール規則を
  作成します。
- **ローカルブラウザーコンソール**：履歴、差分、リスク内訳、推奨事項、ワンクリック
  整合/復元、トークン保護された書き込み、JSON エクスポート、印刷に対応。
- **ダーク/ライトテーマ**、テレメトリーなしのローカル設計。
- **環境プロファイル**：認証情報、Cookie、Token、セッションファイル、アカウント
  身元を保存しません。

## 安全境界

- Claude のログイン状態、Cookie、Token、セッションファイルを読み取り・保存しません。
- hosts、カーネル、ドライバーを変更しません。フォントは警告のみで削除しません。
- サーバー側のリスク管理を回避しません。
- アカウントが制限されないことを保証しません。
- 書き込み操作は明示確認と事前スナップショットが必須です。
- ブラウザーコンソールは `127.0.0.1` のみにバインドし、書き込みにはプロセスごとの
  トークン、Host/Origin 検証、`confirm: true` が必要です。
- Claude の起動と Kill-Switch 解除はデスクトップ版で行います。

## クイックスタート

1. Windows ポータブル ZIP をダウンロードし、すべて展開します。
2. `ClaudeSentinel.exe` をダブルクリックします。
3. **監査**を実行し、指摘とゲート理由を確認します。
4. 必要なら**ワンクリック整合**を実行します。最初にスナップショットが作成されます。
5. **ワンクリック復元**で元に戻せます。
6. ローカルブラウザーコンソールは `run_sentinel_web.bat` で起動します。

ソースから実行：

```powershell
python -m sentinel
python -m sentinel web-preview --open
python -m unittest discover -s tests
powershell -File scripts/build_portable.ps1
```

詳細なチュートリアルとリスクガイドは現在中国語です：

- [クイックスタート（中国語）](tutorials/quick-start.md)
- [リスクガイド（中国語）](docs/anti-ban-guide.md)

## 開発者 / Maintainer

- **開発者：戴亿（Dai Yi / DaiYiqq）**
- **GitHub：** [@DaiYiqq](https://github.com/DaiYiqq)
- **Douyin（抖音）：** `daiyi091004`
- **Twitter / X：** [@daiyi_520](https://x.com/daiyi_520)
- **QQ：** `1703205607`

非公式プロジェクトです。実際のパスワード、Cookie、Token、完全な環境スナップショット、
プロキシ認証情報を送らないでください。

## コミュニティ

Sentinel はコミュニティと共に維持されています：

- [GitHub Discussions](https://github.com/DaiYiqq/claude-environment-sentinel/discussions)
- [Issues](https://github.com/DaiYiqq/claude-environment-sentinel/issues)
- [Pull Requests](https://github.com/DaiYiqq/claude-environment-sentinel/pulls)
- [コントリビューション](CONTRIBUTING.md) · [ガバナンス](GOVERNANCE.md) · [行動規範](CODE_OF_CONDUCT.md)
- [セキュリティポリシー](SECURITY.md) / GitHub Security Advisories
- English / 日本語 README の翻訳貢献を歓迎します。翻訳時も安全境界の意味を
  正確に保ってください。

サーバー側リスク管理の回避、認証情報の収集、アカウント結果を保証する主張は
受け付けません。

## ライセンスとバージョン履歴

**v1.1.0** 以降、このプロジェクトは
**GNU Affero General Public License v3.0 only（AGPL-3.0-only）** です。

- [LICENSE](LICENSE) — AGPL-3.0 全文
- [NOTICE](NOTICE) — 著作権と保証の表示
- [LICENSING.md](LICENSING.md) — バージョン履歴と貢献条件
- [LICENSE-MIT](LICENSE-MIT) — v1.0.0 の歴史的 MIT ライセンス
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

v1.0.0 は MIT で公開され、そのコピーには MIT が適用されます。新しいコードと
新しいリリースは AGPL-3.0-only です。
