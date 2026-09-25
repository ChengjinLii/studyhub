import hashlib
from importlib import resources

import studyhub_agent
from studyhub_agent.contracts.render import TEMPLATE_SHA256


def test_version_is_v3() -> None:
    assert studyhub_agent.__version__ == "3.0.0"


def test_chat_template_is_shipped_and_loadable_via_importlib_resources() -> None:
    # Regression guard for a wheel packaging bug (a stale force-include table duplicated this
    # file in the built wheel and broke `pip install .`). importlib.resources is how an installed,
    # non-editable package should locate its own data files, independent of `contracts/render.py`'s
    # own `Path(__file__)` loading, so this exercises the packaging contract, not the loader.
    template = resources.files("studyhub_agent.contracts").joinpath("templates", "qwen3_5.jinja")
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    assert digest == TEMPLATE_SHA256
