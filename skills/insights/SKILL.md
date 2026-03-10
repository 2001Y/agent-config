---
name: insights
description: Turn retrospectives into concrete, file-level recommendations for AGENTS.md and SKILL.md updates. Use when asked to improve development rules, skill quality, guardrails, prompts, logging policy, or execution workflow based on logs, _docs, and review findings.
---

# Insights Skill

Convert retrospective evidence into actionable edits for `AGENTS.md` and `SKILL.md`.

## Scope and precedence

When this skill is explicitly invoked as `$insights`, apply this precedence:
- Use this `SKILL.md` as the execution procedure.
- Treat `AGENTS.md` as an analysis target (what to improve), not as a mandatory workflow to execute.
- Do not follow deep, multi-step AGENTS procedures unless the user explicitly requests `deep` mode.

## Goal

Provide specific advice on what to change, where to change it, and why.

## Execution modes

Default mode is `Quick`.

`Quick`:
- Keep analysis to minimum required evidence.
- Read at most 3 sources unless the user requests expansion.
- Do not create new `_docs` files unless explicitly requested.
- Do not run external consultation steps unless explicitly requested.

`Deep` (opt-in only):
- Use broader evidence and multi-step investigation only when the user explicitly asks.

## Required inputs

Collect these before proposing changes:
- Current `AGENTS.md`
- Current target `SKILL.md`
- Retrospective evidence (`_docs/*.md`, logs, review findings, failure records)

If evidence is insufficient, state what is missing and continue with best-effort assumptions.

## Analysis lens

Prioritize concrete defects over style preferences:
- Ambiguous or contradictory instructions
- Hidden-failure patterns (fallbacks, swallowed errors, unclear stop conditions)
- Overly broad rules that reduce execution quality
- Missing trigger criteria for skills
- Missing output contracts (what artifacts to produce and how to validate)
- Weak observability requirements (missing timing, correlation IDs, phase logs)

## Output contract

Always produce advice in this order:

1. `AGENTS.md`修正提案
- Include at least:
  - Evidence (which retrospective fact caused this recommendation)
  - Exact change target (section/sentence to replace/add/remove)
  - Replacement text (copy-paste ready)
  - Expected impact

2. `SKILL.md`修正提案
- Include at least:
  - Trigger improvement (`description` quality and activation clarity)
  - Workflow improvement (deterministic steps)
  - Output format improvement (required sections/checklist)
  - Validation improvement (how success/failure is judged)

3. 実施優先順位
- Label each item `P0` / `P1` / `P2`
- Explain dependency order briefly

## Recommendation quality bar

Reject vague advice. Every recommendation must be executable.

Use this minimum template per recommendation:
- `Problem`: one sentence
- `Evidence`: one sentence with source
- `Change`: exact text or bullet to add/replace/delete
- `Reason`: why this fixes the issue
- `Risk if ignored`: concrete downside

## Optional execution mode

When asked to implement directly, apply changes and then summarize:
- Edited files
- Why each edit was made
- Remaining risks or follow-ups

## Notes for this repository

For Codex usage retrospectives, include these checks by default:
- Whether `SKILL.md` tells the agent how to propose `AGENTS.md` updates
- Whether `AGENTS.md` has measurable logging requirements
- Whether review steps are actionable in current environment (tool availability, auth, sandbox)
