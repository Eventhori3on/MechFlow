"""Pipe from Scan - measuring pipework in a 3D scan.

Pure numpy / scipy (no FreeCAD needed), so it can be tested on its own:

    cloud = load_cloud("scan.obj")             # mesh or point cloud -> points + normals
    res = trace(cloud, click_point)            # follows the pipe from flange to flange
    res["path"], res["ends"], res["runs"], res["od"] ...

How it works
  * The scan is turned into surface points with normals (face normals of a
    mesh, averaged on a grid; or estimated from neighbours for a point cloud).
  * At the picked point a cylinder is fitted (RANSAC from pairs of points
    and their normals). That gives the pipe's axis and outside diameter.
  * From there it walks along the axis in both directions, re-centring on
    the pipe wall at every step, until the wall stops being a straight
    cylinder.
  * Where the wall stops it looks for what comes next: a ring of surface
    facing back along the pipe is a flange (or a bulkhead / plate if it
    carries on wide), another cylinder of the same size whose axis meets
    this one is the leg after an elbow, a cylinder in line but a different
    size is after a reducer. Nothing at all is an open end.
  * The corners are where the axes meet; the whole line is then solved
    together (least squares), optionally squared to X / Y / Z.
"""
import math
import os
import re

import numpy as np

# ------------------------------------------------------------------ loading

_FLOAT = rb"([-+0-9.eE]+)"


def _chunks(path, size=64 << 20):
    """The file in big pieces that end on a line break."""
    with open(path, "rb") as fh:
        rest = b""
        while True:
            block = fh.read(size)
            if not block:
                if rest:
                    yield rest
                return
            block = rest + block
            cut = block.rfind(b"\n")
            if cut < 0:
                rest = block
                continue
            rest = block[cut + 1:]
            yield block[:cut + 1]


def read_obj(path, progress=None):
    """Vertices (n,3) and triangles (m,3) of a Wavefront OBJ."""
    vre = re.compile(rb"(?m)^v[ \t]+" + _FLOAT + rb"[ \t]+" + _FLOAT + rb"[ \t]+" + _FLOAT)
    fre = re.compile(rb"(?m)^f[ \t]+(-?\d+)\S*[ \t]+(-?\d+)\S*[ \t]+(-?\d+)\S*(?:[ \t]+(-?\d+)\S*)?")
    vs, fs = [], []
    total = max(1, os.path.getsize(path))
    done = 0
    nv = 0
    for block in _chunks(path):
        done += len(block)
        v = vre.findall(block)
        if v:
            v = np.array(v).astype(np.float64)
            vs.append(v)
        f = fre.findall(block)
        if f:
            a = np.array(f)
            tri = a[:, :3].astype(np.int64)
            quad = a[:, 3] != b""
            if quad.any():
                d = a[quad, 3].astype(np.int64)
                tri = np.vstack([tri, np.c_[tri[quad, 0], tri[quad, 2], d]])
            neg = tri < 0
            if neg.any():
                tri[neg] += nv + (len(v) if len(v) else 0) + 1
            fs.append(tri - 1)
        nv += len(v) if len(v) else 0
        if progress:
            progress(done / total)
    V = np.vstack(vs) if vs else np.zeros((0, 3))
    F = np.vstack(fs).astype(np.int64) if fs else None
    return V, F


def read_stl(path):
    """Triangle soup (m,3,3) of a binary or text STL."""
    with open(path, "rb") as fh:
        head = fh.read(84)
    n = int.from_bytes(head[80:84], "little") if len(head) >= 84 else 0
    if n and os.path.getsize(path) == 84 + 50 * n:
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        return np.fromfile(path, dtype=dt, offset=84)["v"].astype(np.float64)
    vre = re.compile(rb"vertex[ \t]+" + _FLOAT + rb"[ \t]+" + _FLOAT + rb"[ \t]+" + _FLOAT)
    vs = [np.array(vre.findall(b)).astype(np.float64) for b in _chunks(path)]
    vs = [v for v in vs if len(v)]
    v = np.vstack(vs) if vs else np.zeros((0, 3))
    return v[: len(v) // 3 * 3].reshape(-1, 3, 3)


_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2",
              "int16": "i2", "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4",
              "uint": "u4", "uint32": "u4", "float": "f4", "float32": "f4", "double": "f8",
              "float64": "f8"}


def read_ply(path):
    """Vertices, triangles (or None) and normals (or None) of a PLY."""
    with open(path, "rb") as fh:
        header = []
        while True:
            line = fh.readline()
            if not line:
                raise ValueError("not a PLY file")
            line = line.decode("ascii", "replace").strip()
            header.append(line)
            if line == "end_header":
                break
        start = fh.tell()
    fmt = [h.split()[1] for h in header if h.startswith("format")][0]
    elems = []
    for h in header:
        p = h.split()
        if p[0] == "element":
            elems.append([p[1], int(p[2]), []])
        elif p[0] == "property" and elems:
            elems[-1][2].append(p[1:])
    end = "<" if fmt == "binary_little_endian" else ">"
    V = F = Nn = None
    if fmt == "ascii":
        with open(path, "rb") as fh:
            fh.seek(start)
            rows = fh.read().split(b"\n")
        at = 0
        for name, count, props in elems:
            block = rows[at:at + count]
            at += count
            if name == "vertex":
                names = [p[-1] for p in props]
                arr = np.array([r.split()[:len(names)] for r in block]).astype(np.float64)
                V = arr[:, [names.index(c) for c in "xyz"]]
                if all(c in names for c in ("nx", "ny", "nz")):
                    Nn = arr[:, [names.index(c) for c in ("nx", "ny", "nz")]]
            elif name == "face":
                tris = []
                for r in block:
                    q = [int(x) for x in r.split()]
                    k = q[0]
                    for j in range(1, k - 1):
                        tris.append((q[1], q[1 + j], q[2 + j]))
                F = np.array(tris, dtype=np.int64)
        return V, F, Nn
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read()
    off = 0
    for name, count, props in elems:
        if any(p[0] == "list" for p in props):
            if name != "face" or len(props) != 1:
                raise ValueError("PLY with a list property this reader can't follow")
            _l, ct, it, _nm = props[0]
            ct, it = np.dtype(end + _PLY_TYPES[ct]), np.dtype(end + _PLY_TYPES[it])
            # fast path: every face a triangle
            rec = np.dtype([("n", ct), ("i", it, 3)])
            arr = np.frombuffer(data, dtype=rec, count=count, offset=off)
            if (arr["n"] == 3).all():
                F = arr["i"].astype(np.int64)
                off += rec.itemsize * count
            else:                        # mixed polygons: walk them
                tris = []
                for _ in range(count):
                    k = int(np.frombuffer(data, ct, 1, off)[0])
                    off += ct.itemsize
                    q = np.frombuffer(data, it, k, off).astype(np.int64)
                    off += it.itemsize * k
                    for j in range(1, k - 1):
                        tris.append((q[0], q[j], q[j + 1]))
                F = np.array(tris, dtype=np.int64)
            continue
        dt = np.dtype([(p[1], end + _PLY_TYPES[p[0]]) for p in props])
        arr = np.frombuffer(data, dtype=dt, count=count, offset=off)
        off += dt.itemsize * count
        if name == "vertex":
            V = np.c_[arr["x"], arr["y"], arr["z"]].astype(np.float64)
            if all(c in dt.names for c in ("nx", "ny", "nz")):
                Nn = np.c_[arr["nx"], arr["ny"], arr["nz"]].astype(np.float64)
    return V, F, Nn


def read_xyz(path):
    """Point cloud as text: x y z [nx ny nz] per line (.xyz .asc .txt .pts .csv)."""
    rows = []
    for b in _chunks(path):
        b = b.replace(b",", b" ").replace(b";", b" ")
        for line in b.split(b"\n"):
            p = line.split()
            if len(p) >= 3:
                try:
                    rows.append([float(x) for x in p[:6]] if len(p) >= 6 else
                                [float(x) for x in p[:3]])
                except ValueError:
                    continue
    w = max((len(r) for r in rows), default=3)
    arr = np.array([r + [0.0] * (w - len(r)) for r in rows]) if rows else np.zeros((0, 3))
    if w >= 6 and np.abs(arr[:, 3:6]).sum() > 0 and \
            np.allclose(np.linalg.norm(arr[:, 3:6], axis=1)[:100], 1.0, atol=0.05):
        return arr[:, :3], arr[:, 3:6]
    return arr[:, :3], None


MESH_TYPES = (".obj", ".stl", ".ply")
CLOUD_TYPES = (".xyz", ".asc", ".txt", ".pts", ".csv")


def read_any(path, progress=None):
    """(vertices, triangles or None, normals or None, soup or None)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        V, F = read_obj(path, progress)
        return V, F, None, None
    if ext == ".stl":
        return None, None, None, read_stl(path)
    if ext == ".ply":
        V, F, Nn = read_ply(path)
        return V, F, Nn, None
    V, Nn = read_xyz(path)
    return V, None, Nn, None


# ------------------------------------------------------------ points + normals

def _keys(q):
    """One int64 per grid cell."""
    q = q - q.min(0)
    return (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]


def surface_points(V=None, F=None, soup=None, cell=None, target=2.5e6):
    """Surface points and unit normals from a mesh, averaged on a grid of
    `cell` mm (chosen from the surface area when not given)."""
    if soup is not None:
        a, b, c = soup[:, 0], soup[:, 1], soup[:, 2]
    else:
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    fn = np.cross(b - a, c - a)                      # 2 x area, along the normal
    area2 = np.linalg.norm(fn, axis=1)
    ok = area2 > 1e-12
    cen = (a + b + c)[ok] / 3.0
    fn, area2 = fn[ok], area2[ok]
    del a, b, c
    total = float(area2.sum()) / 2
    if cell is None:
        cell = float(np.clip(math.sqrt(total / target), 1.5, 12.0))
    # big triangles (a CAD export: long thin ones down a pipe) get points all
    # over them, not just the one in the middle
    big = area2 / 2 > 1.5 * cell * cell
    if big.any():
        if soup is not None:
            A, B, Cc = soup[:, 0][ok][big], soup[:, 1][ok][big], soup[:, 2][ok][big]
        else:
            Fb = F[ok][big]
            A, B, Cc = V[Fb[:, 0]], V[Fb[:, 1]], V[Fb[:, 2]]
        k = np.minimum(np.ceil(area2[big] / 2 / (cell * cell)).astype(np.int64), 200000)
        rep = np.repeat(np.arange(len(k)), k)
        rng = np.random.default_rng(5)
        r1 = np.sqrt(rng.random(len(rep)))
        r2 = rng.random(len(rep))
        S = (A[rep] * (1 - r1)[:, None] + B[rep] * (r1 * (1 - r2))[:, None] +
             Cc[rep] * (r1 * r2)[:, None])
        wts = (area2[big] / k)[rep]
        fnb = (fn[big] / k[:, None])[rep]
        cen = np.vstack([cen[~big], S])
        fn = np.vstack([fn[~big], fnb])
        area2 = np.concatenate([area2[~big], wts])
    q = np.floor(cen / cell).astype(np.int64)
    k = _keys(q)
    uk, inv = np.unique(k, return_inverse=True)
    w = np.bincount(inv, weights=area2, minlength=len(uk))
    P = np.c_[[np.bincount(inv, weights=cen[:, j] * area2, minlength=len(uk)) for j in range(3)]].T
    P /= w[:, None]
    N = np.c_[[np.bincount(inv, weights=fn[:, j], minlength=len(uk)) for j in range(3)]].T
    nl = np.linalg.norm(N, axis=1)
    good = nl > 0.3 * w                              # the faces in the cell roughly agree
    P, N = P[good], N[good] / nl[good, None]
    return P, N.astype(np.float32), cell, total


def cloud_points(V, Nn=None, cell=None, target=2.5e6, k=16):
    """Points and normals from a point cloud (normals estimated from the
    nearest neighbours when the file has none)."""
    from scipy.spatial import cKDTree
    lo, hi = V.min(0), V.max(0)
    if cell is None:
        # rough surface estimate: points per cell^2
        cell = 1.5
        while True:
            q = np.floor(V / cell).astype(np.int64)
            n = len(np.unique(_keys(q)))
            if n <= target or cell > 12:
                break
            cell *= 1.4
    q = np.floor(V / cell).astype(np.int64)
    uk, idx, inv = np.unique(_keys(q), return_index=True, return_inverse=True)
    cnt = np.bincount(inv, minlength=len(uk)).astype(float)
    P = np.c_[[np.bincount(inv, weights=V[:, j], minlength=len(uk)) for j in range(3)]].T / cnt[:, None]
    if Nn is not None:
        N = np.c_[[np.bincount(inv, weights=Nn[:, j], minlength=len(uk)) for j in range(3)]].T
        nl = np.linalg.norm(N, axis=1)
        good = nl > 1e-9
        return P[good], (N[good] / nl[good, None]).astype(np.float32), cell, None
    tree = cKDTree(P)
    N = np.zeros_like(P)
    for s in range(0, len(P), 200000):
        _d, nb = tree.query(P[s:s + 200000], k=min(k, len(P)))
        Q = P[nb] - P[nb].mean(1, keepdims=True)
        C = np.einsum("nki,nkj->nij", Q, Q)
        _w, vec = np.linalg.eigh(C)
        N[s:s + 200000] = vec[:, :, 0]
    return P, N.astype(np.float32), cell, None


class Cloud:
    """Surface points + unit normals + a search tree."""

    def __init__(self, P, N, cell=0.0, area=None, source=""):
        from scipy.spatial import cKDTree
        self.P = np.ascontiguousarray(P, dtype=np.float64)
        self.N = np.ascontiguousarray(N, dtype=np.float32)
        self.cell = float(cell)
        self.area = area
        self.source = source
        self.tree = cKDTree(self.P, leafsize=24, balanced_tree=False, compact_nodes=False)
        self.rng = np.random.default_rng(7)

    def __len__(self):
        return len(self.P)

    def near(self, c, rad, cap=30000):
        idx = self.tree.query_ball_point(np.asarray(c, float), rad, return_sorted=False)
        idx = np.asarray(idx, dtype=np.int64)
        if len(idx) > cap:
            idx = self.rng.choice(idx, cap, replace=False)
        return idx

    def nearest(self, c):
        d, i = self.tree.query(np.asarray(c, float))
        return int(i), float(d)

    def save(self, path):
        np.savez(path, P=self.P.astype(np.float32), N=self.N, cell=self.cell,
                 area=-1.0 if self.area is None else self.area, source=self.source)

    @staticmethod
    def open(path):
        z = np.load(path)
        area = float(z["area"])
        return Cloud(z["P"].astype(np.float64), z["N"], float(z["cell"]),
                     None if area < 0 else area, str(z["source"]))


def cloud_from_mesh(V=None, F=None, soup=None, Nn=None, cell=None, source=""):
    if soup is not None or F is not None:
        P, N, cell, area = surface_points(V, F, soup, cell)
    else:
        P, N, cell, area = cloud_points(V, Nn, cell)
    return Cloud(P, N, cell, area, source)


def cache_path(path, cache_dir):
    st = os.stat(path)
    key = f"{os.path.basename(path)}-{st.st_size}-{int(st.st_mtime)}"
    key = re.sub(r"[^A-Za-z0-9._-]", "_", key)
    return os.path.join(cache_dir, key + ".npz")


def load_cloud(path, cache_dir=None, progress=None):
    """A Cloud for a scan file, cached as .npz (the second time is quick)."""
    cp = cache_path(path, cache_dir) if cache_dir else None
    if cp and os.path.exists(cp):
        try:
            return Cloud.open(cp)
        except Exception:
            pass
    V, F, Nn, soup = read_any(path, progress)
    cl = cloud_from_mesh(V, F, soup, Nn, source=path)
    if cp:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            cl.save(cp)
        except OSError:
            pass
    return cl


class Scan:
    """A scan held in memory: the mesh (or points), a coarse Cloud of the
    whole thing for finding pipes, and fine Clouds made on demand along a
    pipe for measuring it closely."""

    def __init__(self, V=None, F=None, soup=None, Nn=None, source=""):
        if soup is not None:
            V = soup.reshape(-1, 3)
            F = np.arange(len(V), dtype=np.int64).reshape(-1, 3)
        self.V = np.ascontiguousarray(V, dtype=np.float32)
        self.F = None if F is None else np.ascontiguousarray(F, dtype=np.int32)
        self.Nn = None if Nn is None else np.ascontiguousarray(Nn, dtype=np.float32)
        self.source = source
        self._cloud = None
        self._cen = None

    @property
    def is_mesh(self):
        return self.F is not None

    def cloud(self):
        if self._cloud is None:
            V = self.V.astype(np.float64)
            if self.is_mesh:
                self._cloud = cloud_from_mesh(V, self.F, source=self.source)
            else:
                self._cloud = cloud_from_mesh(V, None, None,
                                              None if self.Nn is None else self.Nn.astype(float),
                                              source=self.source)
        return self._cloud

    def _centres(self):
        if self._cen is None:
            if self.is_mesh:
                F = self.F
                self._cen = (self.V[F[:, 0]] + self.V[F[:, 1]] + self.V[F[:, 2]]) / np.float32(3)
            else:
                self._cen = self.V
        return self._cen

    def corridor(self, pts, radius, cell):
        """A fine Cloud of the scan within radius of the polyline pts."""
        C = self._centres()
        pts = np.asarray(pts, float)
        lo = pts.min(0) - radius
        hi = pts.max(0) + radius
        box = np.nonzero(np.all((C >= lo) & (C <= hi), axis=1))[0]
        Cb = C[box].astype(np.float64)
        keep = np.zeros(len(box), bool)
        for a, b in zip(pts[:-1], pts[1:]):
            d = b - a
            L2 = float(d @ d)
            t = np.clip(((Cb - a) @ d) / L2, 0, 1) if L2 > 0 else np.zeros(len(Cb))
            e = Cb - (a + np.outer(t, d))
            keep |= np.einsum("ij,ij->i", e, e) < radius * radius
        sel = box[keep]
        if len(sel) < 50:
            return None
        if self.is_mesh:
            F = self.F[sel]
            P, N, c, area = surface_points(self.V.astype(np.float64), F, cell=cell)
        else:
            Nn = None if self.Nn is None else self.Nn[sel].astype(float)
            P, N, c, area = cloud_points(self.V[sel].astype(np.float64), Nn, cell=cell)
        if len(P) < 50:
            return None
        return Cloud(P, N, c, area, self.source)

    def save(self, path):
        np.savez(path, V=self.V, F=self.F if self.F is not None else np.zeros((0, 3), np.int32),
                 Nn=self.Nn if self.Nn is not None else np.zeros((0, 3), np.float32),
                 source=self.source)

    @staticmethod
    def open(path):
        z = np.load(path)
        F = z["F"] if len(z["F"]) else None
        Nn = z["Nn"] if len(z["Nn"]) else None
        return Scan(z["V"], F, None, Nn, str(z["source"]))


def load_scan(path, cache_dir=None, progress=None):
    """A Scan for a file (OBJ/STL/PLY/XYZ...), cached (the second time is quick)."""
    cp = cache_path(path, cache_dir).replace(".npz", ".scan.npz") if cache_dir else None
    if cp and os.path.exists(cp):
        try:
            return Scan.open(cp)
        except Exception:
            pass
    V, F, Nn, soup = read_any(path, progress)
    if soup is not None:
        # STL: join the corners that coincide (a mesh, not a soup)
        flat = soup.reshape(-1, 3).astype(np.float32)
        _u, first, inv = np.unique(flat, axis=0, return_index=True, return_inverse=True)
        V = flat[first]
        F = inv.reshape(-1, 3)
    sc = Scan(V, F, None, Nn, path)
    if cp:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            sc.save(cp)
        except OSError:
            pass
    return sc


# -------------------------------------------------------- display mesh

def light_mesh(V=None, F=None, soup=None, cell=None, faces=1.5e6):
    """A lighter copy of a mesh for the screen (vertex clustering):
    returns (vertices, triangles)."""
    if soup is not None:
        V = soup.reshape(-1, 3)
        F = np.arange(len(V)).reshape(-1, 3)
    if cell is None:
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()) / 2
        if len(F) <= faces:
            if soup is None:
                return V, F
            cell = 1e-3
        else:
            cell = math.sqrt(2 * area / faces)
    q = np.floor(V / cell).astype(np.int64)
    uk, inv = np.unique(_keys(q), return_inverse=True)
    cnt = np.bincount(inv, minlength=len(uk)).astype(float)
    NV = np.c_[[np.bincount(inv, weights=V[:, j], minlength=len(uk)) for j in range(3)]].T / cnt[:, None]
    NF = inv[F]
    keep = (NF[:, 0] != NF[:, 1]) & (NF[:, 1] != NF[:, 2]) & (NF[:, 0] != NF[:, 2])
    NF = NF[keep]
    s = np.sort(NF, axis=1)
    _u, first = np.unique(_keys(s) if len(uk) < (1 << 21) else
                          s[:, 0] * len(uk) * len(uk) + s[:, 1] * len(uk) + s[:, 2],
                          return_index=True)
    return NV, NF[np.sort(first)]


def write_stl(path, V, F):
    """Binary STL (quick to write, quick for FreeCAD to read)."""
    tri = V[F].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-20
    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    arr = np.zeros(len(F), dtype=dt)
    arr["n"], arr["v"] = n, tri
    with open(path, "wb") as fh:
        fh.write(b"MechFlow scan".ljust(80, b" "))
        fh.write(np.uint32(len(F)).tobytes())
        arr.tofile(fh)


# ------------------------------------------------------------------ geometry

def _unit(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-300)


def _frame(a):
    h = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(np.cross(a, h))
    return u, np.cross(a, u)


def _circle(x, y):
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    s = np.linalg.lstsq(A, x * x + y * y, rcond=None)[0]
    return s[0], s[1], math.sqrt(max(s[2] + s[0] ** 2 + s[1] ** 2, 0.0))


def _coverage(radial, u, w, bins=24):
    ang = np.arctan2(radial @ w, radial @ u)
    return len(np.unique(np.floor((ang + np.pi) / (2 * np.pi) * bins))) / bins


def closest_points(p1, d1, p2, d2):
    """Closest points of two lines and their distance."""
    w0 = p1 - p2
    a, b, c = d1 @ d1, d1 @ d2, d2 @ d2
    d, e = d1 @ w0, d2 @ w0
    den = a * c - b * b
    if abs(den) < 1e-12:
        s, t = 0.0, e / c
    else:
        s, t = (b * e - c * d) / den, (a * e - b * d) / den
    q1, q2 = p1 + d1 * s, p2 + d2 * t
    return q1, q2, float(np.linalg.norm(q1 - q2)), s, t


class Cyl:
    def __init__(self, c, a, r):
        self.c, self.a, self.r = np.asarray(c, float), _unit(a), float(r)

    def __repr__(self):
        return f"Cyl(D={2 * self.r:.1f}, c={np.round(self.c, 1)}, a={np.round(self.a, 3)})"


def _tol(r, cell):
    """How far off the nominal radius a point on the wall may be (scan
    noise, ovality, the grid the points were averaged on)."""
    return max(2.0, 0.02 * r, 0.7 * cell)


def _round_enough(tol):
    """Largest median distance off the fitted circle for a real pipe wall
    (a scanned pipe is round to a fraction of a mm; flat surfaces that
    happen to touch a circle are not)."""
    return max(1.2, 0.35 * tol)


def _wall(cl, idx, c, a, r, tol, nmax=0.3, ralign=0.75):
    """Which of idx lie on the wall of the cylinder (c, a, r)."""
    d = cl.P[idx] - c
    t = d @ a
    radial = d - np.outer(t, a)
    dist = np.linalg.norm(radial, axis=1)
    n = cl.N[idx].astype(float)
    rn = radial / (dist[:, None] + 1e-9)
    ok = (np.abs(dist - r) < tol) & (np.abs(n @ a) < nmax) & (np.abs(np.sum(n * rn, 1)) > ralign)
    return ok, t, radial, dist


def _refine(cl, ids, a_hint=None):
    """Axis from the normals (they are all square to it), then the centre
    and radius from a circle fit across it."""
    n = cl.N[ids].astype(float)
    _w, vec = np.linalg.eigh(n.T @ n)
    a = vec[:, 0]
    if a_hint is not None and a @ a_hint < 0:
        a = -a
    u, w = _frame(a)
    q = cl.P[ids]
    cx, cy, r = _circle(q @ u, q @ w)
    c = u * cx + w * cy + a * float(np.mean(q @ a))
    return Cyl(c, a, r)


def _hypothesis(cl, i, j):
    """Cylinder through points i and j from their normals, or None."""
    ni, nj = cl.N[i].astype(float), cl.N[j].astype(float)
    a = np.cross(ni, nj)
    L = np.linalg.norm(a)
    if L < 0.25:
        return None
    a /= L
    u, w = _frame(a)
    pi = np.array([cl.P[i] @ u, cl.P[i] @ w])
    pj = np.array([cl.P[j] @ u, cl.P[j] @ w])
    mi = np.array([ni @ u, ni @ w])
    mj = np.array([nj @ u, nj @ w])
    if np.linalg.norm(mi) < 0.9 or np.linalg.norm(mj) < 0.9:
        return None
    M = np.c_[mi, -mj]
    if abs(np.linalg.det(M)) < 1e-3:
        return None
    s = np.linalg.solve(M, pj - pi)
    c2 = pi + s[0] * mi
    ri, rj = np.linalg.norm(pi - c2), np.linalg.norm(pj - c2)
    if abs(ri - rj) > 0.06 * max(ri, rj):
        return None
    c = u * c2[0] + w * c2[1] + a * float(cl.P[i] @ a)
    return Cyl(c, a, (ri + rj) / 2)


def seed_fit(cl, q, rmin=6.0, rmax=700.0, iters=500):
    """The pipe through (or next to) the picked point q."""
    q = np.asarray(q, float)
    i0, d0 = cl.nearest(q)
    if d0 > 60:
        raise ValueError("there is no scan surface where you clicked")
    q = cl.P[i0]
    best = None
    for R in (250.0, 600.0, 1400.0):
        near_q = cl.near(q, max(3 * cl.cell, 12.0), cap=400)
        ball = cl.near(q, R, cap=25000)
        if len(ball) < 30:
            continue
        rng = cl.rng
        for _ in range(iters):
            i = near_q[rng.integers(len(near_q))]
            j = ball[rng.integers(len(ball))]
            h = _hypothesis(cl, i, j)
            if h is None or not (rmin < h.r < min(rmax, R)):
                continue
            tol = _tol(h.r, cl.cell)
            ok, t, radial, _d = _wall(cl, ball, h.c, h.a, h.r, tol)
            n = int(ok.sum())
            if n < 30:
                continue
            u, w = _frame(h.a)
            cov = _coverage(radial[ok], u, w)
            score = n * cov * cov
            if best is None or score > best[0]:
                best = (score, h, ball[ok])
        if best is not None and best[1].r < 0.4 * R:
            break
    if best is None:
        raise ValueError("no pipe found where you clicked - click on the pipe wall")
    _s, h, ids = best
    for _ in range(4):
        h = _refine(cl, ids, h.a)
        ball = cl.near(q, max(600.0, 4 * h.r), cap=40000)
        ok, t, _rad, _d = _wall(cl, ball, h.c, h.a, h.r, _tol(h.r, cl.cell))
        # keep the piece around the click (contiguous along the axis)
        tq = (q - h.c) @ h.a
        tt = t[ok]
        keep = np.abs(tt - tq) < max(6 * h.r, 300)
        ids = ball[ok][keep]
        if len(ids) < 30:
            break
    u, w = _frame(h.a)
    qq = cl.P[ids]
    tq = (q - h.c) @ h.a
    local = np.abs((qq - h.c) @ h.a - tq) < max(1.0 * h.r, 40.0)
    if local.sum() >= 15:
        qq = qq[local]
    cx, cy, rr = _circle(qq @ u, qq @ w)
    res = float(np.median(np.abs(np.hypot(qq @ u - cx, qq @ w - cy) - rr)))
    if res > 3 * _round_enough(_tol(h.r, cl.cell)):
        raise ValueError("no round pipe found where you clicked - click on the pipe wall")
    tq = (q - h.c) @ h.a
    return Cyl(h.c + h.a * tq, h.a, h.r)


DEBUG = []
FACE_DEBUG = False

# ------------------------------------------------------------------ following

def follow_tube(cl, c, a, r, max_len=80000.0, max_turn_step=12.0):
    """Walk along a pipe from centre c in direction a, through straights
    and bends alike: at each step the local axis comes from the wall's
    normals (they are all square to it, straight or bent) and the centre
    from a circle fit across it. Stops at a ring facing back along the pipe
    ('face': a flange or a plate) or where the wall gives out ('lost').
    Returns {'samples': [(centre, dir, radius)], 'stop', 'face_t'}."""
    c = np.asarray(c, float).copy()
    a = _unit(a)
    tol = _tol(r, cl.cell)
    step = float(np.clip(0.3 * r, max(5.0, 1.5 * cl.cell), 60.0))
    h = max(0.45 * r, 1.2 * step, 2.5 * cl.cell)
    samples = []
    misses = 0
    walked = 0.0
    cp = c.copy()
    while walked < max_len:
        idx = cl.near(cp, math.hypot(h, 3.2 * r), cap=16000)
        if len(idx) < 8:
            misses += 1
            if misses >= 3:
                return {"samples": samples, "stop": "lost", "face_t": None}
            cp = cp + a * step
            walked += step
            continue
        d = cl.P[idx] - cp
        tt = d @ a
        radial = d - np.outer(tt, a)
        dist = np.linalg.norm(radial, axis=1)
        n = cl.N[idx].astype(float)
        na = np.abs(n @ a)
        u, w = _frame(a)
        slab = np.abs(tt) < h
        ahead = (tt > -0.2 * h) & (tt < h)
        fm = ahead & (na > 0.9) & (dist > r + 2 * tol) & (dist < 3.2 * r)
        if fm.sum() >= 12 and _coverage(radial[fm], u, w) >= 0.45:
            return {"samples": samples, "stop": "face",
                    "face_t": float(np.median(tt[fm])), "face_from": (cp, a)}
        wm = slab & (np.abs(dist - r) < 3 * tol) & (na < 0.55)
        ok = False
        if wm.sum() >= 10 and _coverage(radial[wm], u, w) >= 0.2:
            nn = n[wm]
            _ev, vec = np.linalg.eigh(nn.T @ nn)
            an = vec[:, 0] if vec[:, 0] @ a > 0 else -vec[:, 0]
            turn = math.degrees(math.acos(min(1.0, float(an @ a))))
            if turn > max_turn_step:
                k = max_turn_step / turn
                an = _unit(a + (an - a) * k)
            an = _unit(a + an)                          # damped
            u2, w2 = _frame(an)
            d2 = cl.P[idx] - cp
            t2 = d2 @ an
            rad2 = d2 - np.outer(t2, an)
            dist2 = np.linalg.norm(rad2, axis=1)
            rn = rad2 / (dist2[:, None] + 1e-9)
            thin = max(0.15 * r, 2.0 * cl.cell, 6.0)     # thin: round even in a bend
            m2 = (np.abs(t2) < thin) & (np.abs(dist2 - r) < 2.5 * tol) & \
                (np.abs(n @ an) < 0.35) & (np.abs(np.sum(n * rn, 1)) > 0.75)
            if m2.sum() >= 10 and _coverage(rad2[m2], u2, w2) >= 0.2:
                q = cl.P[idx[m2]]
                cx, cy, rr = _circle(q @ u2, q @ w2)
                cn = u2 * cx + w2 * cy + an * float(cp @ an)
                res = float(np.median(np.abs(np.hypot(q @ u2 - cx, q @ w2 - cy) - rr)))
                if abs(rr - r) < 3 * tol and np.linalg.norm(cn - cp) < max(0.3 * r, 3 * tol) \
                        and res < _round_enough(tol):
                    ok = True
                    a = an
                    cp = cn
                    samples.append((cn.copy(), an.copy(), rr))
        if ok:
            misses = 0
        else:
            if DEBUG:
                DEBUG.append((cp.copy(), a.copy(), int(wm.sum()), _coverage(radial[wm], u, w) if wm.any() else 0))
            misses += 1
            if misses >= 2:
                return {"samples": samples, "stop": "lost", "face_t": None}
        cp = cp + a * step
        walked += step
    return {"samples": samples, "stop": "lost", "face_t": None}


def _line_of(points, a_hint, keep=None):
    """Best straight line through the centres, ignoring stray ones (the
    first and last can be partly in an elbow). keep: list to fill with the
    centres used."""
    C = np.asarray(points, float)
    if len(C) < 2:
        return (C.mean(0) if len(C) else np.zeros(3)), _unit(a_hint)
    use = np.ones(len(C), bool)
    for _ in range(3):
        m = C[use].mean(0)
        _s, _v, vt = np.linalg.svd(C[use] - m)
        d = vt[0] if vt[0] @ a_hint > 0 else -vt[0]
        v = C - m
        e = np.linalg.norm(v - np.outer(v @ d, d), axis=1)
        lim = max(3.0, 3.0 * float(np.median(e[use])))
        new = e < lim
        if new.sum() < max(2, len(C) // 2) or (new == use).all():
            break
        use = new
    if keep is not None:
        keep[:] = [c for c, u in zip(points, use) if u]
    return m, _unit(d)


# ------------------------------------------------------------- what's at the end

def classify_face(cl, base, a, r, tf):
    """At a face across the pipe at base + a*tf: a flange (its OD, back
    face) or a plate / bulkhead / equipment face."""
    tol = _tol(r, cl.cell)
    p = base + a * tf
    idx = cl.near(p, 6.5 * r + 60, cap=40000)
    d = cl.P[idx] - p
    tt = d @ a
    radial = d - np.outer(tt, a)
    dist = np.linalg.norm(radial, axis=1)
    n = cl.N[idx].astype(float)
    na = np.abs(n @ a)
    u, w = _frame(a)
    near_plane = np.abs(tt) < max(3 * tol, 6)
    wide = near_plane & (na > 0.9) & (dist > 3.6 * r) & (dist < 6.0 * r)
    if wide.sum() >= 20 and _coverage(radial[wide], u, w) >= 0.5:
        return {"kind": "plate", "t": tf, "axis": _face_axis(cl, idx, p, a, r, tol, 3.5 * r)}
    # the flange itself: a closer look
    idx = cl.near(p + a * (0.6 * r + 20), math.hypot(0.8 * r + 40, 2.7 * r), cap=80000)
    d = cl.P[idx] - p
    tt = d @ a
    radial = d - np.outer(tt, a)
    dist = np.linalg.norm(radial, axis=1)
    n = cl.N[idx].astype(float)
    na = np.abs(n @ a)
    # the flange's rim: radial-facing surface round the pipe a little
    # further on. Its radius is the flange OD, where it starts is the back
    # of the flange. (The back face itself is too broken up by the nuts and
    # by what hides it from the scanner to go by.) The outermost radius that
    # goes most of the way round is the rim - nuts are patchy.
    rn = radial / (dist[:, None] + 1e-9)
    rim = (tt > -2 * tol) & (tt < 1.3 * r + 40) & (na < 0.3) & \
        (np.abs(np.sum(n * rn, 1)) > 0.8) & (dist > 1.25 * r) & (dist < 3.0 * r)
    bw = max(2.0, tol)
    od = None
    sel = None
    if rim.sum() >= 12:
        for rb in np.arange(3.0 * r, 1.25 * r, -bw / 2):
            m = rim & (np.abs(dist - rb) < bw)
            if m.sum() < 12:
                continue
            cov = _coverage(radial[m], u, w, bins=72)
            if FACE_DEBUG and cov > 0.3:
                print("   rim r", round(rb, 1), int(m.sum()), round(cov, 2),
                      np.round(np.percentile(tt[m], [3, 50, 97]), 1))
            if cov >= 0.5:
                # the rim's radius from this band (median), its start/end
                od = 2 * float(np.median(dist[m]))
                sel = m
                break
    out = {"kind": "flange", "t": tf, "od": od, "rim": None}
    if sel is not None:
        t0, t1 = np.percentile(tt[sel], [3, 97])
        out["rim"] = (float(t0), float(t1))
        out["t"] = tf + float(t0)              # the back of the flange
    out["axis"] = _flange_axis(cl, p, a, r)
    return out


def _flange_axis(cl, p, a, r):
    """The axis of a flange whose back is near p (pipe radius r, roughly
    along a): almost every surface of a flanged joint - rim, hub, studs,
    the flats of the nuts - faces square to its axis, so the axis is the
    direction the normals there avoid. The centre then comes from the hub
    (a circle fit across the axis). Returns (centre, axis) or None."""
    a = _unit(a)
    tol = _tol(r, cl.cell)
    idx = cl.near(p + a * 0.2 * r, 2.8 * r, cap=60000)
    if len(idx) < 40:
        return None
    n = cl.N[idx].astype(float)
    ax = a
    for _ in range(3):
        d = cl.P[idx] - p
        tt = d @ ax
        rad = d - np.outer(tt, ax)
        dist = np.linalg.norm(rad, axis=1)
        # only ahead of the face: behind it may be the end of a bend
        m = (tt > 0.05 * r) & (tt < 0.7 * r) & (np.abs(n @ ax) < 0.3) & (dist < 2.6 * r)
        if m.sum() < 40:
            return None
        _ev, vec = np.linalg.eigh(n[m].T @ n[m])
        new = vec[:, 0] if vec[:, 0] @ ax > 0 else -vec[:, 0]
        if math.degrees(math.acos(min(1.0, float(new @ a)))) > 35:
            return None
        ax = _unit(new)
    # better: the rim - a round band of points at one radius. Clutter round
    # a flange (small-bore tubes, brackets) spoils the normals; the band's
    # shape doesn't care: its thin direction is the axis, its circle the
    # centre.
    rim_cen = None
    u, w = _frame(ax)
    for _ in range(3):
        d = cl.P[idx] - (rim_cen if rim_cen is not None else p)
        tt = d @ ax
        rad = d - np.outer(tt, ax)
        dist = np.linalg.norm(rad, axis=1)
        rn = rad / (dist[:, None] + 1e-9)
        m = (tt > -0.1 * r) & (tt < 0.8 * r) & (np.abs(n @ ax) < 0.35) & \
            (np.abs(np.sum(n * rn, 1)) > 0.85) & (dist > 1.25 * r) & (dist < 3.0 * r)
        best = None
        for rb in np.arange(1.25 * r, 3.0 * r, max(tol, 3.0)):
            mm = m & (np.abs(dist - rb) < 1.5 * max(tol, 3.0))
            if mm.sum() >= 30:
                cov = _coverage(rad[mm], u, w, bins=36)
                if best is None or cov > best[0]:
                    best = (cov, mm)
        if best is None or best[0] < 0.35:
            break
        q = cl.P[idx[best[1]]]
        qm = q.mean(0)
        _s, _v, vt = np.linalg.svd(q - qm)
        new = vt[2] if vt[2] @ ax > 0 else -vt[2]
        if math.degrees(math.acos(min(1.0, float(new @ a)))) > 35:
            break
        ax = _unit(new)
        u, w = _frame(ax)
        cx, cy, _rr = _circle(q @ u, q @ w)
        rim_cen = u * cx + w * cy + ax * float(np.median(q @ ax))
    if rim_cen is not None:
        return rim_cen + ax * float((p - rim_cen) @ ax), ax
    # centre: the hub / pipe just behind the flange, across the axis
    d = cl.P[idx] - p
    tt = d @ ax
    rad = d - np.outer(tt, ax)
    dist = np.linalg.norm(rad, axis=1)
    rn = rad / (dist[:, None] + 1e-9)
    m = (np.abs(tt + 0.1 * r) < max(0.25 * r, 3 * cl.cell)) & (dist < 1.35 * r) & \
        (dist > 0.7 * r) & (np.abs(n @ ax) < 0.4) & (np.abs(np.sum(n * rn, 1)) > 0.8)
    u, w = _frame(ax)
    if m.sum() < 12 or _coverage(rad[m], u, w) < 0.3:
        return None
    q = cl.P[idx[m]]
    cx, cy, _rr = _circle(q @ u, q @ w)
    cen = u * cx + w * cy + ax * float(p @ ax)
    return cen, ax


def match_flange(cl, base, a, r, t_from, candidates, log=None):
    """Fit standard flanges to the scan where a pipe (axis base + a*t,
    radius r) meets a flange, the flange starting somewhere past t_from.
    candidates: [(std, size, {'rating','D','C'})]. Returns the best
    {'std','size','rating','D','C','t_back','t_joint','fill'} or None.

    For each candidate and each position along the pipe it counts the scan
    points on the candidate's rim (a cylinder of its OD, as long as it is
    thick) and on its back face, as a fraction of what a fully seen flange
    would give."""
    if not candidates:
        return None
    tol = max(_tol(r, cl.cell), 2.0)
    span = 1.6 * r + 140
    p0 = base + a * (t_from - 40)
    Rmax = max(c[2]["D"] for c in candidates) / 2 + 3 * tol
    idx = cl.near(p0 + a * span / 2, math.hypot(span / 2 + 20, Rmax + 10), cap=200000)
    if len(idx) < 30:
        return None
    d = cl.P[idx] - base
    tt = d @ a
    radial = d - np.outer(tt, a)
    dist = np.linalg.norm(radial, axis=1)
    n = cl.N[idx].astype(float)
    na = np.abs(n @ a)
    rn = radial / (dist[:, None] + 1e-9)
    radial_n = (na < 0.35) & (np.abs(np.sum(n * rn, 1)) > 0.85)
    axial_n = na > 0.9
    # how much surface each point stands for, here (scans are denser in
    # some places than others)
    rho = max(4 * cl.cell, 12.0)
    smp = idx[cl.rng.choice(len(idx), min(200, len(idx)), replace=False)]
    cnt = np.array([len(x) for x in cl.tree.query_ball_point(cl.P[smp], rho)])
    area_pt = math.pi * rho * rho / max(float(np.median(cnt)), 1.0)
    lo = t_from - 40
    hi = t_from + span
    steps = np.arange(lo, hi, 1.0)
    best = None
    for std, size, c in candidates:
        R, C = c["D"] / 2, c["C"]
        if R < r + 4 * tol:
            continue
        band = max(tol, 0.012 * R)
        rim_t = np.sort(tt[radial_n & (np.abs(dist - R) < band)])
        back_t = np.sort(tt[axial_n & (dist > 1.3 * r) & (dist < R - band)])
        rim_full = 2 * math.pi * R * C / area_pt
        back_full = math.pi * (R * R - (1.3 * r) ** 2) / area_pt * (2 * band) / max(cl.cell, 1.0)
        rim_n = np.searchsorted(rim_t, steps + C) - np.searchsorted(rim_t, steps)
        back_n = np.searchsorted(back_t, steps + band) - np.searchsorted(back_t, steps - band)
        rim_f = rim_n / rim_full
        back_f = np.minimum(back_n / max(back_full, 1.0), 1.0)
        # nothing of the flange may sit just outside its rim (a bigger
        # flange there means this one is the wrong size)
        out_t = np.sort(tt[radial_n & (dist > R + 2 * band) & (dist < R + 6 * band)])
        out_n = np.searchsorted(out_t, steps + C) - np.searchsorted(out_t, steps)
        out_f = out_n / rim_full
        score = rim_f + 0.5 * back_f - 1.0 * out_f
        k = int(np.argmax(score))
        # the earliest position that is about as good (a mating flange
        # beyond carries the rim on)
        ok = np.nonzero(score >= score[k] - 0.03)[0]
        k = int(ok[0])
        sc = float(score[k])
        if log:
            log(f"    {std} {size} {c['rating']}: D {c['D']:.0f} score {sc:.2f} "
                f"(rim {rim_f[k]:.2f} back {back_f[k]:.2f} out {out_f[k]:.2f}) at {steps[k]:.0f}")
        if best is None or sc > best["score"]:
            best = {"std": std, "size": size, "rating": c["rating"], "D": c["D"], "C": C,
                    "t_back": float(steps[k]), "t_joint": float(steps[k] + C),
                    "fill": float(rim_f[k]), "score": sc}
    if best is None or best["fill"] < 0.2:
        return None
    return best


def _face_axis(cl, idx, p, a, r, tol, rmax):
    """The axis square to a face ring round the pipe: (centre, normal) or
    None. The normal is the face's own (more trustworthy than a short bit
    of pipe, or the end of a bend); the centre is the middle of the ring."""
    n_all = cl.N[idx].astype(float)
    nf = _unit(a)
    cen = np.asarray(p, float)
    found = None
    for cut in (0.85, 0.95, 0.97):
        d = cl.P[idx] - cen
        tt = d @ nf
        radial = d - np.outer(tt, nf)
        dist = np.linalg.norm(radial, axis=1)
        m = (np.abs(tt) < max(4 * tol, 10)) & (np.abs(n_all @ nf) > cut) & \
            (dist > r + 2 * tol) & (dist < max(rmax, r + 4 * tol))
        if m.sum() < 20 or _coverage(radial[m], *_frame(nf)) < 0.6:
            break
        nn = n_all[m] * np.sign(n_all[m] @ nf)[:, None]
        nf_new = _unit(nn.mean(0))
        if nf_new @ _unit(a) < 0.9:
            break
        q = cl.P[idx[m]]
        u, w = _frame(nf_new)
        # the plane through the ring; centre: where the pipe's axis meets it
        plane_t = float(np.median(q @ nf_new))
        cx, cy, _r = _circle(q @ u, q @ w)
        nf = nf_new
        cen = u * cx + w * cy + nf * plane_t
        found = (cen, nf)
    return found


def find_next(cl, end_pt, a, r, exclude_line=None, max_turn=135.0, elbows=False):
    """The pipe after the end of a straight at end_pt (axis point) going a:
    returns {'kind': 'elbow'|'inline'|'reducer', 'cyl': Cyl, 'corner': pt}
    or None."""
    if not elbows:
        return find_inline(cl, end_pt, a, r)
    tol = _tol(r, cl.cell)
    Q = end_pt + a * 2.5 * r
    R = max(7.5 * r, 160.0)
    idx = cl.near(Q, R, cap=24000)
    if len(idx) < 30:
        return None
    d = cl.P[idx] - end_pt
    tt = d @ a
    radial = d - np.outer(tt, a)
    dist = np.linalg.norm(radial, axis=1)
    n = cl.N[idx].astype(float)
    # not the straight we came along
    mine = (tt < 0.3 * r) & (np.abs(dist - r) < 3 * tol)
    idx = idx[~mine]
    if len(idx) < 30:
        return None
    from scipy.spatial import cKDTree
    sub = cKDTree(cl.P[idx])
    rng = cl.rng
    best = None
    for _ in range(700):
        k = rng.integers(len(idx))
        nb = sub.query_ball_point(cl.P[idx[k]], 2.2 * r)
        if len(nb) < 3:
            continue
        j = idx[nb[rng.integers(len(nb))]]
        h = _hypothesis(cl, idx[k], j)
        if h is None or abs(h.r - r) > 0.12 * r:
            continue
        q1, q2, gap, s, _t = closest_points(end_pt, a, h.c, h.a)
        ang = math.degrees(math.acos(min(1.0, abs(float(h.a @ a)))))
        if ang < 6:
            continue                     # in line: handled below
        if gap > 0.5 * r or s < -1.0 * r or s > 7.0 * r:
            continue
        ok, t2, radial2, _d2 = _wall(cl, idx, h.c, h.a, r, tol)
        if ok.sum() < 20:
            continue
        # it must run away from the corner
        corner = 0.5 * (q1 + q2)
        s2 = (cl.P[idx[ok]] - corner) @ h.a
        if np.median(s2) < 0:
            h.a = -h.a
            s2 = -s2
        away = s2 > 0.5 * r
        sc = int(away.sum())
        if best is None or sc > best[0]:
            best = (sc, h, idx[ok][away])
    if best is not None and best[0] >= 25:
        _sc, h, ids = best
        for _ in range(3):
            h2 = _refine(cl, ids, h.a)
            ok, _t2, _r2, _d2 = _wall(cl, idx, h2.c, h2.a, h2.r, tol)
            q1, q2, gap, s, _t = closest_points(end_pt, a, h2.c, h2.a)
            corner = 0.5 * (q1 + q2)
            s2 = (cl.P[idx[ok]] - corner) @ h2.a
            ids_new = idx[ok][s2 > 0.5 * r]
            if len(ids_new) < 20:
                break
            h, ids = h2, ids_new
        q1, q2, gap, s, _t = closest_points(end_pt, a, h.c, h.a)
        ang = math.degrees(math.acos(min(1.0, float(abs(h.a @ a)))))
        if gap < max(0.25 * r, 3 * tol) and ang <= max_turn and abs(h.r - r) < 0.1 * r:
            corner = 0.5 * (q1 + q2)
            s0 = float(np.min((cl.P[ids] - corner) @ h.a))
            return {"kind": "elbow", "cyl": Cyl(corner + h.a * max(s0, 0.3 * r), h.a, h.r),
                    "corner": corner, "gap": gap, "angle": ang}
    return find_inline(cl, end_pt, a, r)


def find_inline(cl, end_pt, a, r):
    """In line after the wall gives out: the same pipe after a gap (a
    clamp, a shadow in the scan) or a reducer to another size."""
    u, w = _frame(a)
    for s in np.arange(0.5 * r, 6.0 * r, 0.4 * r):
        p = end_pt + a * s
        ids = cl.near(p, 2.0 * r + 20, cap=8000)
        if len(ids) < 10:
            continue
        dd = cl.P[ids] - p
        t3 = dd @ a
        rad3 = dd - np.outer(t3, a)
        dist3 = np.linalg.norm(rad3, axis=1)
        n3 = cl.N[ids].astype(float)
        rn3 = rad3 / (dist3[:, None] + 1e-9)
        m = (np.abs(t3) < 0.3 * r) & (np.abs(n3 @ a) < 0.25) & \
            (np.abs(np.sum(n3 * rn3, 1)) > 0.85) & (dist3 > 0.3 * r) & (dist3 < 1.9 * r)
        if m.sum() < 12 or _coverage(rad3[m], u, w) < 0.3:
            continue
        q = cl.P[ids[m]]
        cx, cy, rr = _circle(q @ u, q @ w)
        cen = u * cx + w * cy + a * (p @ a)
        if np.linalg.norm(cen - p) > 0.25 * r:
            continue
        resid = np.abs(np.linalg.norm(np.c_[q @ u - cx, q @ w - cy], axis=1) - rr)
        if np.median(resid) > 1.5 * _tol(rr, cl.cell):
            continue
        # confirm a little further on
        p2 = cen + a * 0.6 * rr
        ids2 = cl.near(p2, 2.0 * rr + 20, cap=8000)
        ok2, t4, rad4, _d4 = _wall(cl, ids2, cen, a, rr, _tol(rr, cl.cell))
        ok2 &= np.abs(t4 - 0.6 * rr) < 0.3 * rr
        if ok2.sum() < 10:
            continue
        kind = "inline" if abs(rr - r) < 0.07 * r else "reducer"
        # a reducer starts about where the pipe before it stopped being round
        corner = end_pt + a * (0.15 * r) if kind == "reducer" else end_pt + a * (0.5 * s)
        return {"kind": kind, "cyl": Cyl(cen, a, rr), "corner": corner,
                "gap": float(np.linalg.norm(cen - p)), "angle": 0.0}
    return None


# ------------------------------------------------------------------ tracing

def _rim_cover(cl, p, a, r):
    """How far round (0..1) there is surface facing outwards beyond the
    pipe at p: a flange's rim goes right round, a pipe hanger's clamp is
    hardly bigger than the pipe and only its lugs stick out."""
    idx = cl.near(p + a * 0.2 * r, 3.1 * r, cap=40000)
    if len(idx) == 0:
        return 0.0
    d = cl.P[idx] - p
    tt = d @ a
    rad = d - np.outer(tt, a)
    dist = np.linalg.norm(rad, axis=1)
    n = cl.N[idx].astype(float)
    rn = rad / (dist[:, None] + 1e-9)
    m = (tt > -0.1 * r) & (tt < 0.35 * r) & (np.abs(n @ a) < 0.35) & \
        (np.abs(np.sum(n * rn, 1)) > 0.85) & (dist > 1.25 * r) & (dist < 3.0 * r)
    if m.sum() < 8:
        return 0.0
    # a rim is round: the best single radius, not clutter at all sorts
    tol = max(_tol(r, cl.cell), 3.0)
    u, w = _frame(a)
    best = 0.0
    for rb in np.arange(1.25 * r, 3.0 * r, tol):
        mm = m & (np.abs(dist - rb) < 1.5 * tol)
        if mm.sum() >= 8:
            best = max(best, _coverage(rad[mm], u, w))
    return best


def _near(points, p, dist):
    return any(np.linalg.norm(np.asarray(q, float) - p) < dist for q in points or ())


def _carry_on(cl, base, a, r, t0, steps):
    """A centre a little past base + a*t0 where the pipe can be followed
    again (past a clamp, a gap, whatever the user said to ignore), or None."""
    for k in steps:
        c2 = base + a * (t0 + k * r)
        f2 = follow_tube(cl, c2, a, r, max_len=2 * r)
        if len(f2["samples"]) >= 3:
            return c2
    return None


def _walk(cl, c, a, r, log, flanges=None, skip=()):
    """Follow one way from the centre c, over gaps in the scan and through
    reducers. Returns (samples [(centre, dir, radius)], events
    [(sample index, find_inline result)], how it ends)."""
    samples, events = [], []
    for _ in range(80):
        f = follow_tube(cl, c, a, r)
        if events and not f["samples"] and f["stop"] == "lost":
            # found something in line but couldn't follow it: try a bit on
            c = c + a * max(0.5 * r, 10.0)
            stuck = getattr(_walk, "_stuck", 0) + 1
            if stuck > 6:
                _walk._stuck = 0
                return samples, events, {"kind": "open", "point": samples[-1][0] if samples else c,
                                         "out": a}
            _walk._stuck = stuck
            continue
        _walk._stuck = 0
        if events and events[-1][1]["kind"] == "reducer" and len(f["samples"]) >= 4 and samples:
            # is it really another size? (measured over a good length now)
            r_new = float(np.median([x[2] for x in f["samples"]]))
            r_old = float(np.median([x[2] for x in samples[-12:]]))
            if abs(r_new - r_old) < 0.07 * r_old:
                events[-1] = (events[-1][0], dict(events[-1][1], kind="inline"))
        if events and events[-1][1]["kind"] == "reducer" and len(f["samples"]) < 4:
            # not a reducer after all (a valve body, a fitting): end before it
            events.pop()
            return samples, events, {"kind": "open", "point": c + a * 0.0,
                                     "note": "something in line here (a valve?)"}
        samples += f["samples"]
        if samples:
            c, a, r = samples[-1]
        if f["stop"] == "face":
            cp, ap = f["face_from"]
            pf = cp + ap * f["face_t"]
            # a pipe hanger (a clamp round the pipe) is not a flange: no rim
            # round it, no standard flange fits, and the pipe carries on
            forced = _near(skip, pf, 2.5 * r)
            if forced or (_rim_cover(cl, pf, ap, r) < 0.45 and (flanges is None or match_flange(
                    cl, pf, ap, r, -0.3 * r, flanges(2 * r)) is None)):
                # carry on from just past it (straight on, or into a bend)
                c2 = _carry_on(cl, cp, ap, r, f["face_t"],
                               (0.5, 0.8, 1.2, 1.8, 2.5, 3.5, 5.0) if forced else (0.5, 0.8, 1.2))
                if c2 is not None:
                    what = "told to carry on" if forced else "hanger / clamp"
                    log(f"  {what} at {np.round(pf)} - carrying on")
                    events.append((len(samples), {"kind": "skip" if forced else "hanger",
                                                  "corner": pf, "cyl": Cyl(c2, ap, r),
                                                  "gap": 0.0, "angle": 0.0}))
                    c, a = c2, ap
                    continue
            info = classify_face(cl, cp, ap, r, f["face_t"])
            info["point"] = cp + ap * info["t"]
            info["out"] = ap
            log(f"  {info['kind']} at {np.round(info['point'])}"
                + (f", OD {info['od']:.0f}" if info.get("od") else ""))
            return samples, events, info
        nxt = find_inline(cl, c, a, r)
        if nxt is None and _near(skip, c, 4.0 * r):
            c2 = _carry_on(cl, c, a, r, 0.0, (0.5, 1.0, 1.5, 2.5, 3.5, 5.0, 7.0, 9.0, 12.0, 15.0))
            if c2 is not None:
                log(f"  told to carry on at {np.round(c)} - carrying on")
                events.append((len(samples), {"kind": "skip", "corner": c, "cyl": Cyl(c2, a, r),
                                              "gap": 0.0, "angle": 0.0}))
                c = c2
                continue
        if nxt is None:
            step = float(np.clip(0.3 * r, max(5.0, 1.5 * cl.cell), 60.0))
            info = {"kind": "open", "point": c + a * (0.5 * step), "out": a}
            log(f"  open end at {np.round(info['point'])}")
            return samples, events, info
        log(f"  {nxt['kind']} at {np.round(nxt['corner'])}: D {2 * nxt['cyl'].r:.1f}")
        if nxt["kind"] == "inline":
            c, a = nxt["cyl"].c, nxt["cyl"].a           # same pipe: keep its size
            events.append((len(samples), nxt))
            continue
        r_ref = float(np.median([x[2] for x in samples[-15:]])) if samples else r
        cs = _cone_start(cl, c, a, r_ref)
        if cs is not None:
            nxt = dict(nxt, corner=cs)
        events.append((len(samples), nxt))
        c, a, r = nxt["cyl"].c, nxt["cyl"].a, nxt["cyl"].r
    return samples, events, {"kind": "open", "point": c, "out": a}


def _cone_start(cl, c, a, r):
    """Where a pipe (centre c, going a, radius r) stops being its own size:
    thin slices across it, from a little behind c on, until the radius
    starts to change."""
    tol = _tol(r, cl.cell)
    u, w = _frame(a)
    h = max(1.5 * cl.cell, 3.0)
    idx = cl.near(c, 2.2 * r + 20, cap=40000)
    d = cl.P[idx] - c
    tt = d @ a
    rad = d - np.outer(tt, a)
    dist = np.linalg.norm(rad, axis=1)
    n = cl.N[idx].astype(float)
    last_ok = None
    for t in np.arange(-1.2 * r, 1.2 * r, max(1.0, h / 2)):
        m = (np.abs(tt - t) < h) & (np.abs(dist - r) < 4 * tol) & (np.abs(n @ a) < 0.6)
        if m.sum() < 10 or _coverage(rad[m], u, w) < 0.3:
            continue
        q = cl.P[idx[m]]
        _cx, _cy, rr = _circle(q @ u, q @ w)
        if abs(rr - r) <= max(1.0, 0.5 * tol):
            last_ok = t
        elif last_ok is not None:
            return c + a * (last_ok + h / 2)
    return None


def _tangents(C, win):
    """Direction of the centre line at each sample (PCA over +-win mm)."""
    n = len(C)
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    T = np.zeros_like(C)
    lo = hi = 0
    for i in range(n):
        while s[i] - s[lo] > win:
            lo += 1
        while hi + 1 < n and s[hi + 1] - s[i] <= win:
            hi += 1
        Q = C[lo:hi + 1]
        if len(Q) < 3:
            T[i] = C[min(i + 1, n - 1)] - C[max(i - 1, 0)]
        else:
            _s, _v, vt = np.linalg.svd(Q - Q.mean(0))
            T[i] = vt[0]
        chord = C[min(i + 1, n - 1)] - C[max(i - 1, 0)]
        if T[i] @ chord < 0:
            T[i] = -T[i]
    return T / (np.linalg.norm(T, axis=1)[:, None] + 1e-12), s


def segment(samples, events, ends, step_hint=None, straight_deg=2.5):
    """Split the centre line into straights. Returns runs [{'p','d','r',
    'centres','join'}] (join: None, 'elbow' or a reducer dict) in order."""
    if not samples:
        return []
    C = np.array([c for c, _a, _r in samples])
    R = np.array([r for _c, _a, r in samples])
    r0 = float(np.median(R))
    T, s = _tangents(C, max(0.8 * r0, 25.0))
    breaks = {i for i, _e in events}
    groups = []
    cur = [0]
    for i in range(1, len(C)):
        g = _unit(T[cur].mean(0))
        ang = math.degrees(math.acos(min(1.0, abs(float(T[i] @ g)))))
        if ang < straight_deg and i not in breaks:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    runs = []
    pending = None                       # a reducer between the last run and the next
    ev_at = {i: e for i, e in events}
    for g in groups:
        if g[0] in ev_at and ev_at[g[0]]["kind"] == "reducer":
            pending = ev_at[g[0]]
        length = s[g[-1]] - s[g[0]]
        if len(g) < 3 or length < 1.0 * float(np.median(R[g])):
            continue
        cent = [C[i] for i in g]
        p, d = _line_of(cent, T[g].mean(0))
        rr = float(np.median(R[g]))
        run = {"p": p, "d": d, "r": rr, "centres": cent, "join": None,
               "s": (s[g[0]], s[g[-1]]), "idx": (g[0], g[-1])}
        if runs:
            prev = runs[-1]
            ang = math.degrees(math.acos(min(1.0, abs(float(prev["d"] @ d)))))
            if ang < 4.0 and pending is None:
                cent2 = prev["centres"] + cent
                p2, d2 = _line_of(cent2, prev["d"])
                prev.update(p=p2, d=d2, centres=cent2, idx=(prev["idx"][0], g[-1]),
                            s=(prev["s"][0], s[g[-1]]))
                continue
            if ang < 4.0:
                # where the size started to change - walking forwards that is
                # the reducer's start, walking back (back=True) its far end
                run["join"] = {"kind": "reducer",
                               "at": (pending or {}).get("corner",
                                                         0.5 * (C[prev["idx"][1]] + C[g[0]])),
                               "back": bool((pending or {}).get("back"))}
            else:
                run["join"] = {"kind": "elbow"}
        pending = None
        runs.append(run)
    # the end legs: a flange face says which way the pipe leaves it - use
    # it where the last straight is short or missing (elbow onto flange)
    for side in (0, 1):
        e = ends[side]
        ax = e.get("axis")
        if ax is None or not runs:
            continue
        fc, fn = ax
        out = np.asarray(e.get("out", fn), float)
        fn = fn if fn @ out > 0 else -fn
        d_run = -fn if side == 0 else fn            # along the line, start to end
        end_run = runs[0] if side == 0 else runs[-1]
        span = end_run["s"][1] - end_run["s"][0]
        k = end_run["idx"][0] if side == 0 else end_run["idx"][1]
        at_end = (k <= 2) if side == 0 else (k >= len(C) - 3)
        ang = math.degrees(math.acos(min(1.0, abs(float(end_run["d"] @ d_run)))))
        if ang < 10.0 and at_end and span >= 3 * end_run["r"]:
            continue                                  # a proper straight up to the flange
        leg = {"p": np.asarray(fc, float), "d": d_run, "r": end_run["r"], "centres": [],
               "join": None, "s": (0.0, 0.0), "idx": (k, k), "from_face": True}
        if ang < 10.0:
            # same line: the face fixes it better than a short bit of pipe
            if side == 0:
                leg["join"] = None
                runs[0] = dict(leg, centres=end_run["centres"], join=None)
            else:
                runs[-1] = dict(leg, centres=end_run["centres"], join=end_run["join"])
            continue
        # only where the pipe really turns before the flange: its centre is
        # well off the line of the last straight (otherwise the face's own
        # direction is just badly seen - the edge of a scan, say - and a
        # stray leg would stick out of the end)
        v = np.asarray(fc, float) - end_run["p"]
        off = float(np.linalg.norm(v - end_run["d"] * (v @ end_run["d"])))
        if off < 1.2 * end_run["r"]:
            continue
        if side == 0:
            runs[0]["join"] = {"kind": "elbow"}
            runs.insert(0, leg)
        else:
            leg["join"] = {"kind": "elbow"}
            runs.append(leg)
    return runs


def trace(cl, pick, end_pick=None, log=print, flanges=None, skip=()):
    """Follow the pipe through the picked point both ways, from one end to
    the other. Returns {'runs', 'ends' (start, end), 'od', 'samples'}."""
    seed = seed_fit(cl, pick)
    log(f"pipe at the pick: D {2 * seed.r:.1f}")
    fs, fev, fend = _walk(cl, seed.c, seed.a, seed.r, log, flanges, skip)
    bs, bev, bend = _walk(cl, seed.c, -seed.a, seed.r, log, flanges, skip)
    nb = len(bs)
    samples = [(c, -a, r) for c, a, r in reversed(bs)] + fs
    events = [(nb - i, dict(e, back=True)) for i, e in bev] + [(nb + i, e) for i, e in fev]
    events.sort(key=lambda t: t[0])
    ends = [bend, fend]
    runs = segment(samples, events, ends)
    if not runs:
        raise ValueError("the pipe couldn't be followed from there - click the middle of a "
                         "straight length of pipe")
    for e, rr in ((ends[0], runs[0]), (ends[1], runs[-1])):
        q = np.asarray(e["point"], float)
        e["point"] = rr["p"] + rr["d"] * ((q - rr["p"]) @ rr["d"])
    if flanges is not None:
        for k, (e, rr) in enumerate(((ends[0], runs[0]), (ends[1], runs[-1]))):
            if e["kind"] != "flange":
                continue
            out = -rr["d"] if k == 0 else rr["d"]          # away from the pipe
            m = match_flange(cl, e["point"], out, rr["r"], -0.3 * rr["r"],
                             flanges(2 * rr["r"]), log if FACE_DEBUG else None)
            e["match"] = m
            if m:
                e["back"] = e["point"] + out * m["t_back"]
                e["joint"] = e["point"] + out * m["t_joint"]
                log(f"  flange: {m['std']} {m['size']} {m['rating']} (OD {m['D']:.0f}), "
                    f"seen {100 * min(1.0, m['fill']):.0f}%")
    # the size at the start (a reducer further on changes it)
    od = 2 * float(next((x["r"] for x in runs if x["centres"]), seed.r))
    res = {"runs": runs, "ends": ends, "od": od, "seed": seed, "samples": samples,
           "events": [e for _i, e in events], "cloud": cl}
    if end_pick is not None:
        res["end_pick_dist"] = min(_dist_to_run(np.asarray(end_pick, float), rr) for rr in runs)
    return res


def _dist_to_run(q, rr):
    v = q - rr["p"]
    return float(np.linalg.norm(v - rr["d"] * (v @ rr["d"])))


# ------------------------------------------------------------- the line itself

def snap_dir(d, deg=3.0):
    """d snapped to the nearest of X/Y/Z when within deg."""
    k = int(np.argmax(np.abs(d)))
    if math.degrees(math.acos(min(1.0, abs(float(d[k]))))) <= deg:
        e = np.zeros(3)
        e[k] = 1.0 if d[k] > 0 else -1.0
        return e
    return d


def solve_line(runs, ends, square=True, snap_deg=3.0, keep=(), force=()):
    """The corner points of the line from end to end: each straight keeps
    its measured direction (or X/Y/Z when square), corners sit where the
    straights meet best (least squares). Returns the points [end, corners..,
    end] and the directions."""
    m = len(runs)
    # a leg straight off a flange face takes its direction from the face,
    # which is seen less well than a length of pipe (often half hidden):
    # square those up from further out
    # (keep: kept as measured - unless within a degree of square, which is
    # just the measurement)
    # (force: squared to the nearest of X / Y / Z however far off)
    D = []
    for k, rr in enumerate(runs):
        if k in force:
            D.append(snap_dir(rr["d"], 90.0))
        elif k in keep:
            D.append(snap_dir(rr["d"], 1.0))
        elif square:
            D.append(snap_dir(rr["d"], max(snap_deg, 15.0) if rr.get("from_face") else snap_deg))
        else:
            D.append(_unit(rr["d"]))
    # unknowns: Q0 (3) and lengths L0..L(m-1)
    nu = 3 + m
    rows, rhs = [], []

    def point_coeffs(i):
        """Q_i = Q0 + sum_{j<i} L_j D_j as (3 x nu)."""
        M = np.zeros((3, nu))
        M[:, :3] = np.eye(3)
        for j in range(i):
            M[:, 3 + j] = D[j]
        return M

    def on_line(i, k, wgt=1.0):
        # Q_i on the line of run k: (I - dd^T)(Q_i - p_k) = 0
        dk = D[k]
        Pm = np.eye(3) - np.outer(dk, dk)
        rows.append(wgt * Pm @ point_coeffs(i))
        rhs.append(wgt * Pm @ runs[k]["p"])

    for i in range(m + 1):
        if i > 0:
            on_line(i, i - 1)
        if i < m:
            on_line(i, i)
        if 0 < i < m:
            j = runs[i].get("join") or {}
            if j.get("kind") == "reducer" or math.degrees(math.acos(
                    min(1.0, abs(float(D[i - 1] @ D[i]))))) < 1.0:
                # in line (a reducer): where along the pipe the change is
                at = np.asarray(j.get("at", 0.5 * (runs[i - 1]["p"] + runs[i]["p"])), float)
                dk = D[i]
                rows.append(np.outer(dk, dk) @ point_coeffs(i))
                rhs.append(np.outer(dk, dk) @ at)
    # the ends where they were measured (along the pipe)
    for i, e in ((0, ends[0]), (m, ends[1])):
        k = 0 if i == 0 else m - 1
        dk = D[k]
        rows.append(np.outer(dk, dk) @ point_coeffs(i) * 2.0)
        rhs.append(np.outer(dk, dk) @ np.asarray(e["point"], float) * 2.0)
    A = np.vstack(rows)
    b = np.concatenate(rhs)
    x = np.linalg.lstsq(A, b, rcond=None)[0]
    Q = [point_coeffs(i) @ x for i in range(m + 1)]
    return Q, D


def deviation(runs, Q):
    """For each straight: the most and the mean distance from the measured
    centres to the solved line (mm)."""
    out = []
    for k, rr in enumerate(runs):
        a, b = Q[k], Q[k + 1]
        d = _unit(b - a)
        C = np.asarray(rr["centres"]) if rr["centres"] else np.zeros((0, 3))
        if len(C) == 0:
            out.append((0.0, 0.0, 0))
            continue
        v = C - a
        e = np.linalg.norm(v - np.outer(v @ d, d), axis=1)
        out.append((float(e.max()), float(e.mean()), len(C)))
    return out


def bend_radii(runs, Q):
    """Measured bend radius at each corner (from where the straights stop),
    or None where it can't be told."""
    out = []
    for k in range(1, len(runs)):
        c = Q[k]
        prev, nxt = runs[k - 1], runs[k]
        if not prev["centres"] or not nxt["centres"]:
            out.append(None)
            continue
        d1 = _unit(Q[k] - Q[k - 1])
        d2 = _unit(Q[k + 1] - Q[k])
        th = math.acos(max(-1.0, min(1.0, float(d1 @ d2))))
        if th < math.radians(5):
            out.append(None)
            continue
        # tangent distance: corner back to the last centre of the straight
        t1 = float((c - np.asarray(prev["centres"][-1])) @ d1)
        t2 = float((np.asarray(nxt["centres"][0]) - c) @ d2)
        T = max(min(t1, t2), 0.0)
        out.append(T / math.tan(th / 2))
    return out


