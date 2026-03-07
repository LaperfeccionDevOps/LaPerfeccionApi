import pathlib

bad = []
for p in pathlib.Path("app").rglob("*.py"):
    try:
        p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        bad.append(str(p))

if bad:
    print("\nArchivos que NO están en UTF-8:\n")
    for x in bad:
        print(" -", x)
else:
    print("\nTodo en UTF-8 ✅")