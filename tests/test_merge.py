"""Tests for the explicit multi-source merge plan.

Directed pytest command (run only this file):

    python -m pytest tests/test_merge.py -v

The three strategies are demonstrated by:

- :func:`test_merge_strategy_append` -- append keeps every value in order.
- :func:`test_merge_strategy_replace` -- replace keeps only the last source.
- :func:`test_merge_strategy_dedup` -- dedup keeps the first occurrence and
  drops later duplicates without changing order.
"""

from __future__ import annotations

from typing import cast

import pytest

from multidict import (
    CIMultiDict,
    MergePlan,
    MergeStrategy,
    MultiDict,
)

# ---------------------------------------------------------------------------
# Three strategy examples
# ---------------------------------------------------------------------------


def test_merge_strategy_append() -> None:
    """Append: every value from every source is kept, in order.

    Two sources each contribute values for ``a``; with append the result is
    ``a=1, a=2, a=3`` -- all three values in source order.
    """
    s1 = MultiDict([("a", 1), ("b", 10)])
    s2 = MultiDict([("a", 2), ("a", 3), ("b", 20)])
    plan = MergePlan([s1, s2], strategies={"a": "append", "b": "append"})
    result = plan.execute()

    assert list(result.md.items()) == [
        ("a", 1),
        ("a", 2),
        ("a", 3),
        ("b", 10),
        ("b", 20),
    ]
    assert result.sources == [0, 1, 1, 0, 1]


def test_merge_strategy_replace() -> None:
    """Replace: only the last source's values are kept.

    ``b`` is replaced, so the earlier value ``10`` is dropped and only the
    new source's ``20`` remains. A multi-value is not split into a single
    value: if the new source has several values for the key, all of them
    are kept.
    """
    s1 = MultiDict([("a", 1), ("b", 10), ("b", 11)])
    s2 = MultiDict([("a", 2), ("b", 20), ("b", 21)])
    plan = MergePlan([s1, s2], strategies={"a": "append", "b": "replace"})
    result = plan.execute()

    assert list(result.md.items()) == [
        ("a", 1),
        ("a", 2),
        ("b", 20),
        ("b", 21),
    ]
    assert result.sources == [0, 1, 1, 1]


def test_merge_strategy_dedup() -> None:
    """Dedup: the first occurrence wins, later duplicates are dropped.

    ``a=2`` appears in both sources; the second occurrence is dropped but
    the first occurrence's position is preserved. The output order is the
    first-occurrence order, unchanged by deduplication.
    """
    s1 = MultiDict([("a", 1), ("a", 2), ("b", 10)])
    s2 = MultiDict([("a", 2), ("a", 3), ("b", 10)])
    plan = MergePlan([s1, s2], strategies={"a": "dedup", "b": "dedup"})
    result = plan.execute()

    assert list(result.md.items()) == [
        ("a", 1),
        ("a", 2),
        ("a", 3),
        ("b", 10),
    ]
    assert result.sources == [0, 0, 1, 0]


# ---------------------------------------------------------------------------
# Acceptance: two a values appended keeping 1,2,3; b replaced
# ---------------------------------------------------------------------------


def test_acceptance_append_a_replace_b() -> None:
    """Two ``a`` values appended keep 1,2,3; ``b`` replaced keeps the new source."""
    s1 = MultiDict([("a", 1), ("b", 2)])
    s2 = MultiDict([("a", 2), ("a", 3), ("b", 4)])
    plan = MergePlan([s1, s2], strategies={"a": "append", "b": "replace"})
    result = plan.execute()

    assert result.md.getall("a") == [1, 2, 3]
    assert result.md.getall("b") == [4]
    assert result.sources == [0, 1, 1, 1]


# ---------------------------------------------------------------------------
# CIMultiDict: case-equivalent keys are correctly grouped
# ---------------------------------------------------------------------------


