import flask
import io
import picorle
import wand.image  # Try --no-install-recommends with python3-wand in Debian.
from PIL import Image, ImageEnhance
from wand.color import Color
from wand.drawing import Drawing

# PIL is "standard", but Wand (ImageMagick) is needed to do better dithering.
# At least we don't up dragging ing Anti-Grain Geometry too; almost did.

# See inky_dither() for information about these constants.
# https://www.instructables.com/Pimoroni-Inky-Frame-Comparison-4-Inch-Vs-57-Inch/
_PICOGRAPHICS_PALETTE = [
    0x00, 0x00, 0x00, # black
    0xFF, 0xFF, 0xFF, # white
    0x00, 0xFF, 0x00, # green
    0x00, 0x00, 0xFF, # blue
    0xFF, 0x00, 0x00, # red
    0xFF, 0xFF, 0x00, # yellow
    0xFF, 0x80, 0x00, # orange (this seems to still get dithered)
    0xDC, 0xB4, 0xC8, # taupe/e-ink clean (also still dithered)
]
_INK_PALETTE = [
    0x00, 0x00, 0x00, # black
    0xFF, 0xFF, 0xFF, # white
    0x4D, 0x8B, 0x4D, # green
    0x4D, 0x4F, 0x95, # blue
    0xFF, 0x44, 0x31, # red
    0xFD, 0xF6, 0x3B, # yellow
    0xFE, 0xA4, 0x3A, # orange
    0xEB, 0xE2, 0xD9, # taupe
]

def _hexorcize(palindex: int) -> str:
    palindex *= 3
    r = _INK_PALETTE[palindex + 0]
    g = _INK_PALETTE[palindex + 1]
    b = _INK_PALETTE[palindex + 2]
    return f"#{r:02x}{g:02x}{b:02x}"

# Export the "native" colors (but note gotcha with last two).
BLACK = _hexorcize(0)
WHITE = _hexorcize(1)
GREEN = _hexorcize(2)
BLUE = _hexorcize(3)
RED = _hexorcize(4)
YELLOW = _hexorcize(5)
ORANGE = _hexorcize(6)
TAUPE = _hexorcize(7)

def add_refresh(response: flask.Response, seconds: int, url: str) -> None:
    response.headers.add('Refresh', f'{seconds}; {url}')

def wand_to_pil(wand_image: wand.image.Image) -> Image.Image:
    # The encode/decode here is kind of stupid, but.
    return Image.open(io.BytesIO(wand_image.make_blob('png')), formats=['PNG'])

def pil_to_wand(pil_image: Image.Image) -> wand.image.Image:
    buf = io.BytesIO()
    pil_image.save(buf, format='PNG')
    return wand.image.Image(blob=buf.getvalue(), format='png')

def inky_dither(original: Image.Image, use_taupe = False, use_wand = True
                ) -> Image.Image:
    """Dither an image down to the Inky palette."""
    # PicoGraphics has a "simplified" idea of the ink colors, and dithers to
    # that. This instead dithers to some eyeballed approximations of the
    # actual ink colors, and then remaps that to the ones PicoGraphics will use
    # to try to stop it from misdithering the image again.
    picographics_palette = _PICOGRAPHICS_PALETTE.copy()
    ink_palette = _INK_PALETTE.copy()
    if not use_taupe:
        picographics_palette.pop()
        ink_palette.pop()
    palimg = Image.new('P', (len(ink_palette), 1))
    palimg.putpalette(ink_palette)

    if use_wand:
        wand_img = pil_to_wand(original)
        # ImageMagick does not use the palette, it uses the *pixels*, because it
        # is Like That. So set a pixel of each color, using PIL, because wand
        # isn't really built for that.
        for x in range(0, len(ink_palette)):
            palimg.putpixel((x, 0), x)
        wand_palimg = pil_to_wand(palimg)
        # Try doing the remap in HSL space. See wand.image.COLORSPACE_TYPES.
        # Lots of these just break...LAB, HSV, YUV, even gray; the transform
        # is fine, but the remap is then busted...annoyingly ImageMagick
        # supports this! https://imagemagick.org/Usage/quantize/
        # However, non-s RGB works...and gets us some white into the cyan!!!
        # ...and it makes images turn too green/blue :C
        # Detuning the red channel 4Ds to 0Ds in the green/blue inks doesn't
        # help much, but some gamma correction does, if a bit of a hack.
        wand_img.transform_colorspace('rgb')
        wand_palimg.transform_colorspace(wand_img.colorspace)
        wand_img.gamma(1.2, channel='red')
        wand_img.gamma(0.9, channel='green')
        wand_img.gamma(0.9, channel='blue')
        wand_img.brightness_contrast(20.0, 20.0)
        # floyd_steinberg looks nicer than riemersma
        wand_img.remap(affinity=wand_palimg, method='floyd_steinberg')
        wand_img.transform_colorspace('srgb')  # If *this* is plain rgb, corrupt
        dithered = wand_to_pil(wand_img)
        # ImageMagick will have output whatever colorspace it feels like; it may
        # be a one-bit image, it may be palettized with different indicies. We'd
        # quite like to use the right fixed palette, but to do *that* we first
        # need to raise it up to RGB. It's all a bit of a farce.
        dithered = dithered.convert('RGB')
        # This is spelled Image.Dither.NONE in newer PIL, but old is compatible.
        dithered = dithered.quantize(palette=palimg, dither=Image.NONE)
        # Give the GC a hand.
        wand_palimg.close()
        wand_img.close()
    else:
        dithered = original.quantize(palette=palimg)

    # Forcefully remap indexwise to the palette.
    dithered.putpalette(picographics_palette)

    palimg.close()
    return dithered

