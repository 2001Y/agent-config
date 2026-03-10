# Payload Examples

Replace model names with the exact model verified from official docs at run time.

## Plain consultation

```json
{
  "model": "gpt-5.2",
  "store": false,
  "input": "Review this rollout plan and identify the weakest assumptions."
}
```

## Web search consultation

```json
{
  "model": "gpt-5.2",
  "store": false,
  "input": "Find the latest official guidance for OpenAI Priority Processing and summarize the operational caveats.",
  "tools": [
    {
      "type": "web_search"
    }
  ],
  "include": [
    "web_search_call.action.sources"
  ]
}
```

## Priority consultation

```json
{
  "model": "gpt-5.2",
  "store": false,
  "service_tier": "priority",
  "input": "Give a concise design review of this API migration plan and call out the highest-risk assumption first."
}
```

## Combined web search and priority consultation

```json
{
  "model": "gpt-5.2",
  "store": false,
  "service_tier": "priority",
  "input": "Search for the latest official docs on the Responses API and identify any request fields that could affect rollout safety.",
  "tools": [
    {
      "type": "web_search"
    }
  ],
  "include": [
    "web_search_call.action.sources"
  ]
}
```
