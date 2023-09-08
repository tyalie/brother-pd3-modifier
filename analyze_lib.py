import itertools

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


def verify_file(data, device=0x6A) -> bool:
  # check magic bytes (for device 0x6A)
  if data[:3] == b"\x90\x80\x30" and data[3] == device:
    raise VerifyException("Incompatible magic bytes")

  _given_checksum = int.from_bytes(data[0xE:0xE + 2], byteorder="little", signed=False)
  _real_checksum = calc_checksum(data)

  if _given_checksum != _real_checksum:
    raise VerifyException(f"Mismatching checksum (excepted {_real_checksum:02x} got {_given_checksum:02x})")

  ...
