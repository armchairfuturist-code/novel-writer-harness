# StoryForge Knowledge Base

Lazy-loaded reference files for debate court agents and the drafting system.
Each file is loaded on demand — never bloating the context window with irrelevant theory.

## File Format

Every `.md` file starts with YAML-style frontmatter:

```yaml
---
topic: short topic label
agent_roles: [lore_prosecutor, plot_sentinel]
keywords: [keyword1, keyword2, keyword3, ...]
---
```

## How Agents Load References

1. The `KnowledgeBase` class scans all `.md` files in the appropriate subdirectory
2. When an agent needs references, it calls `get_references(agent_role, keywords, max_tokens)`
3. Files are scored by keyword overlap with the current chapter/draft context
4. Top-matching files are loaded, concatenated, and injected into the agent's system prompt as a `## RELEVANT WRITING THEORY` block
5. The `max_tokens` cap prevents reference bloat

## Agent Role Directories

| Directory | Target Agent | Content |
|---|---|---|
| `lore-prosecutor/` | Lore Prosecutor | Continuity, trait tracking, worldbuilding consistency |
| `plot-sentinel/` | Plot Sentinel | Foreshadowing, pacing, outline beat compliance |
| `magistrate/` | Mechanical Magistrate | Revision instruction quality, conflict resolution |
| `drafting/` | Draft writer + revision loop | Hook techniques, dialogue craft, sensory immersion |

## Contributing

Add new `.md` files to the appropriate directory. Keep files focused (50-200 lines),
concrete (examples > theory), and well-tagged (frontmatter keywords drive relevance matching).
