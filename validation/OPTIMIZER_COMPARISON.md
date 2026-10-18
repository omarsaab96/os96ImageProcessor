# Optimizer comparison

Single-worker encoding times; metrics excluded. rc1 compressor (with common current engine and Pillow) versus current bounded-lossy JPEG plus verified lossless jpegtran/oxipng. Standalone jpegtran/oxipng reference is lossless, NOT a matched-quality lossy competitor. These tools are also used by current, so this is a reference baseline, not independent evidence of beating them. No commercial GUI app claim.

| Group | Method | Files | Saved | Seconds | Quality pass | Min SSIM |
|---|---|---:|---:|---:|---:|---:|
| all | rc1 | 41 | 32.574% | 27.094 | 41 | 0.963814 |
| all | current | 41 | 34.49% | 32.621 | 41 | 0.963814 |
| all | reference_lossless | 38 | 19.379% | 11.162 | 38 | 1.0 |
| photos | rc1 | 22 | 11.743% | 19.879 | 22 | 0.977978 |
| photos | current | 22 | 15.044% | 20.455 | 22 | 0.977978 |
| photos | reference_lossless | 22 | 5.794% | 5.139 | 22 | 1.0 |
| photos_original | rc1 | 5 | 22.977% | 6.781 | 5 | 0.977978 |
| photos_original | current | 5 | 23.781% | 13.66 | 5 | 0.977978 |
| photos_original | reference_lossless | 5 | 5.475% | 1.694 | 5 | 1.0 |
| photos_web | rc1 | 17 | 0.267% | 13.098 | 17 | 0.99815 |
| photos_web | current | 17 | 6.12% | 6.795 | 17 | 1.0 |
| photos_web | reference_lossless | 17 | 6.12% | 3.445 | 17 | 1.0 |
| illustrations | rc1 | 4 | 56.75% | 3.822 | 4 | 0.963814 |
| illustrations | current | 4 | 56.923% | 7.534 | 4 | 0.963814 |
| illustrations | reference_lossless | 4 | 8.038% | 1.679 | 4 | 1.0 |
| scientific | rc1 | 3 | 0.0% | 2.491 | 3 | 1.0 |
| scientific | current | 3 | 5.28% | 1.401 | 3 | 1.0 |
| scientific | reference_lossless | 3 | 5.28% | 0.748 | 3 | 1.0 |
| screenshots | rc1 | 5 | 5.008% | 0.352 | 5 | 1.0 |
| screenshots | current | 5 | 17.882% | 1.787 | 5 | 1.0 |
| screenshots | reference_lossless | 5 | 20.287% | 2.468 | 5 | 1.0 |
| graphics | rc1 | 7 | 49.685% | 0.55 | 7 | 0.995099 |
| graphics | current | 7 | 49.977% | 1.443 | 7 | 0.995099 |
| graphics | reference_lossless | 4 | 85.521% | 1.129 | 4 | 1.0 |
| JPEG | rc1 | 30 | 27.309% | 26.395 | 30 | 0.963814 |
| JPEG | current | 30 | 29.595% | 29.92 | 30 | 0.963814 |
| JPEG | reference_lossless | 30 | 7.04% | 7.737 | 30 | 1.0 |
| PNG | rc1 | 8 | 89.909% | 0.552 | 8 | 1.0 |
| PNG | current | 8 | 91.424% | 2.566 | 8 | 1.0 |
| PNG | reference_lossless | 8 | 91.597% | 3.425 | 8 | 1.0 |
