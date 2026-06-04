PYTHON ?= /Users/camerondavidson-pilon/code/pioreactor/.venv/bin/python

.PHONY: build clean

build: clean
	$(PYTHON) -m build --wheel --no-isolation

clean:
	rm -rf build dist pioreactor_oled_status_display_plugin.egg-info oled_status_display_plugin.egg-info
