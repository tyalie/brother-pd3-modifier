#!/usr/bin/env python3
import argparse
from analyze_lib import *

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", help="Input file to analyze", required=True)
args = parser.parse_args()

with open(args.file, "rb") as fp:
  data = fp.read()

verify_file(data)
