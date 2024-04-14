# PaperThin - A thin-client for the Inky Frame.
# Expects to be launched directly, suitable for hitting run in Thonny.

import gc
import inky_frame
import jpegdec
import machine
import micropython
import network
import os
import pngdec
import time
import usocket

try:
    # Support fancier type annotations on desktop python.
    import typing
except ImportError:
    # Micropython doesn't have it, but also happily ignores them.
    pass

from paperthin_config import (PicoGraphics, DISPLAY, _BASE_URL, _HELLO_PATH,
                              _BUTTON_PATHS, _HEARTBEAT_PATH, _HOSTNAME,
                              _USER_AGENT, _WIFI_COUNTRY, _ERROR_RETRY_TIME,
                              _ERROR_HIDING, _ERROR_HIDING_MEDIDATE,
                              _ERROR_RERAISE, _WIFI_TIMEOUT, _HTTP_TIMEOUT,
                              _TEMPFILE_THRESHOLD, _TEMPFILE_NAME,
                              _URLFILE_NAME, _WIFI_LED_CONNECTING_BRIGHTNESS,
                              _WIFI_LED_FETCHING_BRIGHTNESS,
                              _WIFI_LED_DECODING_BRIGHTNESS,
                              _WIFI_LED_HEARTBEAT_BRIGHTNESS,
                              _WIFI_LED_STANDBY_BRIGHTNESS,
                              _WIFI_FORCE_RECONNECT,
                              _DOUBLE_UPDATE_CLEAR)

# Set up the display and pin that indicates USB power.
# https://forums.pimoroni.com/t/inky-frame-deep-sleep-explanation/19965/9
display = PicoGraphics(DISPLAY)
display_w, display_h = display.get_bounds()
vbus = machine.Pin('WL_GPIO2', machine.Pin.IN)

def get_wakeup_url() -> typing.Optional[str]:
    """Figure out if we're waking up with an intent to load something."""
    # Currently no need for JSON. Avoiding inky_helper, because this doesn't
    # need to be mashed into state.json, and it fights for the busy LED.
    try:
        with open(_URLFILE_NAME) as urlfile:
            url = urlfile.read()
            return url
    except OSError:
        # May well be the file doesn't exist.
        return None

def set_wakeup_url(url: typing.Optional[str]) -> None:
    if url is None:
        try:
            os.remove(_URLFILE_NAME)
        except OSError:
            return  # Shrug.
    else:
        existing_wakeup_url = get_wakeup_url()
        if existing_wakeup_url == url:
            # Don't waste flash cycles re-writing the same thing.
            return
        # We'll let exceptions propagate here; this write *should* succeed.
        with open(_URLFILE_NAME, "w") as urlfile:
            urlfile.write(url)

