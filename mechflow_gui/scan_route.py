"""Pipe from Scan: from a traced pipe (scan.trace_scan) to a MechFlow
3D sketch and route, in the pipe spec chosen."""
import math

import numpy as np
import FreeCAD as App

from mechflow_gui import scan, scan_match

V = App.Vector

END_NAMES = {"flange": "Flange", "plate": "Plate / bulkhead", "open": "Open end"}


def _v(p):
    return V(float(p[0]), float(p[1]), float(p[2]))


def plan(res, std, square=True, snap_deg=5.0, measured_ends=False, modes=None):
    """What the scan says, in the terms of the standard std ('EN'/'ASME'):
    {'points' (line corners, start to end, before end adjustment), 'sizes'
    (per straight), 'size', 'od', 'ends' [{kind, mode, match, joint,
    note}], 'bends' [(angle, measured radius)], 'dev', 'reducers'}."""
    runs, ends = res["runs"], res["ends"]
    runs = [dict(rr) for rr in runs]
    for k in range(1, len(runs)):
        j = runs[k].get("join")
        if j and j.get("kind") == "reducer":
            # the reducer's own start: the scan sees where the cone begins, a
            # reducer has a short straight before that (and walking back
            # through it, the cone's other end is what was seen)
            from mechflow_gui import routing
            big = scan_match.match_pipe(std, 2 * runs[k - 1]["r"])[0]
            small = scan_match.match_pipe(std, 2 * runs[k]["r"])[0]
            if big != small:
                a_, b_ = (big, small) if 2 * runs[k - 1]["r"] > 2 * runs[k]["r"] else (small, big)
                try:
                    H = routing.reducer_length(std, a_, b_)
                except Exception:
                    H = 0.0
                lead = min(0.12 * H, 0.5 * 25.4)
                d = scan._unit(runs[k]["d"])
                back = (H - lead) if j.get("back") else lead
                runs[k]["join"] = dict(j, at=np.asarray(j["at"], float) - d * back)
    # measured_ends: the straights onto flanges keep the direction the
    # flange faces were measured at (the elbows get cut to suit) instead of
    # being squared up
    keep = set()
    if measured_ends:
        if ends[0]["kind"] in ("flange", "plate"):
            keep.add(0)
        if ends[1]["kind"] in ("flange", "plate"):
            keep.add(len(runs) - 1)
    # modes: {straight index: 'square' | 'measured'} set by hand
    force = set()
    for k, m in (modes or {}).items():
        if k >= len(runs):
            continue
        if m == "measured":
            keep.add(k)
            force.discard(k)
        elif m == "square":
            force.add(k)
            keep.discard(k)
    Q, D = scan.solve_line(runs, ends, square=square, snap_deg=snap_deg, keep=keep, force=force)
    Q = [np.asarray(q, float) for q in Q]
    dev = scan.deviation(runs, Q)
    radii = scan.bend_radii(runs, Q)
    sizes = []
    for rr in runs:
        sz, pod, diff = scan_match.match_pipe(std, 2 * rr["r"])
        sizes.append({"size": sz, "od": pod, "measured": 2 * rr["r"], "diff": diff})
    size, pod, diff = scan_match.match_pipe(std, res["od"])
    bends = []
    for k in range(1, len(Q) - 1):
        d1 = scan._unit(Q[k] - Q[k - 1])
        d2 = scan._unit(Q[k + 1] - Q[k])
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(d1 @ d2)))))
        bends.append((ang, radii[k - 1] if k - 1 < len(radii) else None, runs[k]["join"]))
    out_ends = []
    for k, e in enumerate(ends):
        kind = e["kind"]
        info = {"kind": kind, "mode": "Weld neck flange" if kind == "flange" else "Plain",
                "match": e.get("match"), "joint": e.get("joint"), "point": e["point"],
                "note": e.get("note", "")}
        out_ends.append(info)
    meas = [scan._unit(rr["d"]) for rr in runs]
    off = [math.degrees(math.acos(max(-1.0, min(1.0, float(abs(m @ d)))))) for m, d in zip(meas, D)]
    return {"off_axis": off, "keep": keep, "force": force,
            "Q": Q, "D": D, "sizes": sizes, "size": size, "size_od": pod, "od": res["od"],
            "od_diff": diff, "ends": out_ends, "bends": bends, "dev": dev, "std": std,
            "runs": runs, "square": square}


