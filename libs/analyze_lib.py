import itertools
from dataclasses import dataclass, asdict
from typing import Dict, Any
import struct
import re

MAGIC_BYTES = b"\x90\x80\x30"
COLOR_MAGIC_BYTES = b"\x30\x00\x01\x03"
TABLE_START_IDX = 0x80
STR_COLOR_TABLE = "FP-COLOR"
RE_VERSION_PATTERN = r"V\d{4}[A-Z]+_[A-Z]+"

class VerifyException(Exception):
  ...

@dataclass
class BD3Header:
  x00_magic_bytes: bytes
  x03_device: int
  x04_pd3_type: bytes
  _x14_res0: bytes
  x0E_checksum: int
  _x10_filesize: int
  _x14_res1: bytes
  _x20_table_name: bytes
  _x40_version_name: bytes
  _x60_res2: bytes

  STRUCT_FORMAT = "<3sc4s6sHI12s32s32s32s"
  @classmethod
  def from_bytes(cls, data):
    if len(data) < struct.calcsize(cls.STRUCT_FORMAT):
      raise VerifyException("Insufficient size")

    pack = struct.unpack_from(cls.STRUCT_FORMAT, data)
    return cls(*pack)

  def to_bytes(self) -> bytes:
    return struct.pack(self.STRUCT_FORMAT, *asdict(self).values())

  @property
  def version(self) -> int:
    return int(self.version_name[1:5])

  @property
  def version_name(self) -> str:
    return read_null_str(self._x40_version_name).decode("ascii")

  @property
  def table_name(self) -> str:
    return read_null_str(self._x20_table_name).decode("ascii")

  @property
  def x10_filesize(self) -> int:
    return self._x10_filesize + 0x80

def build_table(table: Dict[int, Any]):
  table_b = bytearray()
  table_b += struct.pack("<I", 4)
  offset = TABLE_START_IDX + 4

  for k in sorted(table):
    while k - ((offset-TABLE_START_IDX)//4) > 0:
      table_b += b"\xff\xff\xff\xff"
      offset += 4

    table_b += struct.pack("<I", table[k]["addr"] - offset)
    offset += 4

  return table_b

def _read_bmp_filesize(data):
  _header = data[:2]
  if _header != b"BM":
    raise VerifyException("Not a BMP image")

  _length = int.from_bytes(data[2:6], byteorder="little", signed=False)
  return _length

def read_bmp(data):
  from PIL import Image
  from io import BytesIO

  length = _read_bmp_filesize(data)
  img = Image.open(BytesIO(data))
  return length, img

def read_null_str(data: bytes) -> bytes:
  for idx in range(len(data)):
    if data[idx] == 0:
      return data[:idx]
  return b""

def find_next_block(data, pattern=0xFF):
  for i, b in enumerate(data):
    if b != pattern:
      return i
  return None

def calc_checksum(data, offset=0x80):
  return sum(data[offset:]) & 0xFFFF

def parse_bitmap_table(data, t_offset=0x80):
  """
  parse position table (I guess?)
  there seems to be some kind of bitmap idx table starting at position 0x80
  note here that all bytes are in 32bit little endian. The first byte seems
  to indicate the byte length (I guess?) with int 4. Afterwards we the addresses
  start. Each address is an offset to the current position of the number. e.g.

  first bitmap is at 0xECC, our offset is in 0x84 so the offset is (0xECC - 0x84) = 0xE48
  00000080   04 00 00 00  48 0E 00 00
  """
  i_data = enumerate(map(
    lambda a: int.from_bytes(a, byteorder="little", signed=False),
    itertools.zip_longest(*[iter(data[t_offset:])] * 4)
  ))
  _, byte_length = next(i_data)
  assert byte_length == 4, f"Expected byte length of 4, got {byte_length}"

  for idx, b_offset in i_data:
    _t_addr = idx * 4 + t_offset
    if data[_t_addr:_t_addr + 2] == b"BM":
      print(f"Got {idx+1} table entries (including errors and header)")
      return

    if b_offset != 0xFFFFFFFF:
      yield idx, _t_addr + b_offset
    else:
      print(f"- Got undefined location at idx {idx} -> ignore")
      yield idx, None

def check_bitmap_chain(data, _bitmap_list, b_offset):
  """
  Check whether all bmp files are chained together
  also verify that detected position matches with bitmap list
  """
  addr = b_offset
  _idx = 0

  while True:
    try:
      _length = _read_bmp_filesize(data[addr:])
    except VerifyException:
      print(f"Couldn't find BM bitmap (loc 0x{addr:08x})")

      _i = find_next_block(data[addr:])
      if _i is None:
        print("- Rest is empty -> good")
        return True
      else:
        print(f"- Found next bytes at (loc 0x{addr + _i:08x})")
        return False

    if addr != _bitmap_list[_idx]:
      raise VerifyException(f"Location mismatch (got {addr:08x} expected {_bitmap_list[_idx]:08x}@{_idx})")

    addr += _length
    _idx += 1

    if addr >= len(data):
      print("success")
      return True

def verify_header(data, device) -> bool:
  header = BD3Header.from_bytes(data)

  # check magic bytes (for device 0x6A)
  if header.x00_magic_bytes != MAGIC_BYTES and header.x03_device == device:
    raise VerifyException(f"Incompatible magic bytes (got {data[:3].hex()}; expected {MAGIC_BYTES.hex()})")

  if header.x04_pd3_type == COLOR_MAGIC_BYTES:
    raise VerifyException(f"Incorrect type (got {header.x04_pd3_type})")

  _real_checksum = calc_checksum(data)
  if header.x0E_checksum != _real_checksum:
    raise VerifyException(f"Mismatching checksum (excepted {_real_checksum:02x} got {header.x0E_checksum:02x})")

  # verify file size
  if header.x10_filesize != len(data):
    raise VerifyException(f"Incorrect length in header (got {header.x10_filesize:08x})")

  # check if it is a color table
  if header.table_name != STR_COLOR_TABLE:
    raise VerifyException(f"Incorrect table type. Make sure its color (got {header.table_name})")

  if not re.match(RE_VERSION_PATTERN, header.version_name):
    raise VerifyException(f"Version didn't match pattern (get {header.version_name})")

  # match end of file, which should match version
  if header.version != int(data[-3:]):
    raise VerifyException(f"Version didn't match. Abort (got {header.version} vs {data[-3:]})")

  return True


def verify_body(data) -> bool:
  _bitmap_list = list(map(lambda v: v[1], filter(lambda a: a[1] is not None, parse_bitmap_table(data))))
  _bitmap_start = _bitmap_list[0]

  if not check_bitmap_chain(data[:-3], _bitmap_list, _bitmap_start):
    raise VerifyException("Couldn't verify body")

  return True


def verify_file(data, device=0x6A) -> bool:
  verify_header(data, device)
  verify_body(data)
  return True
