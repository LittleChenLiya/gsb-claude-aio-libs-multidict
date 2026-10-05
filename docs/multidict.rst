.. _multidict-reference:

============
Reference
============

.. module:: multidict



MultiDict
=========

.. class:: MultiDict(**kwargs)
           MultiDict(mapping, **kwargs)
           MultiDict(iterable, **kwargs)

   Creates a mutable multidict instance.

   Accepted parameters are the same as for :class:`dict`.
   If the same key appears several times it will be added, e.g.::

      >>> d = MultiDict([('a', 1), ('b', 2), ('a', 3)])
      >>> d
      <MultiDict ('a': 1, 'b': 2, 'a': 3)>

   .. note::

      ``d[key]``, :meth:`getone` and :meth:`get` silently return the
      first value and ignore any others. When a key must carry exactly
      one value, as with security-sensitive HTTP headers such as
      ``Host``, ``Content-Length`` or ``Authorization``, fetch every value
      with :meth:`getall` and reject the input unless there is exactly
      one::

         values = headers.getall('Host')
         if len(values) != 1:
             raise ValueError("expected exactly one Host header")
         host = values[0]

   .. method:: len(d)

      Return the number of items in multidict *d*.

   .. method:: d[key]

      Return the **first** item of *d* with key *key*.

      Raises a :exc:`KeyError` if key is not in the multidict.

   .. method:: d[key] = value

      Set ``d[key]`` to *value*.

      Replace all items where key is equal to *key* with single item
      ``(key, value)``.

   .. method:: del d[key]

      Remove all items where key is equal to *key* from *d*.
      Raises a :exc:`KeyError` if *key* is not in the map.

   .. method:: key in d

      Return ``True`` if d has a key *key*, else ``False``.

   .. method:: key not in d

      Equivalent to ``not (key in d)``

   .. method:: iter(d)

      Return an iterator over the keys of the dictionary.
      This is a shortcut for ``iter(d.keys())``.

   .. method:: add(key, value)

      Append ``(key, value)`` pair to the dictionary.

   .. method:: clear()

      Remove all items from the dictionary.

   .. method:: copy()

      Return a shallow copy of the dictionary.

   .. method:: to_dict()

      Return a :class:`dict` mapping each key to a list of all its
      values, preserving insertion order, e.g.::

         >>> d = MultiDict([('a', 1), ('b', 2), ('a', 3)])
         >>> d.to_dict()
         {'a': [1, 3], 'b': [2]}

      The result is a new dictionary with fresh lists; mutating it
      does not affect the multidict.

      Every key maps to a list, even a key with a single value, so feeding
      the result back does not reproduce the original:
      ``MultiDict(d.to_dict())`` builds a multidict whose *values* are
      lists. This differs from
      :class:`dict`\\ ``(d)``, which keeps only the **first** value for each
      key::

         >>> dict(d)
         {'a': 1, 'b': 2}

      For :class:`CIMultiDict` the values are grouped by key identity, so
      each key appears once under its first-seen spelling. That is what a
      ``{k: d.getall(k) for k in d}`` comprehension gets wrong: it emits a
      separate entry for every spelling, each holding the full list::

         >>> ci = CIMultiDict([('A', '1'), ('a', '2')])
         >>> ci.to_dict()
         {'A': ['1', '2']}
         >>> {k: ci.getall(k) for k in ci}
         {'A': ['1', '2'], 'a': ['1', '2']}

      .. versionadded:: 6.9

   .. method:: getone(key[, default])

      Return the **first** value for *key* if *key* is in the
      dictionary, else *default*.

      Raises :exc:`KeyError` if *default* is not given and *key* is not found.

      ``d[key]`` is equivalent to ``d.getone(key)``.

   .. method:: getall(key[, default])

      Return a list of all values for *key* if *key* is in the
      dictionary, else *default*.

      Raises :exc:`KeyError` if *default* is not given and *key* is not found.

   .. method:: get(key[, default])

      Return the **first** value for *key* if *key* is in the
      dictionary, else *default*.

      If *default* is not given, it defaults to ``None``, so that this
      method never raises a :exc:`KeyError`.

      ``d.get(key)`` is equivalent to ``d.getone(key, None)``.

   .. method:: keys()

      Return a new view of the dictionary's keys.

      View contains all keys, possibly with duplicates.

   .. method:: items()

      Return a new view of the dictionary's items (``(key, value)`` pairs).

      View contains all items, multiple items can have the same key.

   .. method:: values()

      Return a new view of the dictionary's values.

      View contains all values.

   .. method:: popone(key[, default])

      If *key* is in the dictionary, remove its **first** occurrence and
      return the corresponding value, else return *default*.

      If *default* is not given and *key* is not in the dictionary, a
      :exc:`KeyError` is raised.

      .. versionadded:: 3.0

   .. method:: pop(key[, default])

      An alias to :meth:`popone`

      .. versionchanged:: 3.0

         Now only *first* occurrence is removed (was all).

   .. method:: popall(key[, default])

      If *key* is in the dictionary, remove all occurrences and return
      a :class:`list` of all values in corresponding order (as
      :meth:`getall` does).

      If *key* is not found and *default* is provided return *default*.

      If *default* is not given and *key* is not in the dictionary, a
      :exc:`KeyError` is raised.

      .. versionadded:: 3.0

   .. method:: popitem()

      Remove and return an arbitrary ``(key, value)`` pair from the dictionary.

      :meth:`popitem` is useful to destructively iterate over a
      dictionary, as often used in set algorithms.

      If the dictionary is empty, calling :meth:`popitem` raises a
      :exc:`KeyError`.

   .. method:: setdefault(key[, default])

      If *key* is in the dictionary, return its the **first** value.
      If not, insert *key* with a value of *default* and return *default*.
      *default* defaults to ``None``.

   .. method:: extend([other], **kwargs)

      Extend the dictionary with the key/value pairs from *other* and *kwargs*,
      appending the pairs to this dictionary. For existing keys,
      values are added.

      Returns ``None``.

      :meth:`extend` accepts either another dictionary object or an
      iterable of key/value pairs (as tuples or other iterables of
      length two). If keyword arguments are specified, the dictionary
      is then extended with those key/value pairs:
      ``d.extend(red=1, blue=2)``.

      Effectively the same as calling :meth:`add` for every
      ``(key, value)`` pair.

      .. seealso::

         :meth:`merge` and :meth:`update`

   .. method:: merge([other], **kwargs)

      Merge the dictionary with the key/value pairs from *other* and *kwargs*,
      appending non-existing pairs to this dictionary. For existing keys,
      the addition is skipped.

      Returns ``None``.

      :meth:`merge` accepts either another dictionary object or an
      iterable of key/value pairs (as tuples or other iterables of
      length two). If keyword arguments are specified, the dictionary
      is then merged with those key/value pairs:
      ``d.merge(red=1, blue=2)``.

      Effectively the same as calling :meth:`add` for every
      ``(key, value)`` pair where ``key not in self``.

      .. seealso::

         :meth:`extend` and :meth:`update`

      .. versionadded:: 6.6

   .. method:: update([other], **kwargs)

      Update the dictionary with the key/value pairs from *other* and *kwargs*,
      overwriting existing keys.

      Returns ``None``.

      :meth:`update` accepts either another dictionary object or an
      iterable of key/value pairs (as tuples or other iterables
      of length two). If keyword arguments are specified, the
      dictionary is then updated with those key/value pairs:
      ``d.update(red=1, blue=2)``.

      .. seealso::

         :meth:`extend` and :meth:`merge`

   .. seealso::

      :class:`MultiDictProxy` can be used to create a read-only view
      of a :class:`MultiDict`.


