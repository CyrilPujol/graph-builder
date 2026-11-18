"""Stable categorical colors with perceptual and consecutive-color spacing.

Style 0 is black for edges. The vertex's built-in style 0 is white and is
handled by ``styles.base_style``. Other styles keep nearly constant lightness
and saturation so their differences come primarily from hue.
"""
from __future__ import annotations

from colorsys import hls_to_rgb
from functools import lru_cache


FIRST_HUES = (0.00, 0.60, 0.34, 0.08, 0.77)  # red, blue, green, orange, purple
_hue_sequence = list(FIRST_HUES)


def _hue_distance(first, second):
    distance = abs(first - second) % 1
    return min(distance, 1 - distance)


def _gap_candidates(previous):
    ordered = sorted(previous)
    return [((start + end) / 2 % 1, end - start)
            for start, end in zip(ordered, ordered[1:] + [ordered[0] + 1])]


@lru_cache(maxsize=4096)
def _perceptual_coordinates(hue):
    # Oklab, Björn Ottosson: https://bottosson.github.io/posts/oklab/
    red, green, blue = (c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
                        for c in hls_to_rgb(hue, .46, .62))
    l = (.4122214708 * red + .5363325363 * green + .0514459929 * blue) ** (1 / 3)
    m = (.2119034982 * red + .6806995451 * green + .1073969566 * blue) ** (1 / 3)
    s = (.0883024619 * red + .2817188376 * green + .6299787005 * blue) ** (1 / 3)
    return (.2104542553 * l + .7936177850 * m - .0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + .4505937099 * s,
            .0259040371 * l + .7827717662 * m - .8086757660 * s)


def _perceptual_hue(previous):
    """Split hue gaps, maximizing separation with extra weight on recent colors.

    HLS saturation and lightness stay fixed. Oklab is used only to compare
    candidates. This is a greedy heuristic, not a globally optimal palette.
    """
    coordinates = [_perceptual_coordinates(hue) for hue in previous]

    def score(hue):
        candidate = _perceptual_coordinates(hue)
        distances = [sum((a - b) ** 2 for a, b in zip(candidate, old)) ** .5
                     for old in coordinates]
        return min(distances) * (.5 + 3 * distances[-1] + distances[-2])

    candidates = [(hue, gap) for hue, gap in _gap_candidates(previous)
                  if _hue_distance(hue, previous[-1]) >= .22]
    # At high style indices, prioritize the widest open gaps. This keeps
    # palette generation responsive even when users create hundreds of styles.
    if len(candidates) > 32:
        candidates = sorted(candidates, key=lambda pair: (
            pair[1], _hue_distance(pair[0], previous[-1]), -pair[0]),
            reverse=True)[:32]
    return max((hue for hue, _ in candidates), key=score)


def _hue(index):
    while len(_hue_sequence) < index:
        _hue_sequence.append(_perceptual_hue(_hue_sequence))
    return _hue_sequence[index - 1]


@lru_cache(maxsize=4096)
def _color(index):
    if index == 0:
        return (0, 0, 0)
    return tuple(round(channel * 255) for channel in hls_to_rgb(
        _hue(index), .46, .62))


def colormap_1(index):
    """Stable RGB color for a basic style, extended lazily without a fixed cap."""
    index = int(index)
    if index < 0:
        raise ValueError('Style indices must be nonnegative')
    return _color(index)
