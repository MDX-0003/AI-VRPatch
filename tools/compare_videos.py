"""Gate 2 check: compare regression output against the project baseline."""
import sys
import cv2
import numpy as np

a = cv2.VideoCapture(sys.argv[1])
b = cv2.VideoCapture(sys.argv[2])
na = int(a.get(cv2.CAP_PROP_FRAME_COUNT))
nb = int(b.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"frames: new={na} baseline={nb}")
maxd = 0.0
n = 0
sumd = 0.0
while True:
    oka, fa = a.read()
    okb, fb = b.read()
    if not (oka and okb):
        break
    d = np.abs(fa.astype(np.int16) - fb.astype(np.int16))
    maxd = max(maxd, float(d.max()))
    sumd += float(d.mean())
    n += 1
print(f"compared {n} frames; maxdiff={maxd:.1f} meandiff={sumd/max(n,1):.4f}")
