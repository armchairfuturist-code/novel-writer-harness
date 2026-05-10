# Benchmark Report: "The Fire and the Mirror"

**Generated**: May 9, 2026
**Pipeline**: StoryForge (customized)
**Novel**: 25 chapters, 47,482 words
**Format**: Literary sci-fi, close-third person POV

---

## Pipeline Phases

| Phase | Method | Status | Time/Notes |
|---|---|---|---|
| Seed | crof.ai API (kimi-k2.6) | ✅ Success | 27s |
| Worldbuilding | crof.ai API (kimi-k2.6) | ✅ Success | 76s |
| Characters | crof.ai API (kimi-k2.6) | ✅ Success | 227s — 7 characters |
| Outline | Manual (from reference) | ✅ Constructed | No API call needed |
| Chapter 1 | Reference material | ✅ Preserved | 3,372 words (existing) |
| Chapters 2-25 | Team agents (kimi-k2.6-precision) | ✅ Written | See below |

## Writer Performance

| Writer | Chapters | Words | Avg/Ch | Time |
|---|---|---|---|---|
| Writer A | Ch 2-8 (Act I) | 14,006 | 2,001 | ~1-2 rounds |
| Writer B | Ch 9-16 (Act II) | 13,094 | 1,637 | ~1-2 rounds |
| Writer C | Ch 17-25 (Act III) | 17,110 | 1,901 | ~2 rounds |

## Quality Assessment

**Prose quality**: High. All three writers produced literary close-third person prose with:
- Specific sensory detail (smell, light, texture)
- Varied sentence length (short for tension, long for reflection)
- Deep POV (staying inside the character's head)
- Earned emotional beats
- Consistent voice with Chapter 1

**Consistency**: Excellent across all three writers. Character names (Carmen, Daniel, Marta, João, Sofia, Tomas), timeline (2026 → 2036), and thematic throughlines (doors vs walls, the Mirror, the third path) are coherent and well-maintained.

**Character depth**: Marta's arc is the strongest — her spreadsheets in Ch 2, her childhood trauma revealed in Ch 16, her hand holding Carmen's in Ch 24. Daniel is consistent as the futurist/optimist. Carmen's growth from child to adult is clear and earned.

## Key Findings

### What Worked
1. **Manual outline construction** — Avoided the deepseek API hang, produced a richer, more detailed outline aligned with the existing reference material
2. **Parallel chapter drafting via team agents** — Three writers working simultaneously wrote the equivalent of a 47K-word novella in ~2 rounds each
3. **Reference-based chapter 1** — Giving writers the existing chapter established style/tone that carried through all 25 chapters
4. **Rich outline spec** — Providing per-chapter summaries, key events, emotional arcs, and foreshadowing notes gave each writer enough context to write independently

### What Needs Improvement
1. **Chapter length** — Target was ~4,000 words/chapter (100K total). Actual average was 1,818 words/chapter (47K total). Writers need explicit length guidance and possibly a "expand this chapter" follow-up task
2. **Act II is thinner** — Chapters 11-15 average 1,372 words. The faction exploration and Mirror encounters need more depth. Each faction could support 2 chapters instead of 1
3. **No dedicated Reviewer pass** — The deepseek-v4-pro-precision model hangs on large inputs, making a full Review pass impossible. Alternative: per-chapter spot reviews using shorter prompts
4. **Pipeline automation limited** — The crof.ai API struggles with large prompts. Any output >2,000 chars risks hanging. Consider chunked generation or model selection that reliably handles longer context
5. **File handling** — Writers saved to different directories (reference/chapters/ vs project chapters/). Need a standardized save path convention

## Technical Metrics

- **API calls avoided**: 1 (outline phase — would have required deepseek-v4-pro-precision, which hangs)
- **Total team messages**: 3 (one per writer) + cleanup
- **Total tasks**: 14 (3 active, 11 stale cleaned)
- **Manuscript file**: manuscript.md (271 KB, 47,482 words)
- **Project size**: ~8 MB (including all checkpoints, spec, world, characters, outline, 25 chapters)

## Recommendations

1. **For longer output**: Give writers a specific word target ("write until you reach 3,500 words") rather than "target ~4,000"
2. **For the reviewer**: Use per-chapter review tasks (smaller, independent prompts that won't hit API timeouts)
3. **For Act II expansion**: Add a dedicated "Mirror Technology" chapter between Ch 12 and Ch 13 exploring the tech itself
4. **For future runs**: Pre-emptively create the chapters/ directory and specify absolute save paths
5. **For crof.ai API**: Avoid deepseek models for prompts >2,000 chars. Kimi K2.6 and its variants handle longer context reliably
