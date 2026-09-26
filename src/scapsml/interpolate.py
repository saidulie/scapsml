"""
interpolate -- material properties between anchor compositions.

Three methods, chosen per property in the workbook:

  linear   straight lines between anchors. The default.
  log      linear in log10 -- for densities spanning decades (Nc, Nv).
  pchip    piecewise-cubic Hermite. Smooth, and MONOTONIC between anchors:
           it never overshoots, which a cubic spline does, so a smooth Eg
           curve cannot dip below its neighbouring anchors.

Outside the anchor range every method clamps to the nearest anchor rather
than extrapolating. Extrapolating a fitted curve beyond its data is how a
composition grid ends up describing a material that does not exist, so it is
refused unless the anchors themselves are extended.

Electron affinity can be given directly or derived from the ionisation
potential (chi = IP - Eg). The derived route interpolates IP and Eg
SEPARATELY on the same anchors, which keeps both band edges consistent. It
does not fix a bad anchor set: if IP has two anchors and Eg has twenty, the
curvature in Eg lands entirely on the conduction band. Supply IP at the same
compositions as Eg when you use it.
"""

from __future__ import annotations

import math

import numpy as np

from .registry import lookup

__all__ = ["Interpolator"]


class Interpolator:
    def __init__(self, anchors, methods=None):
        self.anchors = sorted(anchors, key=lambda r: r["composition"])
        self.methods = {k.lower(): v for k, v in (methods or {}).items()}
        self._cache = {}

    @property
    def span(self):
        c = [a["composition"] for a in self.anchors]
        return min(c), max(c)

    def properties(self):
        keys = set()
        for a in self.anchors:
            keys |= {k for k, v in a.items() if isinstance(v, (int, float))}
        keys.discard("composition")
        keys.discard("abs_onset")      # a property of a spectrum, not the material
        if "IP" in keys and "Eg" in keys:
            keys.add("chi")
        return sorted(keys)

    def method(self, prop):
        m = self.methods.get(prop.lower())
        if m:
            return m
        try:
            return "log" if lookup(prop).log else "linear"
        except KeyError:
            return "linear"

    def _points(self, prop):
        pts = [(a["composition"], a[prop]) for a in self.anchors
               if isinstance(a.get(prop), (int, float))]
        if len(pts) < 1:
            raise KeyError(f"no anchor gives a value for {prop!r}")
        return pts

    def __call__(self, prop, s):
        """Interpolated value of `prop` at composition `s`."""
        if prop == "chi" and not any("chi" in a for a in self.anchors):
            return self("IP", s) - self("Eg", s)
        key = (prop, float(s))
        if key in self._cache:
            return self._cache[key]
        pts = self._points(prop)
        xs = np.array([p[0] for p in pts], float)
        ys = np.array([p[1] for p in pts], float)
        s = float(np.clip(s, xs.min(), xs.max()))
        if len(xs) == 1:
            v = float(ys[0])
        else:
            m = self.method(prop)
            if m == "log":
                if (ys <= 0).any():
                    raise ValueError(f"{prop}: log interpolation needs "
                                     f"positive anchor values")
                v = float(10 ** np.interp(s, xs, np.log10(ys)))
            elif m == "pchip" and len(xs) >= 3:
                from scipy.interpolate import PchipInterpolator
                v = float(PchipInterpolator(xs, ys)(s))
            else:
                v = float(np.interp(s, xs, ys))
        self._cache[key] = v
        return v

    def inside(self, s):
        lo, hi = self.span
        return lo - 1e-9 <= s <= hi + 1e-9

    def neighbours(self, s):
        """The two anchors bracketing s, and the blend weight t toward the upper."""
        c = [a["composition"] for a in self.anchors]
        s = min(max(s, c[0]), c[-1])
        for i in range(len(c) - 1):
            if c[i] <= s <= c[i + 1]:
                t = 0.0 if c[i + 1] == c[i] else (s - c[i]) / (c[i + 1] - c[i])
                return self.anchors[i], self.anchors[i + 1], t
        return self.anchors[-1], self.anchors[-1], 0.0