def test_ci_groups_case_equivalent_keys() -> None:
    """``A`` and ``a`` are the same real key and are grouped together."""
    s1 = CIMultiDict([("A", 1), ("b", 2)])
    s2 = CIMultiDict([("a", 3), ("B", 4)])
    plan = MergePlan([s1, s2], strategies={"A": "append", "b": "replace"})
    result = plan.execute()

    # The real key "a" groups A and a; the output spelling is the first
    # occurrence's ("A").
    assert result.md.getall("a") == [1, 3]
    assert result.md.getall("A") == [1, 3]
    assert result.md.getall("b") == [4]
    assert list(result.md.items()) == [("A", 1), ("A", 3), ("b", 4)]
    assert result.sources == [0, 1, 1]


def test_ci_first_occurrence_position_determines_output_order() -> None:
    """The first source's key occurrence position determines output order."""
    s1 = CIMultiDict([("B", 1), ("a", 2)])
    s2 = CIMultiDict([("A", 3), ("b", 4)])
    plan = MergePlan([s1, s2], default="append")
    result = plan.execute()

    # "B"/"b" are the same real key, as are "a"/"A". The first occurrence
    # of each real key determines its output position: "B" is first (source
    # 1), "a" is second (source 1). Values from source 2 are appended.
    assert list(result.md.items()) == [
        ("B", 1),
        ("B", 4),
        ("a", 2),
        ("a", 3),
    ]
    assert result.sources == [0, 1, 0, 1]


# ---------------------------------------------------------------------------
# Default strategy for undeclared keys
# ---------------------------------------------------------------------------


def test_default_strategy_applies_to_undeclared_keys() -> None:
    """Undeclared keys use the fixed default strategy."""
    s1 = MultiDict([("a", 1), ("c", 2)])
    s2 = MultiDict([("a", 3), ("c", 4)])
    plan = MergePlan([s1, s2], strategies={"a": "append"}, default="replace")
    result = plan.execute()

    # a is declared append; c is undeclared and uses the default (replace).
    assert result.md.getall("a") == [1, 3]
    assert result.md.getall("c") == [4]
    assert result.sources == [0, 1, 1]


def test_default_strategy_defaults_to_append() -> None:
    """When no default is given, undeclared keys are appended."""
    s1 = MultiDict([("a", 1)])
    s2 = MultiDict([("a", 2)])
    plan = MergePlan([s1, s2])
    result = plan.execute()

    assert result.md.getall("a") == [1, 2]
    assert result.sources == [0, 1]


# ---------------------------------------------------------------------------
# Rule conflicts are rejected before execution
# ---------------------------------------------------------------------------


def test_conflicting_strategies_rejected_before_execution() -> None:
    """For CI sources, two strategies that are case-insensitively equal but
    resolve to different strategies are rejected before execution."""
    s1 = CIMultiDict([("A", 1)])
    s2 = CIMultiDict([("a", 2)])
    with pytest.raises(ValueError, match="conflicting merge strategies"):
        MergePlan([s1, s2], strategies={"A": "replace", "a": "append"})


def test_same_strategy_for_case_equivalent_keys_is_allowed() -> None:
    """Two strategy keys that are case-insensitively equal and resolve to
    the same strategy are not a conflict."""
    s1 = CIMultiDict([("A", 1)])
    s2 = CIMultiDict([("a", 2)])
    plan = MergePlan([s1, s2], strategies={"A": "replace", "a": "replace"})
    result = plan.execute()

    assert result.md.getall("a") == [2]


def test_invalid_strategy_rejected() -> None:
    """An invalid strategy value is rejected before execution."""
    s1 = MultiDict([("a", 1)])
    with pytest.raises(ValueError, match="invalid merge strategy"):
        MergePlan([s1], strategies={"a": "bogus"})


def test_invalid_default_rejected() -> None:
    """An invalid default strategy is rejected before execution."""
    s1 = MultiDict([("a", 1)])
    with pytest.raises(ValueError, match="invalid merge strategy"):
        MergePlan([s1], default="bogus")


def test_empty_sources_rejected() -> None:
    """An empty source list is rejected before execution."""
    with pytest.raises(ValueError, match="at least one source"):
        MergePlan([])


# ---------------------------------------------------------------------------
# Result independence
# ---------------------------------------------------------------------------


