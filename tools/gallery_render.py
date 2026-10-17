# Studio render for the README gallery: the same look as the splash
# (tools/splash_render.py) - image-based lighting from a procedural studio, a
# shadowed key light, SSAO, filmic tone mapping and a floor with a baked soft
# ground shadow - but scaled to any model size.
#
# A scene is a folder of <finish>.obj files (mm) written by
# tools/gallery_scenes.py, plus camera.json. A "fea" finish takes its colours
# from fea_rgb.npy (one RGB per vertex, 0..1). Run with FreeCAD's Python (it
# ships VTK) under X:
#   xvfb-run <freecad>/usr/bin/python tools/gallery_render.py <scene dir> <out.png> [W H]
import sys, math, os, json
import numpy as np
from PIL import Image, ImageFilter
from vtkmodules.vtkIOGeometry import vtkOBJReader
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkRenderingCore import (vtkActor, vtkPolyDataMapper, vtkRenderer, vtkRenderWindow,
                                         vtkLight, vtkTexture, vtkWindowToImageFilter)
from vtkmodules.vtkRenderingOpenGL2 import (vtkShadowMapPass, vtkSequencePass, vtkCameraPass,
                                            vtkRenderPassCollection, vtkSSAOPass, vtkToneMappingPass)
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkIOImage import vtkPNGWriter, vtkPNGReader
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
import vtkmodules.vtkInteractionStyle  # noqa: F401

SCENE, OUTP = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1600
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
CAM = json.load(open(os.path.join(SCENE, "camera.json")))

# finish: (rgb, metallic, roughness, clear coat)
FIN = {
    "paint":    ((0.86, 0.88, 0.90), 0.0, 0.32, True),
    "frame":    ((0.11, 0.30, 0.55), 0.0, 0.45, True),
    "yellow":   ((0.98, 0.66, 0.10), 0.0, 0.34, True),
    "red":      ((0.70, 0.07, 0.05), 0.0, 0.30, True),
    "deck":     ((0.42, 0.44, 0.47), 0.85, 0.55, False),
    "steel":    ((0.55, 0.56, 0.58), 1.0, 0.36, False),
    "machined": ((0.80, 0.81, 0.83), 1.0, 0.24, False),
    "cast":     ((0.30, 0.33, 0.37), 0.0, 0.55, False),
    "pipe":     ((0.78, 0.79, 0.81), 1.0, 0.22, False),
    "bolt":     ((0.62, 0.62, 0.58), 1.0, 0.30, False),
    "black":    ((0.06, 0.06, 0.07), 0.0, 0.45, False),
    "gasket":   ((0.05, 0.05, 0.05), 0.0, 0.85, False),
    "valve":    ((0.70, 0.07, 0.05), 0.0, 0.30, True),
    "gauge":    ((0.80, 0.81, 0.83), 1.0, 0.25, False),
    "pump":     ((1.00, 0.55, 0.12), 0.0, 0.30, True),
    "accent":   ((1.00, 0.68, 0.20), 0.0, 0.35, True),
    "motor":    ((0.16, 0.18, 0.21), 0.0, 0.42, False),
    "fea":      ((1.0, 1.0, 1.0), 0.0, 0.40, True),
}


def lin(c):
    return tuple(x ** 2.2 for x in c)


def studio_env(w=1024, h=512):
    u = (np.arange(w) + 0.5) / w * 2 * math.pi - math.pi
    v = (np.arange(h) + 0.5) / h * math.pi
    U, Vv = np.meshgrid(u, v)
    el = math.pi / 2 - Vv
    base = 0.10 + 0.25 * np.clip(np.sin(el), 0, 1)
    base = np.where(el < 0, 0.06 + 0.04 * (1 + np.sin(el)), base)
    img = np.stack([base * 0.85, base * 0.92, base * 1.05], -1)

    def box(az, elv, daz, del_, power, col=(1, 1, 1)):
        d = np.exp(-(((U - az + math.pi) % (2 * math.pi) - math.pi) / daz) ** 8 - ((el - elv) / del_) ** 8)
        for i in range(3):
            img[..., i] += power * col[i] * d
    box(math.radians(-40), math.radians(50), math.radians(30), math.radians(18), 9.0)
    box(math.radians(120), math.radians(25), math.radians(8), math.radians(30), 3.0)
    box(math.radians(-140), math.radians(20), math.radians(8), math.radians(30), 2.0, (0.8, 0.9, 1.0))
    box(math.radians(40), math.radians(10), math.radians(25), math.radians(6), 1.2, (1.0, 0.85, 0.7))
    return img.astype(np.float32)


def env_texture():
    img = studio_env()
    h, w, _ = img.shape
    data = vtkImageData(); data.SetDimensions(w, h, 1)
    arr = numpy_to_vtk(img[::-1].reshape(-1, 3).copy(), deep=True); arr.SetNumberOfComponents(3)
    data.GetPointData().SetScalars(arr)
    t = vtkTexture(); t.SetInputData(data); t.SetColorModeToDirectScalars(); t.MipmapOn(); t.InterpolateOn()
    return t


