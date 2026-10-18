"""The compiler budget must be honored without dropping upstream regressions."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[1] / "ocr/build_component.py"
    spec = importlib.util.spec_from_file_location("ocr_parallelism_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("requested,expected", [(None, "2"), ("1", "1"), ("4", "4"), ("8", "8")])
def test_both_compilers_honor_the_bounded_worker_budget(builder, monkeypatch, requested, expected, sanitized):
    if requested is None:
        monkeypatch.delenv("CMAKE_BUILD_PARALLEL_LEVEL", raising=False)
    else:
        monkeypatch.setenv("CMAKE_BUILD_PARALLEL_LEVEL", requested)
    commands = []

    class CompileReached(Exception):
        pass

    def capture(name, command, **kwargs):
        commands.append(command)
        if name.endswith("-compile"):
            raise CompileReached
        return ""

    monkeypatch.setattr(builder, "run", capture)
    with pytest.raises(CompileReached):
        builder.compile_and_test(Path("/unused-source"), "probe", sanitized)
    compile_command = commands[-1]
    assert compile_command[compile_command.index("--parallel") + 1] == expected
    assert compile_command[compile_command.index("--target") + 1:] == ["tesseract", *builder.LOCK["regressions"]]
    assert any("-DBUILD_TESTS=ON" == arg for arg in commands[0])
    if sanitized:
        assert any("-fsanitize=address,undefined" in arg for arg in commands[0])


@pytest.mark.parametrize("requested", ["", "0", "-1", "9", "4.0", " 4", "4 ", "auto", "04"])
def test_invalid_worker_budget_fails_before_any_build_command(builder, monkeypatch, requested):
    monkeypatch.setenv("CMAKE_BUILD_PARALLEL_LEVEL", requested)
    commands = []
    monkeypatch.setattr(builder, "run", lambda *args, **kwargs: commands.append(args))
    with pytest.raises(ValueError, match="CMAKE_BUILD_PARALLEL_LEVEL"):
        builder.compile_and_test(Path("/unused-source"), "probe", False)
    assert commands == []
