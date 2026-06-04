"""StoryForge pipeline modules - each phase is a standalone module.

v0.4 adds:
- run_debate (Triadic Constraint Debate Protocol — SGDD)

v0.3 adds:
- HindsightStore (canonical state store)
- ReIOCompressor (context compression)
- run_iterative_backpropagation (convergence-based backprop)
- Genre templates (5 genres with structured beats)
- 4 rhetorical strategy profiles (Postwriter-inspired)
"""

from pipeline.hindsight_client import HindsightStore
from pipeline.reio_compression import ReIOCompressor, estimate_tokens
from pipeline.iterative_backprop import run_iterative_backpropagation
from pipeline.debate import run_debate
