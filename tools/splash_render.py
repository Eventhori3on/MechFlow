# Renders the splash showcase (tools/splash_scene.py's triangles) with VTK's
# physically based renderer: image-based lighting from a procedural studio,
# a key light with shadows, supersampled.  Run with FreeCAD's Python (it ships
# VTK) under X:   xvfb-run python tools/splash_render.py <scene dir> <out.png> [W H]
import sys, math, os
import numpy as np
from vtkmodules.vtkIOGeometry import vtkOBJReader
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkRenderingCore import (vtkActor, vtkPolyDataMapper, vtkRenderer, vtkRenderWindow,
                                         vtkLight, vtkTexture, vtkWindowToImageFilter, vtkCamera)
from vtkmodules.vtkRenderingOpenGL2 import (vtkShadowMapPass, vtkSequencePass, vtkCameraPass,
                                            vtkRenderPassCollection, vtkOpaquePass,
                                            vtkLightsPass, vtkRenderStepsPass, vtkSSAOPass,
                                            vtkToneMappingPass)
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.util.numpy_support import numpy_to_vtk
from vtkmodules.vtkIOImage import vtkPNGWriter
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
import vtkmodules.vtkInteractionStyle  # noqa: F401

SCENE = sys.argv[1]
OUTP = sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 2720
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1600

# finish: (rgb, metallic, roughness)
FIN = {
    "paint":  ((0.86, 0.88, 0.90), 0.0, 0.32),
    "frame":  ((0.11, 0.30, 0.55), 0.0, 0.38),
    "deck":   ((0.42, 0.44, 0.47), 0.85, 0.55),
    "steel":  ((0.55, 0.56, 0.58), 1.0, 0.36),
    "pipe":   ((0.78, 0.79, 0.81), 1.0, 0.22),
    "bolt":   ((0.62, 0.62, 0.58), 1.0, 0.30),
    "gasket": ((0.05, 0.05, 0.05), 0.0, 0.85),
    "valve":  ((0.70, 0.07, 0.05), 0.0, 0.30),
    "gauge":  ((0.80, 0.81, 0.83), 1.0, 0.25),
    "pump":   ((1.00, 0.55, 0.12), 0.0, 0.30),
    "accent": ((1.00, 0.68, 0.20), 0.0, 0.35),
    "motor":  ((0.16, 0.18, 0.21), 0.0, 0.42),
}


def srgb_to_lin(c):
    return tuple(x ** 2.2 for x in c)


def studio_env(w=1024, h=512):
    """Equirectangular studio: dark cyclorama, a big soft key box overhead
    front-left, strip lights at the sides, a warm floor bounce."""
    u = (np.arange(w) + 0.5) / w * 2 * math.pi - math.pi          # azimuth
    v = (np.arange(h) + 0.5) / h * math.pi                        # 0 top .. pi bottom
    U, Vv = np.meshgrid(u, v)
    el = math.pi / 2 - Vv                                         # elevation
    base = 0.10 + 0.25 * np.clip(np.sin(el), 0, 1)                # brighter overhead
    base = np.where(el < 0, 0.06 + 0.04 * (1 + np.sin(el)), base)
    img = np.stack([base * 0.85, base * 0.92, base * 1.05], -1)

    def box(az, elv, daz, del_, power, col=(1, 1, 1)):
        d = np.exp(-(((U - az + math.pi) % (2 * math.pi) - math.pi) / daz) ** 8
                   - ((el - elv) / del_) ** 8)
        for i in range(3):
            img[..., i] += power * col[i] * d
    box(math.radians(-40), math.radians(50), math.radians(30), math.radians(18), 9.0)       # key softbox
    box(math.radians(120), math.radians(25), math.radians(8), math.radians(30), 3.0)        # strip right/back
    box(math.radians(-140), math.radians(20), math.radians(8), math.radians(30), 2.0, (0.8, 0.9, 1.0))
    box(math.radians(40), math.radians(10), math.radians(25), math.radians(6), 1.2, (1.0, 0.85, 0.7))
    return img.astype(np.float32)


def env_texture():
    img = studio_env()
    h, w, _ = img.shape
    data = vtkImageData()
    data.SetDimensions(w, h, 1)
    arr = numpy_to_vtk(img[::-1].reshape(-1, 3).copy(), deep=True)
    arr.SetNumberOfComponents(3)
    data.GetPointData().SetScalars(arr)
    t = vtkTexture()
    t.SetInputData(data)
    t.SetColorModeToDirectScalars()
    t.MipmapOn()
    t.InterpolateOn()
    return t


