---
name: rag-answer
description: Retrieve and synthesize traceable evidence from project files, databases, and current authoritative web sources before answering. Use for document Q&A, policy or product research, fact checking, source-backed explanations, and questions where freshness or provenance matters.
---

# Retrieval-Augmented Answer

Answer from retrieved evidence, not model memory alone.

## Source Routing

1. Search project files first for project-specific questions using Glob, Grep, and Read.
2. Use the database MCP for structured business facts and actual metrics.
3. Use WebSearch and WebFetch for current or external facts, preferring official and primary sources.
4. If a required source or tool is unavailable, identify the gap and narrow the answer accordingly.

## Workflow

1. Break the question into claims that require evidence.
2. Retrieve only relevant passages or records and note their source, date, and scope.
3. Compare sources when claims conflict or depend on recent changes.
4. Distinguish directly supported facts from inference.
5. Cite the file, database query scope, or URL close to the supported claim.

## Quality Rules

- Do not imply that a web search ran unless a tool result confirms it.
- Do not fabricate links, quotations, document contents, or database values.
- Prefer concise paraphrase over long quotations.
- Call out stale documents, ambiguous terminology, missing coverage, and conflicting evidence.
- When the Qwen Anthropic-compatible gateway cannot complete WebSearch/WebFetch, state that external verification was not completed.
