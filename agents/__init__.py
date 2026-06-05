"""StoryForge Multi-Agent System.

Showrunner/Worker architecture:
- Showrunner (Orchestrator): plans novel, creates assignments, coordinates workers
- Writer agents: draft chapters in parallel from briefs + canonical state
- Critic agent: reviews and scores chapters (mechanical + dual-persona LLM)
- Continuity agent: manages canonical state, runs backpropagation
- Editor agent: adversarial tightening pass on completed prose

Usage:
    from agents.orchestrator import run_showrunner_pipeline
    result = run_showrunner_pipeline(concept, config)
"""
