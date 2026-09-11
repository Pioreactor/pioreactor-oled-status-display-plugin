# -*- coding: utf-8 -*-

# Config (copy-paste into config.ini):
#
# [oled_status_display.config]
# refresh_interval_seconds = 0.5
# banner_seconds = 5
# driver = auto
# i2c_address = 0x3D
# rotation = 0
# metrics = od_filtered,growth_rate,temperature,measured_rpm


from functools import lru_cache
from importlib.resources import files
import threading
from time import monotonic
from typing import Callable
from typing import Optional
from typing import cast

import busio
import click
from msgspec.json import decode
from PIL import Image
from PIL import ImageDraw
from pioreactor import structs
from pioreactor.background_jobs.base import LongRunningBackgroundJobContrib
from pioreactor.config import config
from pioreactor.utils.networking import get_ip
from pioreactor.utils.timing import RepeatedTimer
from pioreactor.whoami import get_assigned_experiment_name
from pioreactor.whoami import get_unit_name
from pioreactor.whoami import NO_EXPERIMENT
from pioreactor.whoami import UNIVERSAL_EXPERIMENT

__plugin_name__ = "oled_status_display"
__plugin_version__ = "0.2.1"
__plugin_summary__ = "Shows Pioreactor status on a 128x64 OLED display."
__plugin_author__ = "Pioreactor Team"


DEFAULT_I2C_ADDRESS = "0x3C"
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64
MAX_LINE_LENGTH = 21
PIXEL_FONT_WIDTH = 6
PIXEL_FONT_HEIGHT = 6
TTYP0_FONT_RESOURCE = "t0-12.bdf"
TTYP0_FONT_HEIGHT = 12
SPLASH_LOGO_RESOURCE = "splash-logo.png"
SPLASH_SECONDS = 3.0

TTYP0_GLYPH_NAMES = {
    " ": None,
    ".": "PFullStop",
    ",": "PComma",
    ":": "PColon",
    ";": "PSemicolon",
    "-": "PHyphenMinus",
    "+": "MPlus",
    "/": "PSolidus",
    "%": "SPercent",
    "'": "PApostropheAscii",
    '"': "PQuote2Ascii",
    "!": "PExclam",
    "?": "PQuestion",
    "(": "PParenL",
    ")": "PParenR",
    "*": "MMultiply",
    "=": "MEqual",
    "<": "MLess",
    ">": "MGreater",
    "&": "SAmpersand",
    "#": "SNumberSign",
}

for _character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    TTYP0_GLYPH_NAMES[_character] = f"LtCap{_character}"

for _character in "abcdefghijklmnopqrstuvwxyz":
    TTYP0_GLYPH_NAMES[_character] = f"LtSml{_character.upper()}"

for _character in "0123456789":
    TTYP0_GLYPH_NAMES[_character] = f"Digit{_character}"

del _character

def _glyph(*rows: str) -> tuple[int, ...]:
    if len(rows) != PIXEL_FONT_HEIGHT:
        raise ValueError(f"Expected {PIXEL_FONT_HEIGHT} font rows, got {len(rows)}.")
    return tuple(int(row, 2) for row in rows)


