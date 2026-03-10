# Official OpenAI Facts Verified On 2026-03-06

## Sources

- [Models overview](https://platform.openai.com/docs/models)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses/create)
- [Priority Processing guide](https://platform.openai.com/docs/guides/priority-processing)
- [Web search guide](https://platform.openai.com/docs/guides/tools-web-search)

## Verified facts

- The official models page checked on 2026-03-06 lists `gpt-5.2` with the Responses API.
- A public official `gpt-5.4` listing was not found on 2026-03-06.
- The Responses API documents `service_tier`.
- The documented `service_tier` values are `auto`, `default`, `flex`, and `priority`.
- Priority Processing is request-scoped.
- The Priority Processing guide says some priority requests may be downgraded to the default tier if the ramp rate limit is exceeded.
- The web search guide documents the `web_search` tool for the Responses API.
- The web search guide also documents `include: ["web_search_call.action.sources"]` when the full source list is needed.

## Working rules derived from those facts

- Do not hard-code model names into wrappers or helper scripts.
- Keep the payload raw so new request fields can be added without editing local code.
- Inspect `response.service_tier` after every priority request.
- Prefer explicit source inclusion when the answer needs traceability.
