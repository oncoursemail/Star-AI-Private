"""Unpack a server jar's real jar + libraries for McCheck: python3 prep_cp.py /srv/mc/<ver> -> <ver>/cp/{server.jar,lib/*.jar}"""
import sys, zipfile
from pathlib import Path
d = Path(sys.argv[1])
z = zipfile.ZipFile(d / "server.jar")
cp = d / "cp"
(cp / "lib").mkdir(parents=True, exist_ok=True)
for n in z.namelist():
    if n.startswith("META-INF/versions/") and n.endswith(".jar"):
        (cp / "server.jar").write_bytes(z.read(n))
    elif n.startswith("META-INF/libraries/") and n.endswith(".jar"):
        (cp / "lib" / Path(n).name).write_bytes(z.read(n))
print(d.name, len(list((cp / "lib").iterdir())), "libs")
