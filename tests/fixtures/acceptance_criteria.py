"""Acceptance criteria for the StoryForge inventory.

Each user-facing feature has a structured acceptance criterion that can be
machine-checked. This file is the single source of truth for "what done means."
"""

# ──────────────────────────────────────────────────────────────
# CLI flags and command-line behavior
# ──────────────────────────────────────────────────────────────

CRITERIA = {
    # CLI surface (storyforge.py)
    "cli.help": {
        "feature": "StoryForge CLI — --help",
        "acceptance": "Running `python storyforge.py --help` exits 0 and prints parser help with all flags",
        "risk_categories": ["UX", "documentation"],
    },
    "cli.no_args": {
        "feature": "StoryForge CLI — no args",
        "acceptance": "Running with no args prints help + usage error and exits non-zero",
        "risk_categories": ["UX", "error handling"],
    },
    "cli.invalid_genre": {
        "feature": "StoryForge CLI — --genre <invalid>",
        "acceptance": "Invalid genre value is rejected by argparse with a clear error and non-zero exit",
        "risk_categories": ["UX", "error handling"],
    },
    "cli.invalid_store": {
        "feature": "StoryForge CLI — --store <invalid>",
        "acceptance": "Invalid store value rejected; 'json' (default), 'gbrain', 'auto' accepted",
        "risk_categories": ["UX", "error handling"],
    },
    "cli.invalid_depth": {
        "feature": "StoryForge CLI — --depth <invalid>",
        "acceptance": "Invalid depth rejected; 'quick' (3q), 'standard' (~24q), 'comprehensive' (72q) accepted",
        "risk_categories": ["UX", "error handling"],
    },
    "cli.missing_api_key": {
        "feature": "StoryForge CLI — no API key set",
        "acceptance": "Fails fast with a clear ValueError mentioning LLM_API_KEY and CROFAI_API_KEY env vars",
        "risk_categories": ["error handling", "security"],
    },
    "cli.resume_missing_dir": {
        "feature": "StoryForge CLI — --resume <nonexistent>",
        "acceptance": "Fails with a clear error, logs to errors.log, exits non-zero",
        "risk_categories": ["error handling", "data integrity"],
    },
    "cli.resume_no_checkpoint": {
        "feature": "StoryForge CLI — --resume <dir with no checkpoint>",
        "acceptance": "Fails with a clear error mentioning 'no checkpoint found' and exits non-zero",
        "risk_categories": ["error handling", "data integrity"],
    },
    "cli.resume_corrupt_checkpoint": {
        "feature": "StoryForge CLI — --resume <dir with corrupt checkpoint>",
        "acceptance": "Validation runs; on FAIL, attempts recovery; on backup missing, exits non-zero with clear error",
        "risk_categories": ["error handling", "data integrity"],
    },
    "cli.benchmark": {
        "feature": "StoryForge CLI — --benchmark",
        "acceptance": "Routes to run_benchmark from tests/benchmark_writing.py; error path exits non-zero",
        "risk_categories": ["error handling"],
    },
    "cli.feedback_flag_logic": {
        "feature": "StoryForge CLI — --feedback / --no-feedback",
        "acceptance": "When neither flag is set, feedback depends on path (default on for interactive/resume). When --feedback or --no-feedback is explicit, that wins.",
        "risk_categories": ["UX", "configuration"],
    },
    "cli.slugify_edge": {
        "feature": "StoryForge CLI — slugify special characters",
        "acceptance": "Slugifies non-ASCII, unicode, punctuation safely; never produces empty project dir; never produces path-traversal names",
        "risk_categories": ["security", "data integrity"],
    },

    # Pipeline phases
    "phase.seed.cached_resume": {
        "feature": "Pipeline Phase 1 — Seed (cached resume)",
        "acceptance": "When spec.json exists in project_dir, phase 1 is skipped and loaded from disk",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "phase.worldbuilding.cached_resume": {
        "feature": "Pipeline Phase 2 — Worldbuilding (cached resume)",
        "acceptance": "When world.json exists, phase 2 is skipped and loaded from disk",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "phase.characters.cached_resume": {
        "feature": "Pipeline Phase 3 — Characters (cached resume)",
        "acceptance": "When characters.json exists, phase 3 is skipped and loaded from disk",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "phase.outline.cached_resume": {
        "feature": "Pipeline Phase 4 — Outline (cached resume)",
        "acceptance": "When outline.json exists, phase 4 is skipped and loaded from disk",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "phase.outline_validation.fail_blocks": {
        "feature": "Pipeline Phase 4.5 — Outline Validation (FAIL blocks)",
        "acceptance": "When validator returns overall=FAIL, drafting is blocked and pipeline returns early",
        "risk_categories": ["data integrity", "error handling"],
    },
    "phase.outline_validation.warn_continues": {
        "feature": "Pipeline Phase 4.5 — Outline Validation (WARN continues)",
        "acceptance": "When validator returns overall=WARN, drafting proceeds with warnings",
        "risk_categories": ["error handling"],
    },
    "phase.draft.empty_outline": {
        "feature": "Pipeline Phase 5 — Draft with empty outline",
        "acceptance": "Edge case: outline has 0 chapters; pipeline should handle gracefully and not crash",
        "risk_categories": ["error handling", "edge case"],
    },
    "phase.draft.parallel_variants_off": {
        "feature": "Pipeline Phase 5 — Draft with --single-variant",
        "acceptance": "With parallel_variants=False, each chapter is drafted once (no variant comparison)",
        "risk_categories": ["configuration"],
    },
    "phase.export.empty_chapters": {
        "feature": "Pipeline Phase 7 — Export with no chapters",
        "acceptance": "If no chapters exist, export is skipped with a clear WARNING, not a crash",
        "risk_categories": ["error handling", "edge case"],
    },
    "phase.checkpoint_corrupt": {
        "feature": "Pipeline — corrupt checkpoint.json",
        "acceptance": "Corrupt JSON in checkpoint.json is treated as no checkpoint; pipeline proceeds from phase 1",
        "risk_categories": ["data integrity", "error handling"],
    },
    "phase.quick_skips_review": {
        "feature": "Pipeline — --quick mode",
        "acceptance": "--quick skips fact-check, backprop, adversarial edit, and review phases",
        "risk_categories": ["configuration"],
    },
    "phase.genre_template_applied": {
        "feature": "Pipeline — --genre fantasy",
        "acceptance": "When --genre fantasy is set, fantasy template beats are tagged onto chapters in outline.json",
        "risk_categories": ["configuration", "data integrity"],
    },
    "phase.precompiled_spec_skips_seed": {
        "feature": "Pipeline — precompiled_spec (from --interactive)",
        "acceptance": "When precompiled_spec is provided, seed phase is skipped and spec.json is written from the bible",
        "risk_categories": ["configuration", "data integrity"],
    },

    # Interview system
    "interview.empty_answer_handling": {
        "feature": "Interview — empty answer (just whitespace)",
        "acceptance": "Whitespace-only answers are detected as thin; user is not silently moved on without feedback",
        "risk_categories": ["UX", "data integrity"],
    },
    "interview.skip_command": {
        "feature": "Interview — 'skip' command",
        "acceptance": "Typing 'skip' marks answer as [SKIPPED] and moves to next question",
        "risk_categories": ["UX"],
    },
    "interview.quit_command": {
        "feature": "Interview — 'q'/'quit'/'exit' command",
        "acceptance": "Typing 'q' exits the interview gracefully with a completion summary",
        "risk_categories": ["UX", "error handling"],
    },
    "interview.go_with_your_idea": {
        "feature": "Interview — 'go with your idea' follow-up command",
        "acceptance": "On a follow-up, 'go with your idea' marks the follow-up as [SKIPPED] and returns to main flow",
        "risk_categories": ["UX"],
    },
    "interview.checkpoint_saved_periodically": {
        "feature": "Interview — checkpoint every 5 questions",
        "acceptance": "After every 5 questions, checkpoint.json is written to project_dir with current answers",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "interview.resume_skips_interrupted": {
        "feature": "Interview — resume skips [INTERRUPTED] answers",
        "acceptance": "On resume, questions answered [INTERRUPTED] are re-presented; real answers are kept",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "interview.checkpoint_validation_required_keys": {
        "feature": "Interview — checkpoint validation required keys",
        "acceptance": "Each answer must have question_id, dimension, question, answer, is_thin, timestamp; otherwise checkpoint is rejected",
        "risk_categories": ["data integrity"],
    },
    "interview.context_monitor_warning": {
        "feature": "Interview — context monitor warning at 70%",
        "acceptance": "When accumulated tokens cross 70% of 128K, a one-shot warning is displayed",
        "risk_categories": ["UX"],
    },
    "interview.depth_quick_question_count": {
        "feature": "Interview — --depth quick",
        "acceptance": "Quick depth asks 3 questions (1 per dimension-block, 1 wrap-up), not 24 or 72",
        "risk_categories": ["configuration"],
    },
    "interview.depth_comprehensive_question_count": {
        "feature": "Interview — --depth comprehensive",
        "acceptance": "Comprehensive depth asks all 72 questions (or as many as are not filtered by genre)",
        "risk_categories": ["configuration"],
    },
    "interview.genre_filters_questions": {
        "feature": "Interview — --genre filters questions",
        "acceptance": "When --genre fantasy is set, only fantasy-relevant questions from each dimension are asked",
        "risk_categories": ["configuration"],
    },
    "interview.story_bible_compiles": {
        "feature": "Interview — story bible compilation",
        "acceptance": "All non-skipped, non-interrupted answers are compiled into a spec + enrichments dict",
        "risk_categories": ["data integrity"],
    },
    "interview.drilling_graceful_failure": {
        "feature": "Interview — drilling graceful failure",
        "acceptance": "If the LLM fails to generate follow-ups, the engine proceeds without drilling (no crash)",
        "risk_categories": ["error handling"],
    },

    # Memory store
    "store.json_persistence": {
        "feature": "Memory store — JSON persistence",
        "acceptance": "Answers stored in JSONMemoryStore survive across runs (file written, reload reads same data)",
        "risk_categories": ["data integrity"],
    },
    "store.factory_routing": {
        "feature": "Memory store — factory routing",
        "acceptance": "create_memory_store('json') returns JSONMemoryStore; 'gbrain' and 'auto' attempt GBrain then fall back to JSON",
        "risk_categories": ["error handling"],
    },
    "store.recall_word_overlap": {
        "feature": "Memory store — recall word overlap",
        "acceptance": "Recall returns top-K by word overlap score; score is 0-1 range",
        "risk_categories": ["data integrity"],
    },

    # Config
    "config.singleton": {
        "feature": "Config — singleton behavior",
        "acceptance": "Config() called multiple times returns the same instance",
        "risk_categories": ["configuration"],
    },
    "config.model_routing": {
        "feature": "Config — phase-to-model routing",
        "acceptance": "model_for_phase('seed') returns deepseek, 'draft' returns kimi-precision, 'scoring' returns flash",
        "risk_categories": ["configuration"],
    },
    "config.env_overrides": {
        "feature": "Config — env var overrides",
        "acceptance": "Setting LLM_MODEL_DRAFT changes draft-phase model; setting LLM_DEFAULT_MODEL changes default",
        "risk_categories": ["configuration"],
    },
    "config.api_key_fallback": {
        "feature": "Config — API key fallback chain",
        "acceptance": "Reads LLM_API_KEY first, then CROFAI_API_KEY; raises ValueError if neither is set",
        "risk_categories": ["security", "configuration"],
    },
    "config.model_advisor": {
        "feature": "Config — model advisor (print_routing_plan)",
        "acceptance": "Config().print_routing_plan() prints the routing plan: which model handles which role, the rationale, the env-var override, and the available aliases. Output includes phase roles, interview dimensions, and debate court roles.",
        "risk_categories": ["configuration", "UX", "model agnosticism"],
    },
    "config.model_env_override": {
        "feature": "Config — per-role env override (LLM_MODEL_{ROLE})",
        "acceptance": "Setting LLM_MODEL_DRAFT=flash routes the draft phase to the 'flash' alias. Unknown aliases fall back to the default routing for that role.",
        "risk_categories": ["configuration", "model agnosticism"],
    },
    "cli.show_models": {
        "feature": "StoryForge CLI — --show-models",
        "acceptance": "Running `python storyforge.py --show-models` prints the model routing plan and exits 0. Does not require an API key.",
        "risk_categories": ["UX", "configuration"],
    },
    "config.embeddings_opt_in": {
        "feature": "Config — embeddings opt-in (EmbeddingConfig)",
        "acceptance": "Embeddings are disabled by default. LLM_ENABLE_EMBEDDINGS=1 + LLM_EMBEDDING_MODE=local|remote enables them. mode='local' uses sentence-transformers with the user-configured model. mode='remote' uses the LLM API /v1/embeddings endpoint with the user-configured alias.",
        "risk_categories": ["configuration", "model agnosticism", "data integrity"],
    },
    "config.embedding_default_no_deps": {
        "feature": "Config — embeddings default to no-deps mode",
        "acceptance": "With embeddings disabled (default), EmbeddingStore.search() returns [] and add() stores NULL embeddings. The pipeline runs end-to-end without sentence-transformers or torch installed.",
        "risk_categories": ["configuration", "data integrity"],
    },

    # Templates
    "templates.list_templates": {
        "feature": "Templates — list_templates()",
        "acceptance": "Returns all 5 genres: mystery, thriller, romance, fantasy, sci-fi",
        "risk_categories": ["data integrity"],
    },
    "templates.get_template": {
        "feature": "Templates — get_template(<genre>)",
        "acceptance": "Returns the matching template dict; raises KeyError or returns None for invalid",
        "risk_categories": ["error handling"],
    },
    "templates.get_beat_for_chapter": {
        "feature": "Templates — get_beat_for_chapter(genre, chapter_num)",
        "acceptance": "Returns the beat dict for the chapter's range; chapter 0 or > max returns None gracefully",
        "risk_categories": ["error handling", "edge case"],
    },

    # Export
    "export.markdown_written": {
        "feature": "Export — manuscript.md written",
        "acceptance": "After export, manuscript.md exists and contains all chapters in order",
        "risk_categories": ["data integrity"],
    },
    "export.empty_manuscript": {
        "feature": "Export — empty manuscript handling",
        "acceptance": "If no chapters, export is skipped (or produces empty file) without crashing",
        "risk_categories": ["error handling", "edge case"],
    },

    # API client
    "api.retry_only_transient": {
        "feature": "CrofaiClient — retry only transient errors",
        "acceptance": "chat_with_retry retries 429/5xx; does NOT retry 401/400/404",
        "risk_categories": ["error handling"],
    },
    "api.truncation_retry": {
        "feature": "CrofaiClient — truncation retry",
        "acceptance": "When parse_json_output detects TRUNCATED response, chat_parse_with_retry re-issues the chat",
        "risk_categories": ["error handling", "data integrity"],
    },
    "api.empty_response_retry": {
        "feature": "CrofaiClient — empty response retry",
        "acceptance": "Empty responses raise a transient RuntimeError, triggering retry",
        "risk_categories": ["error handling"],
    },
    "api.cache_hit": {
        "feature": "CrofaiClient — cache hit",
        "acceptance": "When use_cache=True and cache key exists, no HTTP call is made",
        "risk_categories": ["performance"],
    },
    "api.json_repair": {
        "feature": "CrofaiClient — parse_json_output repairs common issues",
        "acceptance": "Strips markdown fences; unwraps parenthetical annotations; handles truncated braces; returns dict",
        "risk_categories": ["data integrity"],
    },

    # Backprop
    "backprop.iterative_convergence": {
        "feature": "Backprop — iterative convergence",
        "acceptance": "Loops scan → fix → re-scan until issue count stops decreasing or max iterations reached",
        "risk_categories": ["data integrity", "idempotency"],
    },
    "backprop.iterative_stagnation": {
        "feature": "Backprop — stagnation guard",
        "acceptance": "If scan results don't change between iterations, loop terminates early to avoid infinite loops",
        "risk_categories": ["error handling", "performance"],
    },
    "backprop.one_shot_runs": {
        "feature": "Backprop — one-shot mode (--no-iterative-backprop)",
        "acceptance": "With --no-iterative-backprop, run_backward_propagation runs once and returns",
        "risk_categories": ["configuration"],
    },

    # Adversarial edit
    "adversarial.mechanical_pass_always": {
        "feature": "Adversarial — mechanical pass always runs",
        "acceptance": "Mechanical tightening (22 patterns) runs on every chapter, even when --no-llm is set",
        "risk_categories": ["data integrity"],
    },
    "adversarial.llm_pass_conditional": {
        "feature": "Adversarial — LLM pass conditional",
        "acceptance": "LLM deep edit only runs when mechanical pass removed <5% of words",
        "risk_categories": ["configuration"],
    },

    # Review
    "review.dual_persona_combined": {
        "feature": "Review — dual-persona combined score",
        "acceptance": "Combined score = average of mechanical + literary_critic + professor scores",
        "risk_categories": ["data integrity"],
    },
    "review.single_persona": {
        "feature": "Review — --single-review (single persona)",
        "acceptance": "With --single-review, only one LLM persona runs (half the LLM tokens)",
        "risk_categories": ["configuration"],
    },

    # Foreshadow tracker
    "foreshadow.state_machine": {
        "feature": "Foreshadow — state transitions",
        "acceptance": "States transition planted → hinted → reinforced → due → overdue → paid; invalid transitions raise",
        "risk_categories": ["data integrity"],
    },
    "foreshadow.regex_autodetect": {
        "feature": "Foreshadow — regex auto-detection",
        "acceptance": "Markers like 'would later', 'little did they know' auto-detect new foreshadowings",
        "risk_categories": ["data integrity"],
    },

    # Canonical store
    "canonical.file_persistence": {
        "feature": "Canonical store — FileCanonicalStore persistence",
        "acceptance": "State survives across process restarts via canonical_state.json",
        "risk_categories": ["data integrity"],
    },
    "canonical.recall_top_k": {
        "feature": "Canonical store — recall by query",
        "acceptance": "Recall returns top-K memories matching query by word overlap",
        "risk_categories": ["data integrity"],
    },

    # ReIO compression
    "reio.recent_full": {
        "feature": "ReIO — recent chapters full",
        "acceptance": "Recent N chapters (default 2-3) are kept at full text",
        "risk_categories": ["data integrity"],
    },
    "reio.medium_compressed": {
        "feature": "ReIO — medium chapters one-liner",
        "acceptance": "Medium chapters (2-10) compressed to one-liner summaries",
        "risk_categories": ["data integrity"],
    },
    "reio.early_arc_level": {
        "feature": "ReIO — early chapters arc-level",
        "acceptance": "Early chapters (10+) compressed to arc-level summaries",
        "risk_categories": ["data integrity"],
    },

    # Agent mode
    "agents.showrunner_routes_correctly": {
        "feature": "Agent mode — Showrunner routes phases",
        "acceptance": "With --agents, run_showrunner_pipeline handles planning; standard pipeline is NOT also called",
        "risk_categories": ["configuration"],
    },
    "agents.parallel_writers": {
        "feature": "Agent mode — --parallel-writers N",
        "acceptance": "Writers are batched in groups of N for parallel drafting",
        "risk_categories": ["configuration"],
    },
    "agents.feedback_default_in_interactive": {
        "feature": "Agent mode — feedback default in --interactive",
        "acceptance": "When --interactive, feedback_enabled defaults to True; for direct concept, defaults to False",
        "risk_categories": ["configuration", "UX"],
    },

    # Style profile
    "style.profile_load": {
        "feature": "Style profile — load named profile",
        "acceptance": "With --style-profile <name>, the profile from styles/<name>.json is loaded; missing file produces clear error",
        "risk_categories": ["error handling"],
    },

    # Debate protocol
    "debate.enabled_runs": {
        "feature": "Debate — --debate enables protocol",
        "acceptance": "With --debate, the draft revision loop includes 3-agent cross-examination",
        "risk_categories": ["configuration"],
    },
    "debate.disabled_skips": {
        "feature": "Debate — default (no --debate) skips protocol",
        "acceptance": "Without --debate, no LLM debate calls are made in the draft loop",
        "risk_categories": ["configuration", "performance"],
    },

    # Knowledge base
    "kb.lazy_load": {
        "feature": "Knowledge base — lazy-load on first use",
        "acceptance": "Reference files are not loaded until first retrieve() call",
        "risk_categories": ["performance"],
    },
    "kb.token_cap": {
        "feature": "Knowledge base — token cap respected",
        "acceptance": "No single retrieve() returns more than the configured max_tokens (500 by default)",
        "risk_categories": ["performance", "data integrity"],
    },
}


# Risk-based edge cases per category
EDGE_CASES = {
    "data integrity": [
        "Empty spec.json (zero bytes) — pipeline should re-run phase",
        "Truncated JSON (last byte cut) — should fall back to re-running",
        "Spec with all None fields — should still complete",
        "Outline with 0 chapters — should not crash on len(chapters)==0",
        "Outline with 1 chapter — single-chapter book edge case",
        "Checkpoint with phases out of order — should not double-run",
        "Existing canonical_state.json from a different project — should reset",
        "Chapters dir with non-md files mixed in — should be ignored",
        "Chapter file with binary content — should not crash chapter reader",
    ],
    "error handling": [
        "API returns 401 — should fail fast, not retry",
        "API returns 400 — should fail fast, not retry",
        "API returns 404 — should fail fast, not retry",
        "API returns 429 — should retry with backoff",
        "API returns 500 — should retry with backoff",
        "API returns empty body — should retry",
        "API returns malformed JSON — should call repair path",
        "API returns truncated JSON — should re-issue chat",
        "API times out — should retry then fail",
        "Missing env vars — clear error",
        "Missing required input file — clear error",
        "Disk full mid-write — checkpoint should not corrupt prior phases",
        "Permission denied on project_dir — clear error",
    ],
    "configuration": [
        "--quick with --no-backprop — both are 'off', should not double-log",
        "--feedback with --no-feedback — last one wins, but the implementation is checked",
        "--agents with --single-variant — should not error, variant logic skipped",
        "--genre <invalid> — argparse rejects",
        "--depth <invalid> — argparse rejects",
        "--parallel-writers 0 — should not divide by zero",
        "--parallel-writers -1 — should reject or clamp",
        "--parallel-writers 100 — should be honored but warn",
        "--style-profile <nonexistent> — clear error, not silent fallback",
    ],
    "security": [
        "Concept with shell metacharacters — slugify must sanitize",
        "Project dir with path traversal — must be rejected or normalized",
        "Concept with unicode RTL override — should sanitize or warn",
        "Concept with null bytes — must be rejected",
        "API key in error messages — must never be logged",
        "Interview answers with prompt-injection — should be treated as data, not instructions",
    ],
    "UX": [
        "--help output is readable and complete",
        "Error messages are actionable (mention how to fix)",
        "Resume mode prints 'resuming at question N' status",
        "Long-running phase prints periodic progress (not silent)",
        "Empty / no-args path prints clear usage",
        "Stuck Ctrl-C prints graceful cleanup message",
    ],
    "performance": [
        "Cache hit on second run — no HTTP call",
        "Large outline (50+ chapters) — loops should not O(n^2)",
        "Many small chapters vs one large chapter — both within budget",
        "ReIO compression with 30+ chapters — token budget respected",
    ],
    "idempotency": [
        "Re-running with same project_dir after a crash resumes from checkpoint",
        "Re-running after completion does not re-do anything",
        "Re-running with --quick after a non-quick run uses cached phases",
    ],
    "edge case": [
        "Concept is empty string — argparse should reject",
        "Concept is single word — should still produce a spec",
        "Concept is 10000 characters — should not timeout",
        "Project dir already exists with different files — should not clobber",
        "Project dir is a symlink — should follow or warn",
    ],
}


# ──────────────────────────────────────────────────────────────
# Expanded criteria (v0.5 inventory) — CLI flags, env vars, edge cases
# ──────────────────────────────────────────────────────────────

EXPANDED_CRITERIA = {
    # Remaining CLI flags
    "cli.project_dir_override": {
        "feature": "StoryForge CLI — --project-dir <path>",
        "acceptance": "Overrides default ~/storyforge-projects/<slug> output dir; path is created if missing",
        "risk_categories": ["data integrity", "configuration"],
    },
    "cli.quick_flag": {
        "feature": "StoryForge CLI — --quick",
        "acceptance": "Accepts --quick as valid flag; routed to quick=True in run_full_pipeline",
        "risk_categories": ["configuration"],
    },
    "cli.single_variant_flag": {
        "feature": "StoryForge CLI — --single-variant",
        "acceptance": "Accepts --single-variant; sets parallel_variants=False",
        "risk_categories": ["configuration"],
    },
    "cli.single_review_flag": {
        "feature": "StoryForge CLI — --single-review",
        "acceptance": "Accepts --single-review; sets dual_review=False",
        "risk_categories": ["configuration"],
    },
    "cli.no_backprop_flag": {
        "feature": "StoryForge CLI — --no-backprop",
        "acceptance": "Accepts --no-backprop; sets enable_backprop=False",
        "risk_categories": ["configuration"],
    },
    "cli.no_adversarial_flag": {
        "feature": "StoryForge CLI — --no-adversarial",
        "acceptance": "Accepts --no-adversarial; sets enable_adversarial=False",
        "risk_categories": ["configuration"],
    },
    "cli.no_iterative_backprop_flag": {
        "feature": "StoryForge CLI — --no-iterative-backprop",
        "acceptance": "Accepts --no-iterative-backprop; sets iterative_backprop=False (one-shot mode)",
        "risk_categories": ["configuration"],
    },
    "cli.no_gbrain_flag": {
        "feature": "StoryForge CLI — --no-gbrain",
        "acceptance": "Accepts --no-gbrain flag without error; disables GBrain canonical store",
        "risk_categories": ["configuration"],
    },
    "cli.no_reio_flag": {
        "feature": "StoryForge CLI — --no-reio",
        "acceptance": "Accepts --no-reio flag without error; disables ReIO context compression",
        "risk_categories": ["configuration"],
    },
    "cli.feedback_flag": {
        "feature": "StoryForge CLI — --feedback",
        "acceptance": "Accepts --feedback flag; sets feedback_enabled=True regardless of path",
        "risk_categories": ["configuration"],
    },
    "cli.no_feedback_flag": {
        "feature": "StoryForge CLI — --no-feedback",
        "acceptance": "Accepts --no-feedback flag; sets feedback_enabled=False regardless of path",
        "risk_categories": ["configuration"],
    },
    "cli.feedback_mutual_exclusion": {
        "feature": "StoryForge CLI — --feedback --no-feedback (both set)",
        "acceptance": "Last flag wins; --no-feedback after --feedback means False",
        "risk_categories": ["configuration"],
    },
    "cli.debate_flag": {
        "feature": "StoryForge CLI — --debate",
        "acceptance": "Accepts --debate flag without error; sets enable_debate=True",
        "risk_categories": ["configuration"],
    },
    "cli.no_changes_flag": {
        "feature": "StoryForge CLI — --no-changes",
        "acceptance": "Accepts --no-changes flag; disables structured change declarations",
        "risk_categories": ["configuration"],
    },
    "cli.style_profile_flag": {
        "feature": "StoryForge CLI — --style-profile <name>",
        "acceptance": "Accepts --style-profile with a name argument; stored in args.style_profile",
        "risk_categories": ["configuration"],
    },
    "cli.auto_style_extract_flag": {
        "feature": "StoryForge CLI — --auto-style-extract",
        "acceptance": "Accepts --auto-style-extract flag; sets auto_style_extract=True",
        "risk_categories": ["configuration"],
    },
    "cli.no_knowledge_base_flag": {
        "feature": "StoryForge CLI — --no-knowledge-base",
        "acceptance": "Accepts --no-knowledge-base flag; sets enable_knowledge_base=False",
        "risk_categories": ["configuration"],
    },
    "cli.no_validate_outline_flag": {
        "feature": "StoryForge CLI — --no-validate-outline",
        "acceptance": "Accepts --no-validate-outline flag; sets enable_validate_outline=False",
        "risk_categories": ["configuration"],
    },
    "cli.agents_flag": {
        "feature": "StoryForge CLI — --agents",
        "acceptance": "Accepts --agents flag; routes to run_showrunner_pipeline instead of run_full_pipeline",
        "risk_categories": ["configuration"],
    },
    "cli.parallel_writers_default": {
        "feature": "StoryForge CLI — --parallel-writers default",
        "acceptance": "Default value for --parallel-writers is 3",
        "risk_categories": ["configuration"],
    },
    "cli.parallel_writers_accepts_positive": {
        "feature": "StoryForge CLI — --parallel-writers 5",
        "acceptance": "Accepts positive integer values for --parallel-writers",
        "risk_categories": ["configuration"],
    },
    "cli.model_override_flag": {
        "feature": "StoryForge CLI — --model-override <alias>",
        "acceptance": "Accepts --model-override with a model alias; stored in args.model_override",
        "risk_categories": ["configuration"],
    },
    "cli.invalid_flag": {
        "feature": "StoryForge CLI — unknown flag",
        "acceptance": "Unknown flag is rejected by argparse with non-zero exit",
        "risk_categories": ["error handling"],
    },

    # Environment variables
    "env.base_url_override": {
        "feature": "Config — LLM_BASE_URL override",
        "acceptance": "Setting LLM_BASE_URL changes Config().base_url from the default",
        "risk_categories": ["configuration"],
    },
    "env.crofai_fallback": {
        "feature": "Config — CROFAI_API_KEY fallback",
        "acceptance": "When LLM_API_KEY is not set but CROFAI_API_KEY is, Config uses CROFAI_API_KEY",
        "risk_categories": ["security", "configuration"],
    },
    "env.embedding_model_vars": {
        "feature": "Config — LLM_EMBEDDING_LOCAL_MODEL / LLM_EMBEDDING_REMOTE_ALIAS",
        "acceptance": "Setting LLM_EMBEDDING_LOCAL_MODEL or LLM_EMBEDDING_REMOTE_ALIAS overrides defaults",
        "risk_categories": ["configuration"],
    },

    # API client expanded
    "api.truncation_retry": {
        "feature": "CrofaiClient — truncation retry triggers re-issue",
        "acceptance": "When parse_json_output detects TRUNCATED response via _looks_truncated, chat_parse_with_retry re-issues the chat",
        "risk_categories": ["error handling", "data integrity"],
    },
    "api.cache_disabled_default": {
        "feature": "CrofaiClient — cache disabled by default",
        "acceptance": "Without use_cache=True, no cache directory or files are created",
        "risk_categories": ["performance"],
    },
    "api.timeout_retry": {
        "feature": "CrofaiClient — timeout retry then fail",
        "acceptance": "API timeout raises RuntimeError which chat_with_retry retries up to max_retries times before re-raising",
        "risk_categories": ["error handling"],
    },

    # Pipeline expanded
    "phase.fact_check_no_chapters": {
        "feature": "Fact-check — skipped when no chapters exist",
        "acceptance": "run_fact_check returns SKIPPED status when chapters dir is empty or missing",
        "risk_categories": ["error handling", "edge case"],
    },
    "phase.quick_skips_valid_flags": {
        "feature": "Pipeline — --quick with --no-backprop and --no-adversarial",
        "acceptance": "Combined flags do not cause double-skip logging or error",
        "risk_categories": ["configuration"],
    },

    # Edge cases
    "edge.concept_empty_string": {
        "feature": "Edge — empty string concept",
        "acceptance": "Empty concept string after strip is rejected by argparse or handled gracefully, not silently allowed",
        "risk_categories": ["error handling", "security"],
    },
    "edge.concept_shell_metacharacters": {
        "feature": "Edge — concept with shell metacharacters",
        "acceptance": "Slugify sanitizes shell metacharacters; no shell injection possible via concept name",
        "risk_categories": ["security"],
    },
    "edge.concept_unicode_rtl": {
        "feature": "Edge — concept with Unicode RTL override",
        "acceptance": "Slugify strips or normalizes bidirectional control characters",
        "risk_categories": ["security", "data integrity"],
    },
    "edge.concept_null_bytes": {
        "feature": "Edge — concept with null bytes",
        "acceptance": "Null bytes in concept are rejected or stripped, not passed to filesystem",
        "risk_categories": ["security"],
    },
    "edge.project_dir_symlink": {
        "feature": "Edge — project dir is a symlink",
        "acceptance": "Pipeline follows symlinks without error for output directory",
        "risk_categories": ["data integrity"],
    },
    "edge.project_dir_permission_denied": {
        "feature": "Edge — permission denied on project_dir",
        "acceptance": "Pipeline fails with clear error message when project dir cannot be created",
        "risk_categories": ["error handling"],
    },
    "edge.chapter_binary_file": {
        "feature": "Edge — chapter directory contains binary files",
        "acceptance": "Non-.md files in chapters dir are ignored, not read as text",
        "risk_categories": ["data integrity", "error handling"],
    },
    "edge.large_outline_many_chapters": {
        "feature": "Edge — outline with 50+ chapters",
        "acceptance": "Outline validation and chapter counting handles 50+ chapters without O(n²) crash",
        "risk_categories": ["performance", "data integrity"],
    },

    # Interview expanded
    "interview.resume_all_answers_complete": {
        "feature": "Interview — resume when all answers already present",
        "acceptance": "On resume with fully answered checkpoint, returns immediately without re-prompting",
        "risk_categories": ["UX", "idempotency"],
    },
    "interview.drilling_followups_stored": {
        "feature": "Interview — drilling follow-up answers stored correctly",
        "acceptance": "Follow-up answers via drilling are stored with is_follow_up=True, same dimension and question_id prefix",
        "risk_categories": ["data integrity"],
    },
    "interview.context_monitor_at_threshold": {
        "feature": "Interview — context monitor fires at exactly 70%",
        "acceptance": "Warning triggers when accumulated tokens >= 0.7 * model_limit; one-shot only",
        "risk_categories": ["UX", "performance"],
    },
}

MORE_EDGE_CASES = {
    "flag combinations": [
        "--interactive --genre fantasy — genre filters interview questions",
        "--interactive --resume <dir> — mutual exclusion should error or last-wins",
        "--quick --no-backprop — both skip backprop, should not double-log",
        "--benchmark --show-models — exit after show-models, never runs benchmark",
    ],
    "data integrity (more)": [
        "Project dir with mixed-case concept same as lower-case — should slugify consistently",
        "Chapter file with BOM character — should not corrupt parse",
        "Two-phase write interrupted by crash — left partial file should not be read as valid",
        "Concurrent pipeline on same project_dir from two processes — race condition on checkpoint",
        "Checkpoint.json with extra unknown keys — should not fail validation",
    ],
    "error handling (more)": [
        "LLM returns empty list for outline chapters — should handle gracefully",
        "LLM returns non-JSON for scoring — should fall back to mechanical-only score",
        "File system returns EMFILE (too many open files) during draft — should not lose data",
        "OOM during large embedding — should not crash pipeline",
        "Storage full mid-write — pipeline should not mark phase complete",
    ],
    "config (more)": [
        "LLM_MODEL_<ROLE> with empty string — should fall back, not crash",
        "LLM_MODEL_<ROLE> with unknown role name — ignored, not error",
        "Config singleton across threads — thread-safe read access",
        "LLM_DEFAULT_MODEL set to unknown alias — fall back to kimi-balanced",
        "Multiple LLM_MODEL_<ROLE> set for same underlying model — should each resolve correctly",
    ],
}