ren = vtkRenderer()
win = vtkRenderWindow()
win.SetOffScreenRendering(1)
win.SetSize(W, H)
win.SetMultiSamples(0)
win.AddRenderer(ren)

bounds = None
for fin, (rgb, met, rough) in FIN.items():
    path = os.path.join(SCENE, fin + ".obj")
    if not os.path.exists(path):
        continue
    r = vtkOBJReader(); r.SetFileName(path); r.Update()
    n = vtkPolyDataNormals(); n.SetInputConnection(r.GetOutputPort())
    n.SetFeatureAngle(32); n.SplittingOn(); n.ConsistencyOn(); n.AutoOrientNormalsOff()
    n.ComputePointNormalsOn(); n.Update()
    m = vtkPolyDataMapper(); m.SetInputConnection(n.GetOutputPort())
    a = vtkActor(); a.SetMapper(m)
    p = a.GetProperty()
    p.SetInterpolationToPBR()
    p.SetColor(*srgb_to_lin(rgb))
    p.SetMetallic(met)
    p.SetRoughness(rough)
    if fin in ("paint", "valve", "pump", "accent", "frame"):
        try:
            p.SetCoatStrength(0.6); p.SetCoatRoughness(0.08)
        except Exception:
            pass
    ren.AddActor(a)
    b = r.GetOutput().GetBounds()
    bounds = b if bounds is None else (min(bounds[0], b[0]), max(bounds[1], b[1]), min(bounds[2], b[2]),
                                       max(bounds[3], b[3]), min(bounds[4], b[4]), max(bounds[5], b[5]))
    print(fin, r.GetOutput().GetNumberOfPolys())

