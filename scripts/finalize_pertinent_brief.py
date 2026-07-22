from pathlib import Path


path = Path("pilotdriven_odss_dashboard/tests/test_vaa.py")
text = path.read_text(encoding="utf-8")

broken = '    text = "\n".join(page.extract_text() or "" for page in reader.pages)\n'
correct = '    text = "\\n".join(page.extract_text() or "" for page in reader.pages)\n'

count = text.count(broken)
if count != 1:
    raise RuntimeError(f"Expected one malformed VAAC text-join assertion, found {count}")

path.write_text(text.replace(broken, correct, 1), encoding="utf-8")
