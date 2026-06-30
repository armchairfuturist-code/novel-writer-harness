"""StoryForge pipeline modules."""
from pipeline.reio_compression import ReIOCompressor, estimate_tokens as compression_estimate_tokens
from pipeline.iterative_backprop import run_iterative_backpropagation
from pipeline.debate import run_debate


def HindsightStore(*args, **kwargs):
    """Lazy import of HindsightStore (requires httpx)."""
    from pipeline.hindsight_client import HindsightStore as _HS
    return _HS(*args, **kwargs)

