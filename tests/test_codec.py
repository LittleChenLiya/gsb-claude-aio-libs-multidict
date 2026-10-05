"""Tests for the string MultiDict codec."""

from __future__ import annotations

import pytest

from multidict import CIMultiDict, MultiDict
from multidict.codec import (
    CATEGORY_CIMULTIDICT,
    CATEGORY_MULTIDICT,
    DEFAULT_MAX_ITEMS,
    MAGIC,
    VERSION,
    CodecError,
    Decoder,
    IncompletePacketError,
    InvalidPacketError,
    LimitExceededError,
    _encode_varint,
    decode,
    encode,
)


class TestEncodeDecode:
    """Round-trip tests for both dictionary categories."""

    def test_multidict_round_trip(self) -> None:
        md = MultiDict([("a", "1"), ("b", "2"), ("a", "3")])
        data = encode(md)
        result = decode(data)
        assert result == md
        assert isinstance(result, MultiDict)

    def test_cimultidict_round_trip(self) -> None:
        md = CIMultiDict()
        md.add("A", "1")
        md.add("a", "2")
        md.add("B", "3")
        data = encode(md)
        result = decode(data)
        assert isinstance(result, CIMultiDict)
        # Original key spelling must be preserved.
        assert list(result.items()) == [("A", "1"), ("a", "2"), ("B", "3")]

    def test_duplicate_keys_preserved(self) -> None:
        md = MultiDict()
        md.add("a", "1")
        md.add("a", "2")
        md.add("a", "3")
        data = encode(md)
        result = decode(data)
        assert result.getall("a") == ["1", "2", "3"]

    def test_empty_key(self) -> None:
        md = MultiDict([("", "empty_key"), ("normal", "value")])
        data = encode(md)
        result = decode(data)
        assert list(result.items()) == [("", "empty_key"), ("normal", "value")]

    def test_empty_value(self) -> None:
        md = MultiDict([("key", "")])
        data = encode(md)
        result = decode(data)
        assert result["key"] == ""

    def test_empty_dict(self) -> None:
        md = MultiDict()
        data = encode(md)
        result = decode(data)
        assert len(result) == 0

    def test_unicode(self) -> None:
        md = MultiDict([("ключ", "значение"), ("🔑", "🌍")])
        data = encode(md)
        result = decode(data)
        assert list(result.items()) == [("ключ", "значение"), ("🔑", "🌍")]

    def test_non_string_value_rejected(self) -> None:
        with pytest.raises(TypeError, match="values must be str"):
            encode(MultiDict([("a", 1)]))  # type: ignore[list-item]

    def test_encode_rejects_non_multidict(self) -> None:
        with pytest.raises(TypeError, match="expected MultiDict"):
            encode({"a": "1"})  # type: ignore[arg-type]