CIMultiDict
===========


.. class:: CIMultiDict(**kwargs)
           CIMultiDict(mapping, **kwargs)
           CIMultiDict(iterable, **kwargs)

   Create a case insensitive multidict instance.

   The behavior is the same as of :class:`MultiDict` but key
   comparisons are case insensitive, e.g.::

      >>> dct = CIMultiDict(a='val')
      >>> 'A' in dct
      True
      >>> dct['A']
      'val'
      >>> dct['a']
      'val'
      >>> dct['b'] = 'new val'
      >>> dct['B']
      'new val'

   The class is inherited from :class:`MultiDict`.

   Keys are converted to :class:`istr`::

      >>> dct = CIMultiDict([('Content-Type', 'text/html')])
      >>> key = next(iter(dct))
      >>> isinstance(key, istr), key
      (True, 'Content-Type')

   .. seealso::

      :class:`CIMultiDictProxy` can be used to create a read-only view
      of a :class:`CIMultiDict`.


MultiDictProxy
==============

.. class:: MultiDictProxy(multidict)

   Create an immutable multidict proxy.

   It provides a dynamic view on
   the multidict’s entries, which means that when the multidict changes,
   the view reflects these changes.

   Raises :exc:`TypeError` if *multidict* is not a :class:`MultiDict` instance.

   .. method:: len(d)

      Return number of items in multidict *d*.

   .. method:: d[key]

      Return the **first** item of *d* with key *key*.

      Raises a :exc:`KeyError` if key is not in the multidict.

   .. method:: key in d

      Return ``True`` if d has a key *key*, else ``False``.

   .. method:: key not in d

      Equivalent to ``not (key in d)``

   .. method:: iter(d)

      Return an iterator over the keys of the dictionary.
      This is a shortcut for ``iter(d.keys())``.

   .. method:: copy()

      Return a shallow copy of the underlying multidict.

   .. method:: to_dict()

      Return a :class:`dict` mapping each key to a list of all its
      values, preserving insertion order.

      .. versionadded:: 6.9

   .. method:: getone(key[, default])

      Return the **first** value for *key* if *key* is in the
      dictionary, else *default*.

      Raises :exc:`KeyError` if *default* is not given and *key* is not found.

      ``d[key]`` is equivalent to ``d.getone(key)``.

   .. method:: getall(key[, default])

      Return a list of all values for *key* if *key* is in the
      dictionary, else *default*.

      Raises :exc:`KeyError` if *default* is not given and *key* is not found.

   .. method:: get(key[, default])

      Return the **first** value for *key* if *key* is in the
      dictionary, else *default*.

      If *default* is not given, it defaults to ``None``, so that this
      method never raises a :exc:`KeyError`.

      ``d.get(key)`` is equivalent to ``d.getone(key, None)``.

   .. method:: keys()

      Return a new view of the dictionary's keys.

      View contains all keys, possibly with duplicates.

   .. method:: items()

      Return a new view of the dictionary's items (``(key, value)`` pairs).

      View contains all items, multiple items can have the same key.

   .. method:: values()

      Return a new view of the dictionary's values.

      View contains all values.

