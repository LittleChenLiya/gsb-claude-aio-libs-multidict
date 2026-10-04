"""Tests for MultiDict editing sessions."""

import pytest

from multidict import CIMultiDict, MultiDict
from multidict._multidict_py import BaselineConflict


class TestSessionScenario:
    """Acceptance scenario: setall then add, commit gives established order."""

    def test_setall_then_add_commit(self) -> None:
        md = MultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.setall("a", [4, 5])
        session.add("a", 6)
        session.commit()
        assert list(md.items()) == [("a", 4), ("a", 5), ("a", 6), ("b", 3)]

    def test_baseline_conflict_on_second_value_change(self) -> None:
        md = MultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.setall("a", [4, 5])
        # Change the second 'a' from 2 to 9 during the session
        md["a"] = 9
        with pytest.raises(BaselineConflict):
            session.commit()
        # The session must not have applied any changes
        assert list(md.items()) == [("a", 9), ("b", 3)]


class TestSessionBaseline:
    """Baseline conflict detection, including case-insensitive matching."""

    def test_cimultidict_case_change_conflict(self) -> None:
        md = CIMultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.setall("A", [4, 5])
        # Change the key spelling from 'a' to 'A' during the session
        md["A"] = 9
        with pytest.raises(BaselineConflict):
            session.commit()

    def test_cimultidict_lowercase_spelling_preserved_in_log(self) -> None:
        md = CIMultiDict([("a", 1)])
        session = md.session()
        session.setall("A", [2, 3])
        # The log preserves the caller's original spelling 'A'
        assert session.log == (("setall", "A", (2, 3)),)

    def test_no_change_commit(self) -> None:
        md = MultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.commit()
        assert list(md.items()) == [("a", 1), ("b", 2)]

    def test_commit_after_abandon_raises(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.abandon()
        with pytest.raises(RuntimeError):
            session.commit()

    def test_add_after_commit_raises(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.commit()
        with pytest.raises(RuntimeError):
            session.add("c", 3)


class TestSessionOperations:
    """Individual operation semantics."""

    def test_setall_replaces_all_values(self) -> None:
        md = MultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.setall("a", [4, 5])
        session.commit()
        assert list(md.items()) == [("a", 4), ("a", 5), ("b", 3)]

    def test_setall_with_duplicate_values(self) -> None:
        md = MultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.setall("a", [1, 1, 2])
        session.commit()
        assert list(md.items()) == [("a", 1), ("a", 1), ("a", 2), ("b", 2)]

    def test_setall_empty_removes_key(self) -> None:
        md = MultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.setall("a", [])
        session.commit()
        assert list(md.items()) == [("b", 3)]

    def test_popall_removes_all_values(self) -> None:
        md = MultiDict([("a", 1), ("a", 2), ("b", 3)])
        session = md.session()
        session.popall("a")
        session.commit()
        assert list(md.items()) == [("b", 3)]

    def test_popall_missing_key_no_error(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.popall("z")
        session.commit()
        assert list(md.items()) == [("a", 1)]

    def test_add_new_key_appends(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.commit()
        assert list(md.items()) == [("a", 1), ("b", 2)]

    def test_add_existing_key_inserts_after_last(self) -> None:
        md = MultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.add("a", 3)
        session.commit()
        assert list(md.items()) == [("a", 1), ("a", 3), ("b", 2)]


class TestSessionInputIsolation:
    """Input collections are copied, not referenced."""

    def test_setall_input_list_is_copied(self) -> None:
        values = [4, 5]
        md = MultiDict([("a", 1)])
        session = md.session()
        session.setall("a", values)
        # Mutate the input after recording
        values.append(6)
        values[0] = 99
        session.commit()
        assert list(md.items()) == [("a", 4), ("a", 5)]

    def test_setall_input_tuple_is_copied(self) -> None:
        values = [4, 5]
        md = MultiDict([("a", 1)])
        session = md.session()
        session.setall("a", values)
        session.commit()
        assert session.log[0][2] == (4, 5)
        assert isinstance(session.log[0][2], tuple)


class TestSessionLog:
    """Log format and immutability."""

    def test_log_format(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.setall("c", [3, 4])
        session.popall("a")
        assert session.log == (
            ("add", "b", 2),
            ("setall", "c", (3, 4)),
            ("popall", "a"),
        )

    def test_log_is_read_only_tuple(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        log = session.log
        assert isinstance(log, tuple)
        with pytest.raises(TypeError):
            log[0] = ("add", "x", 9)  # type: ignore[index]

    def test_log_after_commit_not_affected_by_subsequent_edits(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.commit()
        log_after_commit = session.log
        # The log is frozen; subsequent edits cannot change it
        assert log_after_commit == (("add", "b", 2),)
        assert session.log is log_after_commit

    def test_log_after_abandon_shows_recorded_operations(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.abandon()
        assert session.log == (("add", "b", 2),)

    def test_abandon_does_not_modify_original(self) -> None:
        md = MultiDict([("a", 1)])
        session = md.session()
        session.add("b", 2)
        session.setall("a", [9])
        session.abandon()
        assert list(md.items()) == [("a", 1)]


class TestSessionCIMultiDict:
    """CIMultiDict-specific behavior."""

    def test_setall_case_insensitive_matching(self) -> None:
        md = CIMultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.setall("A", [3, 4])
        session.commit()
        assert list(md.items()) == [("A", 3), ("A", 4), ("b", 2)]

    def test_add_case_insensitive_matching(self) -> None:
        md = CIMultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.add("A", 3)
        session.commit()
        assert list(md.items()) == [("a", 1), ("A", 3), ("b", 2)]

    def test_popall_case_insensitive_matching(self) -> None:
        md = CIMultiDict([("a", 1), ("b", 2)])
        session = md.session()
        session.popall("A")
        session.commit()
        assert list(md.items()) == [("b", 2)]
