"""
ATEN AIVoice ComfyUI 節點
分類：
  audio/ATEN/TTS   — AtenSpeechNode, AtenSSMLNode
  audio/ATEN/utils — AtenGetVoicesNode
"""

import json
import os

from ..config.settings import (
    CATEGORY_TTS,
    CATEGORY_UTILS,
    DEFAULT_LANGUAGE,
    DEFAULT_VOICES,
    LANGUAGE_OPTIONS,
    VOICE_AGE_OVERRIDES,
)
from .aten_api import AtenAPI, AtenAPIError, build_ssml, get_temp_directory
from .audio_utils import load_audio_as_comfyui_format

# 全域變數：快取聲優「中文顯示名」列表，以及 顯示名 → model_id 對照表
_CACHED_VOICE_LABELS = None
_VOICE_LABEL_TO_ID = {}


def _voice_age(model: dict) -> str:
    """取得聲優年齡：API 的 age / attrs.年齡 優先，其次 config 手動維護表"""
    age = model.get("age")
    if not age:
        attrs = model.get("attrs")
        if isinstance(attrs, dict):
            age = attrs.get("年齡") or attrs.get("age")
    if not age:
        model_id = model.get("model_id") or model.get("id")
        age = VOICE_AGE_OVERRIDES.get(str(model_id), "")
    return str(age) if age else ""


def _voice_label(model: dict) -> str:
    """組出下拉選單的中文顯示名：中文名｜性別｜年齡｜語系"""
    name = model.get("name") or model.get("model_id") or "未知聲優"
    parts = [str(name)]
    gender = model.get("gender")
    if gender:
        parts.append(str(gender))
    age = _voice_age(model)
    if age:
        parts.append(age)
    languages = model.get("languages") or []
    if languages:
        parts.append("/".join(str(lang) for lang in languages))
    return "｜".join(parts)


def _build_voice_labels(models):
    """把 models 轉成顯示名列表並填入對照表（重名時附 model_id 區別）"""
    global _VOICE_LABEL_TO_ID
    labels = []
    label_map = {}
    for m in models:
        if not isinstance(m, dict):
            continue
        model_id = m.get("model_id") or m.get("id") or m.get("name")
        if not model_id:
            continue
        label = _voice_label(m)
        if label in label_map and label_map[label] != str(model_id):
            label = f"{label}（{model_id}）"
        label_map[label] = str(model_id)
        labels.append(label)
    _VOICE_LABEL_TO_ID = label_map
    return labels


def get_voice_list():
    """獲取聲優中文顯示名列表，使用快取避免重複請求"""
    global _CACHED_VOICE_LABELS

    if _CACHED_VOICE_LABELS is not None:
        return _CACHED_VOICE_LABELS

    try:
        api = AtenAPI()
        labels = _build_voice_labels(api.get_models())
        if labels:
            _CACHED_VOICE_LABELS = labels
            print(f"✅ 已載入 {len(labels)} 位 ATEN 聲優")
            return labels
    except Exception as e:
        print(f"⚠️ 無法取得 ATEN 聲優列表: {e}")

    _CACHED_VOICE_LABELS = _build_voice_labels(DEFAULT_VOICES)
    print(f"⚠️ 使用預設聲優列表 ({len(_CACHED_VOICE_LABELS)} 位)")
    return _CACHED_VOICE_LABELS


def resolve_voice_id(label: str) -> str:
    """顯示名 → model_id。找不到時視為使用者直接給了 model_id（相容舊工作流）"""
    return _VOICE_LABEL_TO_ID.get(label, label)


def _print_api_key_help():
    print("\n請確保：")
    print("1. 複製 config/.env.example 為 config/.env")
    print("2. 在 config/.env 中設定 ATEN_API_TOKEN")
    print("3. 如使用自訂 API Server，請一併設定 ATEN_API_URL")


def _synthesize_and_load(ssml: str, silence_scale: float, timeout: float):
    """
    共用：送出 SSML 合成並載入為 AUDIO。
    音檔只下載到 temp 目錄，載入後即刪除——正式保存交給下游 SaveAudio，
    避免同一段語音被保存兩次。
    """
    api = AtenAPI()
    audio_path = api.synthesize_to_file(
        ssml,
        output_filename="aten_tts",
        silence_scale=silence_scale,
        timeout=timeout,
        output_dir=get_temp_directory(),
    )

    if audio_path and os.path.exists(audio_path):
        print("=" * 60)
        print("✅ 語音生成完成！")
        print("=" * 60)
        audio_dict, _ = load_audio_as_comfyui_format(audio_path)
        try:
            os.remove(audio_path)
        except OSError:
            pass
        if audio_dict:
            return (audio_dict,)
    print("❌ 語音生成失敗！")
    return (None,)


# ======================
# TTS 節點
# ======================

