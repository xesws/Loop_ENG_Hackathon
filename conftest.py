# Presence of a root conftest.py puts the repo root on sys.path (pytest prepend
# import mode), so `import graph`, `import core`, `import runtime` resolve when
# tests run from the repo root. Intentionally empty.
