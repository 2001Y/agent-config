# 2001Y's agent-config

公開用の Codex / Agents 設定 repo です。

この repo は `~/.codex` をそのまま公開せず、共有してよい `AGENTS.md` と custom skills だけを切り出す前提で構成しています。認証、履歴、セッション、キャッシュ、ログ、承認済み権限のような machine-specific な情報は含めません。

## 含めるもの

- `AGENTS.md`
- `skills/coding-confidant`
- `skills/trend-researcher`
- `skills/insights`
- `skills/agent-browser` - 公式 skill の案内ファイル
- `skills/find-skills` - 公式 skill の案内ファイル

## インストール

### custom skill 一覧を見る

```bash
npx skills add 2001Y/agent-config --list
```

### custom skill を入れる

```bash
npx skills add 2001Y/agent-config --skill coding-confidant
npx skills add 2001Y/agent-config --skill trend-researcher
npx skills add 2001Y/agent-config --skill insights
```

### 全 custom skill を入れる

```bash
npx skills add 2001Y/agent-config --skill '*'
```

### 公式 skill は upstream から入れる

`skills/agent-browser` と `skills/find-skills` は実体 skill ではなく、install 方法だけを書いた案内ファイルです。

```bash
npx skills add vercel-labs/agent-browser
npx skills add vercel-labs/skills --skill find-skills
```

### Codex 向けに明示する

```bash
npx skills add 2001Y/agent-config --skill coding-confidant -a codex
```

## `AGENTS.md`

`AGENTS.md` は `skills add` の管理対象ではないので、更新しやすいように repo を clone して使うのを推奨します。

```bash
git clone https://github.com/2001Y/agent-config.git ~/.config/agent-config
ln -sf ~/.config/agent-config/AGENTS.md ~/.codex/AGENTS.md
cd ~/.config/agent-config && git pull
```

## 公開方針

- source of truth はこの repo
- Codex 標準 skill は含めない
- 公開済みの汎用 skill は自 repo に再配布せず、`skills/` 配下の案内ファイルで upstream install を示す
- 保存責務は agent ではなく skill / script 側へ寄せる
- X の最新動向が判断に効くテーマでは `coding-confidant` と `trend-researcher` を並行利用する
