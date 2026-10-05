"""Explicit multi-source merge plans for multidicts.

A :class:`MergePlan` declares, per key, how values from several source
multidicts are combined into a brand-new container:

* ``MergeStrategy.REPLACE`` -- values from the latest source holding the key
  replace all previously collected ones (all of them, a multi-value key is
  never collapsed into a single value);
* ``MergeStrategy.APPEND`` -- values from every source are concatenated in
  source order;
* ``MergeStrategy.DEDUP`` -- like ``APPEND`` but duplicated values are
  dropped, keeping the first occurrence order (stable dedup).

Keys not declared in the plan fall back to the plan's fixed default
strategy (``MergeStrategy.APPEND`` unless overridden).

Key matching follows the real key rules of the first source container:
merging :class:`CIMultiDict` sources groups case-equivalent keys
(``"A"`` and ``"a"``) into a single output slot.  The position of a key
in the output is determined by where the key first occurs while scanning
the sources in order.  Conflicting rules (two rule keys that are
equivalent under the container's key rules but request different
strategies) are rejected with :exc:`ValueError` before any merging
happens.  The result is a fresh container, fully independent from the
input sources, and :attr:`MergeResult.sources` reports the originating
source index for every output item.

>>> from multidict import CIMultiDict, MergePlan, MergeStrategy, merge_sources
>>> plan = MergePlan(
...     {
...         "a": MergeStrategy.APPEND,
...         "b": MergeStrategy.REPLACE,
...         "c": MergeStrategy.DEDUP,
...     }
... )
>>> first = CIMultiDict([("a", 1), ("a", 2), ("b", "old"), ("c", 1), ("c", 2)])
>>> second = CIMultiDict([("A", 3), ("B", "new"), ("c", 2), ("c", 3)])
>>> result = merge_sources(plan, first, second)
>>> result.mapping
<CIMultiDict('a': 1, 'a': 2, 'a': 3, 'b': 'new', 'c': 1, 'c': 2, 'c': 3)>
>>> result.sources
[0, 0, 1, 1, 0, 0, 1]
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ._abc import MultiMapping
from ._compat import USE_EXTENSIONS

if TYPE_CHECKING or not USE_EXTENSIONS:
    from ._multidict_py import (
        CIMultiDict,
        CIMultiDictProxy,
        MultiDict,
        MultiDictProxy,
    )
else:  # pragma: no cover
    from ._multidict import (  # type: ignore[attr-defined]
        CIMultiDict,
        CIMultiDictProxy,
        MultiDict,
        MultiDictProxy,
    )

__all__ = (
    "MergePlan",
    "MergeResult",
    "MergeStrategy",
    "merge_sources",
)

_V = TypeVar("_V")

_CI_TYPES = (CIMultiDict, CIMultiDictProxy)


def _ci_canonical(key: str) -> str:
    # Mirrors ``_CIMixin._identity``: case-insensitive containers identify
    # keys by their lowered spelling.
    ret = key.lower()
    if type(ret) is not str:
        return str.__str__(ret)
    return ret


class MergeStrategy(enum.Enum):
    """Per-key strategy used when merging several multidict sources."""

    REPLACE = "replace"
    APPEND = "append"
    DEDUP = "dedup"


class MergePlan:
    """An explicit plan describing how to merge several multidict sources.

    *rules* maps a key to the :class:`MergeStrategy` used for it; keys
    that are not declared fall back to the fixed *default* strategy
    (``MergeStrategy.APPEND``).
    """

    __slots__ = ("_default", "_rules")

    def __init__(
        self,
        rules: Mapping[str, MergeStrategy | str] | None = None,
        *,
        default: MergeStrategy | str = MergeStrategy.APPEND,
    ) -> None:
        self._default = MergeStrategy(default)
        self._rules: dict[str, MergeStrategy] = {}
        for key, strategy in (rules or {}).items():
            if not isinstance(key, str):
                raise TypeError(
                    f"merge rule keys must be str, got {type(key).__name__}"
                )
            self._rules[key] = MergeStrategy(strategy)

    @property
    def rules(self) -> dict[str, MergeStrategy]:
        """A copy of the declared per-key strategies."""
        return dict(self._rules)

    @property
    def default(self) -> MergeStrategy:
        """The fixed strategy applied to undeclared keys."""
        return self._default

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._rules!r}, default={self._default!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MergePlan):
            return NotImplemented
        return self._rules == other._rules and self._default == other._default

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return eq
        return not eq


class MergeResult(Generic[_V]):
    """The outcome of :func:`merge_sources`.

    ``mapping`` is a fresh container, independent from the input sources.
    ``sources`` lists, for every item of ``mapping`` in iteration order,
    the index of the source it came from.
    """

    __slots__ = ("mapping", "sources")

    def __init__(self, mapping: MultiDict[_V], sources: list[int]) -> None:
        self.mapping = mapping
        self.sources = sources

    def items_with_sources(self) -> list[tuple[str, _V, int]]:
        """Return ``(key, value, source_index)`` triples in output order."""
        return [
            (key, value, source)
            for (key, value), source in zip(self.mapping.items(), self.sources)
        ]

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(mapping={self.mapping!r}, "
            f"sources={self.sources!r})"
        )


class _Slot:
    __slots__ = ("key", "seen_values", "strategy", "values")

    def __init__(self, key: str, strategy: MergeStrategy) -> None:
        self.key = key
        self.strategy = strategy
        self.values: list[tuple[Any, int]] = []
        self.seen_values: list[Any] = []


def merge_sources(plan: MergePlan, *sources: MultiMapping[_V]) -> MergeResult[_V]:
    """Merge *sources* into a new multidict following an explicit *plan*.

    The first source decides the key matching rules (case-insensitive for
    :class:`CIMultiDict` / :class:`CIMultiDictProxy` sources) and the type
    of the returned container.  The output position of every key is fixed
    by the position of its first occurrence while scanning the sources in
    order.  Conflicting rules for equivalent keys are rejected with
    :exc:`ValueError` before any merging is performed.
    """
    if not isinstance(plan, MergePlan):
        raise TypeError(f"plan must be a MergePlan, got {type(plan).__name__}")
    if not sources:
        raise ValueError("merge_sources() requires at least one source")
    for source in sources:
        if not isinstance(source, MultiMapping):
            raise TypeError(
                "merge_sources() sources must be MultiMapping instances, "
                f"got {type(source).__name__}"
            )

    first = sources[0]
    case_insensitive = isinstance(first, _CI_TYPES)
    canonicalize = _ci_canonical if case_insensitive else str

    # Resolve the declared rules against the container's key rules and
    # reject conflicts *before* any merging happens.
    strategies: dict[str, MergeStrategy] = {}
    for rule_key, strategy in plan.rules.items():
        canonical_key = canonicalize(rule_key)
        previous = strategies.get(canonical_key)
        if previous is not None and previous is not strategy:
            raise ValueError(
                f"conflicting merge rules for key {rule_key!r}: "
                f"{previous.value!r} vs {strategy.value!r}"
            )
        strategies[canonical_key] = strategy
    default = plan.default

    slots: dict[str, _Slot] = {}
    order: list[_Slot] = []
    for source_index, source in enumerate(sources):
        seen_in_source: set[str] = set()
        for key in source:
            canonical_key = canonicalize(key)
            if canonical_key in seen_in_source:
                continue
            seen_in_source.add(canonical_key)
            values = source.getall(key)
            slot = slots.get(canonical_key)
            if slot is None:
                slot = _Slot(key, strategies.get(canonical_key, default))
                slots[canonical_key] = slot
                order.append(slot)
            if slot.strategy is MergeStrategy.REPLACE:
                # Wholesale replacement: every value of the latest source
                # is kept, a multi-value key is never collapsed into one.
                slot.values = [(value, source_index) for value in values]
            elif slot.strategy is MergeStrategy.DEDUP:
                for value in values:
                    if value not in slot.seen_values:
                        slot.seen_values.append(value)
                        slot.values.append((value, source_index))
            else:  # MergeStrategy.APPEND
                slot.values.extend((value, source_index) for value in values)

    out: MultiDict[_V] = CIMultiDict() if case_insensitive else MultiDict()
    sources_report: list[int] = []
    for slot in order:
        for value, source_index in slot.values:
            out.add(slot.key, value)
            sources_report.append(source_index)
    return MergeResult(out, sources_report)
