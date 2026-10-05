"""Explicit multi-source merge plan.

A :class:`MergePlan` merges several :class:`~multidict.MultiDict` sources into
a single result. Each key can be merged with one of three strategies:

- :data:`MergeStrategy.REPLACE` -- keep only the values from the last source
  that defines the key (earlier sources are discarded).
- :data:`MergeStrategy.APPEND` -- keep all values from all sources, in order.
- :data:`MergeStrategy.DEDUP` -- like :data:`MergeStrategy.APPEND`, but skip
  duplicate values (the first occurrence wins, order is preserved).

Keys not listed in the plan use the fixed :attr:`~MergePlan.default` strategy.

When the sources are :class:`~multidict.CIMultiDict` instances, keys are
matched by their *real* (case-folded) identity: ``"A"`` and ``"a"`` are the
same key. The position of the first occurrence of a real key across the
sources determines its position in the output. The result is a fresh
container, independent of the input sources, and each output item reports the
index of the source it came from.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, cast

from ._abc import MultiMapping

_V = TypeVar("_V")

__all__ = ("MergeItem", "MergePlan", "MergeResult", "MergeStrategy")


def _ci_classes() -> tuple[type[Any], type[Any]]:
    """Return the active ``(CIMultiDict, MultiDict)`` classes.

    Imported lazily so the plan uses the same implementation (pure Python or
    C extension) as the public API, and to avoid a circular import.
    """
    # Imported lazily to avoid a circular import: multidict/__init__.py
    # imports this module, and this module needs the public
    # CIMultiDict/MultiDict classes.
    from multidict import CIMultiDict, MultiDict  # noqa: PLC0415

    return CIMultiDict, MultiDict


class MergeStrategy(str, Enum):
    """Strategy for merging a key across sources.

    - :data:`REPLACE`: keep only the values from the last source that has
      the key.
    - :data:`APPEND`: keep all values from all sources, in order.
    - :data:`DEDUP`: like :data:`APPEND`, but skip duplicate values (first
      occurrence wins).
    """

    REPLACE = "replace"
    APPEND = "append"
    DEDUP = "dedup"


def _coerce_strategy(value: MergeStrategy | str) -> MergeStrategy:
    """Coerce *value* to a :class:`MergeStrategy`.

    Raises :class:`ValueError` if *value* is not a valid strategy.
    """
    if isinstance(value, MergeStrategy):
        return value
    if isinstance(value, str):
        try:
            return MergeStrategy(value)
        except ValueError:
            pass
    raise ValueError(f"invalid merge strategy: {value!r}")


# A stateless CIMultiDict used to bind the _key/_identity helpers, which do
# not depend on instance state.
_CI_HELPER: Any = None


def _get_ci_helper() -> Any:
    global _CI_HELPER
    if _CI_HELPER is None:
        _CI_HELPER = _ci_classes()[0]()
    return _CI_HELPER


def _ci_identity(key: str) -> str:
    """Return the real (case-folded) identity of *key* for CI matching."""
    return _get_ci_helper()._identity(key)  # type: ignore[no-any-return]


def _ci_key(key: str) -> str:
    """Return the output spelling of *key* for CI sources."""
    return _get_ci_helper()._key(key)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class MergeItem(Generic[_V]):
    """A single output item with the index of the source it came from.

    Attributes:
        key: The output key (the first occurrence's spelling).
        value: The output value.
        source: The index of the source this item came from.
    """

    key: str
    value: _V
    source: int


class MergeResult(Generic[_V]):
    """The result of executing a :class:`MergePlan`.

    Holds the merged multidict and, for each output item, the index of the
    source it came from.
    """

    def __init__(self, items: list[MergeItem[_V]], ci: bool) -> None:
        self._items = items
        self._ci = ci

    @property
    def ci(self) -> bool:
        """Whether the result uses case-insensitive key matching."""
        return self._ci

    @property
    def md(self) -> MultiMapping[_V]:
        """The merged multidict.

        A fresh container, independent of the input sources. For CI sources
        it is a :class:`~multidict.CIMultiDict`, otherwise a
        :class:`~multidict.MultiDict`.
        """
        cls = _ci_classes()[0] if self._ci else _ci_classes()[1]
        return cast(
            MultiMapping[_V],
            cls((item.key, item.value) for item in self._items),
        )

    @property
    def sources(self) -> list[int]:
        """Return the source index for each output item.

        The order matches :meth:`md.items() <multidict.MultiDict.items>`.
        """
        return [item.source for item in self._items]

    def items_with_sources(self) -> list[tuple[str, _V, int]]:
        """Return ``(key, value, source_index)`` for each output item."""
        return [(item.key, item.value, item.source) for item in self._items]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[MergeItem[_V]]:
        return iter(self._items)

    def __repr__(self) -> str:
        return f"MergeResult(ci={self._ci}, items={self._items!r})"


class _Entry(Generic[_V]):
    """Accumulated state for a single real key during merging."""

    __slots__ = ("position", "out_key", "values")

    def __init__(self, position: int, out_key: str) -> None:
        self.position: int = position
        self.out_key: str = out_key
        self.values: list[tuple[_V, int]] = []


class MergePlan(Generic[_V]):
    """An explicit multi-source merge plan.

    Args:
        sources: The multidict sources to merge, in order.
        strategies: A mapping of key to :class:`MergeStrategy` (or its string
            value). Keys not listed here use :attr:`default`.
        default: The strategy for keys not listed in *strategies*. Defaults
            to :data:`MergeStrategy.APPEND`.

    Raises:
        ValueError: If *sources* is empty, if a strategy is invalid, or (for
            :class:`~multidict.CIMultiDict` sources) if two strategy keys
            that are case-insensitively equal resolve to different
            strategies.
    """

    def __init__(
        self,
        sources: Sequence[MultiMapping[_V]],
        strategies: Mapping[str, MergeStrategy | str] | None = None,
        *,
        default: MergeStrategy | str = MergeStrategy.APPEND,
    ) -> None:
        if not sources:
            raise ValueError("merge plan requires at least one source")

        self._sources: list[MultiMapping[_V]] = list(sources)
        # CI matching applies when every source is a CIMultiDict. Otherwise
        # the plan is case-sensitive.
        ci_cls = _ci_classes()[0]
        self._ci: bool = all(isinstance(s, ci_cls) for s in self._sources)

        # Coerce and validate the default strategy before anything else.
        self._default: MergeStrategy = _coerce_strategy(default)

        # Coerce and validate per-key strategies.
        coerced: dict[str, MergeStrategy] = {}
        if strategies is not None:
            for key, strategy in strategies.items():
                coerced[key] = _coerce_strategy(strategy)

        # Reject rule conflicts before execution: for CI sources, two
        # strategy keys that are case-insensitively equal must not resolve
        # to different strategies.
        if self._ci:
            seen: dict[str, MergeStrategy] = {}
            for key, strategy in coerced.items():
                real = _ci_identity(key)
                if real in seen and seen[real] != strategy:
                    raise ValueError(
                        f"conflicting merge strategies for key {key!r}: "
                        f"{seen[real].value} vs {strategy.value}"
                    )
                seen[real] = strategy

        self._strategies: Mapping[str, MergeStrategy] = coerced

    @property
    def ci(self) -> bool:
        """Whether the plan uses case-insensitive key matching."""
        return self._ci

    @property
    def default(self) -> MergeStrategy:
        """The strategy used for keys not listed in :attr:`strategies`."""
        return self._default

    @property
    def strategies(self) -> Mapping[str, MergeStrategy]:
        """The per-key strategies."""
        return self._strategies

    def _strategy_for(self, key: str) -> MergeStrategy:
        if self._ci:
            real = _ci_identity(key)
            for k, s in self._strategies.items():
                if _ci_identity(k) == real:
                    return s
            return self._default
        return self._strategies.get(key, self._default)

    def execute(self) -> MergeResult[_V]:
        """Execute the plan and return a :class:`MergeResult`.

        The result is a fresh container, independent of the input sources.
        """
        # real key -> accumulated entry
        entries: dict[str, _Entry[_V]] = {}
        position = 0

        for source_idx, source in enumerate(self._sources):
            # Within a source, each real key is processed once (a CIMultiDict
            # may yield the same real key under several spellings).
            seen_in_source: set[str] = set()
            for key in source.keys():
                real = _ci_identity(key) if self._ci else key
                if real in seen_in_source:
                    continue
                seen_in_source.add(real)

                values = source.getall(key)
                strategy = self._strategy_for(key)

                if real not in entries:
                    out_key = _ci_key(key) if self._ci else key
                    entries[real] = _Entry(position, out_key)
                    position += 1

                entry = entries[real]
                if strategy is MergeStrategy.REPLACE:
                    # Replace the key's values with *all* values from this
                    # source; a multi-value stays multi-valued.
                    entry.values[:] = [(v, source_idx) for v in values]
                elif strategy is MergeStrategy.APPEND:
                    entry.values.extend((v, source_idx) for v in values)
                else:  # DEDUP
                    for v in values:
                        if not any(existing == v for existing, _ in entry.values):
                            entry.values.append((v, source_idx))

        # Build the output items in first-occurrence position order.
        ordered = sorted(entries.values(), key=lambda e: e.position)
        items: list[MergeItem[_V]] = []
        for entry in ordered:
            for value, source_idx in entry.values:
                items.append(MergeItem(entry.out_key, value, source_idx))

        return MergeResult(items, self._ci)
