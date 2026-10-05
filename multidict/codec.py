"""String :class:`~multidict.MultiDict` codec.

This module implements a compact binary codec for string-valued
:class:`~multidict.MultiDict` and :class:`~multidict.CIMultiDict`
instances.  Every field of the wire format is explicitly length-prefixed
so that a streaming decoder can reject a packet whose declared size
exceeds a configured limit *before* reading the payload bytes, and can
refuse to deliver a half-decoded dictionary when the input is truncated.

Wire format
===========

All multi-byte integers are unsigned `LEB128`_ varints (7 data bits per
byte, least significant group first, high bit set on every byte except
the last).

.. code-block:: text

    +--------+---------+----------+------------------+
    | magic  | version | category | item_count (var) |
    +--------+---------+----------+------------------+
    | for each item:                                  |
    |   key_len (var) | key_bytes (UTF-8)             |
    |   value_len (var) | value_bytes (UTF-8)         |
    +-------------------------------------------------+

* ``magic`` -- ``b"MD"`` (2 bytes), identifies the protocol.
* ``version`` -- protocol version, currently ``1`` (1 byte).
* ``category`` -- ``0`` for :class:`~multidict.MultiDict`, ``1`` for
  :class:`~multidict.CIMultiDict` (1 byte).
* ``item_count`` -- number of ``(key, value)`` pairs that follow.
* Each item is a length-prefixed UTF-8 key followed by a
  length-prefixed UTF-8 value.

Duplicate keys are preserved in their original insertion order.  A
:class:`~multidict.CIMultiDict` round-trips with its original key
spelling intact (the key bytes are the UTF-8 encoding of the key as
stored, not the lower-cased identity).

.. _LEB128: https://en.wikipedia.org/wiki/LEB128

Streaming decoding
==================

:class:`Decoder` is a state machine that accepts input in arbitrarily
small chunks (one byte at a time works).  Feed bytes with
:meth:`Decoder.feed`, check :attr:`Decoder.is_complete`, then call
:meth:`Decoder.result` to obtain the decoded dictionary.  A truncated
packet raises :class:`IncompletePacketError` from :meth:`Decoder.result`;
it never returns a partial dictionary.

Limits
======

The decoder enforces configurable caps on the item count, individual key
and value byte lengths, and the total packet size.  When a varint
declares a length that exceeds the corresponding cap,
:class:`LimitExceededError` is raised immediately -- before the decoder
reads any of the (potentially huge) payload bytes.
"""

from __future__ import annotations

from typing import BinaryIO

from ._multidict_py import CIMultiDict, MultiDict

__all__ = (
    "CATEGORY_CIMULTIDICT",
    "CATEGORY_MULTIDICT",
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_KEY_SIZE",
    "DEFAULT_MAX_PACKET_SIZE",
    "DEFAULT_MAX_VALUE_SIZE",
    "Decoder",
    "CodecError",
    "IncompletePacketError",
    "InvalidPacketError",
    "LimitExceededError",
    "decode",
    "encode",
)

#: Magic bytes identifying the protocol.
MAGIC: bytes = b"MD"

#: Protocol version.
VERSION: int = 1

#: Category code for :class:`~multidict.MultiDict`.
CATEGORY_MULTIDICT: int = 0

#: Category code for :class:`~multidict.CIMultiDict`.
CATEGORY_CIMULTIDICT: int = 1

#: Default cap on the number of items in a packet.
DEFAULT_MAX_ITEMS: int = 10_000

#: Default cap on the UTF-8 byte length of a key.
DEFAULT_MAX_KEY_SIZE: int = 64 * 1024  # 64 KiB

#: Default cap on the UTF-8 byte length of a value.
DEFAULT_MAX_VALUE_SIZE: int = 1024 * 1024  # 1 MiB

#: Default cap on the total number of bytes in a packet.
DEFAULT_MAX_PACKET_SIZE: int = 16 * 1024 * 1024  # 16 MiB

