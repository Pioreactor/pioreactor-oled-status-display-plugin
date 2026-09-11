# Pioreactor OLED Status Display Plugin

Show Pioreactor status on a 128x64 monochrome OLED display.

This is a long-running Pioreactor plugin job named `oled_status_display`. It subscribes to local Pioreactor MQTT topics and renders a compact terminal-style dashboard with:

- unit name and horizontally scrolling IP address
- OD filtered
- growth rate
- temperature
- measured RPM
- transient warning and error banners

The display supports SSD1306 128x64 I2C OLEDs by default. The code can also use `adafruit_sh1106` if that driver module is installed separately; by default, the plugin tries SSD1306 first, then SH1106.

## Install From Source

```bash
pio plugins install oled_status_display --source .
```

The plugin includes a `post_install.sh` hook that starts and enables the startup service:

```bash
sudo systemctl enable pioreactor_startup_run@oled_status_display.service
```

It also includes a `pre_uninstall.sh` hook that stops and disables the same service.

## Configuration

The following defaults are installed into Pioreactor configuration:

```ini
[oled_status_display.config]
refresh_interval_seconds=2
banner_seconds=5
driver=auto
i2c_address=0x3D
rotation=0
metrics=od_filtered,growth_rate,temperature,measured_rpm
```

Set `driver` to `ssd1306`, `sh1106`, or `auto`. Set `i2c_address` to the detected display address, commonly `0x3C` or `0x3D`. Set `rotation` to `0`, `1`, `2`, or `3`.

Set `metrics` to a comma-separated list of exactly four metric ids. These names match the corresponding Pioreactor core MQTT attributes:

- `od_filtered`
- `ods`
- `od_fused`
- `growth_rate`
- `temperature`
- `target_temperature`
- `measured_rpm`
- `target_rpm`
- `volume_change`
- `current_volume_ml`

## Run Manually

```bash
pio run oled_status_display
```
