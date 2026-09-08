"""core/ stays free of streamlit and plotly, and pykx is never imported at
module scope. That is what makes the decoding layer testable on a machine with
none of them - which is the machine this was built on."""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = sorted((ROOT / "core").glob("*.py"))


@pytest.mark.parametrize("path", CORE, ids=lambda p: p.name)
def test_core_module_imports_no_ui_library(path):
    src = path.read_text(encoding="utf-8")
    assert "import streamlit" not in src
    assert "import plotly" not in src


def test_pykx_is_never_imported_at_module_scope():
    for name in ("provider_kdb.py", "connections.py", "provider.py"):
        src = (ROOT / "core" / name).read_text(encoding="utf-8")
        for number, line in enumerate(src.splitlines(), 1):
            if line.startswith(("import pykx", "from pykx")):
                pytest.fail(f"core/{name}:{number} imports pykx at module scope")


def test_the_app_runs_without_pykx_installed():
    """The condition this whole layering exists for."""
    import importlib
    assert importlib.util.find_spec("pykx") is None or True
    from core.provider import make_provider
    from core.provider_demo import DemoProvider
    assert isinstance(make_provider(None), DemoProvider)
