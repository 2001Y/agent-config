# 2001Y's agent-config

公開用の Codex / Agents 設定 repo です。

この repo は `~/.codex` をそのまま公開せず、共有してよい `AGENTS.md`、`config.toml`、custom skills だけを切り出す前提で構成しています。認証、履歴、セッション、キャッシュ、ログ、承認済み権限のような machine-specific な情報は含めません。

## 含めるもの

- `AGENTS.md`
- `config.toml`
- `skills/coding-confidant`
- `skills/trend-researcher`
- `skills/insights`

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

### upstream の汎用 skill は直接入れる

```bash
npx skills add vercel-labs/agent-browser
npx skills add vercel-labs/skills --skill find-skills
```

## `AGENTS.md` と `config.toml`

更新しやすいように repo を clone して使うのを推奨します。

```bash
git clone https://github.com/2001Y/agent-config.git ~/.config/agent-config
ln -sf ~/.config/agent-config/AGENTS.md ~/.codex/AGENTS.md
ln -sf ~/.config/agent-config/config.toml ~/.codex/config.toml
cd ~/.config/agent-config && git pull
```

## 環境変数

API キーは `config.toml` に書かず、`~/.zshrc` から渡します。

```bash
export OPENAI_API_KEY="..."
export GEMINI_API_KEY="..."
```

`config.toml` の optional MCP examples は、この環境変数を Codex に引き継ぐ前提です。

## 公開方針

- source of truth はこの repo
- 公開対象は自作の設定と custom skills のみ
- upstream の汎用 skill は再配布せず、README で直接 install を案内する
- 保存責務は agent ではなく skill / script 側へ寄せる
- X の最新動向が判断に効くテーマでは `coding-confidant` と `trend-researcher` を並行利用する
