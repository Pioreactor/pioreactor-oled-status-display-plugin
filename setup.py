# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from setuptools import find_packages
from setuptools import setup


README = Path("README.md").read_text(encoding="utf-8")


setup(
    name="pioreactor-oled-status-display-plugin",
    version="0.2.2",
    license_files=("LICENSE.txt",),
    description="Show Pioreactor status on a 128x64 OLED display.",
    long_description=README,
    long_description_content_type="text/markdown",
    author_email="hello@pioreactor.com",
    author="Pioreactor",
    url="https://github.com/Pioreactor/pioreactor-oled-status-display-plugin",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "adafruit-circuitpython-ssd1306>=2.12.16",
        "Pillow>=10.1.0",
    ],
    entry_points={
        "pioreactor.plugins": "pioreactor_oled_status_display_plugin = oled_status_display",
    },
)
