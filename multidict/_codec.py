"""Binary codec for string multidicts.

This module implements a small, self-describing binary format that
round-trips :class:`~multidict.MultiDict` and
:class:`~multidict.CIMultiDict` instances whose keys *and* values are
strings.  Duplicate keys (including keys that differ only by letter
case) are preserved in their original order of occurrence, and
:class:`~multidict.CIMultiDict` keeps the original key spelling.

Byte format (all integers are unsigned, big-endian)::

    offset  size  field
    ------  ----  --------------------------------------------------
    0       2     magic, always b"MD"
    2       1     protocol version, currently 0x01
    3       1     dictionary kind: 0x01 = MultiDict, 0x02 = CIMultiDict
    4       4     item count N (number of key/value pairs)
    8       ...   N items, each laid out as:

                  +4   key_len   UTF-8 byte length of the key
                  ...  key       key_len raw UTF-8 bytes (key_len may
                                 be 0: the empty key is a valid item)
                  +4   value_len UTF-8 byte length of the value
                  ...  value     value_len raw UTF-8 bytes

Decoding is incremental: :class:`MultiDictDecoder` accepts arbitrarily
small chunks (down to a single byte per :meth:`MultiDictDecoder.feed`
call).  Every declared length (the item count and each key/value
length) is validated against the configured limits the moment its
field becomes available, so a forged, absurdly large length is
rejected immediately without waiting for the promised payload.  A
truncated stream never yields a partial dictionary: the decoded
mapping is only exposed once the final byte of the final item has
arrived, and :meth:`MultiDictDecoder.finalize` raises
:exc:`CodecError` if the stream ends early.

Encoding is strict: keys and values must be :class:`str` instances.
Undeclared non-string values (or keys) are refused with
:exc:`TypeError` instead of being silently coerced.

>>> from multidict import MultiDict
>>> md = MultiDict([("a", "1"), ("A", "2"), ("a", "3")])
>>> blob = dumps(md)
>>> restored = loads(blob)
>>> list(restored.items())
[('a', '1'), ('A', '2'), ('a', '3')]
>>> restored.getall("a")
['1', '3']
"""

from __future__ import annotations

import struct
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._abc import MultiMapping
    from ._multidict_py import CIMultiDict, MultiDict

__all__ = (
    "CodecError",
    "MultiDictDecoder",
    "dumps",
    "loads",
)

_MAGIC = b"MD"
_VERSION = 1
_KIND_MULTIDICT = 0x01
_KIND_CIMULTIDICT = 0x02

_HEADER_STRUCT = struct.Struct(">2sBBI")  # magic, version, kind, item count
_LENGTH_STRUCT = struct.Struct(">I")  # one uint32 length field
_HEADER_SIZE = _HEADER_STRUCT.size
_LENGTH_SIZE = _LENGTH_STRUCT.size

#: Default ceiling for the declared item count.
DEFAULT_MAX_ITEMS = 1 << 16  # 65536 pairs
#: Default ceiling for the declared UTF-8 byte length of a single key/value.
DEFAULT_MAX_FIELD_LENGTH = 1 << 20  # 1 MiB


class CodecError(ValueError):
    """Raised when encoded data violates the multidict wire format."""


def _impl_modules() -> tuple[ModuleType, ...]:
    """Return the available implementation modules (pure Python and C).

    Both are considered so that instances of either backend are
    accepted no matter which one the package exposes by default.
    """
    # Local import: this module is imported by the package ``__init__``
    # before the implementation classes exist (circular otherwise).
    from . import _multidict_py  # noqa: PLC0415

    modules = [_multidict_py]
    try:
        # Optional C extension; local import keeps it that way.
        from . import _multidict  # type: ignore[attr-defined]  # noqa: PLC0415
    except ImportError:
        pass
    else:
        modules.append(_multidict)
    return tuple(modules)