cx, cy = (bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2
FLOOR_HALF = 7000.0                       # the floor texture covers 14 m square
MODE = os.environ.get("MF_MODE", "beauty")
if MODE == "height":
    # top-down orthographic depth: becomes the ground shadow (see splash_floor.py)
    N = 2048
    win.SetSize(N, N)
    ren.SetBackground(1, 1, 1); ren.GradientBackgroundOff()
    c = ren.GetActiveCamera(); c.ParallelProjectionOn()
    c.SetFocalPoint(cx, cy, 0); c.SetPosition(cx, cy, 20000); c.SetViewUp(0, 1, 0)
    c.SetParallelScale(FLOOR_HALF); c.SetClippingRange(1000, 30000)
    win.Render()
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter as _W
    from vtkmodules.util.numpy_support import vtk_to_numpy
    z = _W(); z.SetInput(win); z.SetInputBufferTypeToZBuffer(); z.ReadFrontBufferOff(); z.Update()
    d = vtk_to_numpy(z.GetOutput().GetPointData().GetScalars()).reshape(N, N)
    # orthographic: depth is linear between near (1000) and far (30000)
    h = 20000 - (1000 + d * (30000 - 1000))
    h[d >= 0.99999] = -1                  # nothing there
    np.save(OUTP, h.astype(np.float32))
    print("height map", OUTP, float(h.max()))
    sys.exit(0)

# floor (textured: vignette + baked ground shadow, see splash_floor.py)
fl = vtkPlaneSource()
fl.SetOrigin(cx - FLOOR_HALF, cy - FLOOR_HALF, -1); fl.SetPoint1(cx + FLOOR_HALF, cy - FLOOR_HALF, -1)
fl.SetPoint2(cx - FLOOR_HALF, cy + FLOOR_HALF, -1)
fm = vtkPolyDataMapper(); fm.SetInputConnection(fl.GetOutputPort())
floor = vtkActor(); floor.SetMapper(fm)
fp = floor.GetProperty(); fp.SetInterpolationToPBR(); fp.SetColor(1, 1, 1)
fp.SetMetallic(0.0); fp.SetRoughness(0.6)
ftex = os.environ.get("MF_FLOOR")
if ftex and os.path.exists(ftex):
    from vtkmodules.vtkIOImage import vtkPNGReader
    pr = vtkPNGReader(); pr.SetFileName(ftex)
    tt = vtkTexture(); tt.SetInputConnection(pr.GetOutputPort()); tt.InterpolateOn(); tt.MipmapOn()
    tt.UseSRGBColorSpaceOn(); tt.EdgeClampOn(); tt.RepeatOff()
    fp.SetBaseColorTexture(tt)
else:
    fp.SetColor(*srgb_to_lin((0.20, 0.25, 0.33)))
ren.AddActor(floor)
# beyond the floor texture: a much bigger floor in the vignette's edge colour
big = vtkPlaneSource()
big.SetOrigin(cx - 200000, cy - 200000, -3); big.SetPoint1(cx + 200000, cy - 200000, -3)
big.SetPoint2(cx - 200000, cy + 200000, -3)
bm = vtkPolyDataMapper(); bm.SetInputConnection(big.GetOutputPort())
ba = vtkActor(); ba.SetMapper(bm)
bp = ba.GetProperty(); bp.SetInterpolationToPBR(); bp.SetMetallic(0); bp.SetRoughness(0.6)
bp.SetColor(*srgb_to_lin(tuple(float(x) for x in os.environ.get("MF_EDGE", "0.07,0.09,0.13").split(","))))
ren.AddActor(ba)

ren.UseImageBasedLightingOn()
ren.SetEnvironmentTexture(env_texture(), False)
ren.SetBackground(0.012, 0.016, 0.026)
ren.SetBackground2(0.010, 0.013, 0.022)
ren.GradientBackgroundOn()
try:
    ren.UseSphericalHarmonicsOn()
except Exception:
    pass

# lights: key (shadows) + fill
ren.AutomaticLightCreationOff()
key = vtkLight(); key.SetLightTypeToSceneLight(); key.SetPositional(True); key.SetConeAngle(40)
key.SetPosition(cx - 6000, cy - 9000, 14000); key.SetFocalPoint(cx, cy, 800); key.SetIntensity(1.6)
key.SetColor(1.0, 0.97, 0.92)
ren.AddLight(key)
fill = vtkLight(); fill.SetLightTypeToSceneLight(); fill.SetPositional(True); fill.SetConeAngle(60)
fill.SetPosition(cx + 9000, cy - 3000, 5000); fill.SetFocalPoint(cx, cy, 1200); fill.SetIntensity(0.35)
fill.SetColor(0.8, 0.88, 1.0)
ren.AddLight(fill)

# passes: shadows -> SSAO -> tone mapping
shadows = vtkShadowMapPass()
seq = vtkSequencePass()
passes = vtkRenderPassCollection()
passes.AddItem(shadows.GetShadowMapBakerPass())
passes.AddItem(shadows)
seq.SetPasses(passes)
cam_pass = vtkCameraPass(); cam_pass.SetDelegatePass(seq)
try:
    shadows.GetShadowMapBakerPass().SetResolution(4096)
except Exception:
    pass
ssao = vtkSSAOPass(); ssao.SetDelegatePass(cam_pass)
ssao.SetRadius(120.0); ssao.SetBias(2.0); ssao.SetKernelSize(128); ssao.BlurOn()
tone = vtkToneMappingPass(); tone.SetDelegatePass(ssao)
tone.SetToneMappingType(vtkToneMappingPass.GenericFilmic)
tone.SetGenericFilmicDefaultPresets()
tone.SetExposure(float(os.environ.get("MF_EXPOSURE", "1.2")))
ren.SetPass(tone)

cam = ren.GetActiveCamera()
foc = (cx + 250, cy, 1500)
az, el, dist = math.radians(float(os.environ.get("MF_AZ", "-58"))), math.radians(float(os.environ.get("MF_EL", "22"))), float(os.environ.get("MF_DIST", "9800"))
cam.SetFocalPoint(*foc)
cam.SetPosition(foc[0] + dist * math.cos(el) * math.sin(az) * -1, foc[1] - dist * math.cos(el) * math.cos(az),
                foc[2] + dist * math.sin(el))
cam.SetViewUp(0, 0, 1)
cam.SetViewAngle(float(os.environ.get("MF_FOV", "30")))
sx = float(os.environ.get("MF_SHIFT_X", "0")); sy = float(os.environ.get("MF_SHIFT_Y", "0"))
cam.SetWindowCenter(sx, sy)
ren.ResetCameraClippingRange()
cam.SetClippingRange(200, 60000)

win.Render()
w2i = vtkWindowToImageFilter(); w2i.SetInput(win); w2i.SetInputBufferTypeToRGB(); w2i.ReadFrontBufferOff()
w2i.Update()
wr = vtkPNGWriter(); wr.SetFileName(OUTP); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
print("wrote", OUTP)