def red_screen_of_death(message: str,
                        autoreboot: bool,
                        exception: typing.Optional[Exception] = None
                        ) -> typing.NoReturn:
    """Stop and sleep with a *fatal* error. Autoreboot if slow-retriable."""
    # print() (throughout) could really do with flushing a few places, but
    # MicroPython sadly does not support (crashes on!) either the keyword arg
    # flush=True print() form, or the full sys.stdout.flush().
    print(f"RSOD: {message}")  # Should flush.
    time.sleep(0.1)  # Try to encourage serial to flush BEFORE display.update().
    inky_frame.led_busy.on()  # Christmas tree mode (but not network)!
    inky_frame.button_a.led_on()
    inky_frame.button_b.led_on()
    inky_frame.button_c.led_on()
    inky_frame.button_d.led_on()
    inky_frame.button_e.led_on()
    inky_frame.led_wifi.off()
    if autoreboot and _ERROR_HIDING:
        if _ERROR_HIDING_MEDIDATE:
            # The traditional guru red-on-black colors don't look that great.
            display.set_pen(inky_frame.WHITE)
            display.rectangle(0, 0, display_w, 44)
            display.set_pen(inky_frame.RED)
            display.rectangle(4, 4, display_w-8, 44-8)
            display.set_pen(inky_frame.WHITE)
            display.set_font("bitmap8")
            display.text(message, 8, 8, display_w - 16, 1)
            display.set_font("serif_italic")
            meditate = "PaperThin guru meditation"
            scale = 0.75
            display.text(meditate,
                         display_w - (display.measure_text(meditate, scale)+8),
                         16, scale=scale)
            display.set_font("bitmap8")
            meditate = "Press RESET button; hold A&E for launcher"
            if autoreboot:
                meditate = f"Restarting in {_ERROR_RETRY_TIME} minutes"
            scale = 1.0
            display.text(meditate,
                         display_w - (display.measure_text(meditate, scale)+8),
                         44-16, scale=scale)
            display.update()
    else:
        display.set_pen(inky_frame.RED)
        display.clear()
        display.set_pen(inky_frame.WHITE)
        display.set_font("serif_italic")
        display.set_thickness(3)
        display.text("PaperThin fatal error", 8, 40, display_w - 16, 2)
        display.set_font("bitmap8")
        display.line(4, 92, display_w - 4, 92, 2)
        display.text(message, 8, 114, display_w - 16, 2)
        footer = ("Press RESET button; "
            "hold A & E buttons as well to return to launcher.")
        if autoreboot:
            footer = (f"Restarting in {_ERROR_RETRY_TIME} minutes, "
                "or hold A & E and press RESET to return to launcher.")
        display.text(footer, 8, display_h - 20, display_w - 16, 2)
        display.update()
    if _ERROR_RERAISE:
        if exception is not None:
            raise exception
        else:
            # Still worth interrupting the autoreboot/poweroff/busyloop.
            raise RuntimeError("(no underlying exception)")
    if autoreboot:
        print(f"Restarting in {_ERROR_RETRY_TIME} minutes unless interrupted.")
        inky_frame.sleep_for(_ERROR_RETRY_TIME)
        machine.reset()
    while True:
        inky_frame.turn_off()
        # For USB, have a little snooze for an hour instead.
        time.sleep(60 * 60)

def network_status_str(status: int) -> str:
    if status == network.STAT_IDLE:
        return "The wireless connection is idle and inactive."
    elif status == network.STAT_CONNECTING:
        return "The wireless connection timed out while connecting."
    elif status == network.STAT_WRONG_PASSWORD:
        return "The wireless password is incorrect."
    elif status == network.STAT_NO_AP_FOUND:
        return "The wireless access point could not be found."
    elif status == network.STAT_CONNECT_FAIL:
        return "The wireless connection failed for an unknown reason."
    elif status == network.STAT_GOT_IP:
        return "The wireless connection appears to be up and has an IP."
    elif status == 2:  # CYW43_LINK_NOIP, not exposed properly.
        # https://www.raspberrypi.com/documentation/pico-sdk/cyw43_8h.html
        return "The wireless is connected but does not yet have an IP."
    else:
        return f"The wireless connection is in an unknown state ({status})."

def network_connect(SSID: str, PSK: str, timeout: int) -> network.WLAN:
    """Patched version of inky_helper n_c() with better error handling.

    Raises a RuntimeError and downs the network again on failure to connect."""
    # Enable the wireless. Set country first to knock out another weird failure.
    # https://github.com/micropython/micropython/issues/11977
    network.country(_WIFI_COUNTRY)
    wlan = network.WLAN(network.STA_IF)
    # This can survive power interruptions, which is...alarming. And can get us
    # into stuck states where we think we're connected, but the router doesn't
    # seem to agree. But it's not always wrong!
    if wlan.isconnected():
        if _WIFI_FORCE_RECONNECT:
            print("WLAN claims to already be connected; disconnecting...")
            wlan.disconnect()
            wlan.active(False)  # This only downs the link (and can ignore you).
            wlan.deinit()
        else:
            print("WLAN claims to already be connected; continuing anyway...")
    wlan.active(True)
    # CYW43_PERFORMANCE_PM is not exported and I'm skeptical of this value
    # which came from inky_helper. It *is* also mentioned in this hell issue:
    # https://github.com/micropython/micropython/issues/9455
    # wlan.config(pm=0xa11140)  # Turn WiFi power saving off for some slow APs.
    network.hostname(_HOSTNAME)  # Set hostname.

    # Light the LED and start connecting.
    # Not reimplementing pulse_network_led()...today.
    inky_frame.led_wifi.brightness(_WIFI_LED_CONNECTING_BRIGHTNESS)
    wlan.connect(SSID, PSK)
    status = wlan.status()
    while timeout > 0 and (
        (status == network.STAT_CONNECTING) or (status == 2)):
        if status == 2:
            print(f"Waiting for IP address ({timeout}s left)...")
        else:
            print(f"Waiting for connection ({timeout}s left)...")
        time.sleep(1)
        timeout -= 1
        status = wlan.status()

    # Handle connection error.
    if wlan.isconnected():
        inky_frame.led_wifi.brightness(_WIFI_LED_STANDBY_BRIGHTNESS)
        if status != network.STAT_GOT_IP:
            print("Weird inconsistent results...wireless is connected, but:"
                  f"{network_status_str(status)}")
    else:
        # Deactivate the wireless.
        inky_frame.led_wifi.off()
        wlan.active(False)
        wlan.deinit()
        # Raise an error based on the incorrect status.
        # These can be a bit kooky; for example, if we recently *did* have a
        # successful session with the AP, we can just timeout or immediately go
        # idle rather than get explicit bad-SSID/bad-password responses.
        # ConnectionError is an OSError, which wants errno, so no good here.
        raise RuntimeError(network_status_str(status))

    return wlan