def best_bend(std, size, schedule, radii, sizes=None):
    """The bend type whose radius is nearest the measured ones. radii: the
    measured radius at each bend (None where it couldn't be told); sizes:
    the pipe size at each bend (default: size)."""
    from mechflow_gui import routing
    opts = routing.BENDS[std]
    sizes = sizes or [size] * len(radii)
    meas = [(r, s_) for r, s_ in zip(radii, sizes) if r]
    if not meas:
        return opts[0], None
    best = None
    for b in opts:
        errs = []
        for r, s_ in meas:
            try:
                R = routing.fitting_dims(std, s_, schedule, b)[2]
            except Exception:
                continue
            errs.append(abs(math.log(r / R)))
        if errs and (best is None or float(np.median(errs)) < best[1]):
            best = (b, float(np.median(errs)))
    return (best[0] if best else opts[0]), float(np.median([r for r, _s in meas]))


def end_points(p, rating, spec_flange):
    """The line's points with its flanged ends moved to the joint faces.
    rating: the flange rating the route will use (for ends where no
    standard flange could be fitted to the scan)."""
    from mechflow_gui import stdparts, routing
    Q = [q.copy() for q in p["Q"]]
    notes = []
    for k, e in enumerate(p["ends"]):
        i, j = (0, 1) if k == 0 else (len(Q) - 1, len(Q) - 2)
        d = scan._unit(Q[i] - Q[j])                    # outwards
        if e["mode"] == "Weld neck flange" and e["kind"] == "flange":
            if e["joint"] is not None:
                target = np.asarray(e["joint"], float)
            else:
                size = p["sizes"][0 if k == 0 else -1]["size"]
                try:
                    th = stdparts.flange_info(spec_flange, size, rating)["thick"]
                except Exception:
                    th = 0.0
                target = np.asarray(e["point"], float) + d * th
                notes.append(f"{'start' if k == 0 else 'end'}: flange position estimated "
                             "(no standard flange fitted the scan there)")
            Q[i] = Q[j] + d * float((target - Q[j]) @ d)
    return Q, notes


def fit_ends(Q, p, std, size, sched, bend, rating, flange_type, notes):
    """A scan is never exact: where an end straight is a little shorter
    than its standard fittings need (an elbow welded straight onto a weld
    neck flange, say), move the end out to fit them and say so."""
    from mechflow_gui import routing, stdparts
    Q = [q.copy() for q in Q]
    if len(Q) < 2:
        return Q
    try:
        R = routing.fitting_dims(std, size, sched, bend)[2]
    except Exception:
        return Q
    for k, e in enumerate(p["ends"]):
        i, j = (0, 1) if k == 0 else (len(Q) - 1, len(Q) - 2)
        need = 0.0
        if e["mode"] in ("Weld neck flange", "Blind flange"):
            need += stdparts._length_in_part(flange_type, size, rating)
        if len(Q) > 2:
            jn = 1 if k == 0 else len(Q) - 2
            d1 = scan._unit(Q[jn] - Q[jn - 1])
            d2 = scan._unit(Q[jn + 1] - Q[jn])
            th = math.acos(max(-1.0, min(1.0, float(d1 @ d2))))
            if th > math.radians(1):
                need += R * math.tan(th / 2)
        L = float(np.linalg.norm(Q[i] - Q[j]))
        short = need - L
        if 0 < short <= max(20.0, 0.06 * need):
            d = scan._unit(Q[i] - Q[j])
            Q[i] = Q[j] + d * need
            notes.append(f"{'start' if k == 0 else 'end'}: moved out {short:.0f} mm so the "
                         "standard fittings fit (the scan had them a little closer)")
    return Q


