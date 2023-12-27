import flask
import os
import paperutils
import random
from PIL import Image

try:
    from overlay import overlay
except ModuleNotFoundError:
    # File doesn't exist is fine; there's no customization. Stub in a no-op.
    def overlay(image: Image.Image, _request: flask.Request) -> Image.Image:
        return image
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
    directory = os.path.join("responses", "abcde"[index])
    try:
        filename = random.choice(os.listdir(directory))
    except FileNotFoundError:
        return paperutils.respond_txt("Directory for that button is missing")
    except IndexError:
        return paperutils.respond_txt("Directory for that button has no files")
    response: flask.Response
    if filename.lower().endswith(('jpg', 'png', 'pri')):
        im = Image.open(os.path.join(directory, filename))
        im = overlay(im, request)
        response = encode_for_inky(im, request)
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

def encode_for_inky(image: Image.Image, request: flask.Request
                    ) -> flask.Response:
    if request.user_agent.string == "PaperThin/1":
        return paperutils.respond_pri(paperutils.inky_dither(image))
    else:
        return paperutils.respond_png(image)
