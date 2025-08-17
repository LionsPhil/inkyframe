import datetime
import logging
import flask
import paperutils
import random
import requests
import time
import typing
import wildlife
from PIL import Image
from wand.color import Color
from wand.drawing import Drawing

# "Overnight" starts at 1am, then resumes at 9am (below), or on button
# press once it's no longer 1am. Can't wrap over midnight.
_OVERNIGHT_STOP_HOUR=1
_OVERNIGHT_RESUME_HOUR=9

_PROMETHEUS = 'http://127.0.0.1:9090'
_PROMETHEUS_TIMESPAN = 600 # 10 minutes.
_PROMETHEUS_INSTANCE = 'lounge'
_PROMETHEUS_JOB = 'enviro-sensors'
# As a nasty hack, a ! prefix on the metric makes it jobless/instanceless.
# (I have some other global monitoring where that's useful.)
_PROMETHEUS_GRAPHS = [
    # metric name, color, minimum, maximum
    ['bme280_humidity_ratio', '#77f', 0.0, 1.0],
    ['bme280_temperature_celsius', 'red', 20.0, 25.0],
    ['scd4x_co2_ppm', '#7f7', 400.0, 2000.0],
]
_PROMETHEUS_TICKER = [
    # metric name, color, formatter, threshold, multiplier
    # Some overlap with trend-display in envsensors, but less precision
    ['bme280_temperature_celsius', '#f88', '{:.0f}', 0.1, 1.0],
    ['bme280_humidity_ratio', '#99f', '{:.0f}', 0.1 * 0.01, 100.0],
    ['scd4x_co2_ppm', '#7f7', '{:.0f}', 100, 1.0],
]

def overlay_time(draw: Drawing):
    draw.push()
    # Try to avoid completely burning in the date. :/
    # Pull a different color inks to front, rather than always black/white.
    dark_colors = [
        paperutils.BLACK,
        # paperutils.GREEN, # Too light, and also getting dithered when thin.
        paperutils.BLUE,
    ]
    light_colors = [
        paperutils.WHITE,
        paperutils.YELLOW,
        # paperutils.TAUPE, # Will dither without use_taupe.
    ]
    random.shuffle(dark_colors)
    random.shuffle(light_colors)
    # Draw the time (modulo ten minutes) and date.
    # https://fonts.google.com/specimen/Antonio
    draw.font = 'Antonio-Bold.ttf'
    draw.font_size = 160
    draw.stroke_width = 4
    draw.gravity = 'forget'  # Allows positioning higher than 'north_west'.
    draw.stroke_color = Color(dark_colors[0])
    draw.fill_color = Color(light_colors[0])
    # Run the clock slightly fast, so it's +/-5 mins off, rather than 0..10.
    clock_time = time.localtime(time.time() + (60 * 5))
    # Try time.strftime('%H:%M')[:4] + 'X') to mask out the last digit,
    # instead of running the clock five minutes fast.
    draw.text(16, 160, time.strftime('%H:%M', clock_time))
    #draw.font = 'Antonio-Regular.ttf'
    #draw.font_size = 64
    #draw.stroke_width = 1
    #draw.text(16, 160+64, time.strftime('%A', clock_time))  # ', %d %B %Y'
    #draw.text(16, 160+64+64, time.strftime('%Y-%m-%d', clock_time))
    draw.pop()

def overlay_graphs(draw: Drawing):
    draw.push()
    # Get prometheus metrics.
    (X1, Y1, X2, Y2) = (16, 304, 336, 464)
    data = {}
    try:
        for graph in _PROMETHEUS_GRAPHS:
            (metric, *_) = graph
            data[metric] = get_metric_prometheus_one(metric)
    except GetMetricError as e:
        draw.font_size = 32
        draw.stroke_width = 1
        draw.stroke_color = Color('white')
        draw.fill_color = Color('red')
        draw.text(X1, Y1+32, f'Graph error: {e}')
        return

    # Draw a box for the graph.
    draw.push()
    draw.fill_opacity = 0.25
    draw.stroke_opacity = 0.0
    draw.fill_color = Color('black')
    draw.rectangle(left=X1, top=Y1, right=X2, bottom=Y2)
    draw.pop()

    # Now the lines.
    for graph in _PROMETHEUS_GRAPHS:
        (metric, color, val_min, val_max) = graph
        draw.stroke_color = Color(color)
        last_datum = data[metric].pop(0)
        for datum in data[metric]:
            def datum_to_coords(datum: typing.Tuple[float, float]):
                (time_frac, value) = datum
                # Map value in range 0.0--1.0.
                value -= val_min
                value /= (val_max - val_min)
                value = max(0.0, min(1.0, value))  # clamp
                value = 1.0 - value  # flip for Y+ graph
                return ((time_frac * (X2 - X1)) + X1,
                        (value * (Y2 - Y1)) + Y1)
            draw.line(datum_to_coords(last_datum), datum_to_coords(datum))
            last_datum = datum
    draw.pop()

