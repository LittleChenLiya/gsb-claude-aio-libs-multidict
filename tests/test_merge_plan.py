"""Tests for the explicit multi-source merge plan API."""

import pytest

from multidict import (
    CIMultiDict,
    CIMultiDictProxy,
    MergePlan,
    MergeResult,
    MergeStrategy,
    MultiDict,
    MultiDictProxy,
    merge_sources,
)


class TestAppendStrategy:
    def test_append_keeps_all_values_in_source_order(self) -> None:
        # Acceptance: two sources contributing "a" values append as 1, 2, 3.
        first = CIMultiDict([("a", 1), ("a", 2)])
        second = CIMultiDict([("a", 3)])
        plan = MergePlan({"a": MergeStrategy.APPEND})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("a") == [1, 2, 3]
        assert result.sources == [0, 0, 1]

    def test_append_is_the_fixed_default_for_undeclared_keys(self) -> None:
        first = MultiDict([("k", 1)])
        second = MultiDict([("k", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert result.mapping.getall("k") == [1, 2]
        assert result.sources == [0, 1]

    def test_custom_default_strategy(self) -> None:
        first = MultiDict([("k", "old")])
        second = MultiDict([("k", "new")])
        plan = MergePlan(default=MergeStrategy.REPLACE)

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("k") == ["new"]


class TestReplaceStrategy:
    def test_replace_keeps_only_new_source(self) -> None:
        # Acceptance: replacing "b" keeps only the new source's values.
        first = CIMultiDict([("b", "old-1"), ("b", "old-2")])
        second = CIMultiDict([("b", "new")])
        plan = MergePlan({"b": MergeStrategy.REPLACE})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("b") == ["new"]
        assert result.sources == [1]

    def test_replace_does_not_collapse_multi_values(self) -> None:
        # A replacing source with several values replaces wholesale:
        # the key must not be split into a single value.
        first = CIMultiDict([("b", "old")])
        second = CIMultiDict([("b", 1), ("b", 2)])
        plan = MergePlan({"b": MergeStrategy.REPLACE})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("b") == [1, 2]
        assert result.sources == [1, 1]

    def test_replace_without_new_values_keeps_old(self) -> None:
        first = MultiDict([("b", "old")])
        second = MultiDict([("other", 1)])
        plan = MergePlan({"b": MergeStrategy.REPLACE})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("b") == ["old"]
        assert list(result.mapping.items()) == [("b", "old"), ("other", 1)]
        assert result.sources == [0, 1]


class TestDedupStrategy:
    def test_dedup_keeps_first_occurrence_order(self) -> None:
        # Acceptance: stable dedup does not reshuffle first occurrences.
        first = CIMultiDict([("c", 2), ("c", 1), ("c", 2)])
        second = CIMultiDict([("c", 3), ("c", 1)])
        plan = MergePlan({"c": MergeStrategy.DEDUP})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("c") == [2, 1, 3]
        assert result.sources == [0, 0, 1]

    def test_dedup_within_a_single_source(self) -> None:
        source = MultiDict([("c", "x"), ("c", "x"), ("c", "y")])
        plan = MergePlan({"c": MergeStrategy.DEDUP})

        result = merge_sources(plan, source)

        assert result.mapping.getall("c") == ["x", "y"]


class TestKeyMatching:
    def test_case_equivalent_keys_are_grouped(self) -> None:
        # Acceptance: "A" and "a" are the same key for CIMultiDict sources.
        first = CIMultiDict([("A", 1)])
        second = CIMultiDict([("a", 2)])
        plan = MergePlan({"a": MergeStrategy.APPEND})

        result = merge_sources(plan, first, second)

        assert isinstance(result.mapping, CIMultiDict)
        assert list(result.mapping.items()) == [("A", 1), ("A", 2)]
        assert result.mapping.getall("A") == [1, 2]
        assert result.sources == [0, 1]

    def test_case_insensitive_rule_lookup(self) -> None:
        first = CIMultiDict([("KEY", "old")])
        second = CIMultiDict([("key", "new")])
        plan = MergePlan({"Key": MergeStrategy.REPLACE})

        result = merge_sources(plan, first, second)

        assert result.mapping.getall("key") == ["new"]

    def test_case_sensitive_sources_keep_distinct_keys(self) -> None:
        first = MultiDict([("A", 1)])
        second = MultiDict([("a", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert isinstance(result.mapping, MultiDict)
        assert not isinstance(result.mapping, CIMultiDict)
        assert list(result.mapping.items()) == [("A", 1), ("a", 2)]

    def test_proxy_sources(self) -> None:
        first = CIMultiDictProxy(CIMultiDict([("a", 1)]))
        second = CIMultiDictProxy(CIMultiDict([("A", 2)]))

        result = merge_sources(MergePlan(), first, second)

        assert isinstance(result.mapping, CIMultiDict)
        assert result.mapping.getall("a") == [1, 2]

    def test_mixed_case_sensitivity_follows_first_source(self) -> None:
        first = CIMultiDict([("A", 1)])
        second = MultiDict([("a", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert isinstance(result.mapping, CIMultiDict)
        assert result.mapping.getall("a") == [1, 2]


class TestOutputPositions:
    def test_first_source_occurrence_fixes_output_position(self) -> None:
        first = CIMultiDict([("z", 1), ("a", 1)])
        second = CIMultiDict([("m", 1), ("a", 2), ("z", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert list(result.mapping.keys()) == ["z", "z", "a", "a", "m"]
        assert result.sources == [0, 1, 0, 1, 1]

    def test_key_only_in_later_source_appends_at_the_end(self) -> None:
        first = MultiDict([("a", 1)])
        second = MultiDict([("b", 2), ("a", 3)])

        result = merge_sources(MergePlan(), first, second)

        assert list(result.mapping.items()) == [("a", 1), ("a", 3), ("b", 2)]


class TestConflictRejection:
    def test_conflicting_case_equivalent_rules_rejected(self) -> None:
        plan = MergePlan({"x": MergeStrategy.APPEND, "X": MergeStrategy.REPLACE})
        source = CIMultiDict([("x", 1)])

        with pytest.raises(ValueError, match="conflicting merge rules"):
            merge_sources(plan, source)

    def test_conflict_rejected_before_merging_starts(self) -> None:
        plan = MergePlan({"x": "append", "X": "dedup"})
        first = CIMultiDict([("a", 1)])
        second = CIMultiDict([("b", 2)])

        with pytest.raises(ValueError, match="conflicting merge rules"):
            merge_sources(plan, first, second)
        # Inputs are untouched by the rejected merge.
        assert list(first.items()) == [("a", 1)]
        assert list(second.items()) == [("b", 2)]

    def test_equivalent_rules_with_same_strategy_are_accepted(self) -> None:
        plan = MergePlan({"x": MergeStrategy.APPEND, "X": MergeStrategy.APPEND})

        result = merge_sources(plan, CIMultiDict([("x", 1)]))

        assert result.mapping.getall("x") == [1]

    def test_case_sensitive_sources_allow_case_variant_rules(self) -> None:
        plan = MergePlan({"x": MergeStrategy.APPEND, "X": MergeStrategy.REPLACE})

        result = merge_sources(plan, MultiDict([("x", 1), ("X", 2)]))

        assert list(result.mapping.items()) == [("x", 1), ("X", 2)]


class TestResultIndependence:
    def test_result_is_a_fresh_container(self) -> None:
        first = CIMultiDict([("a", 1)])
        second = CIMultiDict([("a", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert result.mapping is not first
        assert result.mapping is not second

    def test_mutating_result_does_not_touch_sources(self) -> None:
        first = CIMultiDict([("a", 1)])
        second = CIMultiDict([("a", 2)])
        result = merge_sources(MergePlan(), first, second)

        result.mapping.add("a", 3)
        result.mapping["b"] = 4

        assert first.getall("a") == [1]
        assert "b" not in first
        assert second.getall("a") == [2]
        assert "b" not in second

    def test_mutating_sources_afterwards_does_not_touch_result(self) -> None:
        first = CIMultiDict([("a", 1)])
        result = merge_sources(MergePlan(), first, CIMultiDict([("a", 2)]))

        first.add("a", 99)
        del first["a"]

        assert result.mapping.getall("a") == [1, 2]

    def test_sources_report_aligns_with_items(self) -> None:
        first = MultiDict([("a", 1), ("b", "x")])
        second = MultiDict([("a", 2)])

        result = merge_sources(MergePlan(), first, second)

        assert len(result.sources) == len(result.mapping)
        assert result.items_with_sources() == [
            ("a", 1, 0),
            ("a", 2, 1),
            ("b", "x", 0),
        ]
        for (_, value), (_, value2, src) in zip(
            result.mapping.items(), result.items_with_sources()
        ):
            assert value == value2
            assert src in (0, 1)


class TestThreeStrategiesExample:
    def test_all_three_strategies_together(self) -> None:
        plan = MergePlan(
            {
                "a": MergeStrategy.APPEND,
                "b": MergeStrategy.REPLACE,
                "c": MergeStrategy.DEDUP,
            }
        )
        first = CIMultiDict(
            [("a", 1), ("a", 2), ("b", "old"), ("c", 1), ("c", 2)]
        )
        second = CIMultiDict([("A", 3), ("B", "new"), ("c", 2), ("c", 3)])

        result = merge_sources(plan, first, second)

        assert list(result.mapping.items()) == [
            ("a", 1),
            ("a", 2),
            ("a", 3),
            ("b", "new"),
            ("c", 1),
            ("c", 2),
            ("c", 3),
        ]
        assert result.sources == [0, 0, 1, 1, 0, 0, 1]


class TestMergePlan:
    def test_rules_and_default_properties(self) -> None:
        plan = MergePlan({"a": "append"}, default="dedup")

        assert plan.rules == {"a": MergeStrategy.APPEND}
        assert plan.default is MergeStrategy.DEDUP

    def test_rules_property_returns_a_copy(self) -> None:
        plan = MergePlan({"a": "append"})

        plan.rules["b"] = MergeStrategy.REPLACE

        assert plan.rules == {"a": MergeStrategy.APPEND}

    def test_default_is_append(self) -> None:
        assert MergePlan().default is MergeStrategy.APPEND

    def test_eq(self) -> None:
        assert MergePlan({"a": "append"}) == MergePlan({"a": MergeStrategy.APPEND})
        assert MergePlan({"a": "append"}) != MergePlan({"a": "dedup"})
        assert MergePlan() != MergePlan(default="replace")
        assert MergePlan() != "not a plan"

    def test_repr(self) -> None:
        plan = MergePlan({"a": MergeStrategy.APPEND})

        assert repr(plan) == (
            "MergePlan({'a': <MergeStrategy.APPEND: 'append'>}, "
            "default=<MergeStrategy.APPEND: 'append'>)"
        )

    def test_non_string_rule_key_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be str"):
            MergePlan({1: "append"})  # type: ignore[dict-item]

    def test_unknown_strategy_rejected(self) -> None:
        with pytest.raises(ValueError):
            MergePlan({"a": "explode"})


class TestMergeResult:
    def test_repr(self) -> None:
        result = merge_sources(MergePlan(), MultiDict([("a", 1)]))

        assert "sources=[0]" in repr(result)


class TestInvalidUsage:
    def test_plan_must_be_a_merge_plan(self) -> None:
        with pytest.raises(TypeError, match="MergePlan"):
            merge_sources({"a": "append"}, MultiDict())  # type: ignore[arg-type]

    def test_at_least_one_source_required(self) -> None:
        with pytest.raises(ValueError, match="at least one source"):
            merge_sources(MergePlan())

    def test_sources_must_be_multi_mappings(self) -> None:
        with pytest.raises(TypeError, match="MultiMapping"):
            merge_sources(MergePlan(), {"a": 1})  # type: ignore[arg-type]

    def test_multidict_proxy_source(self) -> None:
        proxy = MultiDictProxy(MultiDict([("a", 1)]))

        result = merge_sources(MergePlan(), proxy)

        assert isinstance(result.mapping, MultiDict)
        assert result.mapping.getall("a") == [1]
        assert result.sources == [0]
