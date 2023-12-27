import flask
import paperutils
import requests
import time
import typing
from PIL import Image
from wand.color import Color
from wand.drawing import Drawing

_PROMETHEUS = 'http://127.0.0.1:9090'

def overlay(image: Image.Image, request: flask.Request) -> Image.Image:
    # https://docs.wand-py.org/en/0.6.11/wand/drawing.html
    wim = paperutils.pil_to_wand(image)
    with Drawing() as draw:
        # Draw the time (modulo ten minutes) and date.
        draw.font = 'Antonio-Bold.ttf'
        draw.font_size = 160
        draw.gravity = 'forget'  # Allows positioning higher than 'north_west'.
        draw.stroke_color = Color('black')
        draw.fill_color = Color('white')
        # Run the clock slightly fast, so it's +/-5 mins off, rather than 0..10.
        clock_time = time.localtime(time.time() + (60 * 5))
        # Or try time.strftime('%H:%M')[:4] + 'X') to mask out the last digit.
        draw.text(16, 160, time.strftime('%H:%M', clock_time))
        draw.font = 'Antonio-Regular.ttf'
        draw.font_size = 64
        draw.text(16, 160+64, time.strftime('%A', clock_time))  # ', %d %B %Y'
        draw.text(16, 160+64+64, time.strftime('%Y-%m-%d', clock_time))

        # Get prometheus metrics.
        (X1, Y1, X2, Y2) = (16, 304, 336, 464)
        try:
            co2_data = get_metric_prometheus(
                'sgp30_co2_ppm', 'lounge', 'enviro-sensors', 600)  # 10 mins
            if len(co2_data) < 2:
                raise GetMetricError('Got less than two CO2 data points')
            temp_data = get_metric_prometheus(
                'bme280_temperature_celsius', 'lounge', 'enviro-sensors', 600)
            if len(temp_data) < 2:
                raise GetMetricError('Got less than two temperature data points')
            humid_data = get_metric_prometheus(
                'bme280_humidity_ratio', 'lounge', 'enviro-sensors', 600)
            if len(humid_data) < 2:
                raise GetMetricError('Got less than two humidity data points')
        except GetMetricError as e:
            draw.font_size = 32
            draw.stroke_color = Color('white')
            draw.fill_color = Color('red')
            draw.text(X1, Y1+32, f'Graph error: {e}')
            co2_data = None

        if co2_data is not None:
            # Draw a box for the graph.
            draw.push()
            draw.fill_opacity = 0.5
            draw.stroke_opacity = 0.0
            draw.fill_color = Color('black')
            draw.rectangle(left=X1, top=Y1, right=X2, bottom=Y2)
            draw.pop()

            # Now the lines.
            draw.stroke_width = 4
            def draw_data(data: typing.List[typing.Tuple[float, float]],
                          val_min: float, val_max: float):
                last_datum = data.pop(0)
                for datum in data:
                    def datum_to_coords(datum: (float, float)):
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

            draw.stroke_color = Color('#77f')
            draw_data(humid_data, 0.0, 1.0)
            draw.stroke_color = Color('red')
            draw_data(temp_data, 20.0, 25.0)
            draw.stroke_color = Color('#7f7')
            draw_data(co2_data, 400.0, 2000.0)

        draw(wim)
    return paperutils.wand_to_pil(wim)

# Hacked-up get_metric_promethus from envsensors trend_display.
# This is quick and dirty.

class GetMetricError(Exception):
    pass

def get_metric_prometheus(metric: str, instance: str, job: str, history: int
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
            if rm['instance'] == instance and rm['job'] == job:
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
