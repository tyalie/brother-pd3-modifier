#!/usr/bin/env python3
import argparse
from analyze_lib import *
import re

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", help="Input file to analyze", required=True)
parser.add_argument("-e", "--extract", help="Output folder to extract to", required=False)
args = parser.parse_args()

with open(args.file, "rb") as fp:
  data = fp.read()

# check magic bytes
assert data[:4] == b"\x90\x80\x30\x6A", "Incompatible magic bytes"

# check type
assert (c := data[4:8]) == b"\x30\x00\x10\x03", f"Incorrect type (got {c})"

_given_checksum = int.from_bytes(data[0xE:0xE + 2], byteorder="little", signed=False)
_real_checksum = calc_checksum(data)
assert _given_checksum == _real_checksum, f"Mismatching checksum expected {_real_checksum:02x}"

# size (bytes) - seesm to have offset of 0x80 (start of table)
_size = 0x80 + int.from_bytes(data[0x10:0x14], byteorder="little", signed=False)
assert _size == len(data), f"Incorrect length in header (got {_size:08x})"

# check if color table
_table_type = read_null_str(data[0x20:])
assert _table_type == b"FP-COLOR", f"Incorrect table type. Make sure its color (got {_table_type})"

_version_name = read_null_str(data[0x40:])
assert _version_name is not None
assert re.match(rb"V\d{4}[A-Z]+_[A-Z]+", _version_name), f"Version didn't match pattern (get {_version_name})"
_version = int(_version_name[1:5])

# - match end of file with version number
assert _version == int(data[-3:]), f"Version didn't match. Abort (got {_version} vs {data[-3:]})"

_bitmap_list = list(parse_bitmap_table(data))

# start of bitmap files
_bitmap_start = _bitmap_list[0]

# - check whether all bitmaps are chained after each other
def check_bitmap_chain(data, b_offset=_bitmap_start):
  addr = b_offset
  _idx = 0

  while True:
    _header = data[addr:addr + 2]

    if _header != b"BM":
      print(f"Couldn't find BM bitmap (loc 0x{addr:08x})")

      _i = find_next_block(data[addr:])
      if _i is None:
        print("- Rest is empty -> good")
        return True
      else:
        print(f"- Found next bytes at (loc 0x{addr + _i:08x})")
        return False

    assert addr == _bitmap_list[_idx], f"Location mismatch (got {addr:08x} expected {_bitmap_list[_idx]:08x}@{_idx})"

    _length = int.from_bytes(data[addr + 2:addr + 6], byteorder="little", signed=False)

    if args.extract is not None:
      with open(f"{args.extract}/{_idx:04}-{addr:08X}.bmp", "wb") as fp:
        fp.write(data[addr:addr + _length])

    addr += _length
    _idx += 1

    if addr >= len(data):
      print("success")
      return True

check_bitmap_chain(data[:-3])
