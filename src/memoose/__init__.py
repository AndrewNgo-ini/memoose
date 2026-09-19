"""memoose: a dual-path memory system for proactive agents. Skills + CLI + MCP, no model calls, no API key."""

__version__ = "0.4.0"

from .engine import Engine  # noqa: E402
from .graph.models import CrossConnectIn, EntityIn, LessonIn, RelationIn  # noqa: E402
from .graph.ontology import OntologyError  # noqa: E402

__all__ = ["Engine", "EntityIn", "RelationIn", "LessonIn", "CrossConnectIn", "OntologyError", "__version__"]
