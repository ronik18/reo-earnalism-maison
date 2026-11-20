"""Lunar attraction and its difference from the acceleration of Earth's centre.

Lengths use Earth radii. The Moon is at ``(moon_distance, 0)`` and lunar GM
defaults to a normalized value of 1; returned acceleration units are therefore
normalized, not SI. ``DEFAULT_MOON_DISTANCE`` is an illustrative mean separation,
not a tide-prediction ephemeris.

The field is a Newtonian point-Moon model. It does not solve the ocean's fluid
response, Earth's self-gravity, basin geometry, rotation, weather or solar tides.
The ellipse helpers are explicitly illustrative, area-preserving 2-D geometry;
they are not calculated ocean heights, trajectories or local tide predictions.

Authoritative explanatory sources:
https://www.nesdis.noaa.gov/about/k-12-education/oceans-coasts/what-causes-tides
https://www.noaa.gov/education/resource-collections/ocean-coasts/tides
https://science.nasa.gov/moon/tides/
"""

import math


DEFAULT_MOON_DISTANCE = 60.3
Point = tuple[float, float]


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _parameters(moon_distance: float, lunar_gm: float) -> tuple[float, float]:
    distance = _finite(moon_distance, "moon_distance")
    gm = _finite(lunar_gm, "lunar_gm")
    if distance <= 1:
        raise ValueError("Moon distance must exceed the unit Earth's radius")
    if gm <= 0:
        raise ValueError("lunar_gm must be positive")
    return distance, gm


def _point(point: Point) -> Point:
    if len(point) != 2:
        raise ValueError("A point must have exactly two coordinates")
    return _finite(point[0], "x"), _finite(point[1], "y")


def actual_lunar_acceleration(
    point: Point,
    moon_distance: float = DEFAULT_MOON_DISTANCE,
    lunar_gm: float = 1.0,
) -> Point:
    """Return actual lunar attraction, directed from the point toward the Moon.

    All three axis samples near/centre/far point Moonward. Their differing
    lengths are real model differences; a renderer that amplifies those length
    differences must label the amplification rather than imply physical scale.
    """
    distance, gm = _parameters(moon_distance, lunar_gm)
    x, y = _point(point)
    dx, dy = distance - x, -y
    separation = math.hypot(dx, dy)
    if separation == 0:
        raise ValueError("Acceleration is undefined at the point Moon")
    if not math.isfinite(separation):
        raise ValueError("Point-Moon separation is outside finite range")
    magnitude = (gm / separation) / separation
    vector = (magnitude * (dx / separation), magnitude * (dy / separation))
    if not all(math.isfinite(component) for component in vector):
        raise ValueError("Acceleration is outside finite numeric range")
    return vector


def relative_tidal_acceleration(
    point: Point,
    moon_distance: float = DEFAULT_MOON_DISTANCE,
    lunar_gm: float = 1.0,
) -> Point:
    """Return lunar acceleration minus its value at Earth's centre.

    This is a relative field, not the direction of actual lunar gravity. On the
    Moon-facing axis it points outward toward the Moon; on the opposite axis it
    points outward away from the Moon. The centre has exactly zero difference.
    Render it in a separately labelled panel, not as reversed lunar attraction.
    """
    acceleration = actual_lunar_acceleration(point, moon_distance, lunar_gm)
    centre = actual_lunar_acceleration((0.0, 0.0), moon_distance, lunar_gm)
    return acceleration[0] - centre[0], acceleration[1] - centre[1]


def far_field_tidal_approximation(
    point: Point,
    moon_distance: float = DEFAULT_MOON_DISTANCE,
    lunar_gm: float = 1.0,
) -> Point:
    """First-order field ``GM / D**3 * (2*x, -y)`` for ``|point| << D``.

    It illustrates axial stretching and transverse compression. Use the exact
    relative field for displayed calculations; this approximation is provided
    to check the model's large-distance limit, not to replace local prediction.
    """
    distance, gm = _parameters(moon_distance, lunar_gm)
    x, y = _point(point)
    factor = ((gm / distance) / distance) / distance
    vector = (2 * factor * x, -factor * y)
    if not all(math.isfinite(component) for component in vector):
        raise ValueError("Approximation is outside finite numeric range")
    return vector


def illustrative_envelope_axes(
    stretch: float = 0.12, radius: float = 1.0
) -> tuple[float, float]:
    """Return area-preserving ellipse axes, with no claimed fluid dynamics.

    ``a = radius * (1 + stretch)`` and ``b = radius / (1 + stretch)`` conserve
    the area ``pi * radius**2``. This is only a two-sided visual analogy; its
    amplitude is not derived from the lunar field and is deliberately exaggerated.
    """
    stretch = _finite(stretch, "stretch")
    radius = _finite(radius, "radius")
    if stretch < 0 or radius <= 0:
        raise ValueError("stretch must be nonnegative and radius positive")
    a, b = radius * (1 + stretch), radius / (1 + stretch)
    if not math.isfinite(a) or b <= 0:
        raise ValueError("Envelope axes are outside finite numeric range")
    return a, b


def illustrative_envelope_point(
    angle_radians: float, stretch: float = 0.12, radius: float = 1.0
) -> Point:
    """Point on the illustrative ellipse, aligned to the Earth-Moon x axis."""
    angle = _finite(angle_radians, "angle_radians")
    a, b = illustrative_envelope_axes(stretch, radius)
    return a * math.cos(angle), b * math.sin(angle)
