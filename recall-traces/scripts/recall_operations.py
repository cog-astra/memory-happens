from dataclasses import dataclass, field
from threading import Event
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class Value(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Evidence(Value):
    source: str
    locator: str
    revision: str | None = None
    observed_at: str | None = None


class Passage(Value):
    text: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)


class Lineage(Value):
    invocation: str
    inputs: list[str] = Field(default_factory=list)
    relation: Literal['unknown', 'quoted', 'transformed'] = 'unknown'
    input_origin: Literal['caller_supplied'] = 'caller_supplied'


class Record(Passage):
    id: str
    lineage: Lineage
    access: list[str] = Field(default_factory=list)


class Outcome(Value):
    status: Literal['success', 'unsupported', 'unavailable', 'failed', 'cancelled', 'partial']
    code: str = ''
    message: str = ''
    next_steps: list[str] = Field(default_factory=list)
    continuation: dict | None = None


class NoParameters(Value):
    pass


@dataclass(frozen=True)
class Operation:
    name: str
    purpose: str
    parameters: type[BaseModel] = NoParameters
    inputs: tuple[str, ...] = ()
    requires_text: bool = False
    version: str = '0.1'


@dataclass
class Context:
    policy: Callable[[tuple[str, ...]], bool]
    cancelled: Event = field(default_factory=Event)
    resources: set[str] = field(default_factory=set)

    def require(self, *resources: str):
        dependencies = self.resources | set(resources)
        if not self.policy(tuple(sorted(dependencies))):
            raise PermissionError('Source access denied by configured policy.')
        self.resources.update(resources)


def passage(record: Record) -> Passage:
    return Passage(text=record.text, evidence=record.evidence, context=record.context)