def test_result_is_independent_of_input_containers() -> None:
    """Modifying the result does not affect the input sources."""
    s1 = MultiDict([("a", 1)])
    s2 = MultiDict([("a", 2)])
    plan = MergePlan([s1, s2], strategies={"a": "append"})
    result = plan.execute()

    # result.md is a fresh container; capture it before mutating.
    merged = cast(MultiDict[int], result.md)
    merged.add("a", 3)
    merged["b"] = 4

    assert list(s1.items()) == [("a", 1)]
    assert list(s2.items()) == [("a", 2)]
    assert merged.getall("a") == [1, 2, 3]
    assert merged.getall("b") == [4]


def test_result_is_a_fresh_container() -> None:
    """The result's container is not the same object as any source."""
    s1 = MultiDict([("a", 1)])
    s2 = MultiDict([("a", 2)])
    plan = MergePlan([s1, s2])
    result = plan.execute()

    assert result.md is not s1
    assert result.md is not s2


# ---------------------------------------------------------------------------
# Source index reporting
# ---------------------------------------------------------------------------


def test_sources_report_each_output_item_origin() -> None:
    """Each output item reports the index of the source it came from."""
    s1 = MultiDict([("a", 1), ("b", 2)])
    s2 = MultiDict([("a", 3), ("b", 4)])
    s3 = MultiDict([("a", 5), ("b", 6)])
    plan = MergePlan(
        [s1, s2, s3],
        strategies={"a": "append", "b": "replace"},
    )
    result = plan.execute()

    # a is appended across all three sources; b is replaced by source 3.
    assert result.md.getall("a") == [1, 3, 5]
    assert result.md.getall("b") == [6]
    assert result.sources == [0, 1, 2, 2]
    assert result.items_with_sources() == [
        ("a", 1, 0),
        ("a", 3, 1),
        ("a", 5, 2),
        ("b", 6, 2),
    ]


def test_sources_match_md_items_order() -> None:
    """The sources list order matches ``md.items()`` order."""
    s1 = MultiDict([("a", 1), ("b", 2)])
    s2 = MultiDict([("a", 3)])
    plan = MergePlan([s1, s2], default="append")
    result = plan.execute()

    items = list(result.md.items())
    assert len(result.sources) == len(items)
    assert len(result.items_with_sources()) == len(items)
    for i in range(len(items)):
        key, value = items[i]
        item_key, item_value, item_source = result.items_with_sources()[i]
        assert key == item_key
        assert value == item_value
        assert result.sources[i] == item_source
        assert isinstance(result.sources[i], int)


# ---------------------------------------------------------------------------
# Strategy enum and string coercion
# ---------------------------------------------------------------------------


def test_merge_strategy_enum_values() -> None:
    """The three strategy enum values are stable strings."""
    assert MergeStrategy.REPLACE.value == "replace"
    assert MergeStrategy.APPEND.value == "append"
    assert MergeStrategy.DEDUP.value == "dedup"


def test_strategy_accepts_enum_and_string() -> None:
    """Both the enum and its string value are accepted."""
    s1 = MultiDict([("a", 1)])
    s2 = MultiDict([("a", 2)])

    plan_enum = MergePlan([s1, s2], strategies={"a": MergeStrategy.APPEND})
    plan_str = MergePlan([s1, s2], strategies={"a": "append"})

    assert plan_enum.execute().md.getall("a") == [1, 2]
    assert plan_str.execute().md.getall("a") == [1, 2]


# ---------------------------------------------------------------------------
# Reusability
# ---------------------------------------------------------------------------


def test_plan_is_reusable() -> None:
    """Executing a plan multiple times returns independent results."""
    s1 = MultiDict([("a", 1)])
    s2 = MultiDict([("a", 2)])
    plan = MergePlan([s1, s2], strategies={"a": "append"})

    r1 = plan.execute()
    r2 = plan.execute()

    assert r1.md is not r2.md
    assert r1.md.getall("a") == [1, 2]
    assert r2.md.getall("a") == [1, 2]
