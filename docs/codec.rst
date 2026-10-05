.. _multidict-codec:

==============================
Binary codec for multidicts
==============================

.. module:: multidict

The :mod:`multidict` package ships a small binary codec that
serializes string multidicts: :func:`dumps` encodes a
:class:`MultiDict` or :class:`CIMultiDict` (keys *and* values must be
:class:`str`) into :class:`bytes`, and :func:`loads` /
:class:`MultiDictDecoder` decode them back.  Duplicate keys --
including keys that differ only by letter case, such as ``a`` and
``A`` -- are preserved in their original order of occurrence, and
:class:`CIMultiDict` keeps the original key spelling.

Byte format
-----------

All integers are unsigned, big-endian.  A frame is self-describing:
it carries the protocol version, the dictionary kind, the item count
and the exact UTF-8 byte length of every key and value::

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

Decoding rules
--------------

* :class:`MultiDictDecoder` accepts arbitrarily small chunks, down to
  one byte per :meth:`~MultiDictDecoder.feed` call; the result is
  identical to one-shot :func:`loads`.
* Every declared length (the item count and each key/value length) is
  checked against the configured limits (``max_items``,
  ``max_field_length``) the moment its field arrives.  A forged,
  oversized length is rejected with :class:`CodecError` immediately,
  without waiting for the promised payload.
* A truncated stream never yields a partial dictionary: the mapping
  is exposed only after the final byte of the final item, and
  :meth:`~MultiDictDecoder.finalize` raises :class:`CodecError` if
  the stream ends early.
* Encoding refuses undeclared non-string keys or values with
  :class:`TypeError`; nothing is silently coerced.

Running the tests
-----------------

The codec test-suite is pure Python and runs against the pure-Python
backend out of the box::

   python -m pytest tests/test_codec.py -m "not c_extension"

(``-m "not c_extension"`` deselects the C-extension parametrizations
when the extension module is not built; drop it to run both backends
in a full build.)
