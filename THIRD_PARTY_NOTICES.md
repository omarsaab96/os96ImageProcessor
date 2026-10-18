# Third-party components

OS96 uses Python, Pillow, PySide6 Essentials, Shiboken6, Qt, and the
PyInstaller bootloader, libjpeg-turbo jpegtran, and oxipng. The build script copies installed package license
texts and metadata to `licenses/` in the distribution. Python's license is
also included. Pillow bundles image codecs with additional notices in its
license file.

The public PySide6/Shiboken/Qt packages offer open-source licensing options,
including LGPLv3 for the modules used here. Qt is dynamically linked; its
shared libraries remain separate under `_internal/`. Users may replace
these libraries with compatible modified versions and may reverse engineer
the application as needed to debug modifications to LGPL components.
These rights take precedence over restrictions in the application notice.

Corresponding upstream source and build instructions:

- https://code.qt.io/cgit/pyside/pyside-setup.git/ (tag v6.10.2)
- https://code.qt.io/cgit/qt/qtbase.git/ (tag v6.10.2)
- https://doc.qt.io/qtforpython-6/building_from_source/index.html
- https://github.com/python-pillow/Pillow/tree/12.3.0
- https://code.qt.io/cgit/qt/qtsvg.git/ (tag v6.10.2)
- https://github.com/libjpeg-turbo/libjpeg-turbo/tree/3.2.0
- https://github.com/oxipng/oxipng/tree/v10.2.1
- https://github.com/python/cpython/tree/v3.13.16
- https://github.com/pyinstaller/pyinstaller/tree/v6.16.0

The Windows build is an unsigned release candidate. Do not publish it as
a signed, independently certified, or macOS-validated release. Before public
distribution, complete the release checklist, verify the bundled third-party
notices against the exact runtime, and provide corresponding LGPL source
through the same distribution channel as the binaries.

The native tools remain separate executables under assets/native. Their bundled
license texts are in licenses/native. The jpegtran reference/helper is built
from the source tag with SIMD disabled; oxipng uses its official x64 MSVC release
archive. Asset hashes and origin URLs are recorded in assets/native/manifest.json.
Optimization results are decoded and checked for identical pixels and retained
metadata before replacing the application's temporary encoding.

scripts/package_upstream_sources.py prepares an additional versioned source
archive in dist/. Keep that archive available alongside any binary download.
The owner still needs to choose the original application's distribution license;
this file does not certify a completed legal review.
