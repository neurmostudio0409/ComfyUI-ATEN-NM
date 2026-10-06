"""
ComfyUI-ATEN-NM 集中設定
所有常數、環境變數載入、節點分類都定義在這裡
"""

import os
import sys

# Windows 主控台可能是 cp950，emoji/中文輸出前先切 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ----------------------------------------------------------------------
# 路徑
# ----------------------------------------------------------------------
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(CONFIG_DIR)

# .env 搜尋順序：config/.env 優先，其次套件根目錄 .env
ENV_PATHS = [
    os.path.join(CONFIG_DIR, ".env"),
    os.path.join(PLUGIN_DIR, ".env"),
]

# ----------------------------------------------------------------------
# API Server 設定
# ----------------------------------------------------------------------
# 可在 .env 以 ATEN_API_URL 覆寫 API Server 位置
DEFAULT_BASE_URL = "https://www.aivoice.com.tw/atzone"

# 單次合成字數上限（含 SSML tag，不含 <speak>/<voice>）
MAX_TEXT_LENGTH = 2000

# ----------------------------------------------------------------------
# 隊列滿（42210）的退避重試（#1594）
# ----------------------------------------------------------------------
# 42210 是「現在滿了」不是「請求錯了」——單發不會踩到，排程一次產多段旁白
# 並發打 ATEN 就會穩定中。實測並發 10 次會中 2 次。
# 其餘 422xx（缺 token / 超字數 / ssml 格式錯）重試幾次都一樣，不在此列。
QUEUE_FULL_CODE = 42210
QUEUE_FULL_RETRY_DELAYS_S = [2, 5, 10, 20]   # 長度＝最多重試次數
QUEUE_FULL_RETRY_JITTER = 0.4                # 再隨機加 0～40%，整批不會同時醒來

# API rate limit：120 次/分鐘（輪詢間隔不要低於 0.5s）
RATE_LIMIT_PER_MINUTE = 120

# ----------------------------------------------------------------------
# ComfyUI 節點分類
# ----------------------------------------------------------------------
CATEGORY_TTS = "audio/ATEN/TTS"
CATEGORY_UTILS = "audio/ATEN/utils"

# ----------------------------------------------------------------------
# 聲優與語言
# ----------------------------------------------------------------------
# API 查詢失敗時的 fallback（欄位與 GET /models 回傳一致）
DEFAULT_VOICES = [
    {"model_id": "Aaron", "name": "沉穩男聲-裕祥", "gender": "男聲", "languages": ["中英文"]},
    {"model_id": "Shawn", "name": "斯文男聲-俊昇", "gender": "男聲", "languages": ["中英文"]},
    {"model_id": "Aurora", "name": "穩重女聲-嘉妮", "gender": "女聲", "languages": ["中英文"]},
    {"model_id": "Bella_host_bert", "name": "動人女聲-貝拉", "gender": "女聲", "languages": ["中英文"]},
]

# 聲優年齡標註：ATEN API「不提供」年齡欄位（實測回傳只有
# model_id/name/description/gender/languages/attrs.應用）。
# 需要在下拉選單顯示年齡時，請在此手動維護：
#   key = model_id，value = 顯示文字（如 "青年"、"中年"、"30歲"）
# 若未來 API 提供 age 或 attrs.年齡，會自動優先採用 API 的值。
VOICE_AGE_OVERRIDES = {
    # "Aaron": "中年",
    # "Bella_host_bert": "青年",
}

# <lang> 支援的語言（UI 顯示 → lang_type）
LANGUAGE_OPTIONS = {
    "TW (中文)": "TW",
    "EN (英文)": "EN",
    "TL (中文轉台語)": "TL",
    "TB (台語)": "TB",
    "HA (中文轉客語)": "HA",
    "HB (客語)": "HB",
}
DEFAULT_LANGUAGE = "TW (中文)"