def plain_dither(original: Image.Image, use_taupe = False) -> Image.Image:
    """Dithered an image to the synthetic palette, uncorrected."""
    picographics_palette = _PICOGRAPHICS_PALETTE.copy()
    if not use_taupe:
        picographics_palette.pop()
    palimg = Image.new('P', (1, 1))
    palimg.putpalette(picographics_palette)
    return original.quantize(palette=palimg)

def suggested_enhance(original: Image.Image) -> Image.Image:
    """Enhance an image as recommended by Pimoroni."""
    # https://learn.pimoroni.com/article/getting-started-with-inky-frame
    # First saturation.
    im = ImageEnhance.Color(original).enhance(1.3)
    # Then brightness, since we can't quite do black level.
    # Wand's level() seems to be the inverse of what we want.
    return ImageEnhance.Brightness(im).enhance(1.02)

def resize_image(image: Image.Image, request: flask.Request) -> Image.Image:
    """Resize an image to fit within the dimensions in the request."""
    want_w = request.args.get('w', 800, type=int)
    want_h = request.args.get('h', 480, type=int)
    want_aspect = float(want_w) / float(want_h)
    got_w = image.width
    got_h = image.height
    got_aspect = float(got_w) / float(got_h)
    w: int
    h: int
    if got_aspect > want_aspect:
        # Width-constrained scaling
        w = want_w
        h = int(want_w / got_aspect)
    else:
        # Height-constrained scaling
        w = int(want_h * got_aspect)
        h = want_h

    resized = image.resize([w, h])
    if resized.width != want_w or resized.height != want_h:
        # Calculate the average color using another resize, then pad the image.
        padding = image.resize([4, int(4 / want_aspect)])
        padding = padding.resize([want_w, want_h])
        offset_w = int((want_w - resized.width) / 2)
        offset_h = int((want_h - resized.height) / 2)
        padding.paste(resized, [offset_w, offset_h])
        resized.close()
        resized = padding

    return resized

def caption(image: Image.Image, caption: str) -> Image.Image:
    """Return a new version of the image with a caption added."""
    # Intended as a very generic easy fixed thing. The easiest way to customize
    # it is to replace it.
    wim = pil_to_wand(image)
    with Drawing() as draw:
        draw.stroke_width = 0
        draw.push()
        draw.fill_opacity = 0.5
        draw.fill_color = Color('black')
        draw.rectangle(left=0, top=image.height - 24,
                       right=image.width, bottom=image.height)
        draw.pop()
        draw.font = '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'
        draw.font_size = 18
        draw.gravity = 'south_west'
        draw.fill_color = Color('white')
        draw.text(0, 0, caption)
        draw(wim)
    image = wand_to_pil(wim)
    wim.close()
    return image


def respond_png(image: Image.Image, dither = False) -> flask.Response:
    """Build a response from a PIL image by PNG-encoding it."""
    # If the image has been pre-dithered, this is potentially small enough to
    # not need to be buffered to flash---tens of kilobytes. There is no JPEG
    # version of this because it seems very unlikely you want lossy, truecolor,
    # photo-suitable compression for an in-memory image.
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    # If we just give flask the BytesIO, it will stream it as chunked, which
    # the PaperThin client cannot handle.
    response: flask.Response = flask.make_response(buf.getvalue())
    response.mimetype = 'image/png'
    if dither:
        response.headers['X-Dither'] = 'True'
    return response

def respond_pri(image: Image.Image) -> flask.Response:
    """Build a response from a PIL image by PRI-encoding it."""
    buf = picorle.encode(image)
    response: flask.Response = flask.make_response(buf)
    response.mimetype = 'image/x.pico-rle'
    return response

def respond_txt(text: str) -> flask.Response:
    """Build a response from UTF-8 plaintext."""
    response: flask.Response = flask.make_response(text, 200)
    response.content_type = 'text/plain; charset=utf-8'
    return response

def respond_file(directory: str, filename: str, dither: bool) -> flask.Response:
    """Respond directly with a preprocessed PNG, JPG, TXT, or PRI file."""
    if filename.lower().endswith('png'):
        mimetype = 'image/png'
    elif filename.lower().endswith('jpg'):
        mimetype = 'image/jpeg'
    elif filename.lower().endswith('txt'):
        mimetype = 'text/plain'
    elif filename.lower().endswith('pri'):
        mimetype = 'image/x.pico-rle'
    else:
        raise ValueError(f'file "{filename}" has unsupported extension')
    response = flask.make_response(flask.send_from_directory(
        directory,
        filename,
        mimetype=mimetype,
        as_attachment=False,
        conditional=False))
    if dither:
        response.headers['X-Dither'] = 'True'
    return response

def encode_for_inky(image: Image.Image, request: flask.Request
                    ) -> flask.Response:
    if request.user_agent.string == "PaperThin/1":
        return respond_pri(inky_dither(image))
    else:
        # Add an inky_dither here (but keep PNG) to test in a browser.
        return respond_png(image)
