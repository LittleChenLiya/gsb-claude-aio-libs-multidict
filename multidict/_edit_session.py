"""Independent edit sessions for mutable multidicts.

An edit session records ``add()``, ``setall()`` and ``popall()`` operations
against a private baseline snapshot of a multidict, preserving the relative
order of duplicate values, and applies them to the underlying multidict in a
single commit once the baseline has been re-verified.

The baseline is the full sequence of ``(key, value)`` pairs -- including
every duplicate and the exact key spelling -- so a commit is rejected when
the multidict changed in any way since the session started, even if the
per-key last values still look the same.  A failed :meth:`commit
<MultiDictEditSession.commit>` and :meth:`abort
<MultiDictEditSession.abort>` never modify the underlying multidict.

Log format
----------
The session log (see :attr:`MultiDictEditSession.log`) is a tuple of
immutable :class:`LogEntry` records, one per recorded operation, in the
order the operations were recorded::

    LogEntry(op="add",    key="a", values=(6,))     # session.add("a", 6)
    LogEntry(op="setall", key="a", values=(4, 5))   # session.setall("a", [4, 5])
    LogEntry(op="popall", key="a", values=())       # session.popall("a")

``key`` always keeps the exact spelling the caller passed in, even for
``CIMultiDict`` targets where keys are matched case-insensitively.
``values`` is always a tuple, so mutating a list passed to ``setall()``
after the call cannot leak into the log, and a log snapshot taken after
commit cannot be affected by any later edit.
"""

import enum
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Generic, TypeVar

from ._abc import MutableMultiMapping

__all__ = (
    "EditSessionClosed",
    "EditSessionConflict",
    "EditSessionError",
    "LogEntry",
    "MultiDictEditSession",
)

_V = TypeVar("_V")


class EditSessionError(Exception):
    """Base class for edit session errors."""


class EditSessionConflict(EditSessionError):
    """The underlying multidict changed after the edit session started."""


class EditSessionClosed(EditSessionError):
    """The edit session was already committed or aborted."""


@dataclass(frozen=True)
class LogEntry(Generic[_V]):
    """A single recorded edit operation.

    ``op`` is one of ``"add"``, ``"setall"`` or ``"popall"``; ``key`` is
    the key exactly as spelled by the caller; ``values`` holds a
    one-element tuple for ``"add"``, the replacement values for
    ``"setall"`` and an empty tuple for ``"popall"``.
    """

    op: str
    key: str
    values: tuple[_V, ...]


class _State(enum.Enum):
    ACTIVE = enum.auto()
    COMMITTED = enum.auto()
    ABORTED = enum.auto()


class MultiDictEditSession(Generic[_V]):
    """An independent edit session over a mutable multidict.

    Operations are only recorded (and replayed against a private shadow
    copy of the items) until :meth:`commit` re-verifies the baseline and
    applies the resulting state to the multidict in a single pass.
    """

    def __init__(self, md: MutableMultiMapping[_V]) -> None:
        self._md = md
        # The baseline snapshot keeps every duplicate (key, value) pair in
        # order and with the exact stored key spelling, so the commit-time
        # check cannot be fooled by changes that leave per-key last values
        # untouched.
        self._baseline: tuple[tuple[str, _V], ...] = tuple(md.items())
        self._items: list[tuple[str, _V]] = list(self._baseline)
        self._log: list[LogEntry[_V]] = []
        self._state = _State.ACTIVE
        self._probe_cls = type(md)

    @property
    def log(self) -> tuple[LogEntry[_V], ...]:
        """An immutable snapshot of the operations recorded so far."""
        return tuple(self._log)

    @property
    def state(self) -> str:
        """The session state: ``"ACTIVE"``, ``"COMMITTED"`` or ``"ABORTED"``."""
        return self._state.name

    def _ensure_active(self) -> None:
        if self._state is not _State.ACTIVE:
            raise EditSessionClosed(
                f"edit session is {self._state.name.lower()}, "
                "no further edits are allowed"
            )

    def _matches(self, existing_key: str, key: str) -> bool:
        # Probe a fresh multidict of the same class, so keys are matched
        # with the target's own semantics (case-insensitive for
        # CIMultiDict, case-sensitive otherwise).
        probe = self._probe_cls([(existing_key, None)])
        return key in probe

    def add(self, key: str, value: _V) -> None:
        """Record an ``add`` operation appending ``(key, value)``."""
        self._ensure_active()
        self._log.append(LogEntry("add", key, (value,)))
        self._items.append((key, value))

    def setall(self, key: str, values: Iterable[_V]) -> None:
        """Record a ``setall`` operation replacing all values for *key*.

        The new values keep their relative order and take the position of
        the first occurrence of *key*; if *key* is absent they are
        appended at the end.  *values* is copied, so later mutation of
        the caller's iterable cannot affect the session.
        """
        self._ensure_active()
        new_values = tuple(values)
        self._log.append(LogEntry("setall", key, new_values))
        items: list[tuple[str, _V]] = []
        inserted = False
        for k, v in self._items:
            if self._matches(k, key):
                if not inserted:
                    inserted = True
                    items.extend((key, nv) for nv in new_values)
            else:
                items.append((k, v))
        if not inserted:
            items.extend((key, nv) for nv in new_values)
        self._items = items

    def popall(self, key: str) -> list[_V]:
        """Record a ``popall`` operation removing every value for *key*.

        Returns the values the operation will remove, mirroring
        ``MultiDict.popall``; raises ``KeyError`` if *key* is absent.
        """
        self._ensure_active()
        removed = [v for k, v in self._items if self._matches(k, key)]
        if not removed:
            raise KeyError(f"Key not found: {key!r}")
        self._log.append(LogEntry("popall", key, ()))
        self._items = [(k, v) for k, v in self._items if not self._matches(k, key)]
        return removed

    def commit(self) -> None:
        """Verify the baseline and apply all recorded operations at once.

        Raises :class:`EditSessionConflict` -- leaving the multidict
        untouched -- if it was modified after the session started.  The
        comparison covers the full ordered sequence of ``(key, value)``
        pairs, so duplicate-only changes are never missed.
        """
        self._ensure_active()
        current = tuple(self._md.items())
        if current != self._baseline:
            raise EditSessionConflict(
                "the multidict was modified after the edit session started"
            )
        final = tuple(self._items)
        if final != current:
            lock = getattr(self._md, "_lock", None)
            with lock if lock is not None else nullcontext():
                self._md.clear()
                add = self._md.add
                for k, v in final:
                    add(k, v)
        self._state = _State.COMMITTED

    def abort(self) -> None:
        """Abandon the session; the multidict is never modified."""
        self._ensure_active()
        self._state = _State.ABORTED
