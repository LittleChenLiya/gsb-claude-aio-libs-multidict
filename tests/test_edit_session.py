"""Tests for multidict edit sessions (pure Python backend)."""

import dataclasses

import pytest

from multidict._edit_session import (
    EditSessionClosed,
    EditSessionConflict,
    EditSessionError,
    LogEntry,
    MultiDictEditSession,
)
from multidict._multidict_py import CIMultiDict, MultiDict, getversion


@pytest.fixture
def md() -> MultiDict[int]:
    return MultiDict([("a", 1), ("a", 2), ("b", 3)])


def test_commit_preserves_relative_order(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    session.setall("a", [4, 5])
    session.add("a", 6)
    session.commit()
    assert list(md.items()) == [("a", 4), ("a", 5), ("b", 3), ("a", 6)]
    assert md.getall("a") == [4, 5, 6]
    assert session.state == "COMMITTED"


def test_popall_removes_all_values(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    assert session.popall("a") == [1, 2]
    session.commit()
    assert list(md.items()) == [("b", 3)]


def test_popall_missing_key_raises(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    with pytest.raises(KeyError):
        session.popall("missing")
    assert session.log == ()


def test_setall_appends_absent_key(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    session.setall("c", [7, 8])
    session.commit()
    assert list(md.items()) == [("a", 1), ("a", 2), ("b", 3), ("c", 7), ("c", 8)]


def test_log_format(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    session.setall("a", [4, 5])
    session.add("a", 6)
    session.popall("b")
    assert session.log == (
        LogEntry(op="setall", key="a", values=(4, 5)),
        LogEntry(op="add", key="a", values=(6,)),
        LogEntry(op="popall", key="b", values=()),
    )


def test_no_change_commit(md: MultiDict[int]) -> None:
    version = getversion(md)
    session = MultiDictEditSession(md)
    session.commit()
    assert list(md.items()) == [("a", 1), ("a", 2), ("b", 3)]
    assert session.log == ()
    # A no-op commit must not touch the multidict at all.
    assert getversion(md) == version


def test_duplicate_values(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    session.setall("a", [7, 7])
    session.add("a", 7)
    session.commit()
    assert md.getall("a") == [7, 7, 7]
    assert list(md.items()) == [("a", 7), ("a", 7), ("b", 3), ("a", 7)]


def test_input_isolation(md: MultiDict[int]) -> None:
    values = [4, 5]
    session = MultiDictEditSession(md)
    session.setall("a", values)
    values.append(999)
    values[0] = -1
    assert session.log[0].values == (4, 5)
    session.commit()
    assert md.getall("a") == [4, 5]


def test_baseline_conflict_on_second_duplicate_change(
    md: MultiDict[int],
) -> None:
    session = MultiDictEditSession(md)
    session.add("c", 4)
    # Externally rewrite the duplicates so the second "a" becomes 9.
    md.popall("a")
    md.add("a", 1)
    md.add("a", 9)
    with pytest.raises(EditSessionConflict):
        session.commit()
    # The failed commit applied nothing, the external state is kept.
    assert list(md.items()) == [("b", 3), ("a", 1), ("a", 9)]
    assert "c" not in md


def test_baseline_conflict_not_masked_by_last_values(
    md: MultiDict[int],
) -> None:
    session = MultiDictEditSession(md)
    session.add("c", 4)
    # Drop a duplicate while keeping every per-key last value identical
    # to the baseline ({a: 2, b: 3}); a last-value-only check would pass.
    md.popall("a")
    md.add("a", 2)
    with pytest.raises(EditSessionConflict):
        session.commit()
    assert list(md.items()) == [("b", 3), ("a", 2)]
    assert "c" not in md


def test_conflict_is_an_edit_session_error(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    md["b"] = 30
    with pytest.raises(EditSessionError):
        session.commit()


def test_failed_commit_leaves_session_active(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    md["b"] = 30
    with pytest.raises(EditSessionConflict):
        session.commit()
    assert session.state == "ACTIVE"


def test_abort_discards_everything(md: MultiDict[int]) -> None:
    version = getversion(md)
    session = MultiDictEditSession(md)
    session.setall("a", [4, 5])
    session.add("c", 6)
    session.abort()
    assert list(md.items()) == [("a", 1), ("a", 2), ("b", 3)]
    assert getversion(md) == version
    assert session.state == "ABORTED"
    with pytest.raises(EditSessionClosed):
        session.add("d", 7)
    with pytest.raises(EditSessionClosed):
        session.commit()
    with pytest.raises(EditSessionClosed):
        session.abort()


def test_committed_log_is_read_only_and_stable(md: MultiDict[int]) -> None:
    session = MultiDictEditSession(md)
    session.setall("a", [4, 5])
    session.add("a", 6)
    session.commit()
    committed_log = session.log
    assert isinstance(committed_log, tuple)
    assert committed_log == (
        LogEntry(op="setall", key="a", values=(4, 5)),
        LogEntry(op="add", key="a", values=(6,)),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        committed_log[0].op = "popall"  # type: ignore[misc]
    with pytest.raises(TypeError):
        committed_log[0] = LogEntry(op="popall", key="a", values=())  # type: ignore[index]
    # Later edits of the multidict cannot affect the committed log.
    md.add("z", 9)
    md.popall("a")
    assert session.log == committed_log
    # The session itself is closed for further edits.
    with pytest.raises(EditSessionClosed):
        session.add("x", 1)
    with pytest.raises(EditSessionClosed):
        session.commit()


def test_ci_case_insensitive_matching() -> None:
    ci = CIMultiDict([("Key", 1), ("Key", 2), ("b", 3)])
    session = MultiDictEditSession(ci)
    session.setall("KEY", [4, 5])
    session.add("kEy", 6)
    session.popall("B")
    session.commit()
    assert ci.getall("key") == [4, 5, 6]
    assert "b" not in ci
    assert list(ci.items()) == [("KEY", 4), ("KEY", 5), ("kEy", 6)]


def test_ci_log_keeps_caller_spelling() -> None:
    ci = CIMultiDict([("key", 1)])
    session = MultiDictEditSession(ci)
    session.setall("KEY", [2])
    session.add("kEy", 3)
    session.popall("KeY")
    assert [entry.key for entry in session.log] == ["KEY", "kEy", "KeY"]


def test_ci_baseline_checks_key_spelling() -> None:
    ci = CIMultiDict([("a", 1), ("b", 2)])
    session = MultiDictEditSession(ci)
    session.add("c", 3)
    # Externally re-spell "a" as "A": values match case-insensitively,
    # but the baseline check must still flag the change.
    del ci["a"]
    ci.add("A", 1)
    with pytest.raises(EditSessionConflict):
        session.commit()
    assert list(ci.items()) == [("b", 2), ("A", 1)]
    assert "c" not in ci


def test_ci_baseline_conflict_on_duplicate_change() -> None:
    ci = CIMultiDict([("a", 1), ("a", 2), ("b", 3)])
    session = MultiDictEditSession(ci)
    session.add("c", 4)
    # Externally change the second "a" to 9 (mixed-case spelling).
    ci.popall("A")
    ci.add("a", 1)
    ci.add("A", 9)
    with pytest.raises(EditSessionConflict):
        session.commit()
    assert ci.getall("a") == [1, 9]
    assert "c" not in ci
