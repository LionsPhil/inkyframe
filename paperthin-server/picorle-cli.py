#!/usr/bin/env python3
# PicoRLE command line tool.
#
# Note: this is *not* compatible with convertimg for Tufty, since that uses the
# similar v1 file format without the header or truecolor support. It also
# doesn't do any resizing or palletizing of the image for you.
#
# Copyright 2023 Philip Boulain.
# Licensed under the EUPL-1.2-or-later.

import argparse
import sys
import os
import picorle
from PIL import Image

arg_parser = argparse.ArgumentParser(
    description="Pico RLE Image encoder.",
    epilog="Encodes any image PIL can read to PicoRLE, or decodes PicoRLE to "
           "any image PIL can write (type determined by file extension).")
arg_parser.add_argument("infile", help="File to read")
arg_parser.add_argument("outfile", help="File to write, will be overwritten")
arg_parser.add_argument("--decode", action="store_true",
    help="Decode the input to the output, instead of encode")
args = arg_parser.parse_args()

if args.decode:
    with open(args.infile, "rb") as prifile:
        image = picorle.decode_stream(prifile)
        image.save(args.outfile)
else:
    image = Image.open(args.infile)
    with open(args.outfile, "wb") as prifile:
        picorle.encode_stream(image, prifile)
