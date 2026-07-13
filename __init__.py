"""
ComfyUI ATEN AIVoice API 整合模組
支援 ATEN 中/英/台/客語 TTS 語音合成服務

結構：
  config/   — 集中設定（settings.py、.env）
  modules/  — API 客戶端、節點、音訊工具
"""

# pytest 等工具可能把本檔當「頂層模組」匯入（無父套件），
# 此時相對匯入不可用，跳過 ComfyUI 節點註冊即可。
if __package__:
    from .config.settings import load_env
    from .modules.aten_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

    # 註冊自訂 API 路由
    try:
        from aiohttp import web
        from server import PromptServer

        @PromptServer.instance.routes.get("/aten/voices")
        async def get_aten_voices(request):
            """GET /aten/voices - 取得可用聲優列表"""
            try:
                from .modules.aten_api import AtenAPI
                api = AtenAPI()
                models = api.get_models()
                return web.json_response({"success": True, "data": models})
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=500)

        print("✅ 已註冊 API 路由: GET /aten/voices")
    except Exception as e:
        print(f"⚠️ 無法註冊 API 路由（可能不在 ComfyUI 環境中）: {e}")

    # 模組載入時載入 API token
    load_env(verbose=True)

    print("=" * 70)
    print("🎙️ ComfyUI ATEN AIVoice TTS - 語音合成支援 v1.0")
    print("=" * 70)
    print("📦 支援的功能：")
    print("   🎙️ 文字轉語音（自動組 SSML，含保留字元 escape）")
    print("   📜 SSML 直接合成（phoneme/break/prosody/lang/say-as）")
    print("   📋 聲優列表查詢")
    print("=" * 70)
    print("✨ 特色：")
    print("   🇹🇼 支援中文、英文、台語(TL/TB)、客語(HA/HB)")
    print("   ⚙️ 可調整語速、音調、音量、停頓時間")
    print("   🔄 自動輪詢合成狀態並下載 WAV")
    print("=" * 70)
else:
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

# ComfyUI 相容性
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
