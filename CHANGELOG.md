# 1.0.0rc24

- Prepare Windows installer/portable and Apple Silicon/Intel macOS beta release builds.
- Add architecture-specific Mac native helpers, locked wheels, app bundles and DMGs.
- Publish only after frozen-app, native-helper and fresh Windows installation checks pass.
- Ensure installer packaging uses the selected build directory and matching version.

# 1.0.0rc23

- Remove the redundant label and its layout space above the empty drop zone.

# 1.0.0rc22

- Hide the table background and border while its empty drop zone is visible.

# 1.0.0rc21

- Add File menu actions for Add images and Add folder, keeping the toolbar buttons.
- Show an empty-table drop zone with drag highlighting; restore column headers when images are added.

# 1.0.0rc20

- Move Settings to a menu-bar action before Help, opening a dedicated window.
- Move Only save smaller into Settings; retain its behavior for copy and in-place
  export. Remove Settings from the side-panel tabs.

# 1.0.0rc19

- Hide the PNG compression setting and its description in Automatic mode.

# 1.0.0rc18

- Add clear borders and contrasting checkmarks to checkbox controls in every state.

# 1.0.0rc17

- Update Pillow to 13.0.0 and refresh the hashed runtime lock.

- Separate Auto concurrency from explicit parallel-image counts.
- Honor numeric values 1 through 8 without silently reducing concurrency;
  Auto retains the memory-aware image budget.

# 1.0.0rc16

- Support large photographs in Compare selected by scaling only display images.
- Keep full-resolution compression and actual byte counts; label scaled previews
  explicitly and bound each displayed image to four megapixels.

# 1.0.0rc15

- Keep Only save smaller available and effective during in-place replacement.
- Disable only output-folder and overwrite controls in in-place mode.

# 1.0.0rc14

- Disable all other Destination controls at 40% opacity during in-place export.
- Ignore the disabled smaller-only option in-place while preserving its choice
  for exports to another folder.

# 1.0.0rc13

- Dim metadata and color-profile options to 40% opacity when Save for web disables them.

# 1.0.0rc12

- Remove Keep original from Resize; use the Resize switch to preserve dimensions.
- Keep Save for web guidance visible and explain its metadata/profile overrides.
- Remove preset controls and preset management; ordinary preferences still persist.

# 1.0.0rc11

- Move Resize and Compression switches inside their tabs as the first control.
- Add animated iOS-style switches and dim disabled settings to 40% opacity.
- Keep the switch fully visible and usable while its settings are disabled.

# 1.0.0rc10

- Add independent Resize and Compression switches directly in the tab headers.
- Support resize-only export without automatic compression searches or native
  optimization passes, preserving the selected step settings while disabled.
- Move metadata, color profile, web export, and parallel-image preferences to
  a separate Settings tab. Remember the enabled steps across sessions.
- Include rc9's sample-based compression and memory-aware concurrency limits.

# 1.0.0rc9

- Select automatic JPEG quality on native-resolution detail samples, then encode
  and verify the full image. Retry stronger settings when full-image checks fail.
- Remove duplicate JPEG optimization passes and unnecessary decoded-image copies.
- Limit batch concurrency using a shared 64-megapixel image budget.
- Benchmark the original nine 60-megapixel photos: first output at 5.4 seconds,
  all nine at 52.5 seconds, peak working set approximately 663 MB on the test host.
  The first-photo baseline took 41.3 seconds and peaked at 1,075 MB; its new
  output is byte-identical at 3,757,908 bytes.

# 1.0.0rc8

- Show live elapsed wall-clock time during each batch, retaining the final duration.

# 1.0.0rc7

- Reduce footer height and vertical padding while preserving status and controls.

# 1.0.0rc6

- Redesign the footer as one rounded progress surface containing status,
  compression strategy, loading state, percentage, and controls.
- Animate a soft full-width shimmer while working; retain file-count progress
  underneath. Freeze the shimmer when paused and reset after completion.
- Replace Start with Pause/Stop during processing and hide them when idle.

# 1.0.0rc5

- Estimate original-size JPEGs from native-resolution detail samples instead of
  resized thumbnails, improving predictions for high-resolution photographs.
- Show percentage file-size changes beside estimated and actual output sizes.
- Animate a loading indicator during estimates, scanning, and processing, and
  reset the progress bar when processing finishes.

# 1.0.0rc4

- Remove processing on drop: dropping images only queues them for Start.
- Always open with Automatic compression, preventing a remembered Lossless
  preference from silently bypassing JPEG compression. Other settings persist;
  Lossless and Manual quality remain selectable and available through presets.
- Show the active compression strategy beside Start across all settings tabs.
- Allow a separate build output directory so a running older app is undisturbed.

# 1.0.0rc3

- Compress dropped images immediately by default, saving copies to the chosen
  output folder or Pictures/OS96 Optimized. Add a remembered Compress on drop
  preference; replacement and overwrite still require Start and confirmation.
- Make Automatic the engine default and remove the shortcut that prevented
  existing JPEGs from being recompressed.
- Extend automatic JPEG search down to quality 60 with full-resolution global
  and local error safeguards, retaining smaller original JPEGs as a fallback.
- Preserve explicit Lossless and Manual quality modes, dimensions, color profiles,
  cancellation, and independent metadata controls.

# 1.0.0rc2

- Add verified lossless JPEG entropy optimization and stronger PNG optimization.
- Search JPEG chroma candidates under the existing full-resolution quality limits;
  use the fast lossless path for already-quantized, untransformed JPEGs.
- Preserve invisible RGB and alpha in lossless WebP and reject alpha damage.
- Upgrade Pillow to 12.3.0 and gate builds on a pinned runtime dependency audit.
- Add hashed runtime wheels, full release file inventory, source hashes and
  upstream source archives.
- Expand the photo corpus and compare against rc1's compressor and established
  lossless reference tools using per-file PSNR/SSIM, quality checks and timings.
- Add a 1,000-image stress run, real Windows file-lock protection check, extended
  packaged-codec/native-helper tests, and fresh-runner/Sandbox verification scripts.
- Prepare optional signing without requiring a certificate for this unsigned beta.

# 1.0.0rc1

- Make smaller-only output an explicit opt-in policy; allow requested enlargement.
- Guarantee web color conversion without a source-color JPEG fallback.
- Remember settings/destination and add named presets.
- Add output-folder access, failed-job retries, and CSV batch reports.
- Add isolated full-resolution before/after views with linked scrolling and zoom.
- Validate encoded output before commit and support destinations without hard links.
- Add failure, collision, high-bit-depth, multiframe, and persistence checks.
- Add reproducible synthetic and optional photographic benchmarks.
- Add version/icon resources, bundled license texts, portable ZIP, Windows
  installer/uninstaller, frozen-app smoke tests, and Windows CI artifact builds.

Unsigned Windows release candidate. No public release, signing, or macOS
validation is implied.