CIMultiDictProxy
================

.. class:: CIMultiDictProxy(multidict)

   Case insensitive version of :class:`MultiDictProxy`.

   Raises :exc:`TypeError` if *multidict* is not :class:`CIMultiDict` instance.

   The class is inherited from :class:`MultiDictProxy`.


Version
=======

All multidicts have an internal version flag. It's changed on every
dict update, thus the flag could be used for checks like cache
expiring etc.

.. function:: getversion(mdict)

   Return a version of given *mdict* object (works for proxies also).

   The type of returned value is opaque and should be used for
   equality tests only (``==`` and ``!=``), ordering is not allowed
   while not prohibited explicitly.

  .. versionadded:: 3.0

  .. seealso:: :pep:`509`


istr
====

:class:`CIMultiDict` accepts :class:`str` as *key* argument for dict
lookups but uses case-folded (lower-cased) strings for the comparison internally.

For more effective processing it should know if the *key* is already
an :class:`istr` instance so it can skip the :meth:`~str.lower()` call.

The performant code may create
:class:`istr` keys explicitly by hand, e.g::

   >>> key = istr('Key')
   >>> key
   'Key'
   >>> mdict = CIMultiDict(key='value')
   >>> key in mdict
   True
   >>> mdict[key]
   'value'

``istr`` itself compares like a regular :class:`str`.
``istr('Key') == 'key'`` is ``False``; case-insensitive matching is
handled by :class:`CIMultiDict`, not by ``istr`` equality.

