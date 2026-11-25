"""Build the portable ZIP using a Windows x64 python.org installation with Tk."""
import argparse
from importlib.metadata import distribution, files
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from distlib.scripts import ScriptMaker

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.base_prefix)


def copy_runtime(runtime):
    runtime.mkdir()
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    for filename in ["python.exe", "pythonw.exe", "python3.dll", f"{version}.dll", "LICENSE.txt"]:
        shutil.copy2(PYTHON / filename, runtime)
    for dll in PYTHON.glob("vcruntime*.dll"):
        shutil.copy2(dll, runtime)
    shutil.copytree(PYTHON / "DLLs", runtime / "DLLs")
    shutil.copytree(PYTHON / "tcl", runtime / "tcl",
                    ignore=shutil.ignore_patterns("demos", "nmake", "*.lib", "*.sh"))

    # Store the standard library in one file so Windows only extracts the native
    # runtime and Tcl/Tk resources as individual files. Exclude local packages.
    lib = PYTHON / "Lib"
    skip = {"site-packages", "test", "tests", "__pycache__", "ensurepip", "idlelib", "turtledemo", "venv"}
    with ZipFile(runtime / f"{version}.zip", "w") as archive:
        for directory, dirs, files in os.walk(lib):
            dirs[:] = sorted(set(dirs) - skip)
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix not in {".pyc", ".pyo"}:
                    archive.write(path, path.relative_to(lib))
    # Copy the installed wheel, including its native BLAS DLLs and licenses.
    wheel = distribution("numpy")
    packages = runtime / "packages"
    for entry in wheel.files:
        if not entry.parts[0].startswith("numpy") or "__pycache__" in entry.parts:
            continue
        target = packages / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wheel.locate_file(entry), target)
    # A DLL-specific ._pth keeps the GUI and its -m analysis subprocess on this
    # runtime, even when Python is absent or another installation is on PATH.
    (runtime / f"{version}._pth").write_text(f"{version}.zip\nDLLs\npackages\n.\n../src\n", encoding="ascii")


def build(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staging = Path(temp) / "portable"
        staging.mkdir()
        copy_runtime(staging / "runtime")
        shutil.copytree(PROJECT / "src", staging / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(PROJECT / "sample_output", staging / "sample_output")
        for filename in ("database.pghembk", "config.json"):
            shutil.copy2(PROJECT / filename, staging)
        maker = ScriptMaker(None, str(staging))
        maker.executable = r"<launcher_dir>\runtime\python.exe"
        maker.variants = {""}
        maker.make("PLO-Detector = plo_multiaccount_detector.desktop:main",
                   options={"gui": True, "interpreter_args": ["-B"]})
        license_file = next(entry.locate() for entry in files("distlib") if entry.name == "LICENSE.txt")
        shutil.copy2(license_file, staging / "runtime" / "distlib-LICENSE.txt")
        archive_path = Path(temp) / "portable.zip"
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging))
        archive_path.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Destination .zip file")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().upper() != "AMD64" or sys.maxsize <= 2**32:
        parser.error("Use 64-bit CPython for Windows x64.")
    if args.output.suffix.lower() != ".zip":
        parser.error("The output must be a .zip file.")
    build(args.output.resolve())