# Maximum number of varint bytes we are willing to read.  A 64-bit
# unsigned value needs at most 10 LEB128 bytes.
_MAX_VARINT_BYTES: int = 10


class CodecError(Exception):
    """Base class for all codec errors."""


class IncompletePacketError(CodecError):
    """Raised when a packet is truncated.

    The decoder has not yet received enough bytes to reconstruct the
    full dictionary.  Feed more bytes and try again.
    """


class InvalidPacketError(CodecError):
    """Raised when a packet is malformed.

    For example: bad magic bytes, an unsupported protocol version, an
    unknown category code, or a varint that is too long.
    """


class LimitExceededError(CodecError):
    """Raised when a declared length exceeds a configured limit.

    This is raised as soon as the offending varint has been decoded,
    before any of the payload bytes are read.
    """


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as an unsigned LEB128 varint."""
    if value < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _decode_varint(buf: bytearray) -> tuple[int | None, int]:
    """Decode an unsigned LEB128 varint from the start of *buf*.

    Returns ``(value, consumed)`` where *consumed* is the number of
    bytes taken from *buf*.  If the varint is incomplete (the last byte
    still has its high bit set but the buffer ends), returns
    ``(None, 0)`` without consuming anything.

    Raises :class:`InvalidPacketError` if the varint spans more than
    :data:`_MAX_VARINT_BYTES` bytes.
    """
    result = 0
    shift = 0
    pos = 0
    while True:
        if pos >= len(buf):
            return None, 0
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise InvalidPacketError(
                f"varint too long: more than {_MAX_VARINT_BYTES} bytes"
            )


def encode(md: MultiDict[str] | CIMultiDict[str]) -> bytes:
    """Encode a string multidict into the wire format.

    Every key and every value must be a :class:`str`.  Non-string keys
    or values are rejected with :class:`TypeError`.

    Duplicate keys are preserved in their original insertion order.
    A :class:`~multidict.CIMultiDict` round-trips with its original key
    spelling intact.
    """
    if isinstance(md, CIMultiDict):
        category = CATEGORY_CIMULTIDICT
    elif isinstance(md, MultiDict):
        category = CATEGORY_MULTIDICT
    else:
        raise TypeError(
            f"expected MultiDict or CIMultiDict, got {type(md).__name__}"
        )

    parts: list[bytes] = [MAGIC, bytes((VERSION, category))]
    parts.append(_encode_varint(len(md)))

    for key, value in md.items():
        if not isinstance(key, str):
            raise TypeError(
                f"keys must be str, got {type(key).__name__}: {key!r}"
            )
        if not isinstance(value, str):
            raise TypeError(
                f"values must be str, got {type(value).__name__}: {value!r}"
            )
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        parts.append(_encode_varint(len(key_bytes)))
        parts.append(key_bytes)
        parts.append(_encode_varint(len(value_bytes)))
        parts.append(value_bytes)

    return b"".join(parts)


class Decoder:
    """A streaming decoder for the wire format.

    Feed bytes with :meth:`feed`; the decoder accepts input in
    arbitrarily small chunks (one byte at a time works).  Check
    :attr:`is_complete` to see whether a full packet has been received,
    then call :meth:`result` to obtain the decoded dictionary.

    The decoder enforces the configured limits and raises
    :class:`LimitExceededError` as soon as a declared length exceeds
    its cap -- before reading any payload bytes.

    A truncated packet never produces a partial dictionary:
    :meth:`result` raises :class:`IncompletePacketError` until the full
    packet has been received.
    """

    def __init__(
        self,
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_key_size: int = DEFAULT_MAX_KEY_SIZE,
        max_value_size: int = DEFAULT_MAX_VALUE_SIZE,
        max_packet_size: int = DEFAULT_MAX_PACKET_SIZE,
    ) -> None:
        self.max_items = max_items
        self.max_key_size = max_key_size
        self.max_value_size = max_value_size
        self.max_packet_size = max_packet_size

        self._buf: bytearray = bytearray()
        self._state: str = "magic"
        self._category: int | None = None
        self._count: int = 0
        self._items_read: int = 0
        self._key_len: int = 0
        self._key_bytes: bytes = b""
        self._value_len: int = 0
        self._items: list[tuple[str, str]] = []
        self._result: MultiDict[str] | CIMultiDict[str] | None = None
        self._total_fed: int = 0

    @property
    def is_complete(self) -> bool:
        """``True`` if a full packet has been received."""
        return self._result is not None

    @property
    def leftover(self) -> bytes:
        """Bytes fed to the decoder that were not part of the packet.

        When the packet is incomplete this is the partial packet data;
        when complete it is any trailing data after the packet.
        """
        return bytes(self._buf)

    def feed(self, data: bytes) -> int:
        """Feed bytes to the decoder.

        Returns the number of bytes consumed from *data*.  Raises
        :class:`LimitExceededError` or :class:`InvalidPacketError` if
        the packet violates a limit or is malformed.
        """
        if self._result is not None:
            raise CodecError("decoder already produced a result")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"data must be bytes-like, got {type(data).__name__}"
            )
        data = bytes(data)
        self._total_fed += len(data)
        if self._total_fed > self.max_packet_size:
            raise LimitExceededError(
                f"packet size {self._total_fed} exceeds limit "
                f"{self.max_packet_size}"
            )
        self._buf.extend(data)
        before = len(self._buf)
        self._process()
        return before - len(self._buf)

    def _process(self) -> None:
        """Run the state machine over the internal buffer."""
        while True:
            if self._state == "magic":
                if len(self._buf) < len(MAGIC):
                    return
                if bytes(self._buf[: len(MAGIC)]) != MAGIC:
                    raise InvalidPacketError(
                        f"bad magic: expected {MAGIC!r}, "
                        f"got {bytes(self._buf[: len(MAGIC)])!r}"
                    )
                del self._buf[: len(MAGIC)]
                self._state = "version"

            elif self._state == "version":
                if len(self._buf) < 1:
                    return
                version = self._buf[0]
                if version != VERSION:
                    raise InvalidPacketError(
                        f"unsupported protocol version: {version}"
                    )
                del self._buf[:1]
                self._state = "category"

            elif self._state == "category":
                if len(self._buf) < 1:
                    return
                self._category = self._buf[0]
                if self._category not in (
                    CATEGORY_MULTIDICT,
                    CATEGORY_CIMULTIDICT,
                ):
                    raise InvalidPacketError(
                        f"unknown category code: {self._category}"
                    )
                del self._buf[:1]
                self._state = "count"

            elif self._state == "count":
                value, consumed = _decode_varint(self._buf)
                if value is None:
                    return
                if value > self.max_items:
                    raise LimitExceededError(
                        f"item count {value} exceeds limit "
                        f"{self.max_items}"
                    )
                self._count = value
                del self._buf[:consumed]
                self._state = "key_len"

            elif self._state == "key_len":
                if self._items_read >= self._count:
                    self._finish()
                    return
                value, consumed = _decode_varint(self._buf)
                if value is None:
                    return
                if value > self.max_key_size:
                    raise LimitExceededError(
                        f"key length {value} exceeds limit "
                        f"{self.max_key_size}"
                    )
                self._key_len = value
                del self._buf[:consumed]
                self._state = "key"

            elif self._state == "key":
                if len(self._buf) < self._key_len:
                    return
                self._key_bytes = bytes(self._buf[: self._key_len])
                del self._buf[: self._key_len]
                self._state = "value_len"

            elif self._state == "value_len":
                value, consumed = _decode_varint(self._buf)
                if value is None:
                    return
                if value > self.max_value_size:
                    raise LimitExceededError(
                        f"value length {value} exceeds limit "
                        f"{self.max_value_size}"
                    )
                self._value_len = value
                del self._buf[:consumed]
                self._state = "value"

            elif self._state == "value":
                if len(self._buf) < self._value_len:
                    return
                value_bytes = bytes(self._buf[: self._value_len])
                del self._buf[: self._value_len]
                key = self._key_bytes.decode("utf-8")
                value = value_bytes.decode("utf-8")
                self._items.append((key, value))
                self._items_read += 1
                self._state = "key_len"

            else:  # pragma: no cover
                raise InvalidPacketError(
                    f"unknown decoder state: {self._state}"
                )

    def _finish(self) -> None:
        """Build the result from the collected items."""
        assert self._category is not None
        if self._category == CATEGORY_CIMULTIDICT:
            self._result = CIMultiDict(self._items)
        else:
            self._result = MultiDict(self._items)
        self._state = "complete"

    def result(self) -> MultiDict[str] | CIMultiDict[str]:
        """Return the decoded dictionary.

        Raises :class:`IncompletePacketError` if the packet has not been
        fully received.  Never returns a partial dictionary.
        """
        if self._result is None:
            raise IncompletePacketError(
                f"packet is incomplete: have {self._items_read} of "
                f"{self._count} items"
            )
        return self._result


def decode(
    data: bytes,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_key_size: int = DEFAULT_MAX_KEY_SIZE,
    max_value_size: int = DEFAULT_MAX_VALUE_SIZE,
    max_packet_size: int = DEFAULT_MAX_PACKET_SIZE,
) -> MultiDict[str] | CIMultiDict[str]:
    """Decode a complete packet in one shot.

    Raises :class:`IncompletePacketError` if *data* is truncated,
    :class:`LimitExceededError` if a declared length exceeds a limit,
    and :class:`InvalidPacketError` if the packet is malformed or has
    trailing data.
    """
    dec = Decoder(
        max_items=max_items,
        max_key_size=max_key_size,
        max_value_size=max_value_size,
        max_packet_size=max_packet_size,
    )
    dec.feed(data)
    if not dec.is_complete:
        raise IncompletePacketError(
            f"packet is incomplete: have {dec._items_read} of "
            f"{dec._count} items"
        )
    if dec.leftover:
        raise InvalidPacketError(
            f"trailing data after packet: {len(dec.leftover)} bytes"
        )
    return dec.result()


def _main(argv: list[str] | None = None) -> int:
    """Command-line interface for the codec.

    Reads a simple line-based text format from stdin and writes the
    binary packet to stdout (``encode``), or reads a binary packet from
    stdin and writes the text format to stdout (``decode``).

    Text format:
        First line: ``multidict`` or ``cimultidict``.
        Subsequent lines: ``key=value`` (key and value separated by the
        first ``=``).
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="multidict.codec",
        description="String MultiDict codec",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("encode", help="encode text to binary")
    sub.add_parser("decode", help="decode binary to text")
    args = parser.parse_args(argv)

    if args.command == "encode":
        return _cmd_encode(sys.stdin.buffer, sys.stdout.buffer)
    else:
        return _cmd_decode(sys.stdin.buffer, sys.stdout.buffer)


def _cmd_encode(infile: BinaryIO, outfile: BinaryIO) -> int:
    import sys

    first = infile.readline().decode("utf-8").strip()
    if first == "multidict":
        md: MultiDict[str] | CIMultiDict[str] = MultiDict()
    elif first == "cimultidict":
        md = CIMultiDict()
    else:
        print(
            f"error: first line must be 'multidict' or 'cimultidict', "
            f"got {first!r}",
            file=sys.stderr,
        )
        return 1
    for raw in infile:
        line = raw.decode("utf-8").rstrip("\n")
        if not line:
            continue
        if "=" not in line:
            print(f"error: line without '=': {line!r}", file=sys.stderr)
            return 1
        key, value = line.split("=", 1)
        md.add(key, value)
    outfile.write(encode(md))
    return 0


def _cmd_decode(infile: BinaryIO, outfile: BinaryIO) -> int:
    import sys

    data = infile.read()
    try:
        md = decode(data)
    except CodecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if isinstance(md, CIMultiDict):
        outfile.write(b"cimultidict\n")
    else:
        outfile.write(b"multidict\n")
    for key, value in md.items():
        outfile.write(f"{key}={value}\n".encode("utf-8"))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
