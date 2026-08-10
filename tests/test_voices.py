from nate_e2a.get_model import DEFAULT_VOICE, VOICE_SPECS


def test_voice_registry():
    assert DEFAULT_VOICE == "alan"
    assert VOICE_SPECS["alan"]["model_filename"] == "en_GB-alan-medium.onnx"
    assert VOICE_SPECS["joe"] == {
        "model_filename": "en_US-joe-medium.onnx",
        "config_filename": "en_US-joe-medium.onnx.json",
        "weights_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_US/joe/medium/en_US-joe-medium.onnx?download=true"
        ),
        "config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            "en/en_US/joe/medium/en_US-joe-medium.onnx.json?download=true"
        ),
    }