For performance :class:`istr` strings should be created once and
stored somewhere for the later usage, see :mod:`aiohttp:aiohttp.hdrs` for example.

How much that is worth, as instruction counts on CPython 3.14 measured
the way :ref:`benchmarking-reference` describes. ``d[key]`` and
``d[key] = v`` run against a :class:`CIMultiDict` of 200 already
lower-case keys; ``d.add()`` builds that mapping from empty. Its row
reports the average cost per insertion across those 200 insertions:

.. list-table:: :class:`CIMultiDict` keyed by ``str`` versus by :class:`istr`
   :header-rows: 1
   :widths: 28 14 14 14 14 16

   * - Operation
     - GIL, ``str``
     - GIL, :class:`istr`
     - Free-threaded, ``str``
     - Free-threaded, :class:`istr`
     - Saved
   * - ``d[key]``
     - 238
     - 151
     - 378
     - 292
     - 23% to 36%
   * - ``d[key] = v``
     - 422
     - 336
     - 602
     - 516
     - 14% to 21%
   * - ``d.add(key, v)``
     - 765
     - 679
     - 939
     - 856
     - 9% to 11%

A key that is not already lower case saves more again: a :class:`str`
key then has to be copied into a lower-cased string, and that copy has
no cached hash, so every operation also hashes it afresh.

.. class:: istr(object='')
           istr(bytes_or_buffer[, encoding[, errors]])

      Create a new :class:`istr` string from the given
      *object*. If *encoding* or *errors* are specified, then the
      object must expose a data buffer that will be decoded using the
      given encoding and error handler.

      Otherwise, returns the result of ``object.__str__()`` (if defined)
      or ``repr(object)``.

      *encoding* defaults to ``sys.getdefaultencoding()``.

      *errors* defaults to ``'strict'``.

      The original casing is preserved. :class:`CIMultiDict` keeps a
      lower-cased identity internally for lookups.

      The class is inherited from :class:`str` and has all regular
      string methods. The class is final and cannot be subclassed.

.. versionchanged:: 2.0

   ``upstr()`` is a deprecated alias for :class:`istr`.

.. versionchanged:: 3.7

   :class:`istr` no longer title-cases its argument. The original
   casing is kept; :class:`CIMultiDict` uses an internal lower-cased
   identity for case-insensitive lookups.


Merge Plan
==========

