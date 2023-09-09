#!/usr/bin/env python3
import argparse
from pathlib import Path
from dataclasses import asdict
import base64
import json
import re

from analyze_lib import *

def get_args():
  parser = argparse.ArgumentParser()
  parser.add_argument("-i", "--input", help="Input file / bitmap folder", required=True)
  sub_parser = parser.add_subparsers()

  lis = sub_parser.add_parser("list")
  lis.set_defaults(cmd = "list")

  ext = sub_parser.add_parser("extract")
  ext.set_defaults(cmd = "extract")
  ext.add_argument("-o", "--output", help="Output folder location", required=True)

  inc = sub_parser.add_parser("replace")
  inc.set_defaults(cmd = "replace")

  inc.add_argument("-b", "--bitmap", help="bitmap file to include", required=True)
  inc.add_argument("-o", "--output", help="output modified file", required=True)
  inc.add_argument("--idx", help="Index of bitmap to extract/replace", required=True)

  comb = sub_parser.add_parser("combine")
  comb.set_defaults(cmd = "combine")

  comb.add_argument("-o", "--output", help="output modified file", required=True)

  return parser.parse_args()

def _open_pd3(input_file: str):
  path = Path(input_file)
  if not path.is_file():
    raise Exception(f"File unknown ({path})")

  with path.open("rb") as fp:
    data = fp.read()

  verify_file(data)

  return data

def custom_encoder(z):
  if isinstance(z, bytes):
    return {"b64": base64.b64encode(z).decode("ascii")}
  else:
    type_name = z.__class__.__name__
    raise TypeError(f"Object of type {type_name} is not serializable")

def custom_decoder(z):
  if isinstance(z, dict) and "b64" in z:
    return base64.b64decode(z["b64"])
  else:
    return z

def cmd_list(input_file: str):
  data = _open_pd3(input_file)

  for bmp_idx, addr in parse_bitmap_table(data):
    print(f"#{bmp_idx:04} - ", end="")
    if addr is not None:
      length, img = read_bmp(data[addr:])
      _compr = [k for k,v in img.COMPRESSIONS.items() if v == img.info["compression"]][0]
      print(f"BMP {img.size} / Compr: {_compr} - 0x{length:0x} bytes")
    else:
      print("empty")

def cmd_extract(input_file: str, output_folder: str):
  data = _open_pd3(input_file)

  out_path = Path(output_folder)
  if not out_path.is_dir():
    raise Exception(f"Folder does not exist {out_path}")

  header = BD3Header.from_bytes(data)
  info_d = asdict(header)
  info_d["table"] = {}

  num = 0
  bmp_idx = 0
  for bmp_idx, addr in parse_bitmap_table(data):
    info_d["table"][bmp_idx] = {"addr": addr}

    if addr is not None:
      num += 1
      length, img = read_bmp(data[addr:])

      info_d["table"][bmp_idx]["size"] = img.size

      with open(out_path / f"{bmp_idx:04}-{img.size[0]}x{img.size[1]}.bmp", "wb") as fp:
        fp.write(data[addr:addr + length])

  with open(out_path / f"header.json", "w") as fp:
    json.dump(info_d, fp, indent=2, default=custom_encoder)

  print(f"Extracted {num}/{bmp_idx} files")

def cmd_combine(input_folder: str, output_file: str):
  in_dir = Path(input_folder)
  if not in_dir.is_dir():
    raise Exception(f"Expected input folder")

  with open(in_dir / "header.json", "r") as fp:
    _d = json.load(fp, object_hook=custom_decoder)
    table = {int(k): v for k, v in _d["table"].items()}
    del _d["table"]
    header = BD3Header(**_d)

  file_list = {}
  for file in in_dir.glob("*.bmp"):
    m = re.search(r"(?P<idx>\d+)-(?P<width>\d+)x(?P<height>\d+)", file.stem)
    if m is None:
      print(f"File ({file.name}) didn't match pattern")
      continue

    idx, width, height = int(m.group("idx")), int(m.group("width")), int(m.group("height"))
    if table[idx]['size'] != [width, height]:
      print(f"Warning: mismatching image dimensions (expected {table[idx]['size']}) for img #{idx}")
    file_list[idx] = {"size": (width, height), "filename": file}

  # derive table length
  _table_size = (len(table)+1) * 4

  # derive address
  d_body = bytearray()
  cum_addr = _table_size + TABLE_START_IDX

  for k in sorted(file_list):
    with file_list[k]["filename"].open("rb") as fp:
      bmp_data = fp.read()


    file_list[k]["addr"] = cum_addr
    cum_addr += len(bmp_data)
    d_body += bmp_data

  d_table = build_table(file_list)

  cum_size = TABLE_START_IDX + len(d_table) + len(d_body)
  if cum_size > header.x10_filesize - 3:
    print(f"max size exceeded by {cum_size - header.x10_filesize} (needed {header.x10_filesize})")

  _version_s = str(header.version).encode("ascii")
  d_fill = (b"\xff" * (header.x10_filesize - cum_size - len(_version_s))) + _version_s

  # stitch everything except header together
  d_data = d_table + d_body + d_fill

  new_checksum = calc_checksum(d_data, offset=0)
  header.x0E_checksum = new_checksum

  d_header = header.to_bytes()

  with open(output_file, "wb") as fp:
    fp.write(d_header)
    fp.write(d_data)

if __name__ == "__main__":
  args = get_args()
  print(args)
  match args.cmd:
    case "list":
      cmd_list(args.input)
    case "extract":
      cmd_extract(args.input, args.output)
    case "combine":
      cmd_combine(args.input, args.output)
    case v:
      raise Exception(f"Unknown command {v}")
