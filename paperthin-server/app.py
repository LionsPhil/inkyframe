import flask
import os
import paperutils
import random
from PIL import Image

try:
    from overlay import overlay, button_override
except ModuleNotFoundError:
    # File doesn't exist is fine; there's no customization. Stub in a no-op.
    def overlay(image: Image.Image, _request: flask.Request) -> Image.Image:
        return image
    def button_override(_index: int, _request: flask.Request
                        ) -> flask.Response|None:
        return None
# ImportError, however, means customization was attempted and is bad.
# Let it propagate.

app = flask.Flask(__name__)

@app.route("/")
def index():
    return flask.redirect("/a")

@app.route("/hello")
def hello():
    return "", 204

@app.route("/a", methods=("GET", "POST"))
def button_a():
    return button(0, flask.request)

@app.route("/b", methods=("GET", "POST"))
def button_b():
    return button(1, flask.request)

@app.route("/c", methods=("GET", "POST"))
def button_c():
    return button(2, flask.request)

@app.route("/d", methods=("GET", "POST"))
def button_d():
    return button(3, flask.request)

@app.route("/e", methods=("GET", "POST"))
def button_e():
    return button(4, flask.request)

@app.route("/heartbeat")
def heartbeat():
    return "", 204

def button(index: int, request: flask.Request) -> flask.Response:
    maybe_response = button_override(index, request)
    if maybe_response:
        return maybe_response
    directory = os.path.join("responses", "abcde"[index])
    try:
        filename = random.choice(os.listdir(directory))
    except FileNotFoundError:
        return paperutils.respond_txt("Directory for that button is missing")
    except IndexError:
        return paperutils.respond_txt("Directory for that button has no files")
    response: flask.Response
    if filename.lower().endswith(('jpg', 'png', 'pri')):
        with Image.open(os.path.join(directory, filename)) as im:
            overlaid_im = overlay(im, request)
            response = paperutils.encode_for_inky(overlaid_im, request)
            overlaid_im.close()
    else:
        response = paperutils.respond_file(directory, filename, True)
    # 10 minutes less one, for PRI decode and e-ink refresh.
    # Flask wasted hours of my time here because request.base_url is SUPPOSED
    # to include the port if nonstandard...and just doesn't! Yay! Because the
    # PaperThin client was leaving it out of the Host header. :C
    paperutils.add_refresh(response, 540, request.base_url)
    return response
    # Encoding findings:
    # inky_dither(suggested_enhance(im), use_wand=False)  # <-- Oversaturates
    # suggested_enhance(im)  # <-- Looks best
    # inky_dither(im)  # <-- PIL dithering lets it down, ends up dark
    # inky_dither(im, use_wand=True)  # <-- Wand sRGB dithering is good, finally
    # plain_dither(suggested_enhance(im)))  # <-- Iffy
