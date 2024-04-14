# Uncomment the line for your Inky Frame display size.
# from picographics import PicoGraphics, DISPLAY_INKY_FRAME_4 as DISPLAY  # 4.0"
# from picographics import PicoGraphics, DISPLAY_INKY_FRAME as DISPLAY    # 5.7"
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_7 as DISPLAY  # 7.3"

# PaperThin server location, and which paths each button should fetch.
_BASE_URL = "http://192.168.0.2:5000/"
_HELLO_PATH = "hello"
_BUTTON_PATHS = ["a", "b", "c", "d", "e"]
# Fetched every minute during USB sleep.
# Response is ignored, but tries to keep the WiFi alive.
_HEARTBEAT_PATH = "heartbeat"
# Network hostname to offer, which is also passed to the server.
_HOSTNAME = "inkyframe"
# And HTTP User-Agent.
_USER_AGENT = "PaperThin/1"
# Wireless country.
_WIFI_COUNTRY = "GB"

# After a retryable serious error (like failing to connect to the wireless),
# reboot after this many minutes.
_ERROR_RETRY_TIME = 15
# Don't repaint the screen for retryable serious errors; keep the previous
# display.
_ERROR_HIDING = True
# Aaaaactually, show a banner for the retryable ones. If this works depends on
# if the framebuffer is still around, which it won't be across programs---this
# can only really work on USB power to keep the last thing *we* drew onscreen.
_ERROR_HIDING_MEDIDATE = True
# For if running via Thonny, rather than reset/sleep forever on serious error,
# reraise the exception so you get a debuggable crash.
_ERROR_RERAISE = False
# How long we're willing to wait for a wireless connection, in seconds.
_WIFI_TIMEOUT = 30
# And how long to wait for an HTTP response.
_HTTP_TIMEOUT = 30
# JPEGDEC and PNGDEC can't stream, so need the whole image buffered.
# If larger than this, switch to buffering to flash, lest we exhaust RAM.
_TEMPFILE_THRESHOLD = 32 * 1024
_TEMPFILE_NAME = "paperthin.buf"
# Wakeup URL state file. We're a bit naughty; this should really be INI format.
_URLFILE_NAME = "paperthin.url"
# Brightness for wireless LED states.
_WIFI_LED_CONNECTING_BRIGHTNESS = 1.0
_WIFI_LED_FETCHING_BRIGHTNESS = 0.25
_WIFI_LED_DECODING_BRIGHTNESS = 0.125
_WIFI_LED_HEARTBEAT_BRIGHTNESS = 0.0625
_WIFI_LED_STANDBY_BRIGHTNESS = 0.0
# Force WiFi to reconnect if it appears to already be connected.
_WIFI_FORCE_RECONNECT = True
# Clear the display to blank before updating to the next image.
# This will delay reading the HTTP response for ~40 seconds for PRI; make sure
# your server config is patient enough with clients. (The total update time
# will also raise to ~80 seconds.)
# https://forums.pimoroni.com/t/inky-frame-7-3-burn-in/24574
# Error screens ignore this; they're delayed enough as it is.
_DOUBLE_UPDATE_CLEAR = True