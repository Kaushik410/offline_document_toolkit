# Third-party components

The application source is licensed under AGPL-3.0-only (see LICENSE). Dependencies retain their own copyright notices and licenses. Include the corresponding source and applicable notices when distributing builds.

| Component | Upstream license / source |
| --- | --- |
| PyMuPDF / MuPDF | [AGPLv3 or commercial](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) |
| PySide6 / Qt / Shiboken | [LGPLv3, GPLv3, or commercial, depending on component](https://doc.qt.io/qtforpython-6/licenses.html) |
| pypdf | [BSD-3-Clause](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |
| Pillow | [HPND](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| OpenCV | [Apache-2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE) |
| NumPy | [BSD-3-Clause and bundled notices](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| pytesseract | [Apache-2.0](https://github.com/madmaze/pytesseract/blob/master/LICENSE) |
| python-docx | [MIT](https://github.com/python-openxml/python-docx/blob/master/LICENSE) |
| lxml | [BSD and bundled notices](https://lxml.de/copyright.html) |
| packaging | [Apache-2.0 or BSD-2-Clause](https://github.com/pypa/packaging/blob/main/LICENSE) |
| typing_extensions | [PSF-2.0](https://github.com/python/typing_extensions/blob/main/LICENSE) |

Tesseract, LibreOffice, and Ghostscript are separate system dependencies, not bundled by this project. Obtain them and their notices from their official distributions. PyInstaller builds include Python and dependency binaries; the build specification collects their installed license metadata. Preserve those files and distribute the matching project source archive with each binary release.
