"""The workflow definition as it is saved, exchanged with the editor and stored: nodes, edges, settings per node.

Shape errors (a node without an id, a wrong type of value) are rejected when the request is parsed. Everything about
whether the graph *makes sense* (unknown node types, missing settings, unreachable nodes, unsafe actions...) is the
validator's job (``validate.py``) and is reported as issues, so an editor can save work in progress.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_NODES = 50
MAX_EDGES = 100
SCHEMA_VERSION = 1

Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,80}$")]


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(default=0.0, ge=-100_000, le=100_000)
    y: float = Field(default=0.0, ge=-100_000, le=100_000)


class NodeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Key
    # Not an enum here: an unknown type is a validation *issue* the editor can show, not a rejected request.
    type: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    label: Annotated[str, StringConstraints(max_length=120)] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)


class EdgeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Key
    source: Key
    target: Key
    # The output port of the source this edge leaves from. Empty means the source's single default port ("next").
    branch: Annotated[str, StringConstraints(max_length=60)] | None = None

    @property
    def port(self) -> str:
        return self.branch or "next"


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(default=SCHEMA_VERSION, alias="schemaVersion", ge=1, le=1)
    nodes: list[NodeDef] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[EdgeDef] = Field(default_factory=list, max_length=MAX_EDGES)
