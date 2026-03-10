---
name: coding-confidant
description: ローカルリポジトリ、GitHub リポジトリ、既存の repomix 出力について、実装だけでは判断が足りず、最新の公開ドキュメントやエコシステム情報と突き合わせた調査・比較・レビューが必要なときに使う skill。ユーザーが調査手段を指定しなくても、エージェントが必要に応じて repomix 文脈を `curl` 経由の OpenAI Responses API と `web_search` に渡して解析する。
---


# Coding Confidant

## 概要

この skill は、リポジトリ文脈を `web_search` 付きの OpenAI Responses API リクエスト 1 回にまとめて渡すために使います。

prompt 編集をできるだけ単純に保ちたい場面を想定しています。再利用する基本指示は `references/default-prompt.md` に置き、依頼ごとの差分は `--task` または `--task-file` で足し、同梱のシェルスクリプトを実行します。

README.md のような補助説明は skill 配下には増やさず、利用メモは `_docs/coding-confidant-usage.md` を参照します。

## ユーザー依頼例

ユーザーはこの skill 名や内部実装を知らなくてよく、依頼達成のために agent 側が必要時にこの skill を選ぶ想定です。以下は発火確認に使いやすい依頼例です。

- 「このリポジトリの実装、今の公式ドキュメントや周辺エコシステムとズレていないか確認して」
- 「この GitHub リポジトリの設計と依存関係をレビューして。公開情報と比べて危ない点があれば知りたい」
- 「このコードベース、現行のベストプラクティスから外れていないか調べて」
- 「この `repomix-output.xml` をもとに、現行の公開情報と突き合わせてリスクを洗い出して」

最小の呼び出し確認なら、次の 1 文が最も短く意図が通りやすいです。

- 「このリポジトリの実装が、今の公式情報やエコシステムとズレていないか確認して」

## ワークフロー

1. 入力元を決めます。
  - **ローカルのリポジトリまたはディレクトリ**: `--repo /absolute/or/relative/path`
  - **GitHub リポジトリ**: `--repo https://github.com/org/repo` または `--repo org/repo`
  - **既存の repomix 出力**: `--repomix-file path/to/repomix-output.xml`
2. 既定 prompt で足りるか判断します。
  - 軽い調整なら `references/default-prompt.md` を編集
  - その場限りの派生ならコピーして `--prompt-file path/to/custom-prompt.md` を渡す
3. トークン削減が必要か判断します。
  - 大きいリポジトリでは `--compress` を優先
  - 巨大コードベース送信前は `--include` と `--ignore` による repomix フィルタを優先
4. ローカルの前提確認は並行で集めます。
  - ファイルツリー、`_docs`、関連 skill、Serena 情報、環境変数確認は可能な限り並行実行
  - Responses API 呼び出しそのものは 1 回だが、その前段の文脈収集はまとめて終わらせる
5. `scripts/run_research.sh` を実行します。
6. 結果を確認し、コマンド全体を書き換えるのではなく prompt file または task 文を調整して反復します。

## 実行ルール

- 主導線では必ず `scripts/run_research.sh` を使います。
- API 実行は `curl` のまま保ちます。利用者が明示しない限り Python に書き換えません。
- スクリプトは常に OpenAI `web_search` を有効にします。
- スクリプトは `service_tier: "priority"` を固定で送ります。低遅延固定のためで、`fast` という値は使いません。
- スクリプトは `store: true` と `include: ["web_search_call.action.sources"]` を固定で送ります。
- 依頼文が長い場合やバージョン管理したい場合は `--task-file` を優先します。
- API 実行前に prompt の差分を確認したい場合は `--save-payload` または `--print-payload` を優先します。
- 監査、デバッグ、後続の解析が必要な場合は `--output-json` で生 JSON を保存します。
- repomix に入れる文脈は「必要最小限」ではなく、「不要物を除外したうえでコンテクスト上限まで必要十分に入れる」を基本にします。
- `_docs`、ログ、生成物も、依頼達成に効くなら送信対象に含めます。
- スクリプトは `--input-token-budget` で概算 input token 上限を持ち、over budget のときはまず自動で `--compress` 相当に切り替えて再梱包します。
- ローカル repo を `--repo` で渡した場合、OpenAI への curl request/response は `<repo>/_docs/_skills/coding-confidant/<timestamp-pid>/openai.jsonl` に自動保存します。
- `openai.jsonl` には少なくとも request 行と response 行を入れ、`curl_command`、prompt を含む payload、結果の生 response を残します。
- repomix の文脈は OpenAI ログとは分けて、同じディレクトリ配下に別ファイルで保存します。
- 保存は prompt で指示するのではなく `scripts/run_research.sh` が自動で吸収します。
- 長時間リクエストでは、呼び出し元で待機時間を曖昧にせず、`--api-connect-timeout` と `--api-max-time` を必ず明示するか、同名の環境変数で固定します。
- 長時間リクエストは再実行で待つのではなく、継続セッション上で実行して進捗を監視します。
- 前処理の情報収集は並行実行を前提にし、重い外部リクエストの前に必要文脈を一気に揃えます。
- HTTP 2xx でも `status=failed|incomplete` は失敗扱いにします。

