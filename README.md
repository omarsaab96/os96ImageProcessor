# OS96 Image Optimizer 1.0.0rc2

Local Windows batch optimization and resizing for JPEG, PNG, WebP, TIFF, and
BMP. No uploads or API keys. Animated/multipage images fail explicitly.
This is an unsigned release candidate; macOS distribution is not validated.

## Run

Use the installer or portable folder in `dist/` after building. Keep the portable
executable beside its `_internal` folder. For source development and release
builds, use Python 3.13.16 or a later 3.13 security update:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Everyday workflow

1. Add/drop images or folders. Subfolders are included, duplicate inputs removed.
   Remove selected/Delete removes queue entries without deleting source files.
2. Choose Resize, Optimize, and Destination settings.
3. Select a row and use Compare selected for a temporary full-resolution encode.
   Views have linked scrollbars and 100%, 50%, and 25% zoom. At 100%, one image
   pixel maps to one display pixel, including on high-DPI displays. Tagged
   display colors convert to sRGB. Comparison supports up to 25 megapixels per
   image; processing supports larger images within Pillow's safety limits.
4. Start optimization. Pause/Stop act at safe checkpoints; native decode/encode
   cannot be interrupted immediately. Completed files remain after Stop.
5. Open output folder or Batch report. Reports include byte savings, per-file
   paths, and readable errors, and export to CSV. Retry failed reduces the queue
   to failed/cancelled/unprocessed images and runs them with current settings.

Settings, destination, and named presets persist per user. Replace originals and
Overwrite existing reset on launch. Reports describe the latest batch; export
them to retain after exit. Compare before in-place processing, which replaces
the original after encoding successfully.

One folder exports relative to itself; multiple selections use their common
parent. Review paths in the queue. Process inputs on different Windows drives
separately. Output folders must be outside selected input folders. Existing
outputs are skipped unless explicitly overwritten.

## Resize and size policy

Keep original preserves dimensions. By dimensions offers Exact (may stretch),
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

- Automatic JPEG uses a fast lossless path for already-quantized images when
  keeping original dimensions without web conversion. This effort heuristic
  uses source quantization tables, not a claimed perceptual quality score.
  Other JPEGs use a bounded binary search over quality levels
  75/80/85/88/91/94/97/100, then tests progressive coding at the chosen level.
  Full chroma, 4:2:2 and 4:2:0 candidates are tested. Selected passing candidates
  meet full-resolution per-channel RGB RMS limits
  of 2.5 globally and 6 per 64-pixel tile, compared against resized pixels.
  If none pass, quality 100 is used and may still exceed these limits. CMYK
  uses the maximum-quality path. Numerical checks do not guarantee invisible
  differences, an exhaustive optimum, or commercial encoder equivalence.
- Automatic PNG/WebP compression is lossless. WebP uses method 4.
- Bundled jpegtran optimizes JPEG entropy coding without changing decoded pixels.
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

Automatic/web estimates use previews bounded to 768 pixels per side and area
extrapolation. Actual sizes may differ substantially. Manual estimates use
trial encodes. Estimates cap at source size only with Only save smaller enabled.
Actual sizes replace estimates after processing. Estimates use temporary folders,
never source files or the chosen output directory.

## Reliability

Two workers are the default; choose one for very large images. Pillow's image
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
without publishing. See RELEASE_CHECKLIST.md for clean-machine, real-corpus,
licensing and signing requirements. LICENSE reserves the owner's rights pending
a public distribution-license decision. Third-party rights remain intact;
see THIRD_PARTY_NOTICES.md and bundled license texts.

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