def extend_ends(Q, ext):
    """The line with its ends moved out (+) or in (-) along their straights
    by ext = (start mm, end mm)."""
    Q = [np.asarray(q, float).copy() for q in Q]
    if len(Q) < 2:
        return Q
    for k, e in enumerate(ext or ()):
        if not e:
            continue
        i, j = (0, 1) if k == 0 else (len(Q) - 1, len(Q) - 2)
        d = scan._unit(Q[i] - Q[j])
        Q[i] = Q[i] + d * float(e)
    return Q


def takeoffs(Q, std, size_a, size_b, sched, bend, rating, modes):
    """For the two end straights: how much of each is taken up by fittings
    (the elbow at the inner end, the flange / cap at the outer end), so
    pipe cut length = straight length - take-off. Returns
    [(straight length, take-off), (straight length, take-off)]."""
    from mechflow_gui import routing, stdparts
    out = []
    n = len(Q)
    ty = routing.types_for(std, bend)
    for k, size, mode in ((0, size_a, modes[0]), (1, size_b, modes[1])):
        i, j = (0, 1) if k == 0 else (n - 1, n - 2)
        L = float(np.linalg.norm(Q[i] - Q[j]))
        t = 0.0
        try:
            od, wall, R, C, E = routing.fitting_dims(std, size, sched, bend)
        except Exception:
            R = E = 0.0
        if n > 2:
            jn = 1 if k == 0 else n - 2
            d1 = scan._unit(Q[jn] - Q[jn - 1])
            d2 = scan._unit(Q[jn + 1] - Q[jn])
            th = math.acos(max(-1.0, min(1.0, float(d1 @ d2))))
            if th > math.radians(1):
                t += R * math.tan(th / 2)
        if mode in ("Weld neck flange", "Blind flange"):
            try:
                t += stdparts._length_in_part(ty["flange"], size, rating)
            except Exception:
                pass
        elif mode == "Cap":
            t += E or 0.0
        out.append((L, t))
    if n == 2:
        # one straight: both ends' fittings come off the same pipe
        L = out[0][0]
        both = out[0][1] + out[1][1]
        out = [(L, both), (L, both)]
    return out


def make(p, spec, size=None, rating=None, bend=None, container=None, label="Scan line",
         ext=(0.0, 0.0)):
    """Make the 3D sketch and the route. spec: a pipe spec dict
    (pipespec); size / rating / bend override the spec's. Returns
    (route, sketch, notes)."""
    from mechflow_gui import sketch3d, routing, pipespec
    std = spec["standard"]
    rating = rating or spec["rating"]
    size = size or p["size"]
    sched = pipespec.schedule_for(spec, size)
    ty = routing.types_for(std, bend or spec["bend"])
    Q, notes = end_points(p, rating, ty["flange"])
    pts = fit_ends(Q, p, std, size, sched, bend or spec["bend"], rating, ty["flange"], notes)
    pts = extend_ends(pts, ext)
    # reducers: the change of size starts on the straight after one
    changes = []                       # (index of the line it starts, size)
    for k in range(1, len(p["runs"])):
        j = p["runs"][k].get("join")
        if j is not None and j.get("kind") == "reducer":
            changes.append((k, p["sizes"][k]["size"]))
    sk = sketch3d.make(container, label)
    ed = sketch3d.Editor(sk)
    ed.start(_v(pts[0]), None)
    for q in pts[1:]:
        ed.line_to(_v(q), None)
    ed.save()
    r = routing.make_route(container, [(sk, None)], std, size, sched, bend or spec["bend"],
                           spec["free_ends"], rating, build_now=False)
    pipespec.apply_to_route(r, spec)
    r.Size = size
    r.FlangeRating = rating
    if bend:
        r.Bend = bend
    # each end as the scan showed it
    modes = {e["mode"] for e in p["ends"]}
    r.FreeEnds = p["ends"][0]["mode"] if len(modes) == 1 else "Weld neck flange"
    for k, e in enumerate(p["ends"]):
        q = pts[0] if k == 0 else pts[-1]
        if e["mode"] != r.FreeEnds:
            routing.set_end_type(r, _v(q), e["mode"])
    if changes:
        segs = routing.path_segments_keyed(routing.path_links(r))
        for k, sz in changes:
            a, b = _v(pts[k]), _v(pts[k + 1])
            for s0, s1, key in segs:
                if ((s0 - a).Length < 0.5 and (s1 - b).Length < 0.5) or \
                        ((s0 - b).Length < 0.5 and (s1 - a).Length < 0.5):
                    routing.set_size_change(r, key, sz)
    r.Label = label.replace("line", "route") if "line" in label else label + " route"
    try:
        routing.build(r)
    except Exception as e:
        r.Error = str(e)
        notes.append(f"the route couldn't be built: {e}")
    return r, sk, notes