def overlay_ticker(draw: Drawing, wim):
    draw.push()
    # draw.font = 'MonomaniacOne-Regular.ttf'
    # https://int10h.org/oldschool-pc-fonts/fontlist/font?master_512
    draw.font = 'Mx437_Master_512.ttf'
    draw.font_size = 24
    draw.stroke_opacity = 0.0
    draw.stroke_width = 0
    draw.stroke_color = Color('black')
    draw.gravity = 'south_west'

    data: typing.Dict[str, typing.List[typing.Tuple[float, float]]] = {}
    try:
        for graph in _PROMETHEUS_TICKER:
            (metric, *_) = graph
            data[metric] = get_metric_prometheus_one(metric)
    except GetMetricError as e:
        draw.stroke_width = 1
        draw.stroke_color = Color('white')
        draw.fill_color = Color('red')
        draw.text(16, 16, f"ERR: {e}")
        return

    x = 18
    y = 18
    y_bot = wim.height - y
    metrics = draw.get_font_metrics(wim, "69")
    y_top = y_bot - metrics.text_height
    for tick in _PROMETHEUS_TICKER:
        (metric, color, formatter, threshold, multiplier) = tick
        old = data[metric].pop(0)[1]
        new = data[metric].pop()[1]
        if abs(new - old) < threshold:
            trend = '\u0016'
        elif new < old:
            trend = '\u001F'
        else:
            trend = '\u001E'
        text = formatter.format(new * multiplier) + trend
        metrics = draw.get_font_metrics(wim, text)
        new_x = x + int(metrics.text_width)
        draw.fill_opacity = 0.5
        draw.fill_color = Color('black')
        draw.rectangle(left=x-2, top=y_top-6, right=new_x+2, bottom=y_bot+2)
        draw.fill_opacity = 1.0
        draw.fill_color = color
        draw.text(x, y, text)
        x = new_x + 8
    draw.pop()

def overlay(image: Image.Image, request: flask.Request) -> typing.Tuple[Image.Image, typing.Optional[int]]:
    # Run the clock slightly fast, so it's +/-5 mins off, rather than 0..10.
    clock_time = time.localtime(time.time() + (60 * 5))
    overnight = (clock_time.tm_hour == _OVERNIGHT_STOP_HOUR)

    # https://docs.wand-py.org/en/0.6.11/wand/drawing.html
    wim = paperutils.pil_to_wand(image)
    with Drawing() as draw:
        if not overnight:
            overlay_time(draw)
            # Pick whichever you want.
            overlay_graphs(draw)
            #overlay_ticker(draw, wim)
        draw(wim)
    image = paperutils.wand_to_pil(wim)
    wim.close()
    if overnight:
        now = datetime.datetime.now()
        morning = now.replace(hour=_OVERNIGHT_RESUME_HOUR, minute=0, second=0, microsecond=0)
        time_until_morning = int((morning - now).total_seconds())
        if time_until_morning <= 0 or time_until_morning > 86400:
            logging.error(f'Stupid time until morning: {time_until_morning}')
            time_until_morning = None
        return image, time_until_morning
    else:
        return image, None

# Hacked-up get_metric_promethus from envsensors trend_display.
# This is quick and dirty.

class GetMetricError(Exception):
    pass

def get_metric_prometheus(metric: str,
                          instance: typing.Optional[str],
                          job: typing.Optional[str],
                          history: int
                          ) -> typing.List[typing.Tuple[float, float]]:
    url = _PROMETHEUS + '/api/v1/query_range'
    end_time = time.time()
    start_time = (end_time - history) + 1  # inclusive range
    query_args = {
        'query': metric,
        'start': start_time,
        'end': end_time,
        'step': '2s'  # about 300 pixels for 600 data points
    }
    # It does not appear the instant-query API lets you add instance/job
    # labels to the query, so we greedily ask for everything, then filter below.
    response = None
    try:
        response = requests.get(url, query_args)
        response.raise_for_status()
    except requests.RequestException as err:
        raise GetMetricError('HTTP error querying Prometheus') from err

    data = None
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as err:
        raise GetMetricError('Got bad JSON from Prometheus') from err
    try:
        if data['status'] != 'success':
            raise GetMetricError('Non-success response from Prometheus')
        for result in data['data']['result']:
            rm = result['metric']
            if instance is None or rm['instance'] == instance:
                if job is None or rm['job'] == job:
                    return [(
                        (val[0] - start_time) / float(history),
                        float(val[1])
                        ) for val in result['values']]
        # Didn't find it in results
        raise GetMetricError(f"No data from Prometheus for {metric} instance=\"{instance}\", job=\"{job}\"")
    except KeyError as err:
        # This means the structure wasn't what we expected according to
        # https://prometheus.io/docs/prometheus/latest/querying/api/#range-queries
        raise GetMetricError('Got unexpected JSON from Prometheus') from err

def get_metric_prometheus_one(metric: str) -> typing.List[typing.Tuple[float, float]]:
    instance = _PROMETHEUS_INSTANCE
    job = _PROMETHEUS_JOB
    if metric.startswith('!'):
        instance = None
        job = None
        metric = metric.removeprefix('!')
    data = get_metric_prometheus(metric, instance, job, _PROMETHEUS_TIMESPAN)
    if len(data) < 2:
        raise GetMetricError(f'Got less than two {metric} data points')
    return data

def button_override(index: int, request: flask.Request) -> flask.Response|None:
    # Button E only.
    if index != 4:
        return None

    response: flask.Response
    (image, caption) = wildlife.wildlife()
    if image is None:
        response = paperutils.respond_txt("Could not find wildlife image; see server log")
    else:
        resized = paperutils.resize_image(image, request)
        image.close()
        image = paperutils.caption(resized, caption.split('.', 1)[0])
        resized.close()
        response = paperutils.encode_for_inky(image, request)
        image.close()
    paperutils.add_refresh(response, 60 * 60, request.base_url)
    return response
