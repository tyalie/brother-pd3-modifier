import itertools
import re

MAGIC_BYTES = b"\x90\x80\x30"
COLOR_MAGIC_BYTES = b"\x30\x00\x01\x03"
TABLE_START_IDX = 0x80
STR_COLOR_TABLE = b"FP-COLOR"
RE_VERSION_PATTERN = rb"V\d{4}[A-Z]+_[A-Z]+"

class VerifyException(Exception):
  ...

def read_null_str(data):
  for idx in range(len(data)):
    if data[idx] == 0:
      return data[:idx]

def find_next_block(data, pattern=0xFF):
  for i, b in enumerate(data):
    if b != pattern:
      return i
  return None

def calc_checksum(data):
  return sum(data[0x80:]) & 0xFFFF

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
      yield _t_addr + b_offset
    else:
      print(f"- Got undefined location at idx {idx} -> ignore")

def check_bitmap_chain(data, _bitmap_list, b_offset):
  """
  Check whether all bmp files are chained together
  also verify that detected position matches with bitmap list
  """
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

    if addr != _bitmap_list[_idx]:
      raise VerifyException(f"Location mismatch (got {addr:08x} expected {_bitmap_list[_idx]:08x}@{_idx})")

    _length = int.from_bytes(data[addr + 2:addr + 6], byteorder="little", signed=False)

    addr += _length
    _idx += 1

    if addr >= len(data):
      print("success")
      return True

def verify_header(data, device) -> bool:
  # check magic bytes (for device 0x6A)
  if data[:3] != MAGIC_BYTES and data[3] == device:
    raise VerifyException(f"Incompatible magic bytes (got {data[:3].hex()}; expected {MAGIC_BYTES.hex()})")

  if (c := data[4:8]) == COLOR_MAGIC_BYTES:
    raise VerifyException(f"Incorrect type (got {c})")

  _given_checksum = int.from_bytes(data[0xE:0xE + 2], byteorder="little", signed=False)
  _real_checksum = calc_checksum(data)
  if _given_checksum != _real_checksum:
    raise VerifyException(f"Mismatching checksum (excepted {_real_checksum:02x} got {_given_checksum:02x})")

  # verify file size
  _size = TABLE_START_IDX + int.from_bytes(data[0x10:0x14], byteorder="little", signed=False)
  if _size != len(data):
    raise VerifyException(f"Incorrect length in header (got {_size:08x})")

  # check if it is a color table
  _table_type = read_null_str(data[0x20:])
  if _table_type is None or _table_type != STR_COLOR_TABLE:
    raise VerifyException(f"Incorrect table type. Make sure its color (got {_table_type})")

  _version_name = read_null_str(data[0x40:])
  if _version_name is None or not re.match(RE_VERSION_PATTERN, _version_name):
    raise VerifyException(f"Version didn't match pattern (get {_version_name})")

  # match end of file, which should match version
  _version = int(_version_name[1:5])
  if _version != int(data[-3:]):
    raise VerifyException(f"Version didn't match. Abort (got {_version} vs {data[-3:]})")

  return True


def verify_body(data) -> bool:
  _bitmap_list = list(parse_bitmap_table(data))
  _bitmap_start = _bitmap_list[0]

  if not check_bitmap_chain(data[:-3], _bitmap_list, _bitmap_start):
    raise VerifyException("Couldn't verify body")

  return True


def verify_file(data, device=0x6A) -> bool:
  verify_header(data, device)
  verify_body(data)
  return True
