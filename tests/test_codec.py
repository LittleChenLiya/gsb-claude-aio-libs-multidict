"""Tests for the binary string-multidict codec (``multidict._codec``)."""

from __future__ import annotations

from types import ModuleType

import pytest

import multidict
from multidict import CIMultiDict, MultiDict
from multidict._codec import (
    CodecError,
    MultiDictDecoder,
    dumps,
    loads,
)

_KIND_MULTIDICT = 0x01
_KIND_CIMULTIDICT = 0x02


def _header(kind: int, count: int) -> bytes:
    return b"MD" + bytes([1, kind]) + count.to_bytes(4, "big")


def _feed_chunks(data: bytes, sizes: tuple[int, ...]) -> MultiDictDecoder:
    decoder = MultiDictDecoder()
    pos = 0
    idx = 0
    while pos < len(data):
        size = sizes[idx % len(sizes)]
        decoder.feed(data[pos : pos + size])
        pos += size
        idx += 1
    return decoder


class TestRoundTrip:
    def test_duplicate_case_variants_case_sensitive(
        self, case_sensitive_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = case_sensitive_multidict_class([("a", "1"), ("A", "2"), ("a", "3")])
        restored = loads(dumps(md))
        assert isinstance(restored, multidict.MultiDict)
        assert not isinstance(restored, multidict.CIMultiDict)
        assert list(restored.items()) == [("a", "1"), ("A", "2"), ("a", "3")]
        assert restored.getall("a") == ["1", "3"]
        assert restored.getall("A") == ["2"]

    def test_duplicate_case_variants_case_insensitive(
        self, case_insensitive_multidict_class: type[CIMultiDict[str]]
    ) -> None:
        md = case_insensitive_multidict_class([("a", "1"), ("A", "2"), ("a", "3")])
        restored = loads(dumps(md))
        assert isinstance(restored, multidict.CIMultiDict)
        # Duplicates collapse case-insensitively, order of occurrence kept.
        assert restored.getall("a") == ["1", "2", "3"]
        assert restored.getall("A") == ["1", "2", "3"]
        # Original key spelling is preserved.
        assert list(restored.keys()) == ["a", "A", "a"]
        assert list(restored.items()) == [("a", "1"), ("A", "2"), ("a", "3")]

    def test_kind_preserved(
        self,
        any_multidict_class: type[MultiDict[str]],
        any_multidict_class_name: str,
    ) -> None:
        # ``loads`` always builds the package-level classes, regardless of
        # which backend supplied the encoded instance.
        expected = {
            "MultiDict": multidict.MultiDict,
            "CIMultiDict": multidict.CIMultiDict,
        }[any_multidict_class_name]
        restored = loads(dumps(any_multidict_class([("k", "v")])))
        assert type(restored) is expected

    def test_empty_dict(
        self,
        any_multidict_class: type[MultiDict[str]],
        any_multidict_class_name: str,
    ) -> None:
        expected = {
            "MultiDict": multidict.MultiDict,
            "CIMultiDict": multidict.CIMultiDict,
        }[any_multidict_class_name]
        restored = loads(dumps(any_multidict_class()))
        assert len(restored) == 0
        assert type(restored) is expected

    def test_empty_key_and_empty_value(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("", "v"), ("k", ""), ("", "")])
        restored = loads(dumps(md))
        assert list(restored.items()) == [("", "v"), ("k", ""), ("", "")]
        assert restored.getall("") == ["v", ""]

    def test_non_ascii_round_trip(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("ключ", "значение"), ("键", "值")])
        restored = loads(dumps(md))
        assert list(restored.items()) == [("ключ", "значение"), ("键", "值")]


