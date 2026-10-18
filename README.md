# OS96 Image Optimizer

Native desktop batch image optimization for Windows and macOS, built with Qt and Pillow.

## Run

Install Python 3.10 or newer, then run from this folder:

```sh
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS:
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Add images or folders (folders include subfolders), choose resize and compression settings, choose a destination, and click Start. One selected folder exports its contents relative to that folder. Multiple selections preserve paths relative to their common parent. Review the output paths in the queue before starting. Inputs on different Windows drives should be processed in separate batches.

Drag local images or folders from Explorer/Finder onto the window or image list to add them. Duplicate images are included only once. Select rows with Ctrl/Cmd-click or Shift-click and use **Remove selected**, Delete, or Backspace to remove them from the queue without deleting source files. Removed images stay excluded when other inputs are added; explicitly add the removed image or its folder again to restore it. Adding, removing, and dropping are disabled while scanning or processing (including while paused).

The queue shows original file size and stored pixel dimensions, predicted output dimensions (including EXIF orientation), and estimated output file size. In manual mode, estimates refresh after settings change using a single background trial encoder and temporary files, never the source or chosen output directory. Size estimates are marked ≈; encoding very large batches may take time. Automatic compression and Save for web estimate sizes in the background using previews bounded to 768 pixels per side, with reduced-resolution JPEG decoding where available. These are rough pixel-area extrapolations, not full-resolution trial encodes; actual sizes may differ substantially with texture and image size. Dimensions update immediately, and actual sizes replace estimates after processing. Processing takes priority and cancels pending manual estimates. Scroll the table horizontally on smaller screens to see all columns.

Resize has three modes and shows only relevant fields, with an explanation of the current option below the controls and tooltips in each menu:

- **Keep original:** Keeps pixel dimensions; optimization settings still apply.
- **By dimensions → Exact:** Sets both width and height, which may stretch the image.
- **By dimensions → Height:** Sets height for every image and calculates width to preserve proportions.
- **By dimensions → Width:** Sets width for every image and calculates height to preserve proportions.
- **By dimensions → Auto:** Landscape and square images use width; portrait images use height. The other dimension is calculated to preserve proportions.
- **By resolution:** Uses print width/height (inches or centimeters) and DPI to resample to exact pixel dimensions and store print density. For example, 6 × 4 inches at 200 DPI becomes 1200 × 800 pixels; at 600 DPI it becomes 3600 × 2400 pixels. This may change proportions.

All dimension options reach their requested target even if that enlarges an image. Resolution can also enlarge images. Enlargement or higher DPI cannot restore missing detail. Very large requested outputs are rejected to protect memory.

Supported: JPEG, PNG, WebP, TIFF, BMP. Original names and formats are retained. Animated and multipage files are reported as errors rather than flattened. Existing outputs are skipped by default. Output folders must be outside selected input folders; use the explicit replacement mode for in-place processing. Replacement requires confirmation and should be used with backups.

Optimize provides direct controls with explanatory text:

- **Save for web:** Separate metadata and color option. Uses the selected compression strategy, removes descriptive metadata, and converts embedded color profiles to sRGB before encoding. Embeds the converted profile to preserve color interpretation. Untagged RGB is assumed to be sRGB; untagged CMYK or invalid profiles are reported as errors instead of silently changing colors. Orientation is applied before metadata removal, transparency is retained, and explicit print density settings still apply. Original filenames and formats are retained, so TIFF/BMP inputs are not converted to web formats. Turning the preset off restores the manual preferences. This does not use Adobe's encoder or promise identical output.
- **Compression ? Automatic:** Enabled by default in the desktop app. JPEGs are encoded at eight quality levels (75–100), each with baseline and progressive coding, without color subsampling. The smallest tested candidate passing full-resolution RGB error checks is selected: per-channel RMS error at most 2.5 globally and 6 in every 64-pixel tile. Resized outputs are compared with the resized pixels. If no candidate passes, quality 100 is used; it may still exceed the limits. CMYK JPEGs use the existing maximum-quality path. PNG uses optimized lossless compression; WebP uses balanced-effort lossless encoding (method 4), preserving decoded quality while reducing CPU time. No uploads or API keys are involved. Numerical checks cannot guarantee invisible differences or provider-equivalent results. Choose Lossless or Manual quality in the Compression selector to use the controls below. The whole application processes images locally and requires no internet connection.
- **Compression ? Lossless:** Preserves pixels in supported formats. JPEGs in Keep original mode keep their compressed pixel data even when removing metadata or color profiles. Resized JPEGs are reencoded at quality 100 and are not mathematically lossless; resizing itself changes pixels in every format.
- **JPEG / WebP quality (1–100):** Appears only when lossless is off. Higher values preserve more detail and usually create larger files. Its value is remembered when toggling lossless. PNG, TIFF, and BMP ignore it.
- **PNG compression (0–9):** Always adjustable. Higher levels increase compression effort without changing pixel quality.
- **Keep metadata:** Retains supported camera information, EXIF, and PNG text. When disabled, required orientation information and explicitly selected print density can remain.
- **Keep color profile:** Independently retains embedded ICC profiles. Recommended on; stripping a profile may affect displayed colors.
- **Parallel images:** Controls concurrency and resource use directly.

If processing without resizing, metadata removal, or color-profile removal would enlarge a file, the original is kept. Metadata and profile support varies by format; preservation is not byte-for-byte archival preservation.

Workers are bounded (default two), with one image decoded per worker and no full-resolution previews. RAM use still depends on decoded dimensions, so choose one worker for very large files. Pillow's decompression-bomb protections remain enabled. Pause and stop take effect at safe checkpoints; an ongoing native decode/encode cannot be interrupted immediately. Errors are isolated per image and shown in its status tooltip. Writes use temporary files beside the destination and atomic replacement; originals are only replaced after a successful encode. Completed files remain after stopping. Start again to run the queue again.

## Build standalone apps

Build on each target OS (Windows builds on Windows, macOS builds on macOS):

```sh
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name OS96ImageOptimizer main.py
```

The result is in `dist/`. Distribution on macOS may require signing and notarization; Windows signing is recommended for public releases.

## Verify

```sh
python -m unittest discover -s tests -v
```

Outputs larger than their source are skipped, including when resizing or converting colors. Preview estimates are capped at the source size. For JPEGs kept at original dimensions, a metadata-filtered copy retaining the source profile is also tested; if smaller, it is used instead of sRGB reencoding. This preserves the original compressed pixels and may retain the source color space. Already optimized files may have little or no further size reduction.