def _kind_of(md: object) -> int | None:
    """Classify a multidict instance, or return None for other types."""
    modules = _impl_modules()
    for mod in modules:
        if isinstance(md, (mod.CIMultiDict, mod.CIMultiDictProxy)):
            return _KIND_CIMULTIDICT
    for mod in modules:
        if isinstance(md, (mod.MultiDict, mod.MultiDictProxy)):
            return _KIND_MULTIDICT
    return None


def _decode_class(
    kind: int,
) -> type[MultiDict[str]] | type[CIMultiDict[str]]:
    """Return the package-level class to build for a decoded frame."""
    # Local import: the package ``__init__`` imports this module while it
    # is still selecting the implementation (circular otherwise).
    from . import CIMultiDict, MultiDict  # noqa: PLC0415

    return CIMultiDict if kind == _KIND_CIMULTIDICT else MultiDict


def _encode_field(value: object, what: str, max_field_length: int) -> bytes:
    if not isinstance(value, str):
        raise TypeError(
            f"dumps() requires str {what}s, got {type(value).__name__}: {value!r}"
        )
    raw = value.encode("utf-8")
    if len(raw) > max_field_length:
        raise CodecError(
            f"{what} is {len(raw)} UTF-8 bytes, "
            f"exceeding the limit of {max_field_length}"
        )
    return raw


def dumps(
    md: MultiMapping[Any],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_field_length: int = DEFAULT_MAX_FIELD_LENGTH,
) -> bytes:
    """Encode a string multidict into bytes.

    ``md`` must be a :class:`~multidict.MultiDict`,
    :class:`~multidict.CIMultiDict` or a proxy of either; every key and
    every value must be a :class:`str`.  :exc:`TypeError` is raised for
    anything else, :exc:`CodecError` when a declared limit is exceeded.
    """
    kind = _kind_of(md)
    if kind is None:
        raise TypeError(
            "dumps() requires a MultiDict or CIMultiDict "
            f"(or a proxy of one), got {type(md).__name__}"
        )

    out = bytearray()
    count = 0
    for key, value in md.items():
        raw_key = _encode_field(key, "key", max_field_length)
        raw_value = _encode_field(value, "value", max_field_length)
        out += _LENGTH_STRUCT.pack(len(raw_key))
        out += raw_key
        out += _LENGTH_STRUCT.pack(len(raw_value))
        out += raw_value
        count += 1
    if count > max_items:
        raise CodecError(f"{count} items exceed the limit of {max_items}")
    return bytes(_HEADER_STRUCT.pack(_MAGIC, _VERSION, kind, count)) + bytes(out)