# ------------------------------------------------------------ correcting it

def trim(res, q):
    """Cut the traced line at the point nearest q (scan coordinates):
    whichever end q is nearer, along the line, finishes there. Returns
    (new res, which end 0/1, how far q was off the line)."""
    runs, ends = res["runs"], res["ends"]
    Q, _D = scan.solve_line(runs, ends, square=False)
    Q = [np.asarray(x, float) for x in Q]
    q = np.asarray(q, float)
    best = None
    total = 0.0
    for k in range(len(Q) - 1):
        a, b = Q[k], Q[k + 1]
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 1e-9:
            continue
        t = min(max(float((q - a) @ d) / (L * L), 0.0), 1.0)
        p = a + d * t
        dist = float(np.linalg.norm(q - p))
        if best is None or dist < best[0]:
            best = (dist, k, p, total + t * L, d / L)
        total += L
    dist, k, p, s, u = best
    side = 0 if s < total / 2 else 1
    runs = [dict(r) for r in runs]
    ends = [dict(e) for e in ends]
    if side == 0:
        runs = runs[k:]
        runs[0]["join"] = None
        ends[0] = {"kind": "open", "point": p, "out": -u, "note": "end set by you"}
    else:
        runs = runs[:k + 1]
        ends[1] = {"kind": "open", "point": p, "out": u, "note": "end set by you"}
    return dict(res, runs=runs, ends=ends), side, dist


def fit_points(res, Q, r_model, bend_r=None):
    """The scan points on the pipe's straights and how far each is off the
    model's surface (mm, + outside): (points (n,3), deviations (n,))."""
    cl = res.get("cloud")
    if cl is None or len(Q) < 2:
        return np.zeros((0, 3)), np.zeros(0)
    r = float(res["od"]) / 2
    tol = scan._tol(r, cl.cell)
    band = max(0.3 * r, 6 * tol)
    P_out, D_out = [], []
    n = len(Q) - 1
    for k in range(n):
        a, b = np.asarray(Q[k], float), np.asarray(Q[k + 1], float)
        L = float(np.linalg.norm(b - a))
        if L < 1e-6:
            continue
        u = (b - a) / L
        # keep clear of the bends (and of the flanges at the ends)
        m0 = (bend_r or 1.5 * r) + 0.3 * r if k > 0 else 0.2 * r
        m1 = (bend_r or 1.5 * r) + 0.3 * r if k < n - 1 else 0.2 * r
        if L - m0 - m1 < 0.2 * r:
            continue
        mid = a + u * (m0 + (L - m1)) / 2
        idx = cl.near(mid, math.hypot((L - m0 - m1) / 2, r + band) + 5, cap=250000)
        if len(idx) == 0:
            continue
        d = cl.P[idx] - a
        t = d @ u
        rad = d - np.outer(t, u)
        dist = np.linalg.norm(rad, axis=1)
        m = (t > m0) & (t < L - m1) & (np.abs(dist - r) < band)
        P_out.append(cl.P[idx[m]])
        rr = r_model[k] if isinstance(r_model, (list, tuple)) else r_model
        D_out.append(dist[m] - rr)
    if not P_out:
        return np.zeros((0, 3)), np.zeros(0)
    return np.vstack(P_out), np.concatenate(D_out)