def trace_scan(sc, pick, end_pick=None, log=print, fine=True, flanges=None, skip=()):
    """trace() on the whole scan, then again on a fine copy of the scan
    along the pipe it found - that measures the pipe and its flanges far
    more closely than the coarse copy of a big scan can."""
    cl = sc.cloud()
    res = trace(cl, pick, end_pick, log, flanges, skip)
    if not fine:
        return res
    r = res["od"] / 2
    cell = float(np.clip(r / 30.0, 0.8, 5.0))
    if cell >= 0.8 * cl.cell:
        return res                           # already as fine as that
    Q, _D = solve_line(res["runs"], res["ends"], square=False)
    Q = np.asarray(Q)
    ext = 1.5 * r + 120
    pts = np.vstack([Q[0] + _unit(Q[0] - Q[1]) * ext, Q[1:-1] if len(Q) > 2 else np.zeros((0, 3)),
                     Q[-1] + _unit(Q[-1] - Q[-2]) * ext]) if len(Q) >= 2 else Q
    fc = sc.corridor(pts, 3.3 * r + 60, cell)
    if fc is None:
        return res
    log(f"close look: {len(fc)} points at {cell:.1f} mm")
    try:
        res2 = trace(fc, pick, end_pick, log, flanges, skip)
    except ValueError as e:
        log(f"close look failed ({e}) - using the first pass")
        return res
    # a plate (bulkhead, deck) is wider than the corridor: keep the coarse
    # verdict for those
    for k in (0, 1):
        e1 = res["ends"][k]
        # match the ends by position (either way round)
        e2 = min(res2["ends"], key=lambda e: np.linalg.norm(np.asarray(e["point"]) - e1["point"]))
        if e1["kind"] == "plate" and e2["kind"] != "plate" and \
                np.linalg.norm(np.asarray(e2["point"]) - e1["point"]) < 2 * r:
            e2["kind"] = "plate"
    n1 = sum(len(x["centres"]) for x in res["runs"])
    if len(res2["runs"]) < len(res["runs"]) and n1 > 0:
        log("close look found less of the pipe - using the first pass")
        return res
    res2["coarse"] = res
    res2["cell"] = cell
    return res2
