# OS96 Image Optimizer 1.0.0rc27

Local desktop batch optimization and resizing for JPEG, PNG, WebP, TIFF, and
BMP. No uploads or API keys. Animated/multipage images fail explicitly.
JPEGs containing MPF thumbnails or identified Apple HDR gain maps are supported
as single photos. Re-encoding exports the standard image without the auxiliary
HDR gain map; unchanged original-file copies retain it.
This is a beta. Windows builds are unsigned. macOS builds use ad-hoc signatures,
without Apple notarization; operating-system security prompts may appear.
The release workflow builds and tests Windows x64, Apple Silicon and Intel Mac
packages before publishing. macOS requires version 13 or newer.

## Run

Use the installer or portable folder in `dist/` after building. Keep the portable
executable beside its `_internal` folder. On a Mac, use the DMG matching your
processor and drag the app to Applications. For source development and release
builds, use Python 3.13.16 or a later 3.13 security update:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Everyday workflow

1. Add/drop images or folders to queue them. Processing starts only when you
   click **Start optimization**. Automatic compression is selected on launch;
   choose Lossless or Manual quality in Optimize when needed.
   Subfolders are included, duplicate inputs removed.
   Remove selected/Delete removes queue entries without deleting source files.
2. Use the iOS-style switches at the top of the Resize and Compression tabs to enable each
   step independently. Resize only, compression only, and both are supported.
   Compression is enabled by default; resizing is disabled. Resize-only JPEG
   export uses quality 100 and skips automatic searches and extra optimization.
   Keep metadata, Keep color profile, Save for web, and Parallel images are in
   Settings in the menu bar, before Help. Only save smaller is also in Settings.
   Choose the output folder in Destination.
3. Select a row and use Compare selected for a temporary full-resolution encode.
   Views have linked scrollbars and 100%, 50%, and 25% zoom. At 100%, one image
   pixel maps to one display pixel, including on high-DPI displays. Tagged
   display colors convert to sRGB. Large comparisons use display previews capped at 4 megapixels, clearly labeled
   as scaled. Compression still uses the full-resolution image; processing stays
   within Pillow's safety limits.
4. Use Start for queued images or changed settings. Replacement/overwrite always
   requires confirmation.
   Pause/Stop act at safe checkpoints; native decode/encode
   cannot be interrupted immediately. Completed files remain after Stop.
5. Open output folder or Batch report. Reports include byte savings, per-file
   paths, and readable errors, and export to CSV. Retry failed reduces the queue
   to failed/cancelled/unprocessed images and runs them with current settings.

Settings and destination persist per user. Compression strategy resets to
Automatic on launch; other strategies remain available in the Compression tab.
Replace originals and
Overwrite existing reset on launch. Reports describe the latest batch; export
them to retain after exit. Compare before in-place processing, which replaces
the original after encoding successfully.

One folder exports relative to itself; multiple selections use their common
parent. Review paths in the queue. Process inputs on different Windows drives
separately. Output folders must be outside selected input folders. Existing
outputs are skipped unless explicitly overwritten.

## Resize and size policy

Turn Resize off to preserve dimensions. By dimensions offers Exact (may stretch),
Width/Height (preserve proportions), and Auto (width for landscape/square,
height for portrait). By resolution resamples to print size and DPI in inches
or centimeters: 6 x 4 inches at 200 DPI becomes 1200 x 800 pixels. Enlargement
is allowed but cannot restore missing detail.

**Larger outputs are allowed by default**, so requested resizing/print changes
are respected. Enable **Only save files smaller than the original** to skip
larger results. Skips create no output. With no requested transformation, a
smaller original may be used instead of an unnecessary larger re-encode.
Names and formats are retained; format conversion is not part of this release.

## Compression and color

- Automatic is the default. JPEG quality and color sampling are selected on
  native-resolution detail samples. The quality search starts at 60 and searches
  up to 100 as needed, across full chroma, 4:2:2 and 4:2:0.
  Usually only one full-resolution progressive JPEG is encoded. The final image
  must pass full-resolution per-channel RGB RMS limits of 4 globally and 12 per
  64-pixel tile. Failed checks retry stronger settings, including full chroma.
  If none pass, quality 100 is used and may still exceed these limits; existing
  smaller JPEG originals remain a fallback. CMYK uses maximum quality.
  Numerical checks do not guarantee invisible differences, an exhaustive optimum,
  or commercial encoder equivalence.
- Automatic PNG/WebP compression is lossless. WebP uses method 4.
- Bundled jpegtran optimizes JPEG entropy coding without changing decoded pixels
  in Lossless/Manual modes. Automatic JPEG already uses optimized progressive
  coding and skips redundant native passes.
  Automatic PNG additionally uses oxipng at effort 2. Native results must be
  smaller, pixel-identical (including alpha/high bit depth), and retain metadata
  and color profiles. Failure or timeout leaves the valid primary output. Native
  helper executables are hash checked and run without a console.
- Lossless original-dimension JPEG with web export off preserves decoded pixels;
  entropy coding and compressed file bytes may change.
  Resizing/web conversion requires re-encoding; JPEG quality 100 is not
  mathematically lossless. PNG and lossless WebP preserve resulting pixels.
- Manual quality controls JPEG/lossy WebP. PNG has an independent effort control;
  TIFF/BMP ignore quality. Metadata and ICC retention are independent and vary
  by format; preservation is not byte-for-byte archival preservation.