def warnings(res, p):
    """Where to look twice: [(text, scan point or None)]."""
    out = []
    for k, e in enumerate(p["ends"]):
        name = "start" if k == 0 else "end"
        m = e.get("match")
        if e["kind"] == "flange" and m is None:
            out.append((f"The {name} flange didn't match a standard flange - check its "
                        "rating and where its face is", e["point"]))
        elif e["kind"] == "flange" and m["fill"] < 0.4:
            out.append((f"Only {100 * m['fill']:.0f}% of the {name} flange's rim was seen - "
                        "its position and angle may be a little out", e["point"]))
        elif e["kind"] == "open" and "you" not in (e.get("note") or ""):
            out.append((f"The line just stops at the {name} (the end of the scan, or "
                        "something in the way) - Carry on past, or Set an end, if that's "
                        "not where it finishes", e["point"]))
    for ev in res.get("events", []):
        kind = ev.get("kind")
        if kind == "hanger":
            out.append(("Stepped over a pipe hanger / clamp here", ev.get("corner")))
        elif kind == "skip":
            out.append(("Carried on past here, as you said", ev.get("corner")))
        elif kind == "inline" and ev.get("corner") is not None:
            out.append(("Followed the pipe past something here (a clamp, or a gap in the "
                        "scan)", ev.get("corner")))
    for k, rr in enumerate(p["runs"]):
        if rr.get("from_face"):
            out.append((f"Straight {k + 1}: its direction comes from the flange face (no "
                        "straight pipe seen there)", None))
    for k, off in enumerate(p.get("off_axis", [])):
        if k not in p.get("keep", ()) and 1.0 < off and k not in p.get("force", ()):
            out.append((f"Straight {k + 1} was measured {off:.1f}° off square - squared up "
                        "(set it to As measured if it really is at an angle)", None))
    return out


def report_rows(p, size, dev_limits):
    """Rows for a CSV fit report."""
    good, check = dev_limits
    rows = [["Item", "Value", "Note"]]
    rows.append(["Measured OD (mm)", f"{p['od']:.1f}", f"made as {size} (OD {p['size_od']:.1f})"])
    for k in range(len(p["Q"]) - 1):
        L = float(np.linalg.norm(p["Q"][k + 1] - p["Q"][k]))
        mx, mean, n = p["dev"][k]
        verdict = "from flange face" if n == 0 else ("good" if mx <= good else
                                                     ("check" if mx <= check else "poor"))
        rows.append([f"Straight {k + 1} length (mm)", f"{L:.1f}",
                     f"centre line off the scan: max {mx:.1f}, mean {mean:.1f} - {verdict}"])
    for k, (a, r, _j) in enumerate(p["bends"]):
        rows.append([f"Bend {k + 1} angle (deg)", f"{a:.2f}",
                     f"measured radius {r:.0f} mm" if r else ""])
    for k, e in enumerate(p["ends"]):
        m = e.get("match")
        txt = e["kind"] + (f": {m['std']} {m['size']} {m['rating']}, rim {100 * min(1, m['fill']):.0f}% seen"
                           if m else "")
        rows.append(["Start" if k == 0 else "End", txt, e.get("note", "")])
    for k, q in enumerate(p["Q"]):
        rows.append([f"Point {k + 1} (x, y, z)", ", ".join(f"{x:.1f}" for x in q), ""])
    return rows