# 每個 lang_type 需要聲優具備的語言能力關鍵字。
# ATEN 的 /models 會回 languages，實測只有三種值：中英文（19 位）/ 台英文（8 位）/ 客英文（3 位）。
# 規格書 Revision History v1.1.103 明寫「若需要其他語系，**除了 model 要支援外**，…」——
# 聲優不支援該語言時 API 會拒絕，所以送出前先擋掉，錯誤訊息才講得清楚是哪裡配錯。
LANG_REQUIREMENTS = {
    "TW": "中",    # 中文
    "TL": "台",    # 中文轉台語
    "TB": "台",    # 台語
    "HA": "客",    # 中文轉客語
    "HB": "客",    # 客語
    # EN 不列：三種組合都含英文
}

# ----------------------------------------------------------------------
# Error codes 對照表
# ----------------------------------------------------------------------
ERROR_CODES = {
    40301: "沒有使用此 model 的權限",
    40401: "API Token 不存在",
    40404: "合成紀錄不存在",
    40406: "model 不存在",
    42203: "缺少 Authorization header",
    42207: "超過單次合成字數",
    # 42208 不在 ATEN 規格書的錯誤碼表裡（v1.1.108 僅列 10 個碼）。
    # 2026-10-07 實測：最短、最保守的請求（純中文、無任何 tag、兩個字）也持續回 42208，
    # 而同組請求 25 分鐘前還成功 —— 不是 SSML 問題、不是聲優不匹配，也不是 42210 那種
    # 併發暫時性。位置落在 42207（單次字數）與 42210（隊列上限）之間，疑似帳號額度用罄。
    # ⚠️ 正式定義未經 ATEN 確認；請至 ATEN 後台核對額度。
    42208: "（ATEN 未記載）持續性拒絕，疑似帳號額度用罄——請至 ATEN 後台確認額度",
    42210: "目前在隊列內或合成中的任務已達到上限",
    42212: "ssml 格式錯誤",
    50001: "伺服器發生未知錯誤",
    50302: "資料庫發生錯誤",
}

HTTP_STATUS_HINTS = {
    # 規格書的 http status 表沒列 422，但 422xx 錯誤碼是配著它回的
    422: "請求被拒絕，詳見 error code",
    403: "沒有使用此 model 的權限",
    404: "找不到資源，URL 錯誤或尚未就緒",
    500: "伺服器發生未知的錯誤",
    503: "伺服器目前無法處理請求",
}

# SSML 保留字元 escape（& 必須最先處理）
SSML_ESCAPES = [
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("'", "&apos;"),
]

_PLACEHOLDER = "<paste-your-token-here>"


# ----------------------------------------------------------------------
# 環境變數載入
# ----------------------------------------------------------------------
def load_env(verbose: bool = False) -> bool:
    """
    從 ENV_PATHS 載入 ATEN_API_TOKEN / ATEN_API_URL 到環境變數。
    優先使用 python-dotenv，無則手動解析。

    Returns:
        bool: 是否成功取得 ATEN_API_TOKEN
    """
    try:
        from dotenv import load_dotenv
        for path in ENV_PATHS:
            if os.path.exists(path):
                load_dotenv(path)
    except ImportError:
        for path in ENV_PATHS:
            _parse_env_file(path)

    token = os.environ.get("ATEN_API_TOKEN", "")
    if token == _PLACEHOLDER:
        os.environ.pop("ATEN_API_TOKEN", None)
        token = ""

    if verbose:
        if token:
            print("✅ 已載入 ATEN API token")
        else:
            print("⚠️ ATEN_API_TOKEN 未配置")
            print("   請複製 config/.env.example 為 config/.env 並設定 ATEN_API_TOKEN")
    return bool(token)


def _parse_env_file(path: str):
    """簡易 .env 解析（python-dotenv 不可用時的保底）"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if value and value != _PLACEHOLDER:
                    os.environ.setdefault(key, value)
    except Exception as e:
        print(f"❌ 解析 {path} 時發生錯誤: {e}")


def get_api_token() -> str:
    """取得 API Token（空字串表示未設定）"""
    return os.environ.get("ATEN_API_TOKEN", "")


def get_base_url() -> str:
    """取得 API Server 位置"""
    return (os.environ.get("ATEN_API_URL") or DEFAULT_BASE_URL).rstrip("/")
