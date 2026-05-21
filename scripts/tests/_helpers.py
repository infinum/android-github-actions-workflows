"""Shared module loader. Script filenames use hyphens (parse-gradle-deps.py),
so we can't import them as normal Python modules — load them via importlib."""
import importlib.util
import pathlib
import sys


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent


def load(filename: str):
    """Load a script from the scripts/ directory by filename."""
    path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
