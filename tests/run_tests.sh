#!/usr/bin/env bash
# Run MechFlow's GUI smoke tests in a real (headless) FreeCAD.
#
#   FREECAD=/path/to/freecad tests/run_tests.sh            # all tests
#   FREECAD=/path/to/freecad tests/run_tests.sh t_draw     # just one
#
# Needs: FreeCAD 1.1 (e.g. the Linux AppImage, extracted with
# --appimage-extract: FREECAD=squashfs-root/usr/bin/freecad) and xvfb-run.
# MechFlow must be in FreeCAD's Mod folder; if it isn't, this script links
# this checkout there.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
FREECAD="${FREECAD:-freecad}"
OUT="${MF_OUT:-${TMPDIR:-/tmp}/mechflow-tests}"
MOD="$HOME/.local/share/FreeCAD/v1-1/Mod"
TIMEOUT="${MF_TIMEOUT:-300}"

command -v xvfb-run >/dev/null || { echo "xvfb-run is needed (apt install xvfb)"; exit 2; }
command -v "$FREECAD" >/dev/null || [ -x "$FREECAD" ] || { echo "Set FREECAD to the freecad binary"; exit 2; }

mkdir -p "$MOD" "$OUT"
if [ ! -e "$MOD/MechFlow" ]; then
    ln -s "$REPO" "$MOD/MechFlow"
    echo "Linked $REPO -> $MOD/MechFlow"
fi

tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then
    tests=(t_tabs t_pat t_dress t_sweep t_thin t_handles t_rel t_tab t_draw t_asm t_splash t_hole t_toolbox t_toolbox2 t_cpat t_lpat t_stdparts t_joint t_smart t_weld t_weld2 t_sm t_mass t_nozzle t_pack t_route t_config)
fi

fail=0
for t in "${tests[@]}"; do
    log="$OUT/$t.log"
    rm -f "$log"
    MF_TESTDIR="$HERE/gui" MF_OUT="$OUT" MF_LOG="$log" \
        timeout "$TIMEOUT" xvfb-run -a -s "-screen 0 1600x1000x24" \
        "$FREECAD" "$HERE/gui/$t.py" > "$OUT/$t.freecad.txt" 2>&1
    problems=""
    [ -f "$log" ] || problems="no log written"
    if [ -f "$log" ]; then
        grep -q "^DONE" "$log" || problems="$problems; did not finish (crash or hang?)"
        n=$(grep -c "Traceback" "$log"); [ "$n" -gt 0 ] && problems="$problems; $n traceback(s)"
        n=$(grep -c "err=True" "$log"); [ "$n" -gt 0 ] && problems="$problems; $n panel error(s)"
        n=$(grep -c "!! " "$log"); [ "$n" -gt 0 ] && problems="$problems; $n unexpected dialog/button(s)"
    fi
    if [ -n "$problems" ]; then
        echo "FAIL  $t: ${problems#; }   (log: $log)"
        fail=1
    else
        echo "ok    $t"
    fi
done
exit $fail
