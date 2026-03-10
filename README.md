# agent-config

公開用の Codex / Agents 設定 repo です。

この repo は `~/.codex` をそのまま公開せず、共有してよいものだけを切り出す前提で構成しています。ローカル状態、認証、セッション、履歴、キャッシュ、承認済み権限のような machine-specific な情報は含めません。

## 含めるもの

- `AGENTS.md`
- `skills/`
  - `coding-confidant`
  - `trend-researcher`
  - `agent-browser`
  - `find-skills`
  - `insights`
  - `screenshot`
- `install.sh`

## 含めないもの

- 認証情報: `auth.json` など
- セッション / 履歴: `sessions/`, `history.jsonl`, `session_index.jsonl`
- ローカル DB / キャッシュ / ログ: `state_*.sqlite`, `cache/`, `log/`, `shell_snapshots/`
- machine-specific な承認ルール: `rules/default.rules`
- 一時生成物: `_docs/_skills/*`, `_log_inlineMark`, `__pycache__`, `.DS_Store`

## 使い方

### 1. repo を clone

```bash
git clone <YOUR_GITHUB_REPO>
cd agent-config
```

### 2. ローカルへ反映

```bash
./install.sh
```

既定では `AGENTS.md` と `skills/` を `CODEX_HOME` もしくは `~/.codex` に同期します。
既存ファイルは上書き前に `*.bak.<timestamp>` として退避します。

### 3. 個別に skill を入れる

GitHub 公開後は、skill ごとに公式導線で追加できます。

```bash
npx skills add <YOUR_GITHUB_REPO> --skill trend-researcher
npx skills add <YOUR_GITHUB_REPO> --skill coding-confidant
```

## install.sh のオプション

```bash
./install.sh                 # AGENTS.md + skills を同期
./install.sh --agents-only   # AGENTS.md のみ同期
./install.sh --skills-only   # skills のみ同期
./install.sh --dry-run       # 実際には書き込まず確認
```

## 更新フロー

```bash
git pull
./install.sh
```

## 公開方針

- source of truth はこの repo
- ローカルでしか意味がない情報は repo に入れない
- 保存物は skill / script 側で吸収し、agent に保存責務を押し付けない
- X 調査が効くテーマでは `coding-confidant` と `trend-researcher` を並行利用する
