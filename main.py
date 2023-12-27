import inky_frame

# Always, always allow holding A&E while resetting to return to launcher.
go_to_launcher = False
if inky_frame.button_a.read() and inky_frame.button_e.read():
    go_to_launcher = True
else:
    # Possibly direct-load to another script without all the framework.
    try:
        with open("boot.txt") as boot_entry:
            application = boot_entry.read()
            print("Direct booting: ", application)
            __import__(application)
    except Exception as e:
        # This might mean boot.txt pointed to a missing file or something. Log
        # but still continue to the menu.
        print("Direct boot exception: ", e)
        go_to_launcher = True

# Ok, we're doing the full-fat launcher.
# Unlike tufty, there's no automatic scrolling list; just five presets.
choices = [
    {"script": "nasa_apod", "name": "NASA Picture of the Day", "direct": False},
    {"script": "word_clock", "name": "Word Clock", "direct": False},
    {"script": "paperthin", "name": "PaperThin", "direct": True},
    {"script": "news_headlines", "name": "Headlines", "direct": False},
    {"script": "random_joke", "name": "Random Joke", "direct": False},
]

# Load and initialize everything.
import gc
import time
from machine import reset
import inky_helper as ih

# Uncomment the line for your Inky Frame display size
# from picographics import PicoGraphics, DISPLAY_INKY_FRAME_4 as DISPLAY  # 4.0"
# from picographics import PicoGraphics, DISPLAY_INKY_FRAME as DISPLAY    # 5.7"
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_7 as DISPLAY  # 7.3"

# Create a secrets.py with your Wifi details to be able to get the time
#
# secrets.py should contain:
# WIFI_SSID = "Your WiFi SSID"
# WIFI_PASSWORD = "Your WiFi password"

# A short delay to give USB chance to initialise
time.sleep(0.5)

# Setup for the display.
graphics = PicoGraphics(DISPLAY)
WIDTH, HEIGHT = graphics.get_bounds()
graphics.set_font("bitmap8")


# Run the launcher menu. Does not return; sets run state and reboots.
def launcher() -> None:
    # Apply an offset for the Inky Frame 5.7".
    if HEIGHT == 448:
        y_offset = 20
    # Inky Frame 7.3"
    elif HEIGHT == 480:
        y_offset = 35
    # Inky Frame 4"
    else:
        y_offset = 0

    # Draws the menu
    graphics.set_pen(1)
    graphics.clear()
    graphics.set_pen(0)

    graphics.set_pen(graphics.create_pen(255, 215, 0))
    graphics.rectangle(0, 0, WIDTH, 50)
    graphics.set_pen(0)
    title = "Launcher"
    title_len = graphics.measure_text(title, 4) // 2
    graphics.text(title, (WIDTH // 2 - title_len), 10, WIDTH, 4)

    color_sequence = [4, 6, 2, 3, 0]
    y = 340 + y_offset
    x = 70

    for i in range(0, 5):
        graphics.set_pen(color_sequence[i])
        graphics.rectangle(30, HEIGHT - y, WIDTH - 100, 50)
        graphics.set_pen(1)
        graphics.text(f"{'ABCDE'[i]}. {choices[i]['name']}",
                      35, HEIGHT - (y - 15), 600, 3)
        graphics.set_pen(graphics.create_pen(220, 220, 220))
        graphics.rectangle(WIDTH - (x + 30), HEIGHT - y, x, 50)
        y -= 60
        x += 50

    graphics.set_pen(0)
    note = "Hold A + E, then press Reset, to return to the Launcher"
    note_len = graphics.measure_text(note, 2) // 2
    graphics.text(note, (WIDTH // 2 - note_len), HEIGHT - 30, 600, 2)

    ih.led_warn.on()
    graphics.update()
    ih.led_warn.off()

    # Now we've drawn the menu to the screen, we wait here for the user to
    # select an app. Then once an app is selected, we set that as the current
    # app and reset the device and load into it.

    # You can replace any of the included examples with one of your own, just
    # change the choices array.

    while True:
        pressed = None
        if ih.inky_frame.button_a.read():
            ih.inky_frame.button_a.led_on()
            pressed = 0
        if ih.inky_frame.button_b.read():
            ih.inky_frame.button_b.led_on()
            pressed = 1
        if ih.inky_frame.button_c.read():
            ih.inky_frame.button_c.led_on()
            pressed = 2
        if ih.inky_frame.button_d.read():
            ih.inky_frame.button_d.led_on()
            pressed = 3
        if ih.inky_frame.button_e.read():
            ih.inky_frame.button_e.led_on()
            pressed = 4
        if pressed is not None:
            if choices[pressed]['direct']:
                # Write the direct-boot file. This takes precedence over state.
                with open("boot.txt", "w") as boot_entry:
                    boot_entry.write(choices[pressed]['script'])
            else:
                # Remove the direct-boot file if it exists.
                try:
                    ih.os.remove("boot.txt")
                except OSError:
                    pass
                ih.update_state(choices[pressed]['script'])
            time.sleep(0.5)
            reset()

# Turn any LEDs off that may still be on from last run.
ih.clear_button_leds()
ih.led_warn.off()

# If A&E were held, or there's no state set, go to the launcher.
if go_to_launcher or not ih.file_exists("state.json"):
    launcher()

# Load the JSON and launch the app.
# (This is a bit of a misnomer; it just loads it and rewrites the state.)
ih.load_state()
ih.launch_app(ih.state['run'])

# Passes the the graphics object from the launcher to the app.
ih.app.graphics = graphics
ih.app.WIDTH = WIDTH
ih.app.HEIGHT = HEIGHT

# Bring up the network, if configured.
try:
    from secrets import WIFI_SSID, WIFI_PASSWORD
    ih.network_connect(WIFI_SSID, WIFI_PASSWORD)
except ImportError:
    print("Create secrets.py with your WiFi credentials")

# Get some memory back, we really need it!
gc.collect()

# The main loop executes the update and draw function from the imported app,
# and then goes to sleep ZzzzZZz

while True:
    ih.app.update()
    ih.led_warn.on()
    ih.app.draw()
    ih.led_warn.off()
    ih.sleep(ih.app.UPDATE_INTERVAL)
