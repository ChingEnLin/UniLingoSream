""" Single place that reads config.json.

Every module used to open and parse the file itself, each with its own try/except and
its own idea of what a failure means. This returns the parsed dict, or {} if the file is
missing or unreadable, so callers just merge it over their own defaults.
"""

import json
import logging

logger = logging.getLogger(__name__)


def load_config(path="config.json"):
    """ Parse `path` and return the dict, or {} if it is missing or unreadable. """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # Normal on first run / when a caller probes an optional path.
        logger.info("Config file not found: %s. Using defaults.", path)
    except Exception as e:
        logger.warning("Failed to load config file %s (%s). Using defaults.", path, e)
    return {}


if __name__ == "__main__":
    import tempfile
    import os

    assert load_config("/no/such/file.json") == {}, "missing file must yield {}"

    bad = tempfile.mktemp(suffix=".json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert load_config(bad) == {}, "corrupt file must yield {} not raise"
    os.remove(bad)

    good = tempfile.mktemp(suffix=".json")
    with open(good, "w", encoding="utf-8") as f:
        json.dump({"ui": {"font_size": 42}}, f)
    assert load_config(good)["ui"]["font_size"] == 42, "valid config not parsed"
    os.remove(good)
    print("config self-check passed")
