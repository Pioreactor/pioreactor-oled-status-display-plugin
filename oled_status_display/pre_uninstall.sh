#!/bin/bash

set -x
set -e

export LC_ALL=C

sudo systemctl stop pioreactor_startup_run@oled_status_display.service
sudo systemctl disable pioreactor_startup_run@oled_status_display.service
