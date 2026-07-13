"""
ComfyUI-ATEN-NM 單元測試
不需要 torch / soundfile / ComfyUI，可在 CI 直接跑
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_NAME = "comfyui_aten_nm"


def _load_package():
    if PKG_NAME in sys.modules:
        return sys.modules[PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        PKG_NAME,
        os.path.join(ROOT, "__init__.py"),
        submodule_search_locations=[ROOT],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pkg():
    # 確保測試不受本機 .env 影響
    os.environ.pop("ATEN_API_TOKEN", None)
    return _load_package()


def _api_module():
    return sys.modules[f"{PKG_NAME}.modules.aten_api"]


# ----------------------------------------------------------------------
# 節點註冊
# ----------------------------------------------------------------------

def test_node_mappings(pkg):
    assert set(pkg.NODE_CLASS_MAPPINGS) == {
        "AtenSpeechNode", "AtenSSMLNode", "AtenGetVoicesNode",
    }
    assert set(pkg.NODE_DISPLAY_NAME_MAPPINGS) == set(pkg.NODE_CLASS_MAPPINGS)


def test_input_types_fallback_without_token(pkg):
    """無 token 時 INPUT_TYPES 應 fallback 預設聲優，不能拋例外"""
    it = pkg.NODE_CLASS_MAPPINGS["AtenSpeechNode"].INPUT_TYPES()
    voices = it["required"]["voice"][0]
    assert isinstance(voices, list) and len(voices) > 0


def test_categories(pkg):
    cats = {c.CATEGORY for c in pkg.NODE_CLASS_MAPPINGS.values()}
    assert cats == {"audio/ATEN/TTS", "audio/ATEN/utils"}


# ----------------------------------------------------------------------
# SSML 組裝
# ----------------------------------------------------------------------

def test_build_ssml_basic(pkg):
    api = _api_module()
    ssml = api.build_ssml("你好", voice="Aaron")
    assert ssml.startswith('<speak xmlns="http://www.w3.org/2001/10/synthesis"')
    assert 'version="1.5"' in ssml
    assert '<voice name="Aaron">你好</voice>' in ssml
    # 預設參數不應產生 prosody / lang tag（節省字元數）
    assert "<prosody" not in ssml
    assert "<lang" not in ssml


def test_build_ssml_escapes_reserved_chars(pkg):
    api = _api_module()
    ssml = api.build_ssml('<A&B> "q" \'s\'', voice="Aaron")
    assert "&lt;A&amp;B&gt;" in ssml
    assert "&quot;q&quot;" in ssml
    assert "&apos;s&apos;" in ssml


def test_build_ssml_prosody_and_lang(pkg):
    api = _api_module()
    ssml = api.build_ssml(
        "測試", voice="Bella_host", pitch=-1.5, rate=1.2, volume=3.0, lang_type="TB",
    )
    assert 'pitch="-1.5st"' in ssml
    assert 'rate="1.20"' in ssml
    assert 'volume="+3.0dB"' in ssml
    assert '<lang lang_type="TB">' in ssml


# ----------------------------------------------------------------------
# API 客戶端（不打網路）
# ----------------------------------------------------------------------

def test_api_requires_token(pkg):
    api = _api_module()
    with pytest.raises(ValueError):
        api.AtenAPI(api_token=None)


def test_synthesize_rejects_over_limit(pkg):
    """超過 2000 字元須在送出前就拋 AtenAPIError（不打網路）"""
    api = _api_module()
    client = api.AtenAPI(api_token="dummy-token")
    long_ssml = api.build_ssml("好" * 2001, voice="Aaron")
    with pytest.raises(api.AtenAPIError) as exc:
        client.synthesize_ssml(long_ssml)
    assert exc.value.code == 42207


def test_error_code_message(pkg):
    api = _api_module()
    err = api.AtenAPIError("測試", code=42212)
    assert "ssml 格式錯誤" in str(err)
