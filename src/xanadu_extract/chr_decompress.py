"""Decompress Falcom's compressed .chr / .map archive payload.

This is the FUN_004e4260 path of the dispatcher in FUN_0044ab70 (XANADU.exe).
Every .chr file we have inspected has byte 2 = 0x00 which selects this
single-shot bitstream decoder; the alternate FUN_004e3fe0 chunked decoder
is for content we haven't seen on disk yet and isn't implemented here.

Output structure
----------------
The decompressed buffer is what the engine then hands to FUN_004f4130
(per-Frame parser).  Bytes 0..3 are the file header read+discarded by
FUN_004f4650; the parser then consumes from byte 4 onward.

Bitstream
---------
- 8-bit initial control word (the byte at input_ptr+1 of the file, i.e.
  byte 3 of the .chr file).  ``input_ptr`` then advances to byte 4.
- Every subsequent control refill reads a 16-bit little-endian word.
- Bits are consumed LSB first.  Variable-length fields (helper
  FUN_004e4200) accumulate MSB-first: ``v = (v << 1) | bit``.

Per-token decode
----------------
Read 1 control bit:

- ``0``  literal — copy 1 byte from input.

- ``1``  back-reference — read another bit:
    - ``0``  ``offset = next_byte()``      (8-bit short offset)
    - ``1``  ``offset = (read_bits(5) << 8) | next_byte()``  (13-bit)
  Sentinel: ``offset == 0`` → end of stream (return).
  ``offset == 1`` → RLE long form (see below).
  Otherwise, the copy length comes from a unary code:
    - bit 1                       → length = 2
    - bits 0,1                    → length = 3
    - bits 0,0,1                  → length = 4
    - bits 0,0,0,1                → length = 5
    - bits 0,0,0,0,1              → length = read_bits(3) + 6
    - bits 0,0,0,0,0              → length = next_byte() + 14
  Then copy ``length`` bytes from ``output[-offset:]``.

RLE long form (offset == 1)
---------------------------
Read 1 bit:
  - ``0``  length is encoded as 4 bits, ``length = read_bits(4) + 0xf``
  - ``1``  length is 4 bits + 8 bits, ``length = (read_bits(4) << 8) +
           next_byte() + 0x10``
Then read 1 byte ``v`` and emit ``v`` repeated ``length + 0xe`` times.
"""

from __future__ import annotations


class ChrDecompressError(Exception):
    pass


class _BitReader:
    __slots__ = ("buf", "pos", "word", "bits")

    def __init__(self, buf: bytes, start: int) -> None:
        self.buf = buf
        # FUN_004e4260 setup: control_word = byte at input+1 (8 bits),
        # then input += 2.
        self.word = buf[start + 1]
        self.bits = 8
        self.pos = start + 2

    def get_bit(self) -> int:
        if self.bits == 0:
            self.word = self.buf[self.pos] | (self.buf[self.pos + 1] << 8)
            self.pos += 2
            self.bits = 16
        b = self.word & 1
        self.word >>= 1
        self.bits -= 1
        return b

    def read_bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.get_bit()
        return v

    def read_byte(self) -> int:
        b = self.buf[self.pos]
        self.pos += 1
        return b


def decompress(payload: bytes) -> bytes:
    """Decompress one .chr/.map file payload.  Input is the entire archive
    entry as it appears on disk."""
    # The dispatcher in FUN_0044ab70 reads bytes [0:2] as a chunk-size
    # header and dispatches on byte [2].  For FUN_004e4260, byte [2] must
    # be 0; the decoder then takes input pointer = byte 2, and its setup
    # sets control_word = byte 3 and advances input to byte 4.
    if len(payload) < 4:
        raise ChrDecompressError("payload too small")
    if payload[2] != 0:
        raise ChrDecompressError(
            f"byte 2 = {payload[2]:#x}, expected 0 (FUN_004e4260 path)"
        )

    br = _BitReader(payload, start=2)
    out = bytearray()

    while True:
        if br.get_bit() == 0:
            # literal byte
            out.append(br.read_byte())
            continue

        # back-reference: 8-bit short offset OR 13-bit extended.  The
        # special offset values (0 = terminator, 1 = RLE long-form) only
        # apply to the 13-bit path; an 8-bit byte of value 0 or 1 is a
        # regular back-reference.
        if br.get_bit() == 0:
            offset = br.read_byte()
        else:
            high = br.read_bits(5)
            low = br.read_byte()
            offset = (high << 8) | low

            if offset == 0:
                return bytes(out)

            if offset == 1:
                # RLE long form (only valid for 13-bit offsets)
                if br.get_bit() == 0:
                    length = br.read_bits(4)
                else:
                    length = (br.read_bits(4) << 8) | br.read_byte()
                value = br.read_byte()
                out.extend(bytes([value]) * (length + 0xE))
                continue

        # length unary code
        if br.get_bit() == 1:
            length = 2
        elif br.get_bit() == 1:
            length = 3
        elif br.get_bit() == 1:
            length = 4
        elif br.get_bit() == 1:
            length = 5
        elif br.get_bit() == 1:
            length = br.read_bits(3) + 6
        else:
            length = br.read_byte() + 14

        # copy `length` bytes from `len(out) - offset`
        base = len(out) - offset
        if base < 0:
            raise ChrDecompressError(
                f"backref before output start (offset={offset}, len={len(out)})"
            )
        for i in range(length):
            out.append(out[base + i])