MCUFONT: dict[str, tuple[int, ...]] = {
    "A": _glyph("011100", "100010", "100010", "111110", "100010", "000000"),
    "B": _glyph("111100", "100010", "111100", "100010", "111100", "000000"),
    "C": _glyph("011100", "100010", "100000", "100010", "011100", "000000"),
    "D": _glyph("111000", "100100", "100010", "100010", "111100", "000000"),
    "E": _glyph("111110", "100000", "111100", "100000", "111110", "000000"),
    "F": _glyph("111110", "100000", "111100", "100000", "100000", "000000"),
    "G": _glyph("011100", "100000", "100110", "100010", "011100", "000000"),
    "H": _glyph("100010", "100010", "111110", "100010", "100010", "000000"),
    "I": _glyph("011100", "001000", "001000", "001000", "011100", "000000"),
    "J": _glyph("000010", "000010", "000010", "100010", "011100", "000000"),
    "K": _glyph("100010", "100100", "111000", "100100", "100010", "000000"),
    "L": _glyph("100000", "100000", "100000", "100000", "111110", "000000"),
    "M": _glyph("100010", "110110", "101010", "100010", "100010", "000000"),
    "N": _glyph("100010", "110010", "101010", "100110", "100010", "000000"),
    "O": _glyph("011100", "100010", "100010", "100010", "011100", "000000"),
    "P": _glyph("111100", "100010", "111100", "100000", "100000", "000000"),
    "Q": _glyph("011100", "100010", "100010", "100110", "011110", "000000"),
    "R": _glyph("111100", "100010", "111100", "100100", "100010", "000000"),
    "S": _glyph("011110", "100000", "011100", "000010", "111100", "000000"),
    "T": _glyph("111110", "001000", "001000", "001000", "001000", "000000"),
    "U": _glyph("100010", "100010", "100010", "100010", "011100", "000000"),
    "V": _glyph("100010", "100010", "100010", "010100", "001000", "000000"),
    "W": _glyph("100010", "100010", "101010", "101010", "010100", "000000"),
    "X": _glyph("100010", "010100", "001000", "010100", "100010", "000000"),
    "Y": _glyph("100010", "010100", "001000", "001000", "001000", "000000"),
    "Z": _glyph("111110", "000100", "001000", "010000", "111110", "000000"),
    "a": _glyph("000000", "011110", "100010", "100010", "011110", "000000"),
    "b": _glyph("100000", "111100", "100010", "100010", "111100", "000000"),
    "c": _glyph("000000", "011110", "100000", "100000", "011110", "000000"),
    "d": _glyph("000010", "011110", "100010", "100010", "011110", "000000"),
    "e": _glyph("000000", "011100", "111110", "100000", "011100", "000000"),
    "f": _glyph("000110", "001000", "011110", "001000", "001000", "000000"),
    "g": _glyph("000000", "011110", "100010", "011110", "000010", "011100"),
    "h": _glyph("100000", "100000", "111100", "100010", "100010", "000000"),
    "i": _glyph("001000", "000000", "011000", "001000", "001000", "000000"),
    "j": _glyph("001000", "000000", "001000", "001000", "001000", "010000"),
    "k": _glyph("010000", "010000", "010010", "011100", "010010", "000000"),
    "l": _glyph("010000", "010000", "010000", "010000", "001100", "000000"),
    "m": _glyph("000000", "110100", "101010", "101010", "100010", "000000"),
    "n": _glyph("000000", "111100", "100010", "100010", "100010", "000000"),
    "o": _glyph("000000", "011100", "100010", "100010", "011100", "000000"),
    "p": _glyph("000000", "111100", "100010", "100010", "111100", "100000"),
    "q": _glyph("000000", "011110", "100010", "100010", "011110", "000010"),
    "r": _glyph("000000", "111100", "100010", "100000", "100000", "000000"),
    "s": _glyph("000000", "001110", "011000", "000110", "111100", "000000"),
    "t": _glyph("010000", "111100", "010000", "010000", "001100", "000000"),
    "u": _glyph("000000", "100010", "100010", "100010", "011100", "000000"),
    "v": _glyph("000000", "100010", "100010", "010100", "001000", "000000"),
    "w": _glyph("000000", "100010", "101010", "101010", "010100", "000000"),
    "x": _glyph("000000", "010010", "001100", "001100", "010010", "000000"),
    "y": _glyph("000000", "100010", "100010", "011110", "000010", "001100"),
    "z": _glyph("000000", "011110", "000100", "001000", "011110", "000000"),
    "0": _glyph("011100", "100010", "101010", "100010", "011100", "000000"),
    "1": _glyph("001000", "011000", "001000", "001000", "011100", "000000"),
    "2": _glyph("001100", "010010", "000100", "001000", "011110", "000000"),
    "3": _glyph("011110", "000010", "000100", "010010", "001100", "000000"),
    "4": _glyph("010100", "010100", "011110", "000100", "000100", "000000"),
    "5": _glyph("011110", "010000", "011100", "000010", "011100", "000000"),
    "6": _glyph("001100", "010000", "011100", "010010", "001100", "000000"),
    "7": _glyph("011110", "000010", "000100", "001000", "001000", "000000"),
    "8": _glyph("001100", "010010", "001100", "010010", "001100", "000000"),
    "9": _glyph("001100", "010010", "001110", "000010", "001100", "000000"),
    ".": _glyph("000000", "000000", "000000", "000000", "001000", "000000"),
    ",": _glyph("000000", "000000", "000000", "001000", "010000", "000000"),
    "!": _glyph("001000", "001000", "001000", "000000", "001000", "000000"),
    "?": _glyph("111000", "000100", "001000", "000000", "001000", "000000"),
    ":": _glyph("000000", "000000", "001000", "000000", "001000", "000000"),
    "+": _glyph("000000", "000000", "001000", "011100", "001000", "000000"),
    "-": _glyph("000000", "000000", "000000", "011100", "000000", "000000"),
    "/": _glyph("000010", "000100", "001000", "010000", "100000", "000000"),
    "=": _glyph("000000", "011100", "000000", "011100", "000000", "000000"),
    "'": _glyph("001000", "001000", "000000", "000000", "000000", "000000"),
    ">": _glyph("100000", "010000", "001000", "010000", "100000", "000000"),
    "<": _glyph("000010", "000100", "001000", "000100", "000010", "000000"),
    "%": _glyph("100010", "000100", "001000", "010000", "100010", "000000"),
    "_": _glyph("000000", "000000", "000000", "000000", "111110", "000000"),
    " ": _glyph("000000", "000000", "000000", "000000", "000000", "000000"),
}