def connect_wifi() -> network.WLAN:
    """Bring up the WiFi; may raise ImportError or RuntimeError."""
    # The config loading wasn't part of inky_helper anyway.
    ssid = None
    password = None
    print("Loading secrets...")
    from secrets import WIFI_SSID, WIFI_PASSWORD
    print("Connecting to WiFi...")
    return network_connect(WIFI_SSID, WIFI_PASSWORD, _WIFI_TIMEOUT)

def connect_wifi_or_die() -> network.WLAN:
    """connect_wifi(), but will either succeed or red_screen_of_death()."""
    try:
        wlan = connect_wifi()
    except ImportError:
        red_screen_of_death(
            "Unable to import secrets.py; see:\n\n"
            "https://learn.pimoroni.com/article/getting-started-with-inky-frame",
            False
        )
    except RuntimeError as e:
        red_screen_of_death(f"Unable to get an internet connection.\n\n{e}",
                            True, e)
    (ip_addr, subnet_mask, gateway, dns_server) = wlan.ifconfig()
    print(f"Connected! (IP: {ip_addr}/{subnet_mask}; " +
          f"gateway: {gateway}; DNS: {dns_server})")
    return wlan

def aggressive_urlencode_byte(byte: int) -> str:
    """URLencode a single byte (URLencoding is bytewise, not charwise)."""
    if ((byte >= ord('0') and byte <= ord('9')) or
        (byte >= ord('A') and byte <= ord('Z')) or
        (byte >= ord('a') and byte <= ord('z'))):
        return chr(byte)
    else:
        return "%{0:02x}".format(byte)

def aggressive_urlencode(unsafe: str) -> str:
    """Simplistic, aggressive URLencoder."""
    return "".join(map(aggressive_urlencode_byte, unsafe.encode()))

def form_urlencode(params: typing.Dict[str, str]) -> str:
    """Silly little rewrite of urllib.parse.urlencode(), which is absent."""
    return "&".join([f"{aggressive_urlencode(k)}={aggressive_urlencode(v)}"
                     for k, v in params.items()])

