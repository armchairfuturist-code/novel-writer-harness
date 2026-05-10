"""StoryForge pipeline modules - each phase is a standalone module.

v0.3 adds:
- GBrainStore (canonical state store)
- ReIOCompressor (context compression)
- run_iterative_backpropagation (convergence-based backprop)
- Genre templates (5 genres with structured beats)
- 4 rhetorical strategy profiles (Postwriter-inspired)
"""

from pipeline.gbrain_client import GBrainStore
from pipeline.reio_compression import ReIOCompressor, estimate_tokens
from pipeline.iterative_backprop import run_iterative_backpropagation
