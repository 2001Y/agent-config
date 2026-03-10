---
name: trend-researcher
description: Agent-driven research skill for current technology, framework, tool, and ecosystem trends on X using xurl collection plus GPT synthesis. Use when live developer chatter, release reactions, adoption signals, or community narratives on X matter more than static documentation alone. Appropriate for requests like "What are people on X saying about React Compiler?", "What frameworks are trending right now?", or "How is the community reacting to tool X?".
---

# Trend Researcher

## Overview

Use this skill when X itself is part of the evidence.

This skill is intentionally high freedom on search strategy. The fixed part is not the queries. The fixed part is:

- raw X evidence must be saved
- GPT synthesis must be separated from observation
- scripts must absorb collection and report artifacts automatically
- the final report must make uncertainty and counter-signals visible

## Quick Start

```bash
bash -lc 'source trend-researcher/scripts/activate-session.sh /path/to/repo && xurl "/2/tweets/search/recent?query=react%20compiler&max_results=10"'

bash trend-researcher/scripts/generate-report.sh \
  --artifacts-dir /path/to/repo/_docs/_skills/trend-researcher/<timestamp-pid> \
  --task "React Compiler に関する X 上の現在の技術トレンドを整理してください。"
```

## Core Loop

1. Define the research scope.
- Clarify the topic, time window, language, communities, named accounts, and what counts as a useful signal.
- Decide whether the goal is discovery, sentiment, competitive positioning, release reaction, or implementation relevance.

2. Start a logged shell session.
- Use `bash` and source `scripts/activate-session.sh <repo-path>`.
- After activation, `xurl` in that shell is the logging wrapper, not the bare binary.

3. Explore on X with `xurl`.
- Use `xurl` freely through `codex exec`.
- Prefer raw X API endpoint access over local shorthand when possible.
- Iterate on queries aggressively. The search plan does not need to be fixed up front.
- Parallelize query branches when it helps coverage.

4. Let the wrapper save raw evidence.
- Every query is recorded automatically.
- Every raw result is saved automatically.
- Do not rely on memory, terminal scrollback, or only the final report.

5. Distill observations.
- Note recurring claims, representative posts, notable accounts, linked URLs, release mentions, disagreement patterns, and obvious gaps.
- Keep this layer observational. Do not merge it with conclusions yet.
- Use `notes.md` only for observations you want to preserve between search passes.

6. Generate the final report with the script.
- Run `scripts/generate-report.sh --artifacts-dir <dir> --task '...'`.
- GPT should interpret saved evidence, not replace collection.
- If the evidence is weak, repetitive, or overfit to a narrow cluster, say so explicitly.

7. Review the generated report.
- Separate "Observed on X" from "Interpretation".
- Include competing narratives, not only the dominant one.
- State confidence and known blind spots.

## Execution Rules

- Prefer raw endpoint-style calls such as `xurl '/2/tweets/search/recent?...'` when possible.
- Never read, print, summarize, or upload `~/.xurl`.
- Free search is allowed. Unlogged search is not.
- Save artifacts under `<repo>/_docs/_skills/trend-researcher/<timestamp-pid>/`.
- If the task is broad, branch the collection work in parallel. Keep each branch's query log and raw results intact before merging.
- If you use a sub-agent, use it after raw artifacts are already being written. Do not let an unlogged sub-agent become the only source of X evidence.
- Do not overstate a trend from a handful of posts, a single account cluster, or one announcement wave.
- Add counter-queries when the first query family is too narrow or one-sided.
- If X evidence conflicts with official documentation, report both rather than forcing a single narrative.
- Do not manually craft `x-search.json` or `report.md`. Let `scripts/xurl` and `scripts/generate-report.sh` absorb them.

## Required Artifacts

Always create these files:

- `queries.jsonl`
- `x-search.json`
- `x-search.jsonl`
- `notes.md`
- `report.md`

Create this file when GPT synthesis is used:

- `openai.jsonl`

Use [references/output-contract.md](references/output-contract.md) for the artifact contract.
Use [references/x-search-notes.md](references/x-search-notes.md) for practical X collection hints.
Use [references/default-prompt.md](references/default-prompt.md) for the GPT synthesis baseline.

## Minimum Output Contract

The final `report.md` should contain these sections:

- `Scope`
- `Observed on X`
- `Competing Narratives`
- `Notable Accounts / Representative Posts`
- `Interpretation`
- `Confidence / Gaps`

The value of this skill is not "what X said" alone. The value is a replayable path from X evidence to a reasoned conclusion.