class AtenSpeechNode:
    """
    ComfyUI 節點：ATEN AIVoice 文字轉語音（自動組 SSML）
    """

    @classmethod
    def INPUT_TYPES(cls):
        voices = get_voice_list()

        return {
            "required": {
                "text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "要轉換成語音的文字（上限 2000 字元）",
                }),
                "voice": (voices, {
                    "default": voices[0] if voices else "沉穩男聲-裕祥｜男聲｜中英文",
                    "tooltip": "聲優（中文名｜性別｜語系，從 ATEN API 動態載入）",
                }),
            },
            "optional": {
                "language": (list(LANGUAGE_OPTIONS.keys()), {
                    "default": DEFAULT_LANGUAGE,
                    "tooltip": "第一語言順位：中/英/台/客語",
                }),
                "speed": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.8,
                    "max": 1.2,
                    "step": 0.01,
                    "tooltip": "語速 (prosody rate 0.8~1.2)",
                }),
                "pitch": ("FLOAT", {
                    "default": 0.0,
                    "min": -2.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "音調偏移，半音 (-2st ~ +2st)",
                }),
                "volume": ("FLOAT", {
                    "default": 0.0,
                    "min": -6.0,
                    "max": 6.0,
                    "step": 0.5,
                    "tooltip": "音量 (-6dB ~ +6dB)",
                }),
                "silence_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.8,
                    "max": 1.2,
                    "step": 0.01,
                    "tooltip": "標點符號停頓時間微調 (0.8~1.2)",
                }),
                "timeout": ("INT", {
                    "default": 300,
                    "min": 30,
                    "max": 1800,
                    "step": 30,
                    "tooltip": "合成等待逾時（秒）",
                }),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "ssml")
    FUNCTION = "generate_speech"
    CATEGORY = CATEGORY_TTS

    def generate_speech(
        self,
        text,
        voice,
        language=DEFAULT_LANGUAGE,
        speed=1.0,
        pitch=0.0,
        volume=0.0,
        silence_scale=1.0,
        timeout=300,
    ):
        print("=" * 60)
        print("🎙️ ATEN AIVoice 語音生成")
        print("=" * 60)

        if not text.strip():
            print("❌ 文字內容為空")
            return (None, "")

        lang_type = LANGUAGE_OPTIONS.get(language, "TW")
        voice_id = resolve_voice_id(voice)
        print(f"🎤 聲優: {voice} → {voice_id}")
        ssml = build_ssml(
            text,
            voice=voice_id,
            pitch=pitch,
            rate=speed,
            volume=volume,
            lang_type=lang_type,
        )
        print(f"📝 SSML: {ssml[:200]}{'...' if len(ssml) > 200 else ''}")

        try:
            result = _synthesize_and_load(ssml, silence_scale, float(timeout))
            return (result[0], ssml)
        except ValueError as e:
            print(f"❌ API 初始化失敗: {e}")
            _print_api_key_help()
            return (None, ssml)
        except AtenAPIError as e:
            print(f"❌ ATEN API 錯誤: {e}")
            return (None, ssml)
        except Exception as e:
            print(f"❌ 生成時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return (None, ssml)


class AtenSSMLNode:
    """
    ComfyUI 節點：ATEN AIVoice SSML 合成（進階，直接輸入 SSML）
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ssml": ("STRING", {
                    "default": (
                        '<speak xmlns="http://www.w3.org/2001/10/synthesis" '
                        'version="1.5" xml:lang="zh-TW">'
                        '<voice name="Aaron">這是一個測試</voice></speak>'
                    ),
                    "multiline": True,
                    "tooltip": "完整 SSML v1.5（支援 phoneme/break/prosody/lang/say-as）",
                }),
            },
            "optional": {
                "silence_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.8,
                    "max": 1.2,
                    "step": 0.01,
                    "tooltip": "標點符號停頓時間微調 (0.8~1.2)",
                }),
                "timeout": ("INT", {
                    "default": 300,
                    "min": 30,
                    "max": 1800,
                    "step": 30,
                    "tooltip": "合成等待逾時（秒）",
                }),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate_from_ssml"
    CATEGORY = CATEGORY_TTS

    def generate_from_ssml(self, ssml, silence_scale=1.0, timeout=300):
        print("=" * 60)
        print("🎙️ ATEN AIVoice SSML 合成")
        print("=" * 60)

        if not ssml.strip():
            print("❌ SSML 內容為空")
            return (None,)

        try:
            return _synthesize_and_load(ssml, silence_scale, float(timeout))
        except ValueError as e:
            print(f"❌ API 初始化失敗: {e}")
            _print_api_key_help()
            return (None,)
        except AtenAPIError as e:
            print(f"❌ ATEN API 錯誤: {e}")
            return (None,)
        except Exception as e:
            print(f"❌ 生成時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return (None,)


# ======================
# 工具節點
# ======================

class AtenGetVoicesNode:
    """
    ComfyUI 節點：取得 ATEN 可用聲優列表
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("voices_info",)
    FUNCTION = "get_voices"
    CATEGORY = CATEGORY_UTILS
    OUTPUT_NODE = True

    def get_voices(self):
        print("=" * 60)
        print("📋 取得 ATEN 聲優列表")
        print("=" * 60)

        try:
            api = AtenAPI()
            models = api.get_models()

            if models:
                voices_text = json.dumps(models, ensure_ascii=False, indent=2)
                print(voices_text)
                return (voices_text,)
            return ("❌ 無法取得聲優列表",)

        except ValueError as e:
            error_msg = f"❌ API 初始化失敗: {e}"
            print(error_msg)
            _print_api_key_help()
            return (error_msg,)
        except Exception as e:
            error_msg = f"❌ 錯誤: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return (error_msg,)


# ======================
# 節點註冊
# ======================

NODE_CLASS_MAPPINGS = {
    "AtenSpeechNode": AtenSpeechNode,
    "AtenSSMLNode": AtenSSMLNode,
    "AtenGetVoicesNode": AtenGetVoicesNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AtenSpeechNode": "🎙️ ATEN 語音 / Speech (文字轉語音)",
    "AtenSSMLNode": "📜 ATEN SSML 合成 (進階)",
    "AtenGetVoicesNode": "📋 ATEN 聲優列表 / Get Voices",
}
