"""
Where each A-scan sample is in the part, for the Analysis page's views and readings. SI throughout
(m, s, m/s); angles in degrees.

Definitions (to be confirmed against the user's OmniPC readings - analysis/tests/fixtures):
    time of sample i      t = ultrasound_offset + i * sample_period
                          (the beam's ultrasoundOffset on a beams dataset, the Ultrasound axis
                          offset on a raster one; time is round trip in the part)
    sound path            SP = velocity * t / 2          (true path, one way)
    depth (leg 1)         d = SP * cos(refracted angle)
    along the surface     SP * sin(refracted angle), towards the skew direction from the exit
                          point: +V for skew 90, -V for skew 270, +U for 0, -U for 180
    skips                 with part thickness T, depth folds every T: leg 1 goes down, leg 2 up...
"""
import math
from dataclasses import dataclass

import numpy as np


def sample_times(group, beam, count=None):
    """Times (s) of a beam's samples."""
    axis = group.ultrasound_axis
    n = axis.quantity if count is None else count
    return beam.ultrasound_offset + np.arange(n) * axis.resolution


def sound_path(time, velocity):
    """One-way sound path (m) for a round-trip time (s)."""
    return velocity * np.asarray(time) / 2.0


@dataclass
class Ray:
    """A beam's path in the part: from its exit point, as far as its last sample."""
    u0: float          # m, exit point along the scan axis
    v0: float          # m, exit point along the index axis
    du: float          # direction per metre of sound path: along U,
    dv: float          # along V,
    dz: float          # and down (cos of the refracted angle)
    sp_start: float    # m, sound path of the first sample
    sp_step: float     # m of sound path per sample


def ray(group, beam):
    angle = math.radians(beam.refracted_angle)
    skew = math.radians(beam.skew_angle)
    across = math.sin(angle)
    period = group.ultrasound_axis.resolution
    return Ray(
        u0=beam.u_offset, v0=beam.v_offset,
        du=across * math.cos(skew), dv=across * math.sin(skew), dz=math.cos(angle),
        sp_start=beam.velocity * beam.ultrasound_offset / 2.0, sp_step=beam.velocity * period / 2.0,
    )


def position(group, beam, sample):
    """(u, v, depth) in m of a sample along a beam (depth not folded at the back wall)."""
    r = ray(group, beam)
    sp = r.sp_start + sample * r.sp_step
    return r.u0 + sp * r.du, r.v0 + sp * r.dv, sp * r.dz


def fold_depth(depth, thickness):
    """(true depth, leg) of an unfolded depth in a part `thickness` thick (leg 1 = first leg)."""
    if not thickness or thickness <= 0:
        return depth, 1
    leg = int(depth // thickness)
    within = depth - leg * thickness
    return (within if leg % 2 == 0 else thickness - within), leg + 1


def frame_rays(group):
    """Every lateral line's ray, for drawing the S-scan (or the raster's index x depth view)."""
    return [ray(group, beam) for beam in group.beams]