class TestStreamingDecoder:
    """Tests for the streaming byte-at-a-time decoder."""

    def test_byte_by_byte(self) -> None:
        md = MultiDict([("a", "1"), ("b", "2"), ("a", "3")])
        data = encode(md)
        dec = Decoder()
        for i, byte in enumerate(data):
            assert not dec.is_complete, f"completed early at byte {i}"
            dec.feed(bytes([byte]))
        assert dec.is_complete
        result = dec.result()
        assert result == md

    def test_small_chunks(self) -> None:
        md = MultiDict([("a", "1"), ("b", "2"), ("a", "3")])
        data = encode(md)
        dec = Decoder()
        chunk_size = 3
        for i in range(0, len(data), chunk_size):
            dec.feed(data[i : i + chunk_size])
        assert dec.is_complete
        assert dec.result() == md

    def test_truncation_raises(self) -> None:
        data = encode(MultiDict([("a", "1"), ("b", "2")]))
        dec = Decoder()
        dec.feed(data[:-1])
        assert not dec.is_complete
        with pytest.raises(IncompletePacketError):
            dec.result()

    def test_truncation_no_partial_result(self) -> None:
        data = encode(MultiDict([("a", "1"), ("b", "2")]))
        dec = Decoder()
        dec.feed(data[: len(data) // 2])
        with pytest.raises(IncompletePacketError):
            dec.result()

    def test_feed_after_complete_raises(self) -> None:
        data = encode(MultiDict([("a", "1")]))
        dec = Decoder()
        dec.feed(data)
        with pytest.raises(CodecError, match="already produced"):
            dec.feed(b"x")

    def test_leftover_bytes(self) -> None:
        data = encode(MultiDict([("a", "1")])) + b"extra"
        dec = Decoder()
        dec.feed(data)
        assert dec.is_complete
        assert dec.leftover == b"extra"

    def test_decode_trailing_data_raises(self) -> None:
        data = encode(MultiDict([("a", "1")])) + b"extra"
        with pytest.raises(InvalidPacketError, match="trailing data"):
            decode(data)


class TestLimits:
    """Tests for declared-length limit enforcement."""

    def test_fake_huge_item_count(self) -> None:
        # Packet declares an item count of 1,000,000 but has no items.
        fake = MAGIC + bytes([VERSION, CATEGORY_MULTIDICT])
        fake += _encode_varint(1_000_000)
        with pytest.raises(LimitExceededError, match="item count"):
            decode(fake, max_items=100)

    def test_fake_huge_key_length(self) -> None:
        fake = MAGIC + bytes([VERSION, CATEGORY_MULTIDICT])
        fake += _encode_varint(1)  # one item
        fake += _encode_varint(1_000_000)  # huge key length
        with pytest.raises(LimitExceededError, match="key length"):
            decode(fake, max_key_size=100)

    def test_fake_huge_value_length(self) -> None:
        fake = MAGIC + bytes([VERSION, CATEGORY_MULTIDICT])
        fake += _encode_varint(1)  # one item
        fake += _encode_varint(1) + b"a"  # key
        fake += _encode_varint(1_000_000)  # huge value length
        with pytest.raises(LimitExceededError, match="value length"):
            decode(fake, max_value_size=100)

    def test_default_max_items(self) -> None:
        assert DEFAULT_MAX_ITEMS == 10_000

    def test_limit_rejected_before_payload_read(self) -> None:
        # The key length is declared as huge; the decoder must reject
        # before reading any key bytes.
        fake = MAGIC + bytes([VERSION, CATEGORY_MULTIDICT])
        fake += _encode_varint(1)
        fake += _encode_varint(1_000_000)
        dec = Decoder(max_key_size=100)
        with pytest.raises(LimitExceededError):
            dec.feed(fake)


class TestMalformed:
    """Tests for malformed packet detection."""

    def test_bad_magic(self) -> None:
        with pytest.raises(InvalidPacketError, match="bad magic"):
            decode(b"XX" + bytes([VERSION, CATEGORY_MULTIDICT]))

    def test_bad_version(self) -> None:
        with pytest.raises(InvalidPacketError, match="protocol version"):
            decode(MAGIC + bytes([99, CATEGORY_MULTIDICT]))

    def test_bad_category(self) -> None:
        with pytest.raises(InvalidPacketError, match="category code"):
            decode(MAGIC + bytes([VERSION, 99]))

    def test_empty_input(self) -> None:
        with pytest.raises(IncompletePacketError):
            decode(b"")

    def test_truncated_magic(self) -> None:
        with pytest.raises(IncompletePacketError):
            decode(b"M")


class TestWireFormat:
    """Tests that verify the explicit byte format."""

    def test_magic_and_version(self) -> None:
        data = encode(MultiDict())
        assert data[:2] == MAGIC
        assert data[2] == VERSION

    def test_category_byte(self) -> None:
        md = MultiDict()
        assert encode(md)[3] == CATEGORY_MULTIDICT
        ci = CIMultiDict()
        assert encode(ci)[3] == CATEGORY_CIMULTIDICT

    def test_item_count_encoded(self) -> None:
        md = MultiDict([("a", "1"), ("b", "2")])
        data = encode(md)
        # After magic(2) + version(1) + category(1), the count varint
        # for 2 is a single byte 0x02.
        assert data[4] == 0x02

    def test_key_length_encoded(self) -> None:
        md = MultiDict([("ab", "v")])
        data = encode(md)
        # count=1, key_len=2, key="ab", value_len=1, value="v"
        assert data[5] == 0x02  # key length
        assert data[6:8] == b"ab"

    def test_varint_encoding(self) -> None:
        from multidict.codec import _encode_varint

        assert _encode_varint(0) == b"\x00"
        assert _encode_varint(1) == b"\x01"
        assert _encode_varint(127) == b"\x7f"
        assert _encode_varint(128) == b"\x80\x01"
        assert _encode_varint(300) == b"\xac\x02"


class TestCLI:
    """Tests for the command-line interface."""

    def test_encode_decode(self, tmp_path) -> None:
        import os
        import subprocess
        import sys

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = os.environ.copy()
        env["PYTHONPATH"] = repo_root
        text = "cimultidict\nA=1\na=2\nB=3\n"
        encoded = subprocess.run(
            [sys.executable, "-m", "multidict.codec", "encode"],
            input=text.encode(),
            capture_output=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert encoded.returncode == 0, encoded.stderr.decode()
        decoded = subprocess.run(
            [sys.executable, "-m", "multidict.codec", "decode"],
            input=encoded.stdout,
            capture_output=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert decoded.returncode == 0, decoded.stderr.decode()
        assert decoded.stdout.decode() == text
