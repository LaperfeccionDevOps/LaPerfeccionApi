# find_bad_utf8.py
from pathlib import Path

# Carpetas de código que tienes en tu repo (ajusta si te falta/sobra alguna)
CANDIDATES = [
    "app", "api", "application", "core", "domain", "infrastructure", "test"
]

bad = []
for folder in CANDIDATES:
    root = Path(folder)
    if not root.exists():
        continue
    for p in root.rglob("*.py"):
        # Evita venvs o cachés por si acaso
        if "__pycache__" in p.parts or "venv" in p.parts:
            continue
        try:
            p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            bad.append((str(p), str(e)))

if bad:
    print("\nArchivos .py con problemas de UTF-8:\n")
    for path, err in bad:
        print(f" - {path}  <-- {err}")
    print("\nSolución por archivo en VS Code:")
    print("  1) Reopen with Encoding -> Western (Windows 1252)")
    print("  2) Save with Encoding   -> UTF-8 (el primero, NO 'UTF-8 with BOM')")
else:
    print("OK: Todos los .py están en UTF-8 ✅")
