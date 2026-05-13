"""StoryForge configuration — crofai model routing, scoring thresholds, API config.

Model routing strategy (updated 2026-05):
- Kimi K2.6 and K2.6 Precision (prose-optimized): chapter drafting, prose generation
- DeepSeek V4 Pro Precision (large context window): worldbuilding, planning, long-context
- DeepSeek V4 Flash (reasoning + cheap): thin-area detection, quick reasoning tasks
- Qwen3.5 9B (fast/cheap): scoring, mechanical checks, quick iterations
- Qwen3.6 27B (mid-tier reasoning): upgrade path for scoring/reasoning tasks
- GLM 5.1 (reasoning, high speed): mid-tier general tasks

Usage:
    from config import Config
    config = Config()
    model = config.model_for_phase("draft")
"""

import os
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelConfig:
    """Single model configuration for crofai API calls."""
    name: str                           # Model identifier string
    provider: str = "crofai"            # Provider name
    base_url: str = "https://beta.crof.ai/v1"
    max_tokens: int = 8192
    temperature: float = 0.8
    top_p: float = 0.95


@dataclass
class ScoringConfig:
    """Scoring thresholds for the dual immune system."""
    banned_word_penalty: float = -0.5       # Per banned word found
    show_dont_tell_threshold: float = 0.3    # Max ratio of telling sentences
    pacing_variance_min: float = 0.1         # Min acceptable sentence length variance
    min_chapter_score: float = 6.0           # Min score before revision
    target_chapter_score: float = 8.0        # Target for revision completion
    max_revision_rounds: int = 3             # Max revision loops per chapter
    max_full_review_rounds: int = 5          # Max full-manuscript review rounds


@dataclass
class ChapterConfig:
    """Chapter generation parameters."""
    target_words_per_chapter: int = 4000
    min_chapters: int = 8
    max_chapters: int = 30
    context_carry_window: int = 3            # Number of previous chapters to include
    auto_compress_at_tokens: int = 900000    # RESERVED: context compression not yet implemented


