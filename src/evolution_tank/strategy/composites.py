"""Composite nodes — Selector and Sequence."""

from __future__ import annotations

from typing import Any

from evolution_tank.strategy.nodes import BTNode, NodeStatus, TickContext


class SelectorNode(BTNode):
    """Try children left-to-right, return SUCCESS on first success."""

    def __init__(self, children: list[BTNode]) -> None:
        self.children = children

    def tick(self, ctx: TickContext) -> NodeStatus:
        for child in self.children:
            status = child.tick(ctx)
            if status == NodeStatus.SUCCESS:
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "selector",
            "children": [c.to_dict() for c in self.children],
        }

    def get_children(self) -> list[BTNode]:
        return list(self.children)


class SequenceNode(BTNode):
    """Run children left-to-right, return FAILURE on first failure."""

    def __init__(self, children: list[BTNode]) -> None:
        self.children = children

    def tick(self, ctx: TickContext) -> NodeStatus:
        for child in self.children:
            status = child.tick(ctx)
            if status == NodeStatus.FAILURE:
                return NodeStatus.FAILURE
        return NodeStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "sequence",
            "children": [c.to_dict() for c in self.children],
        }

    def get_children(self) -> list[BTNode]:
        return list(self.children)
