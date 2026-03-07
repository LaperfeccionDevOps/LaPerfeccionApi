from pathlib import Path

root = Path("app")
changed = []
failed = []

for p in root.rglob("*.py"):
    try:
        # 1) ¿Ya está en UTF-8?
        _ = p.read_text(encoding="utf-8")
        continue  # ok, nada que hacer
    except UnicodeDecodeError:
        pass

    # 2) Intentar como cp1252 (Windows-1252) y regrabar en UTF-8
    try:
        raw = p.read_bytes()
        text = raw.decode("cp1252")  # abrir en ANSI/Windows-1252
        # backup
        bak = p.with_suffix(p.suffix + ".bak")
        if not bak.exists():
            bak.write_bytes(raw)
        # guardar en UTF-8
        p.write_text(text, encoding="utf-8", newline="\n")
        changed.append(str(p))
    except Exception as e:
        failed.append(f"{p} :: {e}")

print("\n=== CONVERSIÓN FINALIZADA ===")
if changed:
    print("\nConvertidos a UTF-8:")
    for x in changed:
        print(" -", x)
else:
    print("\nNo hubo archivos a convertir (ya estaban en UTF-8).")

if failed:
    print("\nFallidos (revisar manualmente):")
    for x in failed:
        print(" -", x)
else:
    print("\nSin fallos 🚀")