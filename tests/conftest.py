import os

# Tests never fetch live exchange rates; the static table is used instead.
os.environ.setdefault("PI_FX_OFFLINE", "1")
