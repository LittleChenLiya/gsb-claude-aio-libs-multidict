.. _multidict-codec:

=============
MultiDict 编解码器
=============

.. module:: multidict.codec

:mod:`multidict.codec` 提供字符串 :class:`~multidict.MultiDict` 和
:class:`~multidict.CIMultiDict` 的紧凑二进制编解码器。

协议版本、字典类别、项数以及每项的 UTF-8 字节长度都在线格式中显式编码。
重复键保留其原始插入顺序。:class:`~multidict.CIMultiDict` 往返后保留
原始键拼写。

字节格式
========

所有多字节整数均为无符号 `LEB128`_ varint（每字节 7 个数据位，最低有效组
在前，除最后一字节外最高位均置 1）。

.. code-block:: text

    +--------+---------+----------+------------------+
    | magic  | version | category | item_count (var) |
    +--------+---------+----------+------------------+
    | 每项:                                            |
    |   key_len (var) | key_bytes (UTF-8)             |
    |   value_len (var) | value_bytes (UTF-8)         |
    +-------------------------------------------------+

字段说明
--------

* ``magic`` -- ``b"MD"``（2 字节），标识协议。
* ``version`` -- 协议版本，当前为 ``1``（1 字节）。
* ``category`` -- ``0`` 表示 :class:`~multidict.MultiDict`，``1`` 表示
  :class:`~multidict.CIMultiDict`（1 字节）。
* ``item_count`` -- 后续 ``(key, value)`` 对的数量。
* 每项由长度前缀的 UTF-8 键和长度前缀的 UTF-8 值组成。

空键按协议正常处理：键长度为 ``0``，后接零字节键内容。

.. _LEB128: https://en.wikipedia.org/wiki/LEB128

编码
====

.. autofunction:: encode

所有键和值必须为 :class:`str`。非字符串值会被拒绝并抛出
:class:`TypeError`。

解码
====

一次性解码使用 :func:`decode`。流式解码使用 :class:`Decoder`，它接受任意
小块输入（逐字节也可）。

.. autofunction:: decode

.. autoclass:: Decoder
   :members:

限额
----

解码器实施可配置的限额：项数、单键字节长度、单值字节长度和数据包总大小。
当 varint 声明的长度超过对应限额时，会立即抛出
:class:`LimitExceededError` -- 在读取任何载荷字节之前。

截断的数据包不会交付半个字典：:meth:`Decoder.result` 会抛出
:class:`IncompletePacketError`，直到收到完整数据包。

异常
====

.. autoexception:: CodecError
.. autoexception:: IncompletePacketError
.. autoexception:: InvalidPacketError
.. autoexception:: LimitExceededError

命令行
======

``multidict.codec`` 模块提供命令行接口，用于在简单的行文本格式和二进制
格式之间转换。

文本格式：
    第一行: ``multidict`` 或 ``cimultidict``。
    后续行: ``key=value``（键和值以第一个 ``=`` 分隔）。

示例::

    $ printf 'cimultidict\nA=1\na=2\nB=3\n' | python -m multidict.codec encode | python -m multidict.codec decode
    cimultidict
    A=1
    a=2
    B=3
