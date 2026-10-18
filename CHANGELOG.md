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
