"""Standard sizes for Pipe from Scan: which pipe a measured OD is, and
which flanges could be on the end of it (pure data, no FreeCAD needed)."""
from mechflow_gui import stdparts_data as T

IN = 25.4


def pipe_sizes(std):
    """[(size name, OD mm)] for EN or ASME."""
    if std == "ASME":
        return [(f"NPS {k}", v[0] * IN) for k, v in T.ASME_PIPE.items() if k in T.B169]
    return [(f"DN{dn}", float(d["A"])) for dn, d in T.EN_PN16.items()]


def match_pipe(std, od):
    """(size, its OD, difference mm) nearest the measured OD."""
    best = min(pipe_sizes(std), key=lambda s: abs(s[1] - od))
    return best[0], best[1], od - best[1]


def flange_candidates(std, size):
    """Weld neck flanges that fit the size: [{'rating', 'D' (OD), 'C'
    (back to joint face), 'K' (bolt circle)}]."""
    out = []
    if std == "ASME":
        nps = size.replace("NPS", "").strip()
        for rating, tab in T.ASME_FLANGES.items():
            f = tab.get(nps)
            if f:
                out.append({"rating": rating, "D": f["O"] * IN, "C": (f["T"] + 0.06) * IN,
                            "K": f["BC"] * IN})
        return out
    dn = int(size[2:])
    for rating, tab in T.EN_FLANGES.items():
        f = tab.get(dn)
        if f:
            out.append({"rating": rating, "D": float(f["D"]), "C": float(f["C2"]),
                        "K": float(f["K"])})
    return out


def all_flanges(od):
    """Every EN and ASME weld neck flange for a pipe of about this OD:
    [(std, size, candidate)]."""
    out = []
    for std in ("EN", "ASME"):
        size, pod, diff = match_pipe(std, od)
        if abs(diff) <= max(3.0, 0.04 * od):
            for c in flange_candidates(std, size):
                out.append((std, size, c))
    return out