class Config:
    """Central configuration — all settings in one place. Singleton."""

    _instance: Optional["Config"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # --- API Configuration ---
        self.api_key: str = self._get_env("CROFAI_API_KEY", "CROFAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "CROFAI_API_KEY environment variable not set. "
                "Set it before running the pipeline:\n"
                "  export CROFAI_API_KEY='your-key-here'   (Mac/Linux)\n"
                "  set CROFAI_API_KEY=your-key-here        (Windows CMD)\n"
                "  $env:CROFAI_API_KEY='your-key-here'     (PowerShell)"
            )
        self.base_url: str = "https://beta.crof.ai/v1"

        # --- Model Aliases (crofai model names) ---
        self.models = {
            # Kimi K2.6 variants — prose-optimized, 3 variants to benchmark
            "kimi-speed": ModelConfig(name="kimi-k2.6"),
            "kimi-balanced": ModelConfig(name="kimi-k2.6-precision"),
            "kimi-precision": ModelConfig(name="kimi-k2.6-precision"),
            # DeepSeek — large context window
            "deepseek": ModelConfig(name="deepseek-v4-pro-precision", temperature=0.7, max_tokens=16384),
            # DeepSeek V4 Flash — reasoning + cheap, good for thin-area detection
            "deepseek-flash": ModelConfig(name="deepseek-v4-flash", temperature=0.3, max_tokens=8192),
            # GLM 5.1 — reasoning-enabled, high speed, mid-tier general
            "glm": ModelConfig(name="glm-5.1", temperature=0.7, max_tokens=8192),
            # Qwen3.5 9B — fast/cheap for scoring
            "flash": ModelConfig(name="qwen3.5-9b", temperature=0.3, max_tokens=4096),
            # Qwen3.6 27B — mid-tier reasoning upgrade
            "qwen-mid": ModelConfig(name="qwen3.6-27b", temperature=0.5, max_tokens=8192),
        }

        # --- Phase-to-Model Routing ---
        # Each phase picks the best model for the task
        self.phase_models = {
            "seed": "deepseek",              # Planning — needs context
            "worldbuilding": "deepseek",      # Expansive world building — needs context
            "characters": "kimi-balanced",    # Character depth — prose matters
            "outline": "kimi-balanced",        # Structural planning — faster generation
            "draft": "kimi-precision",        # Actual chapter writing — prose quality matters most
            "scoring": "flash",               # Mechanical checks — cheap and fast
            "critique": "kimi-precision",     # Deep literary critique — prose-aware
            "final_review": "deepseek",       # Full manuscript review — needs context
            "interview": "deepseek",          # Interactive Q&A — large context for conversation
            "interview_scoring": "flash",     # Thin-area detection — cheap and fast
        }

        # --- Interview Task-to-Model Routing ---
        # Each interview dimension picks the best model based on lechmazur/writing
        # benchmark rankings: DeepSeek for context-heavy Q&A, Kimi K2.6 for
        # prose/literary comparisons, Qwen3.5 9B for scoring/detection/quick turns.
        self.interview_models = {
            "concept_premise": "deepseek",      # Broad creative context
            "world_setting": "deepseek",         # Expansive world details
            "characters": "kimi-balanced",      # Character depth — prose matters
            "plot_structure": "deepseek",        # Structural complexity
            "theme_voice": "kimi-balanced",      # Prose/literary nuance
            "market_comparisons": "flash",       # Quick comparisons
            "drilling": "flash",                 # Follow-up generation — cheap/fast
            "compilation": "deepseek",           # Story bible compilation — large context
        }

        # --- Benchmark Models (3 Kimi K2.6 variants to test) ---
        self.benchmark_models = {
            "kimi-k2.6": ModelConfig(name="kimi-k2.6"),
            "kimi-k2.6-precision": ModelConfig(name="kimi-k2.6-precision"),
            "deepseek-v4-flash": ModelConfig(name="deepseek-v4-flash"),
            "glm-5.1": ModelConfig(name="glm-5.1"),
            "qwen3.6-27b": ModelConfig(name="qwen3.6-27b"),
        }

        # --- Scoring ---
        self.scoring = ScoringConfig()

        # --- Chapter defaults ---
        self.chapter = ChapterConfig()

        # --- Banned words / cliche list (autonovel-inspired) ---
        self.banned_words: list[str] = [
            "suddenly", "very", "quite", "literally", "actually",
            "basically", "incredibly", "amazingly", "unbelievably",
            "truly", "certainly", "surely", "obviously", "absolutely",
            "just", "really", "so", "such a", "a lot",
            "gaze", "smirk", "chuckle", "sigh", "nod",
            "shrug", "blink", "frown", "raise an eyebrow",
            "as if", "as though", "seemed to", "began to", "started to",
        ]

        # --- Export defaults ---
        self.project_dir: str = os.path.join(os.path.expanduser("~"), "storyforge-projects")

        # --- Token tracking ---
        self.track_tokens: bool = True
        self.token_cost_per_input: float = 0.000002
        self.token_cost_per_output: float = 0.000010
        self.report_usage: bool = True

    def _get_env(self, *names: str) -> str:
        """Get first available env var from a list of names."""
        for name in names:
            val = os.environ.get(name)
            if val:
                return val
        return ""

    def model_for_phase(self, phase: str) -> ModelConfig:
        """Get the best model config for a pipeline phase."""
        key = self.phase_models.get(phase, "kimi-balanced")
        return self.models[key]

    def model_for_interview(self, task: str, override: Optional[str] = None) -> ModelConfig:
        """Get the best model config for an interview task.

        Args:
            task: Interview dimension or task type (e.g. 'concept_premise',
                  'drilling', 'compilation').
            override: Optional model alias to use instead of the routed one.
                      Must be a key in self.models (e.g. 'kimi-balanced').

        Returns:
            ModelConfig for the routed or overridden model.
        """
        if override and override in self.models:
            return self.models[override]
        key = self.interview_models.get(task, "kimi-balanced")
        return self.models[key]

    def model_for_benchmark(self, alias: str) -> ModelConfig:
        """Get model config for benchmark variants.

        Falls back to 'kimi-k2.6' (the base variant) when the requested
        alias is not in the benchmark registry.
        """
        return self.benchmark_models.get(alias, self.benchmark_models["kimi-k2.6"])