def http_request(url: str,
                 data: typing.Optional[bytes]=None,
                 method: str="GET",
                 headers: typing.Dict[str, str]={}
                 ) -> tuple[typing.Dict[str, str], usocket.socket]:
    """Make a simple HTTP request. Returns headers; socket at point of data."""
    # Unfortunately, urlopen() eats the headers with no way to recover them.
    # So we get to rewrite that too.
    print(f"Requesting {method} {url}...")

    # Set some default headers.
    headers.setdefault("User-Agent", _USER_AGENT)
    headers.setdefault("Connection", "close")
    headers.setdefault("Accept-Encoding", "identity")
    if data is not None:
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        headers.setdefault("Content-Length", str(len(data)))

    # Do some crude URL parsing, mostly from upstream as-is.
    try:
        protocol, _, host, path = url.split("/", 3)
    except ValueError:
        protocol, _, host = url.split("/", 2)
        path = ""
    if protocol == "http:":
        port = 80
    elif protocol == "https:":
        import ussl
        port = 443
    else:
        raise NotImplementedError(f"Unsupported protocol '{protocol}'")
    if ":" in host:
        host, port = host.split(":", 1)
        port = int(port)
    headers.setdefault("Host", f"{host}:{port}")

    # Resolve DNS. Can raise OSError.
    addrinfo = usocket.getaddrinfo(host, port, 0, usocket.SOCK_STREAM)
    if len(addrinfo) == 0:
        raise RuntimeError(f"Cannot resolve host {host}")
    elif len(addrinfo) > 1:
        print(f"{len(addrinfo)} results; using first...")
    sock_family, sock_type, sock_proto, sock_canonname, sock_addr = addrinfo[0]

    # Connect.
    socket = usocket.socket(sock_family, sock_type, sock_proto)
    socket.settimeout(_HTTP_TIMEOUT)
    # Allow reuse; https://stackoverflow.com/a/3233022
    socket.setsockopt(usocket.SOL_SOCKET, usocket.SO_REUSEADDR, 1)
    try:
        socket.connect(sock_addr)
        if protocol == "https:":
            socket = ussl.wrap_socket(socket, server_hostname=host)

        # Send request.
        socket.write(method.encode())
        socket.write(f" /{path}".encode())
        socket.write(b" HTTP/1.0\r\n")
        for key, value in headers.items():
            socket.write(f"{key}: {value}\r\n".encode())
        socket.write(b"\r\n")
        if data:
            socket.write(data)

        # Read and partially parse response.
        line: str = socket.readline().decode().strip()
        response_headers = {}
        try:
            _, status_str, status_desc = line.split(" ", 2)
            status = int(status_str)
        except ValueError as e:
            print(f"Bad first response line '{line}'")
            raise RuntimeError("Malformed HTTP response from server.")
        if status < 200 or status >= 300:
            raise NotImplementedError(
                f"Server returned '{status} {status_desc}'!\n\n"
                "Non-200 codes are not supported.")
        while True:
            line = socket.readline().decode()
            # Look for EOF or end of headers.
            if line == "" or line == "\r\n":
                break
            # Parse this header.
            line = line.strip()
            try:
                key, value = line.split(": ", 1)
                response_headers[key] = value
            except ValueError:
                print(f"Bad header line '{line}'")
                raise RuntimeError("Malformed HTTP headers from server.")
        # Decide some things for the caller: no content or transfer encodings
        # are permitted, since they'd affect the streamed response body.
        # Location *is* allowed for them to interpret, but 3XX codes are not.
        if "Transfer-Encoding" in response_headers:
            raise NotImplementedError(
                f"Server wants to use'{response_headers['Transfer-Encoding']}',"
                " but transfer encodings are not supported.")
        if "Content-Encoding" in response_headers:
            raise NotImplementedError(
                f"Server wants to use'{response_headers['Content-Encoding']}',"
                " but content encodings are not supported.")
    except (OSError, UnicodeError, RuntimeError, NotImplementedError):
        print("...semi-expected error, closing socket and raising...")
        socket.close()
        raise

    # Return the socket, positioned to read the response body.
    print(f"...success, with status {status} ({len(response_headers)} headers)")
    return response_headers, socket

def any_button_down() -> tuple[typing.Optional[inky_frame.Button], int]:
    """Return which button is down and its index, or None."""
    # woken_by_button() seems to be *always* true for me on USB. :/
    if inky_frame.woken_by_button():
        for index, button in enumerate([inky_frame.button_a,
                                        inky_frame.button_b,
                                        inky_frame.button_c,
                                        inky_frame.button_d,
                                        inky_frame.button_e]):
            if button.raw():
                return button, index
        # Lies! None of you were down!
        return None, -1
    else:
        return None, -1