.. class:: MergePlan(sources, strategies=None, *, default=MergeStrategy.APPEND)

   An explicit multi-source merge plan. It merges several
   :class:`MultiDict` sources into a single result.

   :param sources: The multidict sources to merge, in order.
   :param strategies: A mapping of key to :class:`MergeStrategy` (or its
      string value). Keys not listed here use *default*.
   :param default: The strategy for keys not listed in *strategies*.
      Defaults to :data:`MergeStrategy.APPEND`.

   Each key can be merged with one of three strategies:

   - :data:`MergeStrategy.REPLACE` -- keep only the values from the last
     source that defines the key (earlier sources are discarded). A
     multi-value is not split into a single value: if the new source has
     several values for the key, all of them are kept.
   - :data:`MergeStrategy.APPEND` -- keep all values from all sources, in
     order.
   - :data:`MergeStrategy.DEDUP` -- like :data:`MergeStrategy.APPEND`, but
     skip duplicate values (the first occurrence wins, order is preserved).

   When the sources are :class:`CIMultiDict` instances, keys are matched by
   their *real* (case-folded) identity: ``"A"`` and ``"a"`` are the same
   key. The position of the first occurrence of a real key across the
   sources determines its position in the output.

   Rule conflicts are rejected before execution: for :class:`CIMultiDict`
   sources, two strategy keys that are case-insensitively equal but resolve
   to different strategies raise :exc:`ValueError`.

   The result is a fresh container, independent of the input sources, and
   each output item reports the index of the source it came from.

   .. method:: execute()

      Execute the plan and return a :class:`MergeResult`.

   Usage example::

      >>> from multidict import MultiDict, MergePlan, MergeStrategy
      >>> s1 = MultiDict([('a', 1), ('b', 2)])
      >>> s2 = MultiDict([('a', 3), ('a', 4), ('b', 5)])
      >>> plan = MergePlan(
      ...     [s1, s2],
      ...     strategies={'a': MergeStrategy.APPEND, 'b': MergeStrategy.REPLACE},
      ... )
      >>> result = plan.execute()
      >>> list(result.md.items())
      [('a', 1), ('a', 3), ('a', 4), ('b', 5)]
      >>> result.sources
      [0, 1, 1, 1]

   .. versionadded:: 7.1

.. class:: MergeStrategy

   An :class:`~enum.Enum` of the three merge strategies.

   .. data:: REPLACE

      Keep only the values from the last source that has the key.

   .. data:: APPEND

      Keep all values from all sources, in order.

   .. data:: DEDUP

      Like :data:`APPEND`, but skip duplicate values (first occurrence wins).

   String values (``"replace"``, ``"append"``, ``"dedup"``) are accepted
   wherever a strategy is expected.

.. class:: MergeResult

   The result of executing a :class:`MergePlan`.

   .. attribute:: md

      The merged multidict. A fresh container, independent of the input
      sources. For :class:`CIMultiDict` sources it is a
      :class:`CIMultiDict`, otherwise a :class:`MultiDict`.

   .. attribute:: sources

      The source index for each output item, in :meth:`md.items()
      <multidict.MultiDict.items>` order.

   .. method:: items_with_sources()

      Return ``(key, value, source_index)`` for each output item.

.. class:: MergeItem

   A single output item with the index of the source it came from.

   .. attribute:: key

      The output key (the first occurrence's spelling).

   .. attribute:: value

      The output value.

   .. attribute:: source

      The index of the source this item came from.


Abstract Base Classes
=====================

The module provides two ABCs: ``MultiMapping`` and
``MutableMultiMapping``.  They are similar to
:class:`collections.abc.Mapping` and
:class:`collections.abc.MutableMapping` and inherited from them.

.. versionadded:: 3.3


Typing
======

The library is shipped with embedded type annotations, mypy just picks the annotations
by default.

:class:`MultiDict`, :class:`CIMultiDict`, :class:`MultiDictProxy`, and
:class:`CIMultiDictProxy` are *generic* types; please use the corresponding notation for
multidict value types, e.g. ``md: MultiDict[str] = MultiDict()``.

The type of multidict keys is always :class:`str` or a class derived from a string.

.. versionadded:: 3.7


Environment variables
=====================

.. envvar:: MULTIDICT_NO_EXTENSIONS

   An environment variable that instructs the packaging scripts to skip
   compiling the C-extension based variant of :mod:`multidict`.
   When used in runtime, it instructs the pure-Python variant to be imported
   from the top-level :mod:`multidict` entry-point package, even when the
   C-extension implementation is available.

   .. caution::

      The pure-Python (uncompiled) version is roughly 20-50 times slower than
      its C counterpart, depending on the way it's used.

.. envvar:: MULTIDICT_DEBUG_BUILD

   An environment variable that instructs the packaging scripts to compile
   the C-extension based variant of :mod:`multidict` with debug symbols.
   This is useful for debugging the C-extension code, but it will result in
   a larger binary size and worse performance.

   .. caution::

      The debug build is not intended for production use and should only be
      used for development and debugging purposes.
