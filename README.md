# Offline Document Toolkit

A local Python/PySide6 desktop application for PDF, image, OCR, Word, and batch document processing. Document operations use local libraries and installed command-line engines. No account, cloud API, or network connection is required after dependencies are installed.

## Review and submission tools in 0.4

**Workspace → Checklist** selects an editable Application, Reimbursement, or Client packet example, or a custom list of required roles and minimum document counts. **Document role** assigns selected documents to those roles. **Suggest order** arranges pages by checklist order. Queueing checks for missing roles and asks before including repeated source pages. These examples are user-configurable packet structures; they do not encode a particular organization's submission rules.

**Fill PDF form** edits supported native PDF fields without flattening them. Changes appear in previews, remain undoable, and are saved in the exported PDF. Read-only and signature fields are preserved. **Redact area** physically removes content in the selected area, including intersecting form widgets and comments. Apply redaction before image effects; source snapshots and project history retain the originals. Export privacy options separately remove document metadata, comments/annotations, and embedded attachments. The exported PDF is checked against the selected privacy options.

In **Jobs → Review packet**, compare the original pages with the staged packet inside the app. Navigation and zoom are synchronized; text search highlights matches. The **Highlight visual changes** tab overlays changed pixels in red, including intended edits and compression changes. **Correct OCR text** opens the editable OCR review. Saving corrections resumes preparation; reopen the updated packet and approve it when satisfied. The public export report omits internal staging/review paths.

OCR recognition resolution is independent of export resolution and defaults to 400 DPI. Choose Auto, Block, Columns, or Sparse layout. Adaptive OCR compares preprocessing/layout candidates and retries up to ten uncertain lines, using confidence and retained text coverage. Retry candidates that add or remove entire words from a line are rejected. Confidence is an estimate and does not establish correctness; uncertain results still need review.

Undo history stores edit commands instead of duplicating the entire document after each action, with up to 100 undo steps. Existing 0.3 project histories migrate on load. Page processing releases decoded image caches after each page. Workspace preview files use a bounded 128-entry/128 MiB cache and can be regenerated.

## Portable projects, backups, and storage

**Export project** creates an `.odtproject` archive with normalized source PDFs, cached original input files when available, thumbnails, undo/redo history, document roles, field changes, redactions, and saved workflows. **Import project** verifies checksums and restores independent local copies; existing workflow names are preserved. Project archives include original, unredacted snapshots and are intended for continued editing and backup.

**Storage / backup** shows database/cache usage and lets you remove saved projects or stopped job history. Published exports and original input files are preserved. Cache cleanup removes only unreferenced managed files older than 24 hours, protecting the entire undo history and retained jobs. Derived preview caches can be regenerated.

A workspace `.odtbackup` includes an online SQLite snapshot and managed input/job files. Pause active jobs before backing up. Restore into a new or empty directory; internal paths are relocated and queued jobs restore as paused. The app selects the restored workspace on its next launch. If `ODT_DATA_DIR` is set externally, update it to the restored location. Externally indexed library files and published exports outside the workspace folder are not copied into a workspace backup.

**Library** supports tags, collections, duplicate-content groups, and opening a matching page in the embedded viewer. Visible libraries check file size/mtime every minute and reindex changed files. **Recheck files** performs a content-hash check even when timestamps match. **Relink moved file** verifies matching content before moving the library reference, preserving labels. Removing an entry retains the underlying PDF.

## Linux and Windows release verification in 0.4.1