PIOREACTOR_ICON_FRAMES_12X12 = (
    (
        0b001111111100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b011100001110,
        0b011001100110,
        0b010001100010,
        0b011000000110,
        0b011000000110,
        0b001111111100,
    ),
    (
        0b001111111100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b011100001100,
        0b011011000110,
        0b010011000010,
        0b011000000110,
        0b011000000110,
        0b001100001100,
        0b001111111100,
    ),
    (
        0b001111111100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b011100001110,
        0b011001100110,
        0b010011110010,
        0b011000000110,
        0b011000000110,
        0b011000000110,
        0b001111111100,
    ),
    (
        0b001111111100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001100,
        0b001100001110,
        0b011000110110,
        0b010000110010,
        0b011000000110,
        0b011000000110,
        0b001100001100,
        0b001111111100,
    ),
)

DEFAULT_REFRESH_INTERVAL = 2.0
DEFAULT_BANNER_SECONDS = 5.0
DEFAULT_DRIVER = "auto"
DEFAULT_ROTATION = 2
VALID_ROTATIONS = frozenset((0, 1, 2, 3))
DEFAULT_METRICS = ("od_filtered", "growth_rate", "temperature", "measured_rpm")

MetricDecoder = Callable[[bytes], float | None]


def _decode_float_payload(payload: bytes) -> float | None:
    try:
        return float(payload.decode())
    except (TypeError, ValueError):
        return None


def _decode_od_filtered(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.ODFiltered).od_filtered
    except Exception:
        return None


def _decode_growth_rate(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.GrowthRate).growth_rate
    except Exception:
        return None


def _decode_temperature(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.Temperature).temperature
    except Exception:
        return None


def _decode_measured_rpm(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.MeasuredRPM).measured_rpm
    except Exception:
        return None


def _decode_ods(payload: bytes) -> float | None:
    try:
        od_readings = decode(payload, type=structs.ODReadings).ods
    except Exception:
        return None

    values = [reading.od for reading in od_readings.values()]
    if not values:
        return None
    return sum(values) / len(values)


def _decode_od_fused(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.ODFused).od_fused
    except Exception:
        return None


def _decode_volume_change(payload: bytes) -> float | None:
    try:
        return decode(payload, type=structs.DosingEvent).volume_change
    except Exception:
        return None


