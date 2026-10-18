# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow's studio renderer (Quick Render and Motion Study "Studio" look).

Runs as its own process with FreeCAD's Python (which ships VTK, numpy and
Pillow), so it never touches FreeCAD's 3D view:

    python render_vtk.py job.json

The job (written by render.py) lists the objects (an OBJ mesh in mm and a
finish each), the frames (camera, output file, and for animations each
object's transform or replacement mesh) and the settings (size,
supersampling, backdrop, floor, exposure). Prints "FRAME i n" as each frame
is written, so the caller can show progress.

Look: image-based lighting from a procedural studio, a key light with
shadows, SSAO, filmic tone mapping and a floor with a soft ground shadow.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageFilter
from vtkmodules.vtkIOGeometry import vtkOBJReader
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals, vtkCleanPolyData, vtkFeatureEdges
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkRenderingCore import (vtkActor, vtkPolyDataMapper, vtkRenderer, vtkRenderWindow,
                                         vtkLight, vtkTexture, vtkWindowToImageFilter)
from vtkmodules.vtkRenderingOpenGL2 import (vtkShadowMapPass, vtkSequencePass, vtkCameraPass,
                                            vtkRenderPassCollection, vtkSSAOPass, vtkToneMappingPass,
                                            vtkLightsPass, vtkOpaquePass, vtkTranslucentPass,
                                            vtkOverlayPass)
from vtkmodules.vtkCommonCore import vtkObject, vtkOutputWindow, vtkFileOutputWindow
from vtkmodules.vtkCommonDataModel import vtkImageData
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkIOImage import vtkPNGReader
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
import vtkmodules.vtkInteractionStyle  # noqa: F401

# backdrop: (background top, bottom, floor centre, floor edge, environment brightness)
BACKDROPS = {
    "Studio dark": ((0.012, 0.016, 0.026), (0.010, 0.013, 0.022), (0.42, 0.48, 0.58), (0.07, 0.09, 0.13), 1.0),
    "Studio light": ((0.86, 0.88, 0.91), (0.70, 0.73, 0.77), (0.93, 0.94, 0.95), (0.70, 0.73, 0.77), 1.25),
    "White": ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0), 1.3),
}


def lin(c):
    return tuple(max(0.0, float(x)) ** 2.2 for x in c)


def studio_env(bright, w=1024, h=512):
    """Equirectangular studio: soft key box overhead, strip lights, floor bounce."""
    u = (np.arange(w) + 0.5) / w * 2 * math.pi - math.pi
    v = (np.arange(h) + 0.5) / h * math.pi
    U, Vv = np.meshgrid(u, v)
    el = math.pi / 2 - Vv
    # a lit cyclorama: brighter than black all round, so metals have
    # something to reflect on their sides
    base = 0.22 + 0.25 * np.clip(np.sin(el), 0, 1)
    base = np.where(el < 0, 0.16 + 0.06 * (1 + np.sin(el)), base)
    img = np.stack([base * 0.85, base * 0.92, base * 1.05], -1)

    def box(az, elv, daz, del_, power, col=(1, 1, 1)):
        d = np.exp(-(((U - az + math.pi) % (2 * math.pi) - math.pi) / daz) ** 8 - ((el - elv) / del_) ** 8)
        for i in range(3):
            img[..., i] += power * col[i] * d
    box(math.radians(-40), math.radians(50), math.radians(30), math.radians(18), 9.0)
    box(math.radians(120), math.radians(25), math.radians(8), math.radians(30), 3.0)
    box(math.radians(-140), math.radians(20), math.radians(8), math.radians(30), 2.0, (0.8, 0.9, 1.0))
    box(math.radians(40), math.radians(10), math.radians(25), math.radians(6), 1.2, (1.0, 0.85, 0.7))
    # tall soft boxes at the sides, low: highlights down vertical faces
    box(math.radians(-100), math.radians(8), math.radians(22), math.radians(16), 2.6)
    box(math.radians(80), math.radians(8), math.radians(18), math.radians(14), 1.6, (0.9, 0.95, 1.0))
    return (img * bright).astype(np.float32)


def env_texture(bright):
    img = studio_env(bright)
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


def read_mesh(path):
    r = vtkOBJReader()
    r.SetFileName(path)
    r.Update()
    pd = r.GetOutput()
    if pd.GetPointData().GetNormals() is None:
        n = vtkPolyDataNormals()
        n.SetInputData(pd)
        n.SetFeatureAngle(32)
        n.SplittingOn()
        n.ConsistencyOn()
        n.Update()
        pd = n.GetOutput()
    return pd


