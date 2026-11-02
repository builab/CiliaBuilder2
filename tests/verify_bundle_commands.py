"""In a fresh ChimeraX session: runscript tests/verify_bundle_commands.py."""

import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from chimerax.core.commands import run

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from src import bundle_api

# Register every advertised command using ChimeraX's real signature checks.
metadata = ElementTree.parse(root / "bundle_info.xml").getroot()
names = []
for element in metadata.findall("Classifiers/ChimeraXClassifier"):
    fields = [field.strip() for field in element.text.split("::")]
    if fields[:2] != ["ChimeraX", "Command"]:
        continue
    name = fields[2]
    bundle_api.register_command(None, SimpleNamespace(name=name, synopsis=fields[4]), session.logger)
    names.append(name)

before = set(session.models.list())
try:
    run(session, "cbstraight length 1000 nDoublet 3 radius 100 spacing 500 openStar false")
    run(session, "buildcentralpair length 1000 spacing 500 openStar false")
    stars = [model for model in session.models.list()
             if model not in before and hasattr(model, "_cb_star_rows")]
    assert sorted(len(model._cb_star_rows) for model in stars) == [3, 9]
finally:
    session.models.close([model for model in session.models.list() if model not in before])

print("Bundle command registration and STAR generation passed:", ", ".join(names))