## Prompt 編集

基本 prompt は `references/default-prompt.md` にあります。

次の分離を保ちます。

- 安定した振る舞いは prompt file に置く
- 今回の依頼は `--task` または `--task-file` に置く
- 出力フォーマット要件は、新しい既定値にしたい場合を除き task 側に置く

口調、構成、評価軸を変えたい場合は、シェルスクリプトではなく先に prompt file を編集します。

## コマンド例

### 1. ローカルリポジトリ

```bash
bash scripts/run_research.sh \
  --repo /path/to/repo \
  --task "技術アドバイザーとしてこのリポジトリをレビューし、アーキテクチャ、外部依存、主要リスクに絞って整理してください。" \
  --api-connect-timeout 30 \
  --api-max-time 900 \
  --input-token-budget 120000 \
  --compress

# OpenAI の curl request/response は /path/to/repo/_docs/_skills/coding-confidant/<timestamp-pid>/openai.jsonl に自動保存
```

### 2. GitHub リポジトリ

```bash
bash scripts/run_research.sh \
  --repo https://github.com/example/project \
  --task-file my-task.md \
  --api-max-time 900 \
  --output-text answer.md \
  --output-json answer.json
```

### 3. 既存の repomix ファイル

```bash
bash scripts/run_research.sh \
  --repomix-file repomix-output.xml \
  --prompt-file references/default-prompt.md \
  --task "ライブ Web 検索を使い、このリポジトリを現行の公開ドキュメントとエコシステムに照らして比較してください。" \
  --api-max-time 900 \
  --save-payload payload.json
```

### 4. API を呼ばずに prompt を確認

```bash
bash scripts/run_research.sh \
  --repomix-file repomix-output.xml \
  --task-file my-task.md \
  --api-max-time 900 \
  --print-payload
```

## リソース

### `scripts/run_research.sh`

メインの入口です。このスクリプトは次を行います。

- リポジトリパス、GitHub リポジトリ、既存 repomix ファイルを受け取る
- 必要な場合に repomix を実行する
- prompt テンプレートと task 文を読み込む
- `web_search` 付き Responses API payload を組み立てる
- `service_tier: "priority"` を固定で payload に入れる
- `store: true` と `web_search` 出典 include を固定で payload に入れる
- `curl` で API を呼ぶ
- 明示的な connect timeout / max time で API を呼ぶ
- 概算 input token を計測し、over budget 時はまず自動 compress を試す
- 応答の `status`, `service_tier`, `usage`, `incomplete_details`, `error` を検査してログを出す
- OpenAI の curl request/response を repo 配下の `openai.jsonl` に自動保存する
- repomix の文脈は別ファイルで保存する
- payload、生 JSON、プレーンテキスト出力を追加の任意パスへも保存できる

### `references/default-prompt.md`

再利用する既定 prompt です。評価観点、口調、深さ、出力嗜好を変えたいときは最初にここを編集します。

### `references/prompt-variants.md`

よくある用途向けの短い prompt 派生です。既定の振る舞いを変えたいときはここから複製します。

### OpenAI 運用資料

- `references/official-openai-2026-03-06.md`
- `references/payload-examples.md`
- `references/response-inspection.md`

## 依存関係と確認事項

- 必須: `curl`, `python3`
- リポジトリ梱包に必須: `npx` または `repomix`
- API 呼び出しに必須: `OPENAI_API_KEY`

`repomix` の実行は `npx -y repomix@latest` を優先し、`npx` がない場合だけローカルの `repomix` を使います。

## 出力挙動

出力形式は意図的に固定しません。

既定挙動は次の通りです。

- Responses API に自由形式のリクエストを 1 回送る
- 構成は prompt と task に委ねる
- `output_text` があれば標準出力に出す

固定フォーマットが必要な場合は、スクリプトを変えるのではなく prompt file または task file にその構造を入れます。