ren = vtkRenderer()
win = vtkRenderWindow(); win.SetOffScreenRendering(1); win.SetMultiSamples(0); win.AddRenderer(ren)

bounds = None
for fin, (rgb, met, rough, coat) in FIN.items():
    path = os.path.join(SCENE, fin + ".obj")
    if not os.path.exists(path):
        continue
    r = vtkOBJReader(); r.SetFileName(path); r.Update()
    pd = r.GetOutput()
    if fin == "fea":
        cols = np.load(os.path.join(SCENE, "fea_rgb.npy")).astype(np.float32)
        cols = np.clip(cols, 0, 1) ** 2.2                          # sRGB to linear
        a = numpy_to_vtk((cols * 255).astype(np.uint8), deep=True); a.SetName("rgb")
        pd.GetPointData().SetScalars(a)
    m = vtkPolyDataMapper()
    if pd.GetPointData().GetNormals() is not None:
        m.SetInputData(pd)                                  # exact normals from the exporter
    else:
        n = vtkPolyDataNormals(); n.SetInputData(pd)
        n.SetFeatureAngle(32); n.SplittingOn(); n.ConsistencyOn(); n.AutoOrientNormalsOff()
        n.ComputePointNormalsOn(); n.Update()
        m.SetInputConnection(n.GetOutputPort())
    if fin == "fea":
        m.SetColorModeToDirectScalars(); m.ScalarVisibilityOn()
    else:
        m.ScalarVisibilityOff()
    a = vtkActor(); a.SetMapper(m)
    p = a.GetProperty(); p.SetInterpolationToPBR()
    p.SetColor(*lin(rgb)); p.SetMetallic(met); p.SetRoughness(rough)
    if coat:
        try:
            p.SetCoatStrength(float(CAM.get("coat", 0.3))); p.SetCoatRoughness(0.18)
        except Exception:
            pass
    ren.AddActor(a)
    b = pd.GetBounds()
    bounds = b if bounds is None else (min(bounds[0], b[0]), max(bounds[1], b[1]), min(bounds[2], b[2]),
                                       max(bounds[3], b[3]), min(bounds[4], b[4]), max(bounds[5], b[5]))
    print(fin, pd.GetNumberOfPolys())

cx, cy = (bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2
z0 = bounds[4]
D = math.dist(bounds[0::2], bounds[1::2])                 # model diagonal
HALF = 1.6 * D                                            # floor texture half size
N = 2048

# --- pass 1: top-down height map -> floor texture with baked ground shadow
win.SetSize(N, N)
ren.SetBackground(1, 1, 1)
c = ren.GetActiveCamera(); c.ParallelProjectionOn()
top = z0 + 4 * D
c.SetFocalPoint(cx, cy, z0); c.SetPosition(cx, cy, top); c.SetViewUp(0, 1, 0)
c.SetParallelScale(HALF); near, far = 0.05 * D, 6 * D; c.SetClippingRange(near, far)
win.Render()
z = vtkWindowToImageFilter(); z.SetInput(win); z.SetInputBufferTypeToZBuffer(); z.ReadFrontBufferOff(); z.Update()
d = vtk_to_numpy(z.GetOutput().GetPointData().GetScalars()).reshape(N, N)
hgt = (top - z0) - (near + d * (far - near))
hgt[d >= 0.99999] = -1
hgt = hgt[::-1]
px = 2 * HALF / N
k = D / 6000.0                                             # shadow softness scales with the model


def blur(mask, mm):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(max(0.5, mm / px))), dtype=np.float32) / 255


light = np.ones_like(hgt)
for lo, hi, soft, dark in ((-0.5, 60 * k, 20 * k, 0.85), (60 * k, 400 * k, 70 * k, 0.65),
                           (400 * k, 1500 * k, 220 * k, 0.5), (1500 * k, 1e12, 450 * k, 0.4)):
    m = ((hgt >= lo) & (hgt < hi)).astype(np.float32)
    if m.any():
        light *= 1 - dark * blur(m, soft)
fp_ = (hgt >= 0).astype(np.float32)
light *= 1 - 0.7 * blur(fp_, 600 * k)
light *= 1 - 0.35 * blur(fp_, 1600 * k)
yy, xx = np.mgrid[0:N, 0:N]
rr = np.hypot(xx - N / 2, yy - N / 2) / (N / 2)
t = np.clip((rr - 0.12) / 0.85, 0, 1) ** 1.4
centre = np.array(CAM.get("floor_centre", [0.42, 0.48, 0.58])); edge = np.array([0.07, 0.09, 0.13])
col = centre[None, None] * (1 - t[..., None]) + edge[None, None] * t[..., None]
col = col * light[..., None]
floor_png = os.path.join(SCENE, "_floor.png")
Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(floor_png)