def outline(pd):
    """The sharp and open edges of a mesh: see-through parts get these drawn,
    as the 3D view does, so the panels still read."""
    c = vtkCleanPolyData()
    c.SetInputData(pd)
    c.PointMergingOn()
    fe = vtkFeatureEdges()
    fe.SetInputConnection(c.GetOutputPort())
    fe.BoundaryEdgesOn()
    fe.FeatureEdgesOn()
    fe.SetFeatureAngle(30)
    fe.NonManifoldEdgesOff()
    fe.ManifoldEdgesOff()
    fe.ColoringOff()
    fe.Update()
    return fe.GetOutput()


def matrix(m16):
    m = vtkMatrix4x4()
    for i in range(16):
        m.SetElement(i // 4, i % 4, float(m16[i]))
    return m


def main(job_path):
    # VTK's warnings go to a log file: on Windows they'd open a console window
    try:
        fow = vtkFileOutputWindow()
        fow.SetFileName(os.path.join(os.path.dirname(os.path.abspath(job_path)), "vtk_log.txt"))
        fow.FlushOn()
        vtkOutputWindow.SetInstance(fow)
        vtkObject.GlobalWarningDisplayOff()
    except Exception:
        pass
    job = json.load(open(job_path))
    st = job["settings"]
    W, H = int(st.get("width", 1920)), int(st.get("height", 1080))
    SS = max(1.0, float(st.get("supersample", 2)))
    # keep the render window within ~16 Mpx (5400 x 3000): beyond that the
    # SSAO / peeling buffers run the graphics memory out (4K Best froze PCs)
    SS = max(1.0, min(SS, math.sqrt(16.0e6 / (W * H)), 8192.0 / max(W, H)))
    RW, RH = int(round(W * SS)), int(round(H * SS))
    top, bottom, fcen, fedge, bright = BACKDROPS.get(st.get("backdrop", "Studio dark"),
                                                     BACKDROPS["Studio dark"])
    ren = vtkRenderer()
    win = vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetMultiSamples(0)
    win.AddRenderer(ren)

    actors, mappers, edges = {}, {}, {}
    for o in job["objects"]:
        pd = read_mesh(o["mesh"])
        m = vtkPolyDataMapper()
        m.SetInputData(pd)
        m.ScalarVisibilityOff()
        a = vtkActor()
        a.SetMapper(m)
        p = a.GetProperty()
        p.SetInterpolationToPBR()
        p.SetColor(*lin(o.get("rgb", (0.8, 0.8, 0.8))))
        p.SetMetallic(float(o.get("metal", 0.0)))
        p.SetRoughness(float(o.get("rough", 0.5)))
        if o.get("coat", 0) > 0:
            try:
                p.SetCoatStrength(float(o["coat"]))
                p.SetCoatRoughness(0.15)
            except Exception:
                pass
        ren.AddActor(a)
        actors[o["id"]] = a
        mappers[o["id"]] = m
        if o.get("opacity", 1.0) < 1.0:
            p.SetOpacity(float(o["opacity"]))
            a.ForceTranslucentOn()
            em = vtkPolyDataMapper()
            em.SetInputData(outline(pd))
            em.ScalarVisibilityOff()
            e = vtkActor()
            e.SetMapper(em)
            ep = e.GetProperty()
            ep.LightingOff()
            ep.SetColor(*lin(tuple(0.35 * c for c in o.get("rgb", (0.5, 0.5, 0.5)))))
            ep.SetLineWidth(max(1.0, 1.4 * RW / 1920.0))
            ep.SetOpacity(min(0.9, 0.35 + float(o["opacity"])))
            e.ForceTranslucentOn()
            ren.AddActor(e)
            edges[o["id"]] = (e, em)

    def place(frame):
        for k, m16 in frame.get("xf", {}).items():
            a = actors.get(int(k))
            if a is not None:
                a.SetUserMatrix(matrix(m16))
            if int(k) in edges:
                edges[int(k)][0].SetUserMatrix(matrix(m16))
        for k, path in frame.get("mesh", {}).items():
            m = mappers.get(int(k))
            if m is not None:
                pd = read_mesh(path)
                m.SetInputData(pd)
                if int(k) in edges:
                    edges[int(k)][1].SetInputData(outline(pd))

    frames = job["frames"]
    place(frames[0])
    b = ren.ComputeVisiblePropBounds()
    cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
    z0 = b[4]
    D = max(1.0, math.dist(b[0::2], b[1::2]))
    HALF = 1.6 * D

    # floor texture: vignette, and (stills) the model's baked ground shadow
    N = 2048
    light = np.ones((N, N), np.float32)
    if st.get("floor", True) and st.get("bake", True):
        seethrough = [a for a in actors.values() if a.GetProperty().GetOpacity() < 0.5]
        seethrough += [e for e, _ in edges.values()]
        for a in seethrough:
            a.VisibilityOff()             # see-through context casts no ground shadow
        win.SetSize(N, N)
        ren.SetBackground(1, 1, 1)
        c = ren.GetActiveCamera()
        c.ParallelProjectionOn()
        topz = z0 + 4 * D
        c.SetFocalPoint(cx, cy, z0)
        c.SetPosition(cx, cy, topz)
        c.SetViewUp(0, 1, 0)
        c.SetParallelScale(HALF)
        near, far = 0.05 * D, 6 * D
        c.SetClippingRange(near, far)
        win.Render()
        zb = vtkWindowToImageFilter()
        zb.SetInput(win)
        zb.SetInputBufferTypeToZBuffer()
        zb.ReadFrontBufferOff()
        zb.Update()
        d = vtk_to_numpy(zb.GetOutput().GetPointData().GetScalars()).reshape(N, N)
        hgt = (topz - z0) - (near + d * (far - near))
        hgt[d >= 0.99999] = -1
        hgt = hgt[::-1]
        px = 2 * HALF / N
        k = D / 6000.0

        def blur(mask, mm):
            im = Image.fromarray((mask * 255).astype(np.uint8))
            return np.asarray(im.filter(ImageFilter.GaussianBlur(max(0.5, mm / px))), dtype=np.float32) / 255
        for lo, hi, soft, dark in ((-0.5, 60 * k, 20 * k, 0.85), (60 * k, 400 * k, 70 * k, 0.65),
                                   (400 * k, 1500 * k, 220 * k, 0.5), (1500 * k, 1e12, 450 * k, 0.4)):
            m = ((hgt >= lo) & (hgt < hi)).astype(np.float32)
            if m.any():
                light *= 1 - dark * blur(m, soft)
        fp_ = (hgt >= 0).astype(np.float32)
        light *= 1 - 0.7 * blur(fp_, 600 * k)
        light *= 1 - 0.35 * blur(fp_, 1600 * k)
        c.ParallelProjectionOff()
        for a in seethrough:
            a.VisibilityOn()
    yy, xx = np.mgrid[0:N, 0:N]
    rr = np.hypot(xx - N / 2, yy - N / 2) / (N / 2)
    t = np.clip((rr - 0.12) / 0.85, 0, 1) ** 1.4
    col = np.array(fcen)[None, None] * (1 - t[..., None]) + np.array(fedge)[None, None] * t[..., None]
    col = col * light[..., None]
    floor_png = os.path.join(os.path.dirname(job_path), "_floor.png")
    Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(floor_png)

    if st.get("floor", True):
        fl = vtkPlaneSource()
        fl.SetOrigin(cx - HALF, cy - HALF, z0 - 0.002 * D)
        fl.SetPoint1(cx + HALF, cy - HALF, z0 - 0.002 * D)
        fl.SetPoint2(cx - HALF, cy + HALF, z0 - 0.002 * D)
        fm = vtkPolyDataMapper()
        fm.SetInputConnection(fl.GetOutputPort())
        floor = vtkActor()
        floor.SetMapper(fm)
        fpr = floor.GetProperty()
        fpr.SetInterpolationToPBR()
        fpr.SetColor(1, 1, 1)
        fpr.SetMetallic(0.0)
        fpr.SetRoughness(0.6)
        pr = vtkPNGReader()
        pr.SetFileName(floor_png)
        tt = vtkTexture()
        tt.SetInputConnection(pr.GetOutputPort())
        tt.InterpolateOn()
        tt.MipmapOn()
        tt.UseSRGBColorSpaceOn()
        tt.EdgeClampOn()
        tt.RepeatOff()
        fpr.SetBaseColorTexture(tt)
        ren.AddActor(floor)
        big = vtkPlaneSource()
        big.SetOrigin(cx - 60 * D, cy - 60 * D, z0 - 0.004 * D)
        big.SetPoint1(cx + 60 * D, cy - 60 * D, z0 - 0.004 * D)
        big.SetPoint2(cx - 60 * D, cy + 60 * D, z0 - 0.004 * D)
        bm = vtkPolyDataMapper()
        bm.SetInputConnection(big.GetOutputPort())
        ba = vtkActor()
        ba.SetMapper(bm)
        bp = ba.GetProperty()
        bp.SetInterpolationToPBR()
        bp.SetMetallic(0)
        bp.SetRoughness(0.6)
        bp.SetColor(*lin(fedge))
        ren.AddActor(ba)

    ren.UseImageBasedLightingOn()
    ren.SetEnvironmentTexture(env_texture(bright), False)
    ren.SetEnvironmentUp(0, 0, 1)
    ren.SetEnvironmentRight(1, 0, 0)
    ren.SetBackground(*top)
    ren.SetBackground2(*bottom)
    ren.GradientBackgroundOn()
    try:
        ren.UseSphericalHarmonicsOn()
    except Exception:
        pass
    ren.AutomaticLightCreationOff()
    key = vtkLight()
    key.SetLightTypeToSceneLight()
    key.SetPositional(True)
    key.SetConeAngle(40)
    key.SetPosition(cx - 1.0 * D, cy - 1.5 * D, z0 + 2.3 * D)
    key.SetFocalPoint(cx, cy, z0 + 0.1 * D)
    key.SetIntensity(1.6)
    key.SetColor(1.0, 0.97, 0.92)
    ren.AddLight(key)
    fill = vtkLight()
    fill.SetLightTypeToSceneLight()
    fill.SetPositional(True)
    fill.SetConeAngle(60)
    fill.SetPosition(cx + 1.5 * D, cy - 0.5 * D, z0 + 0.8 * D)
    fill.SetFocalPoint(cx, cy, z0 + 0.2 * D)
    fill.SetIntensity(0.35)
    fill.SetColor(0.8, 0.88, 1.0)
    ren.AddLight(fill)

    shadows = vtkShadowMapPass()
    opaque = vtkSequencePass()
    op = vtkRenderPassCollection()
    op.AddItem(vtkLightsPass())
    op.AddItem(vtkOpaquePass())
    opaque.SetPasses(op)
    shadows.SetOpaqueSequence(opaque)
    shadows.GetShadowMapBakerPass().SetOpaqueSequence(opaque)
    seq = vtkSequencePass()
    passes = vtkRenderPassCollection()
    passes.AddItem(shadows.GetShadowMapBakerPass())
    passes.AddItem(shadows)
    passes.AddItem(vtkTranslucentPass())        # see-through parts (peeling miscolours under SSAO)
    passes.AddItem(vtkOverlayPass())
    seq.SetPasses(passes)
    cam_pass = vtkCameraPass()
    cam_pass.SetDelegatePass(seq)
    try:
        shadows.GetShadowMapBakerPass().SetResolution(4096)
    except Exception:
        pass
    ssao = vtkSSAOPass()
    ssao.SetDelegatePass(cam_pass)
    ssao.SetRadius(0.02 * D)
    ssao.SetBias(0.0003 * D)
    ssao.SetKernelSize(128)
    ssao.BlurOn()
    tone = vtkToneMappingPass()
    tone.SetDelegatePass(ssao)
    tone.SetToneMappingType(vtkToneMappingPass.GenericFilmic)
    tone.SetGenericFilmicDefaultPresets()
    tone.SetExposure(float(st.get("exposure", 1.2)))
    ren.SetPass(tone)

    win.SetSize(RW, RH)
    cam = ren.GetActiveCamera()
    n = len(frames)
    for i, fr in enumerate(frames):
        if i:
            place(fr)
        c = fr["camera"]
        pos, tgt = c["pos"], c["target"]
        cam.SetPosition(*pos)
        cam.SetFocalPoint(*tgt)
        cam.SetViewUp(*c.get("up", (0, 0, 1)))
        if c.get("projection") == "Orthographic":
            cam.ParallelProjectionOn()
            cam.SetParallelScale(float(c.get("height", D)) / 2)
        else:
            cam.ParallelProjectionOff()
            cam.SetViewAngle(float(c.get("fov", 30)))
        dist = math.dist(pos, tgt)
        cam.SetClippingRange(max(0.001 * D, dist - 4 * D) if c.get("projection") == "Orthographic"
                             else max(0.01 * D, 0.02 * dist), dist + 6 * D)
        win.Render()
        w2i = vtkWindowToImageFilter()
        w2i.SetInput(win)
        w2i.SetInputBufferTypeToRGB()
        w2i.ReadFrontBufferOff()
        w2i.Update()
        img = w2i.GetOutput()
        dims = img.GetDimensions()
        arr = vtk_to_numpy(img.GetPointData().GetScalars()).reshape(dims[1], dims[0], 3)[::-1]
        if st.get("backdrop") == "White":
            # tone mapping greys white: lift the levels so the backdrop is
            # white again (the model brightens by the same small factor)
            ref = arr[: max(2, arr.shape[0] // 40), : max(2, arr.shape[1] // 40)].reshape(-1, 3).mean(0)
            k = 255.0 / max(1.0, float(ref.mean()))
            arr = np.clip(arr.astype(np.float32) * k, 0, 255).astype(np.uint8)
        out = Image.fromarray(np.ascontiguousarray(arr))
        if (RW, RH) != (W, H):
            out = out.resize((W, H), Image.LANCZOS)
        out.save(fr["out"])
        print(f"FRAME {i + 1} {n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
