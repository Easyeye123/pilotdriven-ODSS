from pathlib import Path


path = Path("pilotdriven_odss_dashboard/tests/test_vaa.py")
text = path.read_text(encoding="utf-8")

broken = '    text = "\n"\n".join(page.extract_text() or "" for page in reader.pages)\n'
correct = '    text = "\\n".join(page.extract_text() or "" for page in reader.pages)\n'

if broken in text:
    text = text.replace(broken, correct, 1)
elif correct not in text:
    raise RuntimeError("Broken VAAC text-join assertion was not found")

path.write_text(text, encoding="utf-8")
