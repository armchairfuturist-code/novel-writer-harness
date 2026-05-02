"""StoryForge configuration — crofai model routing, scoring thresholds, API config.

Model routing strategy:
- Kimi K2.6 variants (prose-optimized, writing benchmark rank #8): chapter drafting, prose generation
- DeepSeek V4 Pro (large context window): worldbuilding, planning, long-context tasks
- Gemini 2.5 Flash Thinking (cheap/fast): scoring, mechanical checks, quick iterations

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
    auto_compress_at_tokens: int = 900000    # Trigger context compression (gemini-writer inspired)


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
        self.base_url: str = "https://beta.crof.ai/v1"

        # --- Model Aliases (crofai model names) ---
        self.models = {
            # Kimi K2.6 variants — prose-optimized, 3 variants to benchmark
            "kimi-speed": ModelConfig(name="kimi-k2.6-speed"),
            "kimi-balanced": ModelConfig(name="kimi-k2.6-test"),
            "kimi-precision": ModelConfig(name="kimi-k2.6-precision"),
            # DeepSeek — large context window
            "deepseek": ModelConfig(name="deepseek-v4-pro-precision", temperature=0.7),
            # Gemini Flash — cheap fast for scoring
            "flash": ModelConfig(name="gemini-2.5-flash-thinking", temperature=0.3, max_tokens=4096),
        }

        # --- Phase-to-Model Routing ---
        # Each phase picks the best model for the job
        self.phase_models = {
            "seed": "deepseek",              # Planning — needs context
            "worldbuilding": "deepseek",      # Expansive world building — needs context
            "characters": "kimi-balanced",    # Character depth — prose matters
            "outline": "deepseek",            # Structural planning — needs context
            "draft": "kimi-precision",        # Actual chapter writing — prose quality matters most
            "scoring": "flash",               # Mechanical checks — cheap and fast
            "critique": "kimi-precision",     # Deep literary critique — prose-aware
            "final_review": "deepseek",       # Full manuscript review — needs context
        }

        # --- Benchmark Models (3 Kimi K2.6 variants to test) ---
        self.benchmark_models = {
            "kimi-k2.6-speed": ModelConfig(name="kimi-k2.6-speed"),
            "kimi-k2.6-test": ModelConfig(name="kimi-k2.6-test"),
            "kimi-k2.6-precision": ModelConfig(name="kimi-k2.6-precision"),
        }

        # --- Scoring ---
        self.scoring = ScoringConfig()

        # --- Chapter defaults ---
        self.chapter = ChapterConfig()

        # --- Banned words / cliche list (autonovel-inspired) ---
        self.banned_words: list[str] = field(default_factory=lambda: [
            "suddenly", "very", "quite", "literally", "actually",
            "basically", "incredibly", "amazingly", "unbelievably",
            "truly", "certainly", "surely", "obviously", "absolutely",
            "just", "really", "so", "such a", "a lot",
            "gaze", "smirk", "chuckle", "sigh", "nod",
            "shrug", "blink", "frown", "raise an eyebrow",
            "as if", "as though", "seemed to", "began to", "started to",
        ])

        # --- Export defaults ---
        self.project_dir: str = os.path.join(os.path.expanduser("~"), "storyforge-projects")

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

    def model_for_benchmark(self, alias: str) -> ModelConfig:
        """Get model config for benchmark variants."""
        return self.models.get(alias, self.models["kimi-balanced"])
