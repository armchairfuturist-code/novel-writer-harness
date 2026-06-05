"""Agent base class — abstract interface for all StoryForge agents.

Every agent implements:
- run(): Execute the agent's task
- can_handle(task_type): Check if this agent can process a given task
- capabilities: Read-only dict describing what the agent does
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from config import Config


class StoryForgeAgent(ABC):
    """Abstract base class for all StoryForge agents.

    Agents are the atomic unit of work in the multi-agent system.
    Each agent has a specific role and model routing.

    Attributes:
        agent_id: Unique identifier for this agent instance.
        config: Shared Config singleton.
        capabilities: Dict describing what this agent can do.
    """

    def __init__(
        self,
        agent_id: str,
        config: Optional[Config] = None,
        **kwargs,
    ):
        self.agent_id = agent_id
        self.config = config or Config()
        self._extra = kwargs

    @property
    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return a dict describing this agent's capabilities.

        Standard keys:
        - role: Human-readable role name (e.g. 'Writer', 'Critic')
        - can_handle: List of task types this agent can process
        - model: Model name used by this agent
        - max_concurrency: Max parallel instances (1 for most agents)
        """
        ...

    @abstractmethod
    def can_handle(self, task_type: str) -> bool:
        """Return True if this agent can process the given task type.

        Args:
            task_type: String identifying the task (e.g. 'draft_chapter',
                      'review_chapter', 'scan_continuity')
        """
        ...

    @abstractmethod
    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the agent's task and return results.

        Args:
            task: Task dict with at minimum a 'type' key.
                  Type-specific fields are documented per subclass.
            context: Optional shared context (canonical state, project dir, etc.)

        Returns:
            Result dict. Type-specific shape documented per subclass.
            Must include at minimum:
            - 'status': 'success', 'failed', or 'skipped'
            - 'agent_id': This agent's identifier
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(agent_id={self.agent_id!r})"


# ── Task Type Constants ───────────────────────────────────────────────

TASK_PLAN_NOVEL = "plan_novel"
TASK_DRAFT_CHAPTER = "draft_chapter"
TASK_REVIEW_CHAPTER = "review_chapter"
TASK_SCORE_MECHANICAL = "score_mechanical"
TASK_SCAN_CONTINUITY = "scan_continuity"
TASK_BACKWARD_PROPAGATE = "backward_propagate"
TASK_EDIT_ADVERSARIAL = "edit_adversarial"
TASK_EXPORT_MANUSCRIPT = "export_manuscript"
TASK_BUILD_WORLD = "build_world"
TASK_CREATE_CHARACTERS = "create_characters"
TASK_CREATE_OUTLINE = "create_outline"
TASK_ASSIGN_BATCH = "assign_batch"

# Batch task types — the showrunner creates batches of these
TASK_BATCH_DRAFT = "batch_draft"
TASK_BATCH_REVIEW = "batch_review"

ALL_TASK_TYPES = {
    TASK_PLAN_NOVEL,
    TASK_DRAFT_CHAPTER,
    TASK_REVIEW_CHAPTER,
    TASK_SCORE_MECHANICAL,
    TASK_SCAN_CONTINUITY,
    TASK_BACKWARD_PROPAGATE,
    TASK_EDIT_ADVERSARIAL,
    TASK_EXPORT_MANUSCRIPT,
    TASK_BUILD_WORLD,
    TASK_CREATE_CHARACTERS,
    TASK_CREATE_OUTLINE,
    TASK_ASSIGN_BATCH,
    TASK_BATCH_DRAFT,
    TASK_BATCH_REVIEW,
}
