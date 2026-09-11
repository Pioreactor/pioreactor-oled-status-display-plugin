# -*- coding: utf-8 -*-
from __future__ import annotations

from pioreactor.actions.self_test import register_self_tests
from pioreactor.hardware import is_i2c_device_present
from pioreactor.logging import CustomLogger
from pioreactor.utils import managed_lifecycle

from oled_status_display.display import _get_i2c_address_from_config
from oled_status_display.display import _parse_i2c_address
from oled_status_display.display import __plugin_author__
from oled_status_display.display import __plugin_name__
from oled_status_display.display import __plugin_summary__
from oled_status_display.display import __plugin_version__
from oled_status_display.display import click_oled_status_display


def test_oled_display_is_present(
    managed_state: managed_lifecycle, logger: CustomLogger, unit: str, experiment: str
) -> None:
    address = _parse_i2c_address(_get_i2c_address_from_config())
    assert is_i2c_device_present(address), f"OLED display is not responding at I2C address {address:#04x}."


register_self_tests(test_oled_display_is_present)


__all__ = [
    "__plugin_author__",
    "__plugin_name__",
    "__plugin_summary__",
    "__plugin_version__",
    "click_oled_status_display",
]