# --- pass 2: beauty
c.ParallelProjectionOff()
win.SetSize(W, H)
fl = vtkPlaneSource()
fl.SetOrigin(cx - HALF, cy - HALF, z0 - 0.5); fl.SetPoint1(cx + HALF, cy - HALF, z0 - 0.5)
fl.SetPoint2(cx - HALF, cy + HALF, z0 - 0.5)
fm = vtkPolyDataMapper(); fm.SetInputConnection(fl.GetOutputPort())
floor = vtkActor(); floor.SetMapper(fm)
fp = floor.GetProperty(); fp.SetInterpolationToPBR(); fp.SetColor(1, 1, 1); fp.SetMetallic(0.0); fp.SetRoughness(0.6)
pr = vtkPNGReader(); pr.SetFileName(floor_png)
tt = vtkTexture(); tt.SetInputConnection(pr.GetOutputPort()); tt.InterpolateOn(); tt.MipmapOn()
tt.UseSRGBColorSpaceOn(); tt.EdgeClampOn(); tt.RepeatOff()
fp.SetBaseColorTexture(tt)
ren.AddActor(floor)
big = vtkPlaneSource()
big.SetOrigin(cx - 60 * D, cy - 60 * D, z0 - 2); big.SetPoint1(cx + 60 * D, cy - 60 * D, z0 - 2)
big.SetPoint2(cx - 60 * D, cy + 60 * D, z0 - 2)
bm = vtkPolyDataMapper(); bm.SetInputConnection(big.GetOutputPort())
ba = vtkActor(); ba.SetMapper(bm)
bp = ba.GetProperty(); bp.SetInterpolationToPBR(); bp.SetMetallic(0); bp.SetRoughness(0.6)
bp.SetColor(*lin((0.07, 0.09, 0.13)))
ren.AddActor(ba)

ren.UseImageBasedLightingOn(); ren.SetEnvironmentTexture(env_texture(), False)
ren.SetEnvironmentUp(0, 0, 1); ren.SetEnvironmentRight(1, 0, 0)        # the model is Z-up
ren.SetBackground(0.012, 0.016, 0.026); ren.SetBackground2(0.010, 0.013, 0.022); ren.GradientBackgroundOn()
try:
    ren.UseSphericalHarmonicsOn()
except Exception:
    pass
ren.AutomaticLightCreationOff()
key = vtkLight(); key.SetLightTypeToSceneLight(); key.SetPositional(True); key.SetConeAngle(40)
key.SetPosition(cx - 1.0 * D, cy - 1.5 * D, z0 + 2.3 * D); key.SetFocalPoint(cx, cy, z0 + 0.1 * D)
key.SetIntensity(1.6); key.SetColor(1.0, 0.97, 0.92); ren.AddLight(key)
fill = vtkLight(); fill.SetLightTypeToSceneLight(); fill.SetPositional(True); fill.SetConeAngle(60)
fill.SetPosition(cx + 1.5 * D, cy - 0.5 * D, z0 + 0.8 * D); fill.SetFocalPoint(cx, cy, z0 + 0.2 * D)
fill.SetIntensity(0.35); fill.SetColor(0.8, 0.88, 1.0); ren.AddLight(fill)

shadows = vtkShadowMapPass(); seq = vtkSequencePass(); passes = vtkRenderPassCollection()
passes.AddItem(shadows.GetShadowMapBakerPass()); passes.AddItem(shadows); seq.SetPasses(passes)
cam_pass = vtkCameraPass(); cam_pass.SetDelegatePass(seq)
try:
    shadows.GetShadowMapBakerPass().SetResolution(4096)
except Exception:
    pass
ssao = vtkSSAOPass(); ssao.SetDelegatePass(cam_pass)
ssao.SetRadius(0.02 * D); ssao.SetBias(0.0003 * D); ssao.SetKernelSize(128); ssao.BlurOn()
tone = vtkToneMappingPass(); tone.SetDelegatePass(ssao)
tone.SetToneMappingType(vtkToneMappingPass.GenericFilmic); tone.SetGenericFilmicDefaultPresets()
tone.SetExposure(float(CAM.get("exposure", 1.2)))
ren.SetPass(tone)

foc = CAM.get("focus") or [cx, cy, (bounds[4] + bounds[5]) / 2]
az, el = math.radians(CAM.get("az", -50)), math.radians(CAM.get("el", 24))
dist = CAM.get("dist", 1.9) * D
c.SetFocalPoint(*foc)
c.SetPosition(foc[0] - dist * math.cos(el) * math.sin(az), foc[1] - dist * math.cos(el) * math.cos(az),
              foc[2] + dist * math.sin(el))
c.SetViewUp(0, 0, 1); c.SetViewAngle(CAM.get("fov", 30))
c.SetWindowCenter(*CAM.get("shift", [0, 0]))
c.SetClippingRange(0.02 * D, 80 * D)

SS = int(CAM.get("supersample", 2))                         # render big, shrink: clean edges
win.SetSize(W * SS, H * SS)
win.Render()
w2i = vtkWindowToImageFilter(); w2i.SetInput(win); w2i.SetInputBufferTypeToRGB(); w2i.ReadFrontBufferOff()
w2i.Update()
tmp = OUTP + ".big.png"
wr = vtkPNGWriter(); wr.SetFileName(tmp); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
Image.open(tmp).resize((W, H), Image.LANCZOS).save(OUTP)
os.remove(tmp)
print("wrote", OUTP)
