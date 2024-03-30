# Scrape The Guardian's "The Week in Wildlife" for images.
# Tends to be consistently colorful.
# There *is* (currently) some LD+JSON buried at the bottom of the page that
# might be nicer than HTML scraping, but it'd take HTML scraping to *find* it.

import logging
import random
import re
import requests
from io import BytesIO
from PIL import Image

_BASE_PAGE = 'https://www.theguardian.com/environment/series/weekinwildlife'
_WEEK_REGEX = re.compile(
    r'href="(https://www.theguardian.com/environment/gallery/[^"]+)"')
_IMG_START_REGEX = re.compile(r'<img class="gallery__img')
_ALT_REGEX = re.compile(r'alt="([^"]+)"')
_SRC_REGEX = re.compile(r'src="([^"]+)"')
_END_REGEX = re.compile(r'>')

def find_page_for_week(session: requests.Session) -> str|None:
    """Find the gallery page URL for the most recent week."""
    try:
        response = session.get(_BASE_PAGE, stream=True)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logging.exception('Fetching base page failed')
        return None

    # The first match for _WEEK_REGEX's capture group should be the URL.
    line: str
    for line in response.iter_lines(decode_unicode=True):
        match = _WEEK_REGEX.search(line)
        if match:
            return match.group(1)
    return None

def find_pictures_of_week(session: requests.Session, url: str|None
                          ) -> list[tuple[str, str]]:
    """Given a gallery page URL, return a list of [src, alt] for the images."""
    if not url:
        return None
    try:
        response = session.get(url, stream=True)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logging.exception('Fetching gallery page failed')
        return None

    urls: list[tuple[str, str]] = []
    line: str
    alt: str
    src: str
    in_image = False
    for line in response.iter_lines(decode_unicode=True):
        if _IMG_START_REGEX.search(line):
            in_image = True
            alt = ''
            src = ''
        if in_image:
            maybe_alt = _ALT_REGEX.search(line)
            if maybe_alt:
                alt = maybe_alt.group(1)
            maybe_src = _SRC_REGEX.search(line)
            if maybe_src:
                src = maybe_src.group(1)
                # Tiny bad HTML entity decoding.
                src = src.replace('&amp;', '&')
            if _END_REGEX.search(line):
                if src:
                    urls.append([src, alt])
                in_image = False

    return urls

def wildlife() -> tuple[Image.Image, str]|None:
    session = requests.Session()
    gallery_url = find_page_for_week(session)
    pictures = find_pictures_of_week(session, gallery_url)
    if not pictures:
        return None

    # There are more pictures in a week than days.
    # Randomly select one each time instead.
    random.shuffle(pictures)
    (src, alt) = pictures[0]

    try:
        response = requests.get(src, headers={'Referer': gallery_url})
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logging.exception('Fetching picture failed')
        return None
    image = Image.open(BytesIO(response.content))
    # Actually read the image data now, not later.
    image.load()
    return image, alt