- Save for web removes descriptive metadata and converts tagged colors to sRGB.
  Untagged RGB is assumed sRGB. Invalid profiles and untagged CMYK fail explicitly.
  It never falls back to a JPEG retaining another color space. Web export may
  be larger; Only save smaller can skip it. Orientation, alpha, and explicit
  print density are respected. TIFF/BMP retain their formats.

Original-size JPEG estimates use a mosaic of native-resolution detail sampled
across the image, avoiding texture loss from thumbnail resizing. Other
automatic/web estimates use previews bounded to 768 pixels per side and area
extrapolation. Actual sizes may differ substantially. Manual estimates use
trial encodes. Estimates cap at source size only with Only save smaller enabled.
Actual sizes replace estimates after processing. Estimates use temporary folders,
never source files or the chosen output directory.

## Reliability

Parallel images defaults to Auto, which uses up to two workers and a shared
64-megapixel budget. Explicit values 1 through 8 are honored without that limit.
More concurrent large photos use more RAM and may slow down under memory pressure.
Pillow's image
safety limits remain enabled. Encoded output is decoded again before commit.
Temporary files sit beside destinations; replacement uses atomic replacement.
New files use exclusive creation. Filesystems lacking hard links use exclusive
stream copying: interruption can leave an incomplete new file, but existing
files remain protected. Errors are isolated per image. Use backups when replacing
originals. Filesystem attributes, permissions and timestamps are not archival.

Grayscale 16-bit PNG/TIFF is supported. Color PNG/TIFF with more than eight bits
per channel is rejected explicitly because this encoder cannot preserve its full
channel precision. Such files require a 16-bit color-capable editor/encoder.

## Verify and build

```powershell
python -m unittest discover -s tests -v
python scripts/benchmark.py --count 256
python scripts/benchmark.py --corpus C:\images --report validation\real-corpus.json
python -m venv .venv-release
.venv-release\Scripts\python -m pip install --index-url https://pypi.org/simple -r requirements-build.txt
.venv-release\Scripts\python scripts/build_windows.py
.venv-release\Scripts\python scripts/package_windows.py
.venv-release\Scripts\python scripts/verify_installer.py
```

Benchmarks report throughput, compression totals, peak memory, source hashes,
and numerical quality. Synthetic results do not establish photographic quality
or competitor speed. The build runs tests, bundles icon/version resources and
licenses, smoke-tests the executable, and creates a portable ZIP with SHA-256.
Inno Setup creates an installer/uninstaller. GitHub Actions builds artifacts
with `.github/workflows/release.yml`; dispatch with Publish enabled to publish
a GitHub beta after all platform checks pass. See RELEASE_CHECKLIST.md for clean-machine, real-corpus,
licensing and signing requirements. LICENSE reserves the owner's rights pending
a public distribution-license decision. Third-party rights remain intact;
see THIRD_PARTY_NOTICES.md and bundled license texts.

### macOS builds

Run on each target architecture using Python 3.13.16 or a later 3.13 security
update, Xcode command-line tools, CMake, and Rust 1.88 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-release-macos-$(uname -m).lock
python -m pip install -r requirements-build.txt
python scripts/build_macos_native.py
python scripts/build_macos.py
```

The Mac build compiles static jpegtran and oxipng helpers from the matching source
versions, freezes an app bundle, verifies its ad-hoc signature, runs the frozen
self-test, and creates ZIP/DMG downloads with checksums. Source archives are
published alongside binaries. Developer ID signing/notarization is not configured
for this beta. Windows cannot produce a runnable macOS bundle.

For the expanded reproducible comparison and workload checks:

```powershell
.venv-release\Scripts\python -m pip install -r requirements-benchmark.txt
.venv-release\Scripts\python scripts/fetch_photo_corpus.py
.venv-release\Scripts\python scripts/fetch_original_photos.py
.venv-release\Scripts\python scripts/prepare_reference_tools.py
.venv-release\Scripts\python scripts/compare_optimizers.py
.venv-release\Scripts\python scripts/stress_release.py
```

The comparison separates original camera assets, web renditions, screenshots,
and generated graphics. It reports source hashes, per-file bytes/timing, PSNR,
SSIM, strict alpha checks, and the app's quality limits. The rc1 compressor runs
on the common current engine/Pillow; it is not presented as an old-binary test.
Standalone lossless jpegtran/oxipng are reference baselines also used by this
release, not independent evidence of beating them or commercial GUI products.
Original photographic samples and derived graphics are never mixed silently.

Release builds use Python 3.13.16 (or a later 3.13 security update). The
Windows/Python 3.13 runtime wheel hashes are pinned in
requirements-release.lock (`pip install --require-hashes -r requirements-release.lock`).
Builds fail on runtime dependency advisories. This scan covers Python package
advisories, not every native library or possible vulnerability. Release folders
include a full file hash inventory and source-code hashes in the build manifest.
Benchmark/audit packages are excluded from the frozen app.

scripts/prepare_sandbox.py creates a Windows Sandbox configuration with
read-only release inputs and separate writable reports, with networking disabled.
Run validation/OS96-clean-windows.wsb on a host that has Sandbox enabled. The same
PowerShell test runs in a separate GitHub-hosted Windows job without setting up
Python. A prepared workflow is not evidence of an executed independent test.
This candidate remains unsigned by the owner's choice. No public release is
performed by these scripts. Upstream source archives can be prepared with
scripts/package_upstream_sources.py and must stay available beside public binaries.
