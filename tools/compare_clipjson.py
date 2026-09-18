"""Gate 3: semantic field-by-field comparison of a generated clip.json vs baseline."""
import json
import sys

a = json.load(open(sys.argv[1], encoding="utf-8"))
b = json.load(open(sys.argv[2], encoding="utf-8"))

fa = set(a) | {k for s in a["segments"] for k in s}
fb = set(b) | {k for s in b["segments"] for k in s}
assert fa == fb, f"field sets differ: {fa ^ fb}"
assert a == b, "values differ"
print(f"clip.json semantically identical ({len(fa)} fields, version={a.get('version')})")
