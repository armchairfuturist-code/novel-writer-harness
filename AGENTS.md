# StoryForge — AGENTS.md

## Entry point

`storyforge.py` is the CLI entrypoint. Pipeline phases live in `pipeline/`; interactive interview lives in `interview/`.

## Commands

| Command | Notes |
|---|---|
| `python storyforge.py "concept"` | Full pipeline: seed → export |
| `python storyforge.py --interactive` | Guided Q&A before pipeline |
| `python storyforge.py --interactive --depth comprehensive` | 73 questions, 6 dimensions |
| `python storyforge.py --resume ~/path` | Resume interrupted interview |
| `python storyforge.py "concept" --resume 7` | Resume drafting from ch 7 |
| `python storyforge.py --quick "concept"` | Skip review, backprop, adversarial |
| `python storyforge.py --benchmark` | Benchmark model variants |
| `python storyforge.py --help` | All flags |

Auto-resumes: running same concept again detects `checkpoint.json` and skips completed phases.

## Testing

```
python -m pytest tests/ -v
```

Single file: `python -m pytest tests/test_v03.py -v`. No coverage or tox config exists.

`test_e2e.py` runs subprocess pytest on 4 test files as a smoke test. Quick interview tests mock stdin. All tests must pass without live API (`CrofaiClient` is never called in CI-unit-style tests).

## API and environment

- Requires `CROFAI_API_KEY` env var (checked at Config init, raises ValueError if missing).
- API base: `https://beta.crof.ai/v1` (OpenAI-compatible).
- Singleton `Config` in `config.py` — all routing, scoring thresholds, model aliases live there.
- `CrofaiClient` (httpx, 600s timeout) in `pipeline/api.py`. Retries only 429/5xx, up to 3 attempts.
- API response caching: opt-in via `CrofaiClient(use_cache=True)`, dir `.api-cache/`.
- No conventional Python linter/formatter/typechecker config found.

## Architecture

- Phase-to-model routing in `Config.phase_models` (config.py:104). Different phases use different crofai models (DeepSeek V4 Pro for planning, Kimi K2.6 Precision for drafting, Qwen for scoring).
- `HindsightStore` (`pipeline/hindsight_client.py`) — structured memory server at `localhost:8888`. Disabled with `--no-gbrain`. Tests mock the HTTP calls; no live Hindsight needed.
- `ReIOCompressor` (`pipeline/reio_compression.py`) — context compression for long novels. Disabled with `--no-reio`.
- Genre templates: JSON files in `templates/` (5 genres: mystery, thriller, romance, fantasy, sci-fi). Applied via `--genre` flag.
- `pipeline/api.py:parse_json_output()` handles LLM JSON output with multiple repair strategies (unwrap fences, escape newlines, fix parenthetical annotations, brace-counting extraction). All LLM responses go through this.

## Project output

Landing dir: `~/storyforge-projects/{slug}/`. Override with `--project-dir`. Contains `checkpoint.json` for resume, `chapters/` per chapter md, plus all phase artifacts (world.json, characters.json, outline.json, etc.).

## Key conventions

- `sys.path.insert(0, ...)` at the top of every test file and `storyforge.py` itself — the package is not installed, it runs from source root.
- All LLM calls go through `CrofaiClient.chat()` or `chat_with_retry()`. Phase modules never call httpx directly.
- `test_e2e.py` imports and patches `sys.stdin` — it's the broadest coverage check.
- README describes v0.3 features but is the source of truth for the feature set.