# viper doesn't support the streaming byte reads we do
@micropython.native
def picorle_decode(pri: usocket.socket) -> None:
    print("Decoding PRI2...")
    # Header
    if pri.read(4) != b"PRI2":
        raise ValueError("Incorrect magic header")
    width = int.from_bytes(pri.read(2), 'little')
    height = int.from_bytes(pri.read(2), 'little')

    # Palette
    palette_size = int.from_bytes(pri.read(1), 'little')
    truecolor: bool
    palette: list[int]  # PicoGraphics pens
    if palette_size == 0:
        truecolor = True
        print("...truecolor...")
    else:
        truecolor = False
        palette_size += 1
        palette = [0] * palette_size
        rgb = bytearray(3)
        for i in range(0, palette_size):
            pri.readinto(rgb)
            palette[i] = display.create_pen(rgb[0], rgb[1], rgb[2])
        print(f"...palette of size {palette_size}...")

    # Image data
    bytes_per_pixel = 3 if truecolor else 1
    span_data = bytearray(2)  # 2, even for truecolor
    for y in range(0, height):
        x = 0
        while x < width:
            if pri.readinto(span_data) != 2:
                raise ValueError(f"File truncated after x={x}, y={y}")
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
                    if truecolor:
                        display.set_pen(display.create_pen(
                            pixel[0], pixel[1], pixel[2]))
                    else:
                        display.set_pen(palette[pixel])
                    display.pixel(x, y)
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
                if truecolor:
                    display.set_pen(display.create_pen(
                        pixel[0], pixel[1], pixel[2]))
                else:
                    display.set_pen(palette[pixel])
                display.pixel_span(x, y, count)
                x += count

    print("...PRI2 decoded!")

def maybe_buffer_to_file(size: int, socket: usocket.socket) -> bool:
    """Read all the data to a file, if large enough, and return True."""
    if size > _TEMPFILE_THRESHOLD:
        print(f"{size} bytes is too large, buffering to flash!")
        buf = bytearray(1024)
        with open(_TEMPFILE_NAME, "wb") as buf_file:
            while socket.readinto(buf) != 0:
                buf_file.write(buf)
        del buf
        gc.collect()
        return True
    else:
        return False

def maybe_double_clear() -> None:
    if _DOUBLE_UPDATE_CLEAR:
        print("...preliminary clear to white...")  # Should flush.
        display.set_pen(inky_frame.WHITE)
        display.clear()
        display.update()
        print("...proceeding to update framebuffer...")

def display_using_decoder(headers: typing.Dict[str, str],
                          socket: usocket.socket,
                          decoder,
                          **decoder_args: typing.Dict[str, typing.Any]) -> None:
    size: int = int(headers.get("Content-Length", 0))
    too_big = maybe_buffer_to_file(size, socket)
    if too_big:
        inky_frame.led_wifi.brightness(_WIFI_LED_DECODING_BRIGHTNESS)
        decoder.open_file(_TEMPFILE_NAME)
    else:
        data = bytearray(size)
        socket.readinto(data)
        inky_frame.led_wifi.brightness(_WIFI_LED_DECODING_BRIGHTNESS)
        decoder.open_RAM(data)
    # Fight for as much RAM as we can get.
    # (...assuming open_RAM keeps the underlying bytes marked in use...)
    socket.close()
    gc.collect()
    maybe_double_clear()
    decoder.decode(0, 0, **decoder_args)
    if too_big:
        os.remove(_TEMPFILE_NAME)

def display_response(headers: typing.Dict[str, str],
                     socket: usocket.socket) -> None:
    """Display one of the supported HTTP responses."""
    type: str = headers.get("Content-Type", "")
    type = type.split(";", 1)[0]  # Ignore any MIME options (UTF-8 or bust!)
    size: int = int(headers.get("Content-Length", 0))
    if size == 0:
        # Ah, we've been told it's a no-op.
        print("No-op response.")
        return
    elif type == "text/plain":
        print("Rendering plaintext...")
        display.set_pen(inky_frame.WHITE)
        display.clear()
        display.set_font("bitmap8")
        display.set_pen(inky_frame.BLACK)
        text = socket.read(size).decode()
        display.text(text, 4, 4,
                     wordwrap=display_w-8, scale=2, fixed_width=True)
    elif type == "image/jpeg":
        # This is a little painful, because we can't stream to the deocder.
        print("Rendering JPEG...")
        decoder = jpegdec.JPEG(display)
        dither = (headers.get("X-Dither", "") != "")
        display_using_decoder(headers, socket, decoder, dither=dither)
    elif type == "image/png":
        # Ditto.
        print("Rendering PNG...")
        decoder = pngdec.PNG(display)
        dither = (headers.get("X-Dither", "") != "")
        mode = pngdec.PNG_DITHER if dither else pngdec.PNG_POSTERISE
        display_using_decoder(headers, socket, decoder, mode=mode)
    elif type == "image/x.pico-rle":
        # While slow and dumb, this format streams directly to the display.
        inky_frame.led_wifi.brightness(_WIFI_LED_DECODING_BRIGHTNESS)
        maybe_double_clear()
        picorle_decode(socket)
        socket.close()
    else:
        # This is *really* borderline use of "fatal", but.
        red_screen_of_death(f"Cannot display server response of type '{type}'!",
                            True)
    print("...done!")  # Should flush.
    display.update()

