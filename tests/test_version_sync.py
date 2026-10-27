"""One release version, everywhere it is written down.

`star/version.py` is the source. The package attribute `star.__version__` once said 0.2.0
while the release was 0.9.0; it now re-exports the source, and the two places a build tool
reads without importing Python (pyproject.toml, frontend/package.json) must say the same.
"""
import json
import re
import tomllib
from pathlib import Path

import star
from star import version

ROOT = Path(__file__).resolve().parents[1]


def test_the_package_attribute_is_the_release_version_and_not_a_copy():
    assert star.__version__ == version.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.__version__)
    # No version number of its own in star/__init__.py: a literal there is what went stale.
    source = (ROOT / "star" / "__init__.py").read_text(encoding="utf-8")
    assert "from .version import __version__" in source
    assert not re.search(r"\d+\.\d+\.\d+", source)


def test_pyproject_and_the_frontend_package_carry_the_same_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert project["version"] == package["version"] == star.__version__ == version.__version__


def test_the_installer_script_and_the_site_version_file_carry_the_same_version():
    installer = (ROOT / "installer" / "STAR.iss").read_text(encoding="utf-8")
    defined = re.search(r'#define\s+StarVersion\s+"([^"]+)"', installer)
    assert defined and defined.group(1) == version.__version__
    site = json.loads((ROOT / "site" / "version.json").read_text(encoding="utf-8"))
    assert site["version"] == version.__version__
