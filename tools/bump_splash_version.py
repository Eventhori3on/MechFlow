# Writes a new version number on the splash screen (re-composes it from the
# rendered artwork, Resources/splash/SplashArt.jpg):
#   python3 tools/bump_splash_version.py 0.27.0
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, os.path.join(here, "make_splash.py")] + sys.argv[1:2]))
