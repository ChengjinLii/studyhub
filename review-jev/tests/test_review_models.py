from types import SimpleNamespace

import pytest
from test_review_guard import request

from review_jev.backends import BackendUnavailable
from review_jev.config import Settings
from review_jev.media import prepare_images
from review_jev.shieldgemma import ShieldGemmaBackend


def test_removed_cascade_module_is_not_shipped():
    import importlib.util

    assert importlib.util.find_spec("review_jev.cascade") is None


def test_native_image_adapter_preserves_image_and_policy_mapping():
    torch = pytest.importorskip("torch")
    backend = ShieldGemmaBackend(Settings())
    calls = []

    class Inputs(dict):
        def to(self, device):
            return self

    def processor(**kwargs):
        calls.append(kwargs)
        assert set(kwargs) == {"images", "policies", "return_tensors"}
        assert kwargs["policies"] == ["sexual", "dangerous", "violence"]
        assert len(kwargs["images"]) == 1
        return Inputs(
            input_ids=torch.tensor([[1, 2], [1, 2], [1, 2]]), attention_mask=torch.ones(3, 2)
        )

    class Model:
        device = "cpu"

        def __call__(self, **inputs):
            return SimpleNamespace(logits=torch.tensor([[9, -9], [-9, 9], [-9, 9]]))

    backend.processor, backend.model = processor, Model()
    media = prepare_images(request("", 2).content).media
    response = backend.decide({"image_ids": ["first", "second"]}, {}, media)
    assert len(calls) == 2 and len(response.scores) == 6
    assert [score.input_id for score in response.scores] == ["first"] * 3 + ["second"] * 3
    assert response.scores[0].probabilities["Yes"] > 0.999
    assert response.scores[1].probabilities["Yes"] < 0.001
    assert response.usage["input_tokens"] == 12
    backend.close()
    assert not backend.ready()


def test_image_backend_refuses_text_only_before_loading():
    with pytest.raises(BackendUnavailable, match="no_images"):
        ShieldGemmaBackend(Settings()).decide({}, {}, [])


def test_invalid_image_id_mapping_refused_before_loading():
    with pytest.raises(BackendUnavailable, match="mismatch"):
        ShieldGemmaBackend(Settings()).decide({"image_ids": []}, {}, [{"data": "untrusted"}])
