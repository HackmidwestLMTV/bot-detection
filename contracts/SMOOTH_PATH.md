# Versioned challenge motion

The three-second challenge supports `v1` and `smooth_v2`. A missing `path_version`
means `v1`, preserving existing fixtures and recordings. Python `make_path(seed,
path_version="v1")` and JavaScript `makePath(seed, pathVersion = "v1")` share this
default. Unsupported versions fail explicitly.

`smooth_v2` uses the same mulberry32 generator, drawing frequency, phase, and
amplitude for two components on X, then two on Y:

- Frequency: `0.08 + 0.06 * random()` Hz.
- Phase: `2π * random()` radians.
- Amplitude: `base * (0.8 + 0.2 * random())`, with bases X `[120,35]`, Y `[70,20]`.
- Position: `(300,200)` plus each axis's summed `amplitude * sin(2π * frequency * t + phase)`.

There are no kicks, clips, or piecewise transitions. The amplitude sums guarantee
X remains within 145–455 and Y within 110–290 logical pixels for every seed and
timestamp. The analytic speed bound is `2π * 0.14 * hypot(155,90) < 158` pixels per
second; acceleration is below 139 pixels per second squared. These are geometry
limits, not measured evidence of accessibility or bot-detection accuracy.

The challenge's issued version must select rendering, scoring, and synthetic
forging. Store that version with saved recordings and feature evidence. Scoring
uses `variant.get("path_version", "v1")`; the API must supply the issued challenge
version rather than trusting client data or letting a later configuration change
reinterpret the attempt.

The local recorder issues `smooth_v2` by default and saves its version. Its existing
scoring bands remain provisional. Calibration selects only the baseline variant's
version, defaulting to `v1`; request `--path-version smooth_v2` to analyze the new
cohort. It never pools these two populations. Residual transplantation subtracts
the source recording's own version and adds the requested target version.

`fixtures/path_vectors_smooth_v2.json` is separate from unchanged legacy vectors.
Engine tests check both implementations against those vectors, dense numerical
speed/acceleration bounds, known-delay scoring, transplantation, recorder metadata,
and calibration cohort isolation.
