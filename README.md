# 2001Y's agent-config

公開用の Codex / Agents 設定 repo です。

この repo は `~/.codex` をそのまま公開せず、共有してよい `AGENTS.md` と custom skills だけを切り出す前提で構成しています。認証、履歴、セッション、キャッシュ、ログ、承認済み権限のような machine-specific な情報は含めません。

## 含めるもの

- `AGENTS.md`
- `skills/coding-confidant`
- `skills/trend-researcher`
- `skills/agent-browser`
- `skills/find-skills`
- `skills/insights`

## インストール

### skill 一覧を見る

```bash
npx skills add 2001Y/agent-config --list
```

### 個別に入れる

```bash
npx skills add 2001Y/agent-config --skill coding-confidant
npx skills add 2001Y/agent-config --skill trend-researcher
npx skills add 2001Y/agent-config --skill agent-browser
npx skills add 2001Y/agent-config --skill find-skills
npx skills add 2001Y/agent-config --skill insights
```

### 全部入れる

```bash
npx skills add 2001Y/agent-config --skill '*'
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
- 保存責務は agent ではなく skill / script 側へ寄せる
- X の最新動向が判断に効くテーマでは `coding-confidant` と `trend-researcher` を並行利用する