METRIC_SPECS: dict[str, dict[str, object]] = {
    "od_filtered": {
        "label": "OD",
        "topic": "growth_rate_calculating/od_filtered",
        "decoder": _decode_od_filtered,
        "format": "{:.2f}",
    },
    "growth_rate": {
        "label": "GR",
        "topic": "growth_rate_calculating/growth_rate",
        "decoder": _decode_growth_rate,
        "format": "{:+.2f}/h",
    },
    "temperature": {
        "label": "TEMP",
        "topic": "temperature_automation/temperature",
        "decoder": _decode_temperature,
        "format": "{:.1f}C",
    },
    "ods": {
        "label": "ODS",
        "topic": "od_reading/ods",
        "decoder": _decode_ods,
        "format": "{:.2f}",
    },
    "od_fused": {
        "label": "fOD",
        "topic": "od_reading/od_fused",
        "decoder": _decode_od_fused,
        "format": "{:.2f}",
    },
    "measured_rpm": {
        "label": "mRPM",
        "topic": "stirring/measured_rpm",
        "decoder": _decode_measured_rpm,
        "format": "{:.0f}",
    },
    "target_rpm": {
        "label": "tRPM",
        "topic": "stirring/target_rpm",
        "decoder": _decode_float_payload,
        "format": "{:.0f}",
    },
    "target_temperature": {
        "label": "TTEMP",
        "topic": "temperature_automation/target_temperature",
        "decoder": _decode_float_payload,
        "format": "{:.1f}C",
    },
    "volume_change": {
        "label": "VOL +/-",
        "topic": "dosing_events",
        "decoder": _decode_volume_change,
        "format": "{:+.2f}mL",
        "allow_retained": False,
    },
    "current_volume_ml": {
        "label": "VOL",
        "topic": "bioreactor/current_volume_ml",
        "decoder": _decode_float_payload,
        "format": "{:.1f}mL",
    },
}


