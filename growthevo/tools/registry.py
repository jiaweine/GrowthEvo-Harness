from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolFn = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    fn: ToolFn
    read_only: bool = True
    description: str = ""


class ToolRegistry:
    """Minimal typed registry used by the harness execution boundary."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not spec.name.strip():
            raise ValueError("tool name cannot be empty")
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def call(self, name: str, /, **kwargs: Any) -> Any:
        return self.get(name).fn(**kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