# Ok. Time to do stuff. Reset LEDs and get us online.
# Read the initial button state BEFORE doing things that take time.
button_down, button_index = any_button_down()
inky_frame.button_a.led_off()
inky_frame.button_b.led_off()
inky_frame.button_c.led_off()
inky_frame.button_d.led_off()
inky_frame.button_e.led_off()
inky_frame.led_busy.off()
if button_down is not None:
    button_down.led_on()  # Give feedback the press has been registered.
# https://www.raspberrypi.com/documentation/microcontrollers/raspberry-pi-pico.html
# VBUS and VSYS are separate pins, but I don't know if we're still fighting for
# the ADC, and we only need a single reading.
on_usb_power = vbus.value()
# Get us online.
wlan = connect_wifi_or_die()

# Figure out when it is.
inky_frame.pcf_to_pico_rtc()
year, _, _, _, _, _, _, _ = machine.RTC().datetime()
if year < 2020:
    print(f"It's probably not {year}, asking NTP...")
    inky_frame.led_wifi.brightness(_WIFI_LED_FETCHING_BRIGHTNESS)
    try:
        inky_frame.set_time()
    except OSError as e:
        print(f"Error setting time: {e}")
    inky_frame.led_wifi.brightness(_WIFI_LED_STANDBY_BRIGHTNESS)