def _parse_i2c_address(value: str) -> int:
    try:
        return int(value, 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("I2C address should be an int like 60 or 0x3C.") from exc


def _validate_rotation(rotation: int) -> int:
    if rotation not in VALID_ROTATIONS:
        valid_values = ", ".join(str(value) for value in sorted(VALID_ROTATIONS))
        raise ValueError(f"Display rotation should be one of: {valid_values}.")
    return rotation


def _get_refresh_interval_from_config() -> float:
    return config.getfloat(
        "oled_status_display.config",
        "refresh_interval_seconds",
        fallback=DEFAULT_REFRESH_INTERVAL,
    )


def _get_banner_seconds_from_config() -> float:
    return config.getfloat(
        "oled_status_display.config",
        "banner_seconds",
        fallback=DEFAULT_BANNER_SECONDS,
    )


def _get_driver_from_config() -> str:
    return config.get(
        "oled_status_display.config",
        "driver",
        fallback=DEFAULT_DRIVER,
    )


def _get_rotation_from_config() -> int:
    return config.getint(
        "oled_status_display.config",
        "rotation",
        fallback=DEFAULT_ROTATION,
    )


def _get_i2c_address_from_config() -> str:
    return config.get(
        "oled_status_display.config",
        "i2c_address",
        fallback=DEFAULT_I2C_ADDRESS,
    )


def _parse_metrics(value: str) -> tuple[str, str, str, str]:
    metric_ids = tuple(metric.strip() for metric in value.split(",") if metric.strip())
    if len(metric_ids) != 4:
        raise ValueError("Exactly four OLED metrics are required.")

    unknown_metric_ids = sorted(set(metric_ids) - set(METRIC_SPECS))
    if unknown_metric_ids:
        available_metrics = ", ".join(sorted(METRIC_SPECS))
        unknown_metrics = ", ".join(unknown_metric_ids)
        raise ValueError(f"Unknown OLED metric(s): {unknown_metrics}. Available metrics: {available_metrics}.")

    return metric_ids


def _get_metrics_from_config() -> tuple[str, str, str, str]:
    return _parse_metrics(
        config.get(
            "oled_status_display.config",
            "metrics",
            fallback=",".join(DEFAULT_METRICS),
        )
    )


def _truncate(text: str, max_chars: int = MAX_LINE_LENGTH) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."


@lru_cache
def _get_ttyp0_font() -> dict[str, dict[str, object]]:
    lines = files("oled_status_display").joinpath(TTYP0_FONT_RESOURCE).read_text(encoding="utf-8").splitlines()
    glyphs: dict[str, dict[str, object]] = {}
    index = 0

    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue

        name = lines[index].split()[1]
        dwidth = PIXEL_FONT_WIDTH
        bbx: tuple[int, int, int, int] | None = None
        bitmap: list[str] = []
        index += 1

        while index < len(lines) and lines[index] != "ENDCHAR":
            parts = lines[index].split()
            if not parts:
                index += 1
                continue

            if parts[0] == "DWIDTH":
                dwidth = int(parts[1])
            elif parts[0] == "BBX":
                bbx = (int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
            elif parts[0] == "BITMAP":
                index += 1
                while index < len(lines) and lines[index] != "ENDCHAR":
                    bitmap.append(lines[index].strip())
                    index += 1
                break

            index += 1

        if bbx is not None:
            glyphs[name] = {
                "dwidth": dwidth,
                "bbx": bbx,
                "bitmap": tuple(bitmap),
            }

        index += 1

    return glyphs


def _ttyp0_glyph_for_character(character: str) -> dict[str, object] | None:
    glyph_name = TTYP0_GLYPH_NAMES.get(character)
    if glyph_name is None:
        return None
    return _get_ttyp0_font().get(glyph_name, _get_ttyp0_font()["PQuestion"])


def _pixel_text_width(text: str, *, scale: int = 1, tracking: int = 0) -> int:
    width = 0
    for character in text:
        glyph = _ttyp0_glyph_for_character(character)
        width += int(glyph["dwidth"]) * scale if glyph is not None else PIXEL_FONT_WIDTH * scale
    return width + max(0, len(text) - 1) * tracking


def _truncate_to_pixel_width(text: str, max_width: int, *, scale: int = 1, tracking: int = 0) -> str:
    if _pixel_text_width(text, scale=scale, tracking=tracking) <= max_width:
        return text

    suffix = ".."
    suffix_width = _pixel_text_width(suffix, scale=scale, tracking=tracking)
    output = ""
    for character in text:
        if _pixel_text_width(output + character, scale=scale, tracking=tracking) + suffix_width > max_width:
            break
        output += character
    return output + suffix


def _character_capacity_for_pixel_width(max_width: int, *, scale: int = 1, tracking: int = 0) -> int:
    character_width = _pixel_text_width("0", scale=scale, tracking=tracking) + tracking
    return max(1, (max_width + tracking) // character_width)


def _scroll_text_to_pixel_width(
    text: str,
    max_width: int,
    *,
    tick: int,
    scale: int = 1,
    tracking: int = 0,
) -> str:
    capacity = _character_capacity_for_pixel_width(max_width, scale=scale, tracking=tracking)
    if len(text) <= capacity:
        return text

    pause_ticks = 2
    padded_text = f"{text}   "
    wrapped_tick = tick % (len(padded_text) + pause_ticks)
    offset = max(0, wrapped_tick - pause_ticks)
    return (padded_text + padded_text)[offset : offset + capacity]


def _draw_pixel_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill: int = 255,
    scale: int = 1,
    tracking: int = 0,
    max_width: int | None = None,
) -> None:
    x, y = xy
    if max_width is not None:
        text = _truncate_to_pixel_width(text, max_width, scale=scale, tracking=tracking)

    if not text:
        return

    for character in text:
        glyph = _ttyp0_glyph_for_character(character)
        if glyph is None:
            x += PIXEL_FONT_WIDTH * scale + tracking
            continue

        glyph_width, _, x_offset, _ = glyph["bbx"]
        for row_index, row in enumerate(glyph["bitmap"]):
            row_bits = int(row, 16)
            bit_count = len(row) * 4
            for bit_index in range(glyph_width):
                if row_bits & (1 << (bit_count - 1 - bit_index)):
                    draw.rectangle(
                        (
                            x + (x_offset + bit_index) * scale,
                            y + row_index * scale,
                            x + (x_offset + bit_index + 1) * scale - 1,
                            y + (row_index + 1) * scale - 1,
                        ),
                        fill=fill,
                    )
        x += int(glyph["dwidth"]) * scale + tracking


def _draw_scrolling_pixel_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    max_width: int,
    tick: int,
    fill: int = 255,
) -> None:
    visible_text = _scroll_text_to_pixel_width(text, max_width, tick=tick)
    _draw_pixel_text(draw, xy, visible_text, fill=fill, max_width=max_width)


def _draw_pioreactor_icon(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    frame_index: int,
    *,
    fill: int = 255,
    scale: int = 1,
) -> None:
    x, y = xy
    icon = PIOREACTOR_ICON_FRAMES_12X12[frame_index % len(PIOREACTOR_ICON_FRAMES_12X12)]
    for row_index, row in enumerate(icon):
        for bit_index in range(12):
            if row & (1 << (11 - bit_index)):
                draw.rectangle(
                    (
                        x + bit_index * scale,
                        y + row_index * scale,
                        x + (bit_index + 1) * scale - 1,
                        y + (row_index + 1) * scale - 1,
                    ),
                    fill=fill,
                )


@lru_cache
def _get_splash_logo() -> Image.Image:
    with files("oled_status_display").joinpath(SPLASH_LOGO_RESOURCE).open("rb") as splash_logo_file:
        return Image.open(splash_logo_file).convert("1")


class OLEDStatusDisplay(LongRunningBackgroundJobContrib):
    job_name = "oled_status_display"

    def __init__(
        self,
        unit: str,
        experiment: str,
        *,
        refresh_interval: float,
        i2c_address: int,
        rotation: int,
        driver: str,
        banner_seconds: float,
        metrics: tuple[str, str, str, str],
    ) -> None:
        super().__init__(unit=unit, experiment=experiment, plugin_name=__plugin_name__)

        self._data_lock = threading.Lock()
        self._experiment = self._resolve_experiment()
        self._metrics = metrics
        self._metric_values: dict[str, float | None] = {metric_id: None for metric_id in self._metrics}
        self._ip = get_ip() or "unknown"
        self._banner_text: Optional[str] = None
        self._banner_until = 0.0
        self._banner_priority = -1
        self._banner_seconds = banner_seconds
        self._banner_scroll_tick = 0
        self._ip_scroll_tick = 0
        self._icon_animation_tick = 0

        self.disp = self._initialize_display(i2c_address=i2c_address, rotation=rotation, driver=driver)

        self.width = self.disp.width
        self.height = self.disp.height
        self.image = Image.new("1", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)
        self.show_splash_page()

        self.refresh_timer = RepeatedTimer(
            refresh_interval,
            self.update_display,
            job_name=self.job_name,
            run_immediately=False,
            run_after=SPLASH_SECONDS,
            logger=self.logger,
        ).start()

        self.start_passive_listeners()

    def _initialize_display(self, *, i2c_address: int, rotation: int, driver: str):
        from pioreactor.hardware import SCL
        from pioreactor.hardware import SDA

        rotation = _validate_rotation(rotation)
        i2c = busio.I2C(SCL, SDA)
        return self._initialize_display_with_bus(
            i2c=i2c,
            i2c_address=i2c_address,
            rotation=rotation,
            driver=driver,
        )

    def _initialize_display_with_bus(self, *, i2c, i2c_address: int, rotation: int, driver: str):
        if driver == "auto":
            for candidate in ("ssd1306", "sh1106"):
                try:
                    return self._initialize_display_with_bus(
                        i2c=i2c,
                        i2c_address=i2c_address,
                        rotation=rotation,
                        driver=candidate,
                    )
                except Exception:
                    continue
            self.logger.error("Unable to initialize OLED display with SSD1306 or SH1106 drivers.")
            self.clean_up()
            raise RuntimeError("No compatible OLED driver found.")

        if driver == "ssd1306":
            import adafruit_ssd1306

            disp = adafruit_ssd1306.SSD1306_I2C(DISPLAY_WIDTH, DISPLAY_HEIGHT, i2c, addr=i2c_address)
        elif driver == "sh1106":
            import adafruit_sh1106

            disp = adafruit_sh1106.SH1106_I2C(DISPLAY_WIDTH, DISPLAY_HEIGHT, i2c, addr=i2c_address)
        else:
            raise ValueError(f"Unknown driver: {driver}")

        disp.rotation = rotation
        disp.fill(0)
        disp.show()
        return disp

    def _resolve_experiment(self) -> str:
        try:
            experiment = get_assigned_experiment_name(self.unit)
        except Exception:
            experiment = UNIVERSAL_EXPERIMENT
        if experiment in (UNIVERSAL_EXPERIMENT, NO_EXPERIMENT):
            return "-"
        return experiment

    def _set_current_experiment(self, experiment: str) -> None:
        with self._data_lock:
            if experiment == self._experiment:
                return

            self._experiment = experiment
            for metric_id in self._metric_values:
                self._metric_values[metric_id] = None
            self._banner_text = None
            self._banner_priority = -1

    def _normalize_assignment_experiment(self, experiment: object) -> str:
        if isinstance(experiment, str) and experiment not in (UNIVERSAL_EXPERIMENT, NO_EXPERIMENT):
            return experiment
        return "-"

    def _update_assignment(self, msg) -> None:
        if not msg.payload:
            return
        try:
            payload = decode(msg.payload)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("pioreactor_unit") != self.unit:
            return

        self._set_current_experiment(self._normalize_assignment_experiment(payload.get("experiment")))

    def _topic_matches_current_experiment(self, topic: str) -> bool:
        parts = topic.split("/")
        if len(parts) < 4:
            return False
        experiment = parts[2]
        if not experiment or experiment in (UNIVERSAL_EXPERIMENT, NO_EXPERIMENT):
            return False
        with self._data_lock:
            return experiment == self._experiment

    def start_passive_listeners(self) -> None:
        self.subscribe_and_callback(
            self._update_assignment,
            f"pioreactor/{self.unit}/$experiment/assignment",
        )

        for metric_id in sorted(set(self._metrics)):
            spec = METRIC_SPECS[metric_id]
            topic = cast(str, spec["topic"])
            allow_retained = cast(bool, spec.get("allow_retained", True))
            self.subscribe_and_callback(
                self._metric_update_callback(metric_id),
                f"pioreactor/{self.unit}/+/{topic}",
                allow_retained=allow_retained,
            )

        self.subscribe_and_callback(
            self._update_log_event,
            [
                f"pioreactor/{self.unit}/+/logs/+/warning",
                f"pioreactor/{self.unit}/+/logs/+/error",
            ],
            allow_retained=False,
        )

    def _metric_update_callback(self, metric_id: str) -> Callable[[object], None]:
        def update_metric(msg) -> None:
            self._update_metric(metric_id, msg)

        return update_metric

    def _update_metric(self, metric_id: str, msg) -> None:
        if not self._topic_matches_current_experiment(msg.topic):
            return
        if not msg.payload:
            value = None
        else:
            decoder = cast(MetricDecoder, METRIC_SPECS[metric_id]["decoder"])
            value = decoder(msg.payload)
        with self._data_lock:
            self._metric_values[metric_id] = value

    def _update_log_event(self, msg) -> None:
        parts = msg.topic.split("/")
        if len(parts) < 5:
            return
        if not self._topic_matches_current_experiment(msg.topic):
            return
        if not msg.payload:
            return
        try:
            payload = decode(msg.payload)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        level = str(payload.get("level", "")).upper() or "LOG"
        message = str(payload.get("message", "")).strip()
        if not message:
            return
        message = message.splitlines()[0]
        priority = 3 if level == "ERROR" else 2
        self._set_banner_text(f"{level}: {message}", priority=priority)

    def _set_banner_text(self, text: str, priority: int) -> None:
        now = monotonic()
        with self._data_lock:
            if now <= self._banner_until and priority < self._banner_priority:
                return
            self._banner_text = text
            self._banner_priority = priority
            self._banner_until = now + self._banner_seconds
            self._banner_scroll_tick = 0

    def _snapshot(self) -> dict[str, object]:
        with self._data_lock:
            banner_text = None
            if self._banner_text and monotonic() <= self._banner_until:
                banner_text = self._banner_text
            elif self._banner_text:
                self._banner_text = None
                self._banner_priority = -1
            return {
                "metric_values": dict(self._metric_values),
                "banner_text": banner_text,
            }

    def _format_metric_value(self, metric_id: str, metric_values: dict[str, float | None]) -> str:
        spec = METRIC_SPECS[metric_id]
        value = metric_values.get(metric_id)
        if value is None:
            return "--"
        return cast(str, spec["format"]).format(value)

    def update_display(self) -> None:
        snapshot = self._snapshot()
        metric_values = cast(dict[str, float | None], snapshot["metric_values"])
        banner_text = snapshot.get("banner_text")

        rows = [
            (
                cast(str, METRIC_SPECS[metric_id]["label"]),
                self._format_metric_value(metric_id, metric_values),
            )
            for metric_id in self._metrics
        ]

        self.draw.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        self.draw.rectangle((0, 0, self.width - 1, self.height - 1), outline=255)
        self.draw.line((0, 15, self.width - 1, 15), fill=255)

        _draw_pioreactor_icon(self.draw, (4, 2), self._icon_animation_tick)
        self._icon_animation_tick += 1
        _draw_pixel_text(self.draw, (20, 2), str(self.unit), max_width=42)
        _draw_scrolling_pixel_text(
            self.draw,
            (67, 2),
            str(self._ip),
            max_width=58,
            tick=self._ip_scroll_tick,
        )
        self._ip_scroll_tick += 1

        self.draw.line((63, 16, 63, self.height - 1), fill=255)
        self.draw.line((0, 39, self.width - 1, 39), fill=255)

        metric_cells = (
            (5, 18, 58),
            (68, 18, 57),
            (5, 42, 58),
            (68, 42, 57),
        )
        for (label, value), (x, y, max_width) in zip(rows, metric_cells):
            _draw_pixel_text(self.draw, (x, y), label, max_width=max_width)
            _draw_pixel_text(self.draw, (x, y + 10), value, max_width=max_width)

        if banner_text:
            banner_y = self.height - TTYP0_FONT_HEIGHT
            self.draw.rectangle((0, banner_y, self.width - 1, self.height - 1), fill=255)
            _draw_scrolling_pixel_text(
                self.draw,
                (3, banner_y),
                str(banner_text),
                max_width=121,
                tick=self._banner_scroll_tick,
                fill=0,
            )
            self._banner_scroll_tick += 1

        self.disp.image(self.image)
        self.disp.show()

    def show_splash_page(self) -> None:
        self.draw.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        splash_logo = _get_splash_logo()
        x = (self.width - splash_logo.width) // 2
        y = (self.height - splash_logo.height) // 2
        self.image.paste(splash_logo, (x, y))
        self.disp.image(self.image)
        self.disp.show()

    def clear_display(self) -> None:
        self.draw.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        self.disp.image(self.image)
        self.disp.show()

    def on_disconnected(self) -> None:
        try:
            self.refresh_timer.cancel()
        except Exception:
            pass
        try:
            self.clear_display()
        except Exception:
            pass


@click.command(name="oled_status_display")
@click.option(
    "--refresh-interval",
    type=float,
    default=None,
    help="Seconds between display refreshes. Defaults to oled_status_display.config.refresh_interval_seconds.",
)
@click.option(
    "--banner-seconds",
    type=float,
    default=None,
    help="Seconds to keep transient banners on screen. Defaults to oled_status_display.config.banner_seconds.",
)
@click.option(
    "--driver",
    type=click.Choice(["auto", "ssd1306", "sh1106"]),
    default=None,
    help="OLED driver to use. Defaults to oled_status_display.config.driver.",
)
@click.option(
    "--i2c-address",
    default=None,
    help="I2C address for the display. Defaults to oled_status_display.config.i2c_address.",
)
@click.option(
    "--rotation",
    type=click.IntRange(0, 3),
    default=None,
    help="Display rotation (0-3). Defaults to oled_status_display.config.rotation.",
)
@click.option(
    "--metrics",
    default=None,
    help="Comma-separated list of four OLED metrics. Defaults to oled_status_display.config.metrics.",
)
def click_oled_status_display(
    refresh_interval: float | None,
    banner_seconds: float | None,
    driver: str | None,
    i2c_address: str | None,
    rotation: int | None,
    metrics: str | None,
) -> None:
    """Show Pioreactor status on a 128x64 OLED display."""
    refresh_interval = refresh_interval if refresh_interval is not None else _get_refresh_interval_from_config()
    banner_seconds = banner_seconds if banner_seconds is not None else _get_banner_seconds_from_config()
    driver = driver if driver is not None else _get_driver_from_config()
    rotation = rotation if rotation is not None else _get_rotation_from_config()
    i2c_address = i2c_address if i2c_address is not None else _get_i2c_address_from_config()
    try:
        parsed_metrics = _parse_metrics(metrics) if metrics is not None else _get_metrics_from_config()
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="metrics") from exc

    try:
        parsed_i2c_address = _parse_i2c_address(i2c_address)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    try:
        rotation = _validate_rotation(rotation)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="rotation") from exc
    with OLEDStatusDisplay(
        unit=get_unit_name(),
        experiment=UNIVERSAL_EXPERIMENT,
        refresh_interval=refresh_interval,
        i2c_address=parsed_i2c_address,
        rotation=rotation,
        driver=driver,
        banner_seconds=banner_seconds,
        metrics=parsed_metrics,
    ) as job:
        job.block_until_disconnected()