class TestIncrementalDecoding:
    def test_byte_by_byte_matches_one_shot(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("a", "1"), ("A", "2"), ("", "empty-key"), ("k", "")])
        blob = dumps(md)
        expected = loads(blob)

        decoder = MultiDictDecoder()
        for offset, byte in enumerate(blob):
            assert not decoder.done, f"done too early at byte {offset}"
            decoder.feed(bytes([byte]))
        assert decoder.done
        assert list(decoder.result().items()) == list(expected.items())

    def test_arbitrary_chunk_sizes(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("a", "1"), ("A", "2"), ("a", "3")])
        blob = dumps(md)
        decoder = _feed_chunks(blob, sizes=(1, 2, 3, 5, 7, 11, 13))
        assert decoder.done
        assert list(decoder.finalize().items()) == [("a", "1"), ("A", "2"), ("a", "3")]

    def test_single_feed(self, any_multidict_class: type[MultiDict[str]]) -> None:
        md = any_multidict_class([("x", "y")])
        decoder = MultiDictDecoder()
        decoder.feed(dumps(md))
        assert decoder.done
        assert list(decoder.result().items()) == [("x", "y")]

    def test_result_before_completion_raises(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        blob = dumps(any_multidict_class([("x", "y")]))
        decoder = MultiDictDecoder()
        decoder.feed(blob[:-1])
        assert not decoder.done
        with pytest.raises(CodecError, match="incomplete"):
            decoder.result()

    def test_feed_after_completion_raises(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        decoder = MultiDictDecoder()
        decoder.feed(dumps(any_multidict_class([("x", "y")])))
        assert decoder.done
        with pytest.raises(CodecError, match="trailing data"):
            decoder.feed(b"x")

    def test_feed_non_bytes_raises(self) -> None:
        decoder = MultiDictDecoder()
        with pytest.raises(TypeError, match="bytes-like"):
            decoder.feed("MD")  # type: ignore[arg-type]

    def test_decoder_accepts_bytearray_and_memoryview(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        blob = dumps(any_multidict_class([("x", "y")]))
        decoder = MultiDictDecoder()
        decoder.feed(bytearray(blob[:3]))
        decoder.feed(memoryview(blob)[3:])
        assert decoder.done
        assert list(decoder.result().items()) == [("x", "y")]


class TestDeclaredLengthLimits:
    def test_oversized_item_count_rejected_immediately(self) -> None:
        decoder = MultiDictDecoder(max_items=10)
        with pytest.raises(CodecError, match="item count 11"):
            decoder.feed(_header(_KIND_MULTIDICT, 11))
        assert not decoder.done

    def test_huge_item_count_rejected_by_loads(self) -> None:
        with pytest.raises(CodecError, match="exceeds the limit"):
            loads(_header(_KIND_MULTIDICT, 0xFFFFFFFF))

    def test_oversized_key_length_rejected_before_payload(self) -> None:
        decoder = MultiDictDecoder(max_field_length=8)
        decoder.feed(_header(_KIND_MULTIDICT, 1))
        # Only the 4-byte length field arrives; the payload never does.
        with pytest.raises(CodecError, match="key length 1000000"):
            decoder.feed((1_000_000).to_bytes(4, "big"))

    def test_oversized_value_length_rejected_before_payload(self) -> None:
        decoder = MultiDictDecoder(max_field_length=8)
        decoder.feed(_header(_KIND_MULTIDICT, 1))
        decoder.feed((1).to_bytes(4, "big") + b"k")
        with pytest.raises(CodecError, match="value length 1000000"):
            decoder.feed((1_000_000).to_bytes(4, "big"))

    def test_oversized_declared_length_in_one_shot(self) -> None:
        blob = _header(_KIND_MULTIDICT, 1) + (10**9).to_bytes(4, "big")
        with pytest.raises(CodecError, match="exceeds the limit"):
            loads(blob, max_field_length=1024)

    def test_forged_frame_never_completes(self) -> None:
        # A lying length field must not make the decoder wait for (or
        # deliver) gigabytes of payload: it fails on the spot.
        decoder = MultiDictDecoder(max_field_length=16)
        with pytest.raises(CodecError):
            decoder.feed(_header(_KIND_CIMULTIDICT, 1) + (2**31).to_bytes(4, "big"))
        assert not decoder.done


class TestTruncation:
    @pytest.fixture(params=(1, 2, 4, 7, 8, 9, 12, 20), ids=lambda n: f"cut@{n}")
    def cut(self, request: pytest.FixtureRequest) -> int:
        return request.param  # type: ignore[no-any-return]

    def test_truncated_stream_never_delivers(
        self, any_multidict_class: type[MultiDict[str]], cut: int
    ) -> None:
        md = any_multidict_class([("alpha", "1"), ("A", "2"), ("beta", "3")])
        blob = dumps(md)
        decoder = MultiDictDecoder()
        decoder.feed(blob[:cut])
        assert not decoder.done
        with pytest.raises(CodecError, match="incomplete"):
            decoder.result()
        with pytest.raises(CodecError, match="truncated"):
            decoder.finalize()

    def test_loads_rejects_truncated_frame(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        blob = dumps(any_multidict_class([("alpha", "1"), ("beta", "2")]))
        with pytest.raises(CodecError, match="truncated"):
            loads(blob[:-1])

    def test_loads_rejects_empty_input(self) -> None:
        with pytest.raises(CodecError, match="truncated"):
            loads(b"")


class TestStrictEncoding:
    @pytest.mark.parametrize("bad_value", [1, None, b"bytes", 1.5, ("t",), object()])
    def test_non_string_value_rejected(
        self, any_multidict_class: type[MultiDict[object]], bad_value: object
    ) -> None:
        md = any_multidict_class([("key", "ok")])
        md.add("key2", bad_value)
        with pytest.raises(TypeError, match="str values"):
            dumps(md)

    def test_non_string_key_rejected(
        self, case_sensitive_multidict_class: type[MultiDict[str]]
    ) -> None:
        class SneakyMultiDict(
            case_sensitive_multidict_class,  # type: ignore[valid-type,misc]
        ):
            def items(self) -> list[tuple[int, str]]:
                return [(42, "value")]

        with pytest.raises(TypeError, match="str keys"):
            dumps(SneakyMultiDict())

    def test_non_multidict_rejected(self) -> None:
        with pytest.raises(TypeError, match="requires a MultiDict"):
            dumps({"a": "1"})  # type: ignore[arg-type]

    def test_too_many_items_rejected(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("k", "v")] * 5)
        with pytest.raises(CodecError, match="exceed the limit"):
            dumps(md, max_items=4)

    def test_oversized_key_rejected(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("k" * 100, "v")])
        with pytest.raises(CodecError, match="key is 100"):
            dumps(md, max_field_length=16)

    def test_oversized_value_rejected(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        md = any_multidict_class([("k", "v" * 100)])
        with pytest.raises(CodecError, match="value is 100"):
            dumps(md, max_field_length=16)

    def test_proxy_round_trip(
        self,
        any_multidict_class: type[MultiDict[str]],
        multidict_module: ModuleType,
    ) -> None:
        proxy_class = getattr(multidict_module, any_multidict_class.__name__ + "Proxy")
        md = any_multidict_class([("a", "1"), ("A", "2")])
        restored = loads(dumps(proxy_class(md)))
        assert list(restored.items()) == [("a", "1"), ("A", "2")]


class TestProtocolViolations:
    def test_bad_magic(self) -> None:
        with pytest.raises(CodecError, match="bad magic"):
            loads(b"XX" + bytes([1, 1]) + (0).to_bytes(4, "big"))

    def test_bad_version(self) -> None:
        with pytest.raises(CodecError, match="version"):
            loads(b"MD" + bytes([2, 1]) + (0).to_bytes(4, "big"))

    def test_bad_kind(self) -> None:
        with pytest.raises(CodecError, match="kind"):
            loads(b"MD" + bytes([1, 9]) + (0).to_bytes(4, "big"))

    def test_trailing_garbage_rejected(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        blob = dumps(any_multidict_class([("k", "v")]))
        with pytest.raises(CodecError, match="trailing data"):
            loads(blob + b"x")

    def test_invalid_utf8_key_rejected(self) -> None:
        blob = (
            _header(_KIND_MULTIDICT, 1)
            + (1).to_bytes(4, "big")
            + b"\xff"
            + (1).to_bytes(4, "big")
            + b"v"
        )
        with pytest.raises(CodecError, match="UTF-8"):
            loads(blob)

    def test_invalid_utf8_value_rejected(self) -> None:
        blob = (
            _header(_KIND_MULTIDICT, 1)
            + (1).to_bytes(4, "big")
            + b"k"
            + (2).to_bytes(4, "big")
            + b"\xc0\xaf"
        )
        with pytest.raises(CodecError, match="UTF-8"):
            loads(blob)

    def test_header_fields_explicit(
        self, any_multidict_class: type[MultiDict[str]]
    ) -> None:
        blob = dumps(any_multidict_class([("ab", "cd")]))
        assert blob[:2] == b"MD"
        assert blob[2] == 1  # protocol version
        assert blob[3] in (_KIND_MULTIDICT, _KIND_CIMULTIDICT)
        assert int.from_bytes(blob[4:8], "big") == 1  # item count
        assert int.from_bytes(blob[8:12], "big") == 2  # key length in bytes
        assert blob[12:14] == b"ab"
        assert int.from_bytes(blob[14:18], "big") == 2  # value length
        assert blob[18:20] == b"cd"
        assert len(blob) == 20