class MultiDictDecoder:
    """Incremental decoder for the multidict wire format.

    Feed arbitrary chunks with :meth:`feed`; once a complete frame has
    arrived, :attr:`done` becomes true and :meth:`result` returns the
    decoded :class:`~multidict.MultiDict` or
    :class:`~multidict.CIMultiDict`.  Call :meth:`finalize` at end of
    stream: it returns the mapping, or raises :exc:`CodecError` if the
    stream was truncated -- a partial dictionary is never delivered.
    """

    __slots__ = (
        "_buf",
        "_count",
        "_done",
        "_items",
        "_kind",
        "_max_field_length",
        "_max_items",
        "_result",
    )

    def __init__(
        self,
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_field_length: int = DEFAULT_MAX_FIELD_LENGTH,
    ) -> None:
        self._max_items = max_items
        self._max_field_length = max_field_length
        self._buf = bytearray()
        self._kind: int | None = None
        self._count: int | None = None
        self._items: list[tuple[str, str]] = []
        self._result: MultiDict[str] | CIMultiDict[str] | None = None
        self._done = False

    @property
    def done(self) -> bool:
        """Whether a complete frame has been decoded."""
        return self._done

    def feed(self, data: bytes | bytearray | memoryview) -> None:
        """Consume the next chunk of encoded data.

        Raises :exc:`CodecError` as soon as a protocol violation is
        visible -- including a declared length that exceeds the
        configured limits, even if the promised payload has not (and
        will never) arrive.
        """
        if self._done:
            raise CodecError("trailing data after a complete frame")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"feed() requires a bytes-like object, got {type(data).__name__}"
            )
        self._buf += data
        self._parse()

    def result(self) -> MultiDict[str] | CIMultiDict[str]:
        """Return the decoded multidict.

        Raises :exc:`CodecError` if the frame is not complete yet.
        """
        if not self._done:
            raise CodecError("incomplete data: the frame is not fully decoded yet")
        assert self._result is not None
        return self._result

    def finalize(self) -> MultiDict[str] | CIMultiDict[str]:
        """Finish decoding at end of stream.

        Returns the decoded multidict, or raises :exc:`CodecError`
        when the stream ended in the middle of a frame.
        """
        if not self._done:
            raise CodecError(
                "truncated data: stream ended before the frame was complete"
            )
        assert self._result is not None
        return self._result

    def _read_length(self, offset: int, what: str) -> int:
        length: int = _LENGTH_STRUCT.unpack_from(self._buf, offset)[0]
        if length > self._max_field_length:
            raise CodecError(
                f"declared {what} length {length} exceeds "
                f"the limit of {self._max_field_length}"
            )
        return length

    def _parse(self) -> None:
        buf = self._buf
        pos = 0
        if self._kind is None:
            if len(buf) < _HEADER_SIZE:
                return
            magic, version, kind, count = _HEADER_STRUCT.unpack_from(buf, 0)
            if magic != _MAGIC:
                raise CodecError(f"bad magic {magic!r}, expected {_MAGIC!r}")
            if version != _VERSION:
                raise CodecError(f"unsupported protocol version {version}")
            if kind not in (_KIND_MULTIDICT, _KIND_CIMULTIDICT):
                raise CodecError(f"unknown dictionary kind {kind:#x}")
            if count > self._max_items:
                raise CodecError(
                    f"declared item count {count} exceeds "
                    f"the limit of {self._max_items}"
                )
            self._kind = kind
            self._count = count
            pos = _HEADER_SIZE

        assert self._kind is not None
        assert self._count is not None
        while len(self._items) < self._count:
            available = len(buf) - pos
            if available < _LENGTH_SIZE:
                break
            key_len = self._read_length(pos, "key")
            if available < _LENGTH_SIZE + key_len + _LENGTH_SIZE:
                break
            value_len = self._read_length(pos + _LENGTH_SIZE + key_len, "value")
            item_size = 2 * _LENGTH_SIZE + key_len + value_len
            if available < item_size:
                break
            key_start = pos + _LENGTH_SIZE
            value_start = key_start + key_len + _LENGTH_SIZE
            try:
                key = bytes(buf[key_start : key_start + key_len]).decode("utf-8")
                value = bytes(buf[value_start : value_start + value_len]).decode(
                    "utf-8"
                )
            except UnicodeDecodeError as exc:
                raise CodecError(f"invalid UTF-8 in item {len(self._items)}") from exc
            self._items.append((key, value))
            pos += item_size

        if len(self._items) == self._count:
            if pos < len(buf):
                raise CodecError("trailing data after a complete frame")
            self._result = _decode_class(self._kind)(self._items)
            self._done = True
            self._items = []
            self._buf = bytearray()
            return
        del buf[:pos]


def loads(
    data: bytes | bytearray | memoryview,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_field_length: int = DEFAULT_MAX_FIELD_LENGTH,
) -> MultiDict[str] | CIMultiDict[str]:
    """Decode a complete frame in one shot.

    Raises :exc:`CodecError` on any protocol violation, on trailing
    garbage, or when ``data`` is a truncated frame.
    """
    decoder = MultiDictDecoder(max_items=max_items, max_field_length=max_field_length)
    decoder.feed(data)
    return decoder.finalize()
