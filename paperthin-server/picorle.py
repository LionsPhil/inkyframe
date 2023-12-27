# PicoRLE file format (version 2), image/x.pico-rle
# A tiny run-length-encoded file format for embedded applications with a very
# simple streaming decoder.
#
# Format (all little-endian):
#   "PRI2" literal header
#   16-bit unsigned width, then height, of image
#   Single byte palette size minus one, followed by palette, 256x3 RGB
#     Palette size of zero means a truecolor image
#     (Palette size of one makes no sense and cannot convey image data)
#   Then data is a sequence of spans:
#     One byte span length, then single pixel that is repeated that many times.
#     A zero-length span instead means the next byte is the number of "non-RLE"
#     pixels.
#
# There is deliberately no header expansibility, alpha support, alternate
# colorspace support, etc. Use a real image format like PNG if you need that.
#
# Copyright 2023 Philip Boulain.
# Licensed under the EUPL-1.2-or-later.

# https://github.com/python-pillow/Pillow/issues/3396
# Pillow versions before 8.2.0 will not preserve palettes below 256-color and
# will expand them. There is then a further bug with this:
# https://github.com/python-pillow/Pillow/issues/6046
# ...which is not fixed until 9.1.0. Make sure you're not on old Debian.

import io
import typing
from PIL import Image

def encode(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    writer = io.BufferedWriter(buf)  # Must stay alive until getvalue().
    encode_stream(image, writer)
    writer.flush()  # Else it silently truncates, which is nice.
    return buf.getvalue()

def encode_stream(image: Image.Image, out: io.BufferedWriter) -> None:
    truecolor: bool
    if image.mode == 'P':
        truecolor = False
    elif image.mode == 'RGB':
        truecolor = True
    else:
        # Alpha channels and other color spaces are not supported.
        raise ValueError(f"Unsupported image mode {image.mode}")

    # Header
    out.write(b"PRI2")
    out.write(image.width.to_bytes(length=2, byteorder='little'))
    out.write(image.height.to_bytes(length=2, byteorder='little'))

    # Palette
    if truecolor:
        out.write((0).to_bytes(length=1, byteorder='little'))
    else:
        pal = image.getpalette()
        palette_size = (len(pal) // 3) - 1
        out.write(palette_size.to_bytes(length=1, byteorder='little'))
        out.write(bytes(pal))  # List of ints, each <=255, allows this.

    # Image data
    bytes_per_pixel = 3 if truecolor else 1
    for y in range(0, image.height):
        span_pixel = -1
        span_count = 0
        unspan: typing.List[int] = []
        def write_unspan():
            if len(unspan) == 0:
                return
            elif len(unspan) == 1:
                # Simpler to just write this as a size-one span.
                out.write(b'\x01')
                out.write(unspan[0].to_bytes(length=bytes_per_pixel, byteorder='little'))
            else:
                # Write a zero, a size, and then the non-RLE'd pixels.
                out.write(b'\x00')
                out.write(len(unspan).to_bytes(length=1, byteorder='little'))
                for p in unspan:
                    out.write(p.to_bytes(length=bytes_per_pixel, byteorder='little'))
            unspan.clear()

        def write_span():
            if span_count == 0:
                write_unspan()  # Flush any unspan as well.
            elif span_count == 1:
                # Buffer this up as an unspan of non-contiguous pixels.
                unspan.append(span_pixel)
                if len(unspan) == 255:
                    write_unspan()  # Don't overflow unspan size.
            else:
                # A genuine RLE span!
                write_unspan()  # If we'd built one up.
                out.write(span_count.to_bytes(length=1, byteorder='little'))
                out.write(span_pixel.to_bytes(length=bytes_per_pixel, byteorder='little'))

        for x in range(0, image.width):
            pil_pixel = image.getpixel((x,y))
            pixel: int
            if truecolor:
                pixel = (pil_pixel[2]<<16) | (pil_pixel[1]<<8) | (pil_pixel[0])
            else:
                pixel = pil_pixel
            if pixel == span_pixel:
                # Extend the existing span.
                span_count += 1
                # Commit and start a new one if we reached max length.
                if span_count == 255:
                    write_span()
                    span_pixel = -1
                    span_count = 0
            else:
                # Commit the previous span, and start a new one of this.
                write_span()
                span_pixel = pixel
                span_count = 1
        # Write any leftover span (zero-length automatically ignored).
        write_span()
        # Flush any unspan as well; write_span() can refill this if the very
        # last column was a unique pixel.
        write_unspan()

def decode(pri: memoryview) -> Image.Image:
    # Convert our memoryview into a read stream.
    return decode_stream(io.BufferedReader(io.BytesIO(pri)))

def decode_stream(pri: io.BufferedReader) -> Image.Image:
    # Header
    if pri.read(4) != b"PRI2":
        raise ValueError("Incorrect magic header")
    width = int.from_bytes(pri.read(2), byteorder='little')
    height = int.from_bytes(pri.read(2), byteorder='little')

    # Palette
    palette_size = int.from_bytes(pri.read(1), byteorder='little')
    truecolor: bool
    image: Image.Image
    if palette_size == 0:
        truecolor = True
        image = Image.new('RGB', (width, height))
    else:
        truecolor = False
        image = Image.new('P', (width, height))
        palette_size += 1
        palette_data = bytearray(palette_size * 3)
        pri.readinto(palette_data)
        image.putpalette(palette_data)

    # Image data
    bytes_per_pixel = 3 if truecolor else 1
    span_data = bytearray(2)  # 2, even for truecolor
    for y in range(0, height):
        x = 0
        while x < width:
            if pri.readinto(span_data) != 2:
                raise ValueError("File truncated")
            count = int(span_data[0])
            value = int(span_data[1])
            if count == 0:
                # This is actually an unspan; value is the number of pixels.
                unspan_data = pri.read(value * bytes_per_pixel)
                pixels: typing.List[typing.Union[int,typing.Tuple[int,int,int]]]
                if truecolor:
                    pixels = []
                    for i in range(0, len(unspan_data), 3):
                        pixels.append((unspan_data[i],
                                       unspan_data[i+1],
                                       unspan_data[i+2]))
                else:
                    pixels = unspan_data
                for pixel in pixels:
                    image.putpixel((x, y), pixel)
                    x += 1
            else:
                # Normal RLE span.
                pixel: typing.Union[int,typing.Tuple[int,int,int]]
                if truecolor:
                    # We need to read two more bytes to complete the pixel.
                    green_blue = bytearray(2)
                    pri.readinto(green_blue)
                    pixel = (value, int(green_blue[0]), int(green_blue[1]))
                else:
                    pixel = value
                while count > 0:
                    image.putpixel((x, y), pixel)
                    x += 1
                    count -= 1

    return image