Native releases and CI target **Linux and Windows**. Windows builds are unsigned by default, as selected for this project. The target repository is [Kaushik410/offline_document_toolkit](https://github.com/Kaushik410/offline_document_toolkit).

The installed application can run synthetic acceptance checks without a development Python environment:

```bash
OfflineDocumentToolkit --self-test --self-test-report native-self-test.json
# A release runner must also verify the real external conversion engine:
OfflineDocumentToolkit --self-test --require-libreoffice --self-test-report native-engines.json
# Local package extraction and native saved-project/GUI migration check:
python scripts/verify_installer.py release/installers/offline-document-toolkit_0.4.1_amd64.deb
```

Native reports confirm that the bundled Python runtime is running. They exercise isolated workers, PDF comparison/search, portable projects, form filling, redaction/privacy checks, export/indexing, and backup/restore. The saved-project probe launches the installed GUI, renders a legacy project, exercises undo/redo, saves its migrated history, and exports its content. Installer tests check original input files and published exports as well as saved project state.

The **Native installers** workflow runs on Linux and Windows when manually dispatched or when a `release/linux-windows-*` branch is pushed. It installs LibreOffice and requires its integration test to pass. `ODT_REQUIRE_LIBREOFFICE=1` turns a missing engine or blocked IPC into a failure rather than a skipped verification.

By default, `scripts/build_previous_release.py` verifies and builds the audited **0.4.0 source snapshot** in `packaging/baseline/` on each target OS. This enables a genuine 0.4.0 → 0.4.1 package upgrade even before older Windows installers have been published. The snapshot contains distributable source, not user documents. Supply `previous_release` to use an existing older GitHub release instead. Verification rejects a same-version or newer predecessor instead of labeling a reinstall as an upgrade.

The disposable runner first installs and verifies the current release on a clean machine, then removes it. It installs the predecessor, prepares a saved project with undo history and existing exports, upgrades to the new release, reopens the project in the native GUI, validates its export and real LibreOffice conversion, then uninstalls the app and checks that user data survives. Linux uses Xvfb with the real XCB platform plugin; Windows uses its native Windows plugin. `--system-install` is restricted to disposable GitHub Actions runners. Local default mode only extracts the package and runs the acceptance/migration probes; it does not claim system-install/upgrade/uninstall results.

Windows signing is optional and selected through the workflow's `windows_signing` input:

| Provider | Configuration |
| --- | --- |
| `unsigned` (default) | No signing account or secrets required; reports explicitly say unsigned. |
| `certificate` | `ODT_WINDOWS_CERT_SHA1` for an identity installed in the runner certificate store; optional `ODT_WINDOWS_PFX_BASE64` and `ODT_WINDOWS_PFX_PASSWORD` import an exportable identity. Hardware/KSP-backed identities need a suitably provisioned Windows runner. |
| `azure` | Azure Artifact Signing using OIDC. Secrets: `ODT_AZURE_CLIENT_ID`, `ODT_AZURE_TENANT_ID`, `ODT_AZURE_SUBSCRIPTION_ID`. Repository variables: `ODT_AZURE_SIGN_ENDPOINT`, `ODT_AZURE_SIGN_ACCOUNT`, `ODT_AZURE_SIGN_PROFILE`. Configure the application's federated credential for this repository/ref and grant its identity the certificate-profile signer role. |

Signed builds sign the application before packaging and sign the final installer afterward. Authenticode verification requires a valid trusted signature and a timestamp; certificate-store signing also checks the expected certificate thumbprint. The Azure path verifies the signature produced by the official cloud-signing action. `require_signing=true` refuses an unsigned release. Signing reports and installer/GUI/LibreOffice reports are uploaded even on failures. No signing credentials are included in source or source archives.

The workflows are prepared for remote execution; they are not evidence that external runs have completed. Repository authentication is required to push the release branch and run Actions. Certificate-backed signing requires a configured signing account. A fresh-machine check of downloaded Windows packages is still needed for download-specific OS prompts; unsigned testing does not establish public publisher trust.

## Shared workspace and submission workflows

Start in **Workspace**. Drop PDFs, DOCX files, or images into the page list. Imported documents are copied into a private local cache, so edits never change the original files. Drag pages to reorder them; select an area in the preview to crop, blur, or add text. Rotate, grayscale, brightness, and denoise operations can be combined. Undo and redo preserve the order of edits and are saved with the project.

Projects save automatically. **New** creates another project and **Open project** restores a previous one, including its undo history. Image effects rasterize the affected page; exporting a form page with an image effect is rejected to prevent silently flattening its fields.

Click **Prepare for submission** to choose a recipe, output requirements, and a destination folder. Recipes can contain clean scan → OCR → compress → merge → rename → export, and can be saved as named workflows. Configure a file-size limit, packet page limit, minimum quality/resolution, and optional pixel dimensions for JPG/PNG outputs. PDF exports use document geometry rather than image pixel dimensions. Without Merge, PDF export creates one file per page.

**Jobs** keeps the queue across restarts. Pause or cancel a running job, resume interrupted work, and retry failed jobs. Completed assembly/clean/export stages and individual OCR pages are checkpointed. One application instance runs the queue at a time; other instances can enqueue and inspect jobs. A crashed queue lease expires after 20 seconds; stopped work can then be resumed. Worker processes stop if their parent application dies.

The default workflow stages the packet for review. In Jobs, inspect the validation summary, use **Review OCR** to correct highlighted uncertain words, and open the staged packet. **Approve and export** publishes only after the configured size/page/dimension requirements and preservation checks pass. If a target is not reached at the configured quality floor, the job remains in review with an explanation. Adjust the requirements or workspace and queue another job. No target is silently relaxed.

Outputs go into a job-specific subfolder and include `export-report.json`; OCR jobs also export the reviewed text. PDF exports are automatically indexed in **Library**, where you can search words, see matching page numbers, open documents, index external PDFs, or remove entries without deleting their files.

Smart OCR handles mixed text/scanned pages, preserves existing selectable text, corrects orientation and skew for recognition, and highlights uncertain words. Corrections are saved into the invisible PDF text layer as well as the reviewed text. Original page graphics remain intact. The original OCR screen also provides a **Smart OCR** shortcut. Confidence is an engine estimate; review the staged document before submitting it.

Export validation opens and renders every page, checks expected page counts and requested limits, and compares required selectable text, form values, and attachments. These checks detect corruption and content loss; resolution/quality floors and human preview remain important for visual legibility.

## Desktop installers and engine setup

The Linux `.deb` installer in `release/installers/` contains Python and the application. Install it with your desktop package manager or `sudo apt install ./offline-document-toolkit_0.4.1_amd64.deb` (use the actual architecture in the filename). Its dependencies install Tesseract English/Hindi, Ghostscript, and LibreOffice Writer. No Python environment or manual PATH setup is needed.

First-run **Setup**, also available from Settings, detects bundled engines, common installation locations, and PATH. **Locate executable** saves an explicit engine location; **Official installation guide** opens the engine vendor's instructions. PDF/image tools remain available when optional engines are missing. The workflow checks OCR availability before queueing it.

Build native installers with `python scripts/build_installer.py` after freezing the app on Linux or Windows. Linux uses `dpkg-deb`; Windows uses the supplied Inno Setup recipe. The **Native installers** workflow builds and verifies both targets. Windows signing is optional; unsigned builds do not require a signing account.

## Requirements and installation

Use 64-bit Python 3.11 or 3.12. Create a separate virtual environment so an existing OpenCV or Qt installation cannot interfere with the application.

```bash
python -m venv .venv
# Linux
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
python main.py
# After installation, the equivalent launcher is:
# offline-document-toolkit
```

The editable installation needs setuptools and wheel. If your virtual environment does not provide them, install the pinned build tools with `python -m pip install setuptools==70.2.0 wheel==0.43.0` before that step. You can also run `python main.py` without installing the project itself.

`requirements.txt` is the runtime lock, including transitive dependencies. `requirements-dev.txt` adds the test tools; `requirements-build.txt` adds PyInstaller. The application uses **opencv-python-headless** because image processing does not need OpenCV's separate Qt distribution. Avoid installing `opencv-python` in the same environment.

The following system engines are optional; the corresponding features need them:

| Engine | Features |
| --- | --- |
| Tesseract OCR, including the `eng` and optionally `hin` language models | Image/scanned-document OCR |
| LibreOffice Writer (`libreoffice` or `soffice` on PATH) | DOCX to PDF |
| Ghostscript (`gs`, `gswin64c`, or `gswin32c` on PATH) | PDF compression |

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-hin libreoffice-writer ghostscript fonts-dejavu-core libegl1 libopengl0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-shape0 libxcb-keysyms1
```

On Windows, install [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html), [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/), and [Ghostscript](https://ghostscript.com/releases/gsdnld.html). Setup detects common installation locations; use **Locate executable** for a custom location. Ensure the desired Tesseract language data is installed. Settings displays detected engine locations and versions.

## Features and behavior

- **PDF:** merge, split, extract/delete/rotate pages, drag pages into a new order, compress, convert images, add watermarks/page numbers, protect and unlock with a password. Protection and unlocking preserve document metadata, bookmarks, forms, and attachments. Watermarks appear above scanned page images; numbering follows the visible rotation and crop. Transparent images use a white PDF background, and multipage TIFF input contributes every page.
- **Images:** resize, crop, rotate, flip, format conversion, brightness/contrast, sharpen, denoise, grayscale, add text, and blur a selected area. Crop, blur, and text additions accumulate on the current preview; Undo restores the original image. Parameter adjustments such as brightness recalculate from the original. CMYK JPEGs can be previewed and converted to RGB formats. Saves confirm the actual destination if format normalization changes an existing filename.
- **Compression:** JPEG and WebP use the selected quality for preview estimates and saved files. PNG uses lossless compression; its quality slider does not change image detail. BMP does not offer quality-based compression. TIFF compression preserves every page and its resolution; its preview shows the first page. TIFF-to-TIFF conversion also preserves all pages. Single-page editing and single-page export formats reject multipage inputs rather than dropping pages; split the TIFF before using those tools. A compressed file may be larger than its input.
- **OCR:** image/scanned PDF to text, editable page-by-page review, searchable PDF, TXT/DOCX export, and optional scan preprocessing. English/Hindi selection requires the corresponding Tesseract language data. OCR accuracy depends on scan quality; verify extracted text.
- **Searchable PDFs:** preserve original page graphics, MediaBox/CropBox, rotation, annotations, links, bookmarks, and document metadata while adding an invisible OCR text layer. Preprocessing affects recognition only. Smart OCR recognizes scanned areas on mixed-content pages while masking existing selectable text during recognition. The legacy searchable-PDF action skips pages with selectable text; choose Smart OCR or Workspace for mixed pages. Digitally signed PDFs must be re-signed after any modification.
- **PDF to DOCX:** choose **Preserve page appearance** for full-page images with matching page sizes, or **Editable layout** to reconstruct styled paragraphs, tables, and images. The appearance mode preserves layout and colors at the render resolution; its text is part of the page images. Editable mode reconstructs tables and text styles, but complex columns, fonts, vector artwork, and pagination can differ. Scanned PDF to DOCX creates editable OCR paragraphs.
- **Word:** DOCX/TXT conversion, replacement across formatting runs including tables/headers/footers, image insertion, and certificate generation. Replacements inherit the first matched run's formatting. Pictures, drawings, and field instructions are preserved; a match cannot cross these structural boundaries.
- **Batch:** PDF/image compression, image conversion, image OCR, scanned PDF to searchable PDF, and DOCX to PDF. Individual errors are reported; existing filenames receive numeric suffixes instead of being overwritten.

Expensive processing and previews run in isolated worker processes. **Cancel** stops the current worker and its command-line engines, cleans partial temporary files, and leaves existing destination files intact. Completed outputs from a batch remain available. Closing a window cancels its work; quitting waits for worker cleanup. Multi-file operations are atomic per output file, rather than as one transaction for the entire batch.

LibreOffice uses a fresh writable profile for each conversion, checks for a newly generated output, and has a 120-second timeout. Ghostscript and individual Tesseract calls also have 120-second limits. LibreOffice requires local IPC socket binding; a restricted execution sandbox may prohibit it even when the executable is installed. Run conversion on a normal desktop or container that permits local IPC. No sandbox bypass is included.

## Settings and local documents

Settings are independent of the current working directory:

- Linux: `$XDG_CONFIG_HOME/offline-document-toolkit/settings.json`, defaulting to `~/.config/offline-document-toolkit/settings.json`.
- Windows: `%APPDATA%/offline-document-toolkit/settings.json`.

The default output location is `~/Documents/Offline Document Toolkit`. Set `ODT_DATA_DIR` for the workspace database/cache, or `ODT_CONFIG_DIR` / `ODT_OUTPUT_DIR` before launch to override these defaults, or change the output folder in Settings. `app_settings.example.json` illustrates the settings format; the old working-directory `app_settings.json` is no longer read.

Personal input/output folders have been preserved under ignored `local_data/`. They are excluded from source archives and Python distributions. File ignores do not remove documents from existing Git history; this workspace snapshot has no usable Git history to inspect or rewrite.

Generate safe demonstration inputs with:

```bash
python examples/generate_samples.py
```

This creates synthetic PDF, DOCX, and image files in `local_data/synthetic_examples/`. `python scripts/organize_workspace.py` previews further workspace cleanup; `--apply` moves non-source document/output directories under `local_data/` without deleting their contents.

## Development and validation

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
# Library/UI tests without system engines:
python -m pytest -m "not integration"
# Real Tesseract, Ghostscript, and LibreOffice tests:
python -m pytest -m integration
```

Tests generate synthetic fixtures in temporary directories. Missing engines are reported as skipped tests. The LibreOffice integration test also reports a skip when the execution environment denies local IPC binding; an installed engine with an actual conversion failure fails the test. Qt tests use the offscreen platform.

CI runs unit/UI tests on Linux and Windows with Python 3.11/3.12, real-engine integration tests on Linux, and a mandatory LibreOffice conversion check on Windows. These workflows run when this source is pushed to GitHub; their presence does not imply those remote jobs have already run.

## Document-quality benchmark

```bash
python -m scripts.benchmark_documents --output artifacts/benchmarks/latest --large-pages 40 --strict
# Optional comparison against an installed OCRmyPDF backend:
python -m scripts.benchmark_documents --output artifacts/benchmarks/comparison --compare-ocrmypdf
```

The generator creates synthetic English/Hindi scans, skewed and rotated scans, mixed-content PDFs, forms with attachments and tables, a large text document, and a separate image-heavy scan packet. Each measurement runs in a fresh process. Reports include character/word error rates against ground truth, structure checks, visible-pixel preservation, input/output bytes, runtime, and peak worker resident memory. JSON and CSV reports are saved with the corpus. Hindi fixture generation needs a Devanagari font; optional OCRmyPDF comparisons are explicitly skipped if that engine is absent. The native benchmark gates on structure/visual preservation and 12% character-error and 35% word-error ceilings (configurable with `--max-cer` and `--max-wer`), while reporting the actual errors. The image-heavy scan case also has a 256 MiB worker-memory ceiling.

OCRmyPDF is an optional comparison adapter, not a required dependency or an automatically selected replacement. Evaluate its preservation and accuracy results on the corpus before adopting it. See the [OCRmyPDF cookbook](https://ocrmypdf.readthedocs.io/en/stable/cookbook.html).

## Packaging

Create a shareable source archive from an explicit allowlist:

```bash
python scripts/package_source.py
# release/offline-document-toolkit-source.zip
```

Build a Python wheel or source distribution:

```bash
python -m pip install -r requirements-dev.txt
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir release
python -c "import setuptools.build_meta as b; b.build_sdist('release')"
```

For a desktop executable, build on **each target OS** from a clean virtual environment:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm --distpath release/desktop OfflineDocumentToolkit.spec
python scripts/build_installer.py
# release/desktop/OfflineDocumentToolkit/ and release/installers/
```

System Tesseract, LibreOffice, Ghostscript, and language packs remain external dependencies. Distribute the entire executable folder with its license notices and matching source archive. Test the application on a clean machine before publishing a binary release. Native packaging/signing and system engine installers are platform-specific.

## Source layout

```text
main.py                     Desktop entry point
ui/                         Qt screens and dialogs
services/                   Processing, recipes, validation, SQLite state, and search
utils/                      Settings, atomic output, and cancellable process jobs
tests/                      Synthetic regression and integration checks
examples/generate_samples.py
scripts/                    Source/native packaging and quality benchmarks
assets/, packaging/         Application icon and native installer definitions
local_data/                 Ignored personal documents and generated examples
.github/workflows/ci.yml
```

## License

Application source is licensed under **AGPL-3.0-only**; see [LICENSE](LICENSE). Dependencies keep their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). PyMuPDF is offered under [AGPL or commercial terms](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). Keep dependency notices and provide matching source when distributing AGPL builds.