# Infinite loop is useful for the USB-powered case, where ih.sleep() resumes
# from where it left off, rather than powercycling and restarting from the top.
usb_loop = False
while True:
    # If we don't know better, we ask for the hello path.
    url = _BASE_URL + _HELLO_PATH
    method = 'GET'
    error = None

    if usb_loop:
        # Do a fresh button read, else stick with what we saw before waiting
        # for the wireless.
        button_down, button_index = any_button_down()
        # Also kick the wireless, possibly.
        if wlan.status() != network.STAT_GOT_IP:
            wlan = connect_wifi_or_die()
            gc.collect()

    if button_down is not None:
        button_down.led_on()
        method = 'POST'
        url = _BASE_URL + _BUTTON_PATHS[button_index]
    else:
        # We slept until our refresh time, one way or another.
        # Remember what it was we wanted to refresh to.
        maybe_wakeup_url = get_wakeup_url()
        if maybe_wakeup_url is None:
            if inky_frame.woken_by_rtc() or usb_loop:
                # ...uh. You ever wake up with amnesia? Guess it'll be hello.
                # This can happen if the button that caused the wakeup has been
                # released by the time we look again. :C
                error = "Woke from sleep but forgot what to load...ouchie."
                print(error)
                time.sleep(10)  # Don't tightloop if we're stuck here.
            # Else this is a clean poweron with no remembered URL.
        else:
            url = maybe_wakeup_url

    headers = {}  # User-Agent is set in our own http_request().
    query_params = {
        "hostname": _HOSTNAME,
        "w": str(display_w),
        "h": str(display_h),
    }
    if error is not None:
        query_params["error"] = error
    # We don't have urllib.parse on the Inky Frame, else this could be:
    # url = url + "?" + urllib.parse.urlencode(query_args)
    encoded_query_params = form_urlencode(query_params)
    url = url + "?" + encoded_query_params
    # We don't have urlib.request either. If in future we do, try:
    # request = urllib.request.Request(url, headers=headers, method=method)
    # and then using that request with urllib.request.urlopen()

    # Do the fetch.
    inky_frame.led_wifi.brightness(_WIFI_LED_FETCHING_BRIGHTNESS)
    try:
        # I'm not entirely convinced this can succeed on retry if it fails.
        attempts = 5
        succeeded = False
        while not succeeded:
            attempts -= 1
            try:
                response_headers, response_socket = http_request(
                    url, None, method, headers)
                succeeded = True  # We're done!
            except OSError as e:
                if attempts >= 0:
                    # Try to tolerate network blips.
                    print(f"...ignoring {e} ({attempts} attempts left)...")
                    time.sleep(2)
                else:
                    # Throw it up a level; out of attempts or different error.
                    raise e
    except (OSError, UnicodeError, RuntimeError, NotImplementedError) as e:
        # If we've gone hard-down on trying to reach it, forget any saved URL.
        # This avoids us getting stuck in a retry/RSOD loop and never listening
        # to the buttons to pick up a new URL configuration.
        print("Forgetting any saved wakeup URL in case it's bad.")
        set_wakeup_url(None)
        red_screen_of_death(f"Failed to {method} {url}:\n\n{e}", True, e)

    # Parse the response.
    reload_time = None  # seconds
    new_wakeup_url = False
    if "Refresh" in response_headers:
        try:
            when, what = response_headers["Refresh"].split(";", 1)
            reload_time = int(when)
            set_wakeup_url(what.strip())
            new_wakeup_url = True
            print(f"Refresh requested in {when}s to {what}")
        except ValueError:
            print(f"Ignoring bad Refresh header '{response_headers['Refresh']}'")
    try:
        # A lot of different things can go wrong here. At least try to hit the
        # error handler and set up for a restart. Grab as much free memory as
        # we can first.
        gc.collect()
        display_response(response_headers, response_socket)
    except Exception as e:
        red_screen_of_death(f"Unhandled exception rendering response:\n\n{e}",
                            True, e)
    response_socket.close()  # Possibly a double-close, but should be safe.
    inky_frame.led_wifi.brightness(_WIFI_LED_STANDBY_BRIGHTNESS)
    inky_frame.button_a.led_off()
    inky_frame.button_b.led_off()
    inky_frame.button_c.led_off()
    inky_frame.button_d.led_off()
    inky_frame.button_e.led_off()

    # Clear the wakeup URL if everything worked (so if it didn't, we retry it).
    if not new_wakeup_url:
        set_wakeup_url(None)

    if not on_usb_power:
        # Gracefully down network before we power off or reset. This all kind
        # of sucks; even on USB, leaving it idle makes it drop; there's probably
        # keepalive stuff the microcontroller isn't doing. But reconnecting
        # doesn't work properly---the interface will come back up, but sockets
        # will never work again.
        wlan.disconnect()
        wlan.active(False)
        wlan.deinit()
        wlan = None
        gc.collect()  # Hammer it down as hard as possible.
        inky_frame.led_wifi.off()

    # Sleep appropriately before next action.
    if on_usb_power:
        # We won't be interrupted by buttons, so can't just sleep.
        usb_sleep = 1.0
        approx_time_slept = 0.0
        if reload_time is None:
            print("On USB; polling for a button press...")
        else:
            print(f"On USB; sleeping for {reload_time}s or until button...")
            usb_sleep = reload_time
        while usb_sleep > 0:
            # woken_by_button() is being always-true for me again.
            button_down, button_index = any_button_down()
            if button_down is not None:
                print(f"...button {button_index} is down!")
                break
            time.sleep(0.1)
            approx_time_slept += 0.1
            if reload_time is not None:
                usb_sleep -= 0.1
            if approx_time_slept > 60.0:
                print("...ba-dump...")
                try:
                    inky_frame.led_wifi.brightness(
                        _WIFI_LED_HEARTBEAT_BRIGHTNESS)
                    _, heart_socket = http_request(
                        _BASE_URL + _HEARTBEAT_PATH +
                        "?" + encoded_query_params)
                    heart_socket.close()
                    inky_frame.led_wifi.brightness(_WIFI_LED_STANDBY_BRIGHTNESS)
                    gc.collect()
                except (OSError, UnicodeError, RuntimeError,
                        NotImplementedError) as e:
                    print(f"...ignoring heart problem: {e}")
                approx_time_slept = 0.0
        print("...wakey wakey!")
    else:
        # Battery power; sleep will reboot us.
        if reload_time is None:
            # Have a big nap until a button is pressed.
            inky_frame.turn_off()
        else:
            # Have a little nap until our time is up.
            if reload_time < 60:
                reload_time = 60
            inky_frame.sleep_for(reload_time // 60)
        red_screen_of_death(
            "Somehow resumed execution in-place after non-USB sleep.\n\n"
            "This is very likely a bug, and wireless is now disconnected",
            False)

    # Remember we're stuck in a time loop.
    usb_loop = True
