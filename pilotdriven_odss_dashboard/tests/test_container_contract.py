from pathlib import Path


DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()


def test_runtime_uses_supported_lts_python_and_playwright_contract() -> None:
    assert DOCKERFILE.startswith("FROM ubuntu:24.04 AS dependencies\n")
    assert "python3 -m venv /opt/venv" in DOCKERFILE
    assert "PATH=/opt/venv/bin:$PATH" in DOCKERFILE
    assert (
        "python -m playwright install --with-deps --only-shell chromium"
        in DOCKERFILE
    )
    assert "FROM dependencies AS runtime" in DOCKERFILE
    assert "COPY --from=test /tmp/odss-tests-passed /app/.tests-passed" in DOCKERFILE
    assert "python3-pip-whl" in DOCKERFILE.split("apt-get purge --yes", 1)[1]
    assert "python3-venv" in DOCKERFILE.split("apt-get purge --yes", 1)[1]
    assert "groupadd --gid 1000" not in DOCKERFILE
    assert "USER 1000:1000" in DOCKERFILE
