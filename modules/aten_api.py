"""
ATEN AIVoice API 客戶端
依 ATEN AIVoice API 使用說明 v1.2.111 實作

合成流程：
1. POST Synthesize SSML 取得 synthesis_id
2. 輪詢 Get Synthesize Status 直到 Success
3. GET synthesis_path 下載 WAV 音檔
"""

import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from ..config.settings import (
    DEFAULT_BASE_URL,
    ERROR_CODES,
    HTTP_STATUS_HINTS,
    MAX_TEXT_LENGTH,
    SSML_ESCAPES,
    get_api_token,
    get_base_url,
    load_env,
)

# 模組載入時先確保 .env 已讀入
load_env()

# Try to import ComfyUI's folder_paths, use fallback if not available
try:
    import folder_paths
except ImportError:
    import tempfile

    class FolderPaths:
        @staticmethod
        def get_output_directory():
            return os.path.join(os.getcwd(), "output")

        @staticmethod
        def get_temp_directory():
            return os.path.join(tempfile.gettempdir(), "comfyui_aten")
    folder_paths = FolderPaths()


def get_temp_directory() -> str:
    """取得暫存目錄（合成的 WAV 放這裡，正式保存交給下游 SaveAudio）"""
    try:
        return folder_paths.get_temp_directory()
    except Exception:
        import tempfile
        return os.path.join(tempfile.gettempdir(), "comfyui_aten")


def escape_ssml_text(text: str) -> str:
    """將文字中的 SSML 保留字元轉為 escape code"""
    for char, code in SSML_ESCAPES:
        text = text.replace(char, code)
    return text


def build_ssml(
    text: str,
    voice: str,
    pitch: float = 0.0,
    rate: float = 1.0,
    volume: float = 0.0,
    lang_type: str = "TW",
    escape_text: bool = True,
) -> str:
    """
    將純文字組成 ATEN SSML v1.5

    Args:
        text: 要合成的文字
        voice: 聲優 model_id（如 "Aaron", "Bella_host"）
        pitch: 音調偏移，範圍 -2 ~ +2 半音(st)
        rate: 語速，範圍 0.8 ~ 1.2
        volume: 音量，範圍 -6 ~ +6 dB
        lang_type: 第一語言順位 TW/EN/TL/TB/HA/HB（TW 為預設可不包 lang tag）
        escape_text: 是否 escape 保留字元
    """
    body = escape_ssml_text(text) if escape_text else text
    body = body.strip()

    if lang_type and lang_type != "TW":
        body = f'<lang lang_type="{lang_type}">{body}</lang>'

    # 僅在非預設值時包 prosody，節省字元數（tag 也算字數）
    prosody_attrs = []
    if abs(pitch) > 1e-6:
        prosody_attrs.append(f'pitch="{pitch:+.1f}st"')
    if abs(rate - 1.0) > 1e-6:
        prosody_attrs.append(f'rate="{rate:.2f}"')
    if abs(volume) > 1e-6:
        prosody_attrs.append(f'volume="{volume:+.1f}dB"')

    if prosody_attrs:
        body = f'<prosody {" ".join(prosody_attrs)}>{body}</prosody>'

    return (
        '<speak xmlns="http://www.w3.org/2001/10/synthesis" '
        f'version="1.5" xml:lang="zh-TW"><voice name="{voice}">{body}</voice></speak>'
    )


def get_unique_filename(output_dir: str, base_name: str, extension: str) -> str:
    """生成唯一的檔案名稱，使用8位序號"""
    counter = 1
    while True:
        filename = f"{base_name}_{counter:08d}.{extension}"
        full_path = os.path.join(output_dir, filename)
        if not os.path.exists(full_path):
            return full_path
        counter += 1
        if counter > 99999999:
            filename = f"{base_name}_{int(time.time())}.{extension}"
            return os.path.join(output_dir, filename)


class AtenAPIError(Exception):
    """ATEN API 錯誤，帶有官方 error code 說明"""

    def __init__(self, message: str, code: Optional[int] = None):
        self.code = code
        if code and code in ERROR_CODES:
            message = f"{message} (error {code}: {ERROR_CODES[code]})"
        super().__init__(message)


class AtenAPI:
    """
    ATEN AIVoice TTS API 客戶端
    """

    def __init__(self, api_token: Optional[str] = None, base_url: Optional[str] = None):
        """
        Args:
            api_token: ATEN API Token（User Settings 取得）。未提供時讀環境變數 ATEN_API_TOKEN。
            base_url: API Server 位置。未提供時讀環境變數 ATEN_API_URL，預設為 atzone。
        """
        self.api_token = api_token or get_api_token()
        self.base_url = (base_url or get_base_url() or DEFAULT_BASE_URL).rstrip("/")

        if not self.api_token:
            raise ValueError(
                "找不到 ATEN API Token。請執行以下任一方式：\n"
                "1. 複製 config/.env.example 為 config/.env 並設定 ATEN_API_TOKEN\n"
                "2. 初始化 AtenAPI 時提供 api_token 參數\n"
                "Token 可從 ATEN AIVoice 網站的 User Settings 取得"
            )

        self.session = requests.Session()
        self.session.headers.update({"Authorization": self.api_token})

    # ------------------------------------------------------------------
    # 四、Query Model (支援聲優查詢)
    # ------------------------------------------------------------------
    def get_models(self) -> List[Dict[str, Any]]:
        """
        取得可用聲優列表

        Returns:
            List[Dict]: [{"model_id": ..., "name": ..., "description": ...}, ...]
        """
        url = f"{self.base_url}/api/v1/models/api_token"
        resp = self.session.get(url, timeout=30)
        self._raise_for_error(resp, "查詢聲優列表失敗")
        data = resp.json()
        # atzone 版回傳裸陣列 [{...}]；PDF 文件寫的是 {"data": [...]}，兩種都支援
        if isinstance(data, list):
            models = data
        elif isinstance(data, dict):
            models = data.get("data", [])
        else:
            models = []
        return models if isinstance(models, list) else []

    # ------------------------------------------------------------------
    # 五、Synthesize SSML
    # ------------------------------------------------------------------
    def synthesize_ssml(
        self,
        ssml: str,
        silence_scale: Optional[float] = None,
        is_customized_poly_list_used: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        送出 SSML 合成任務

        Args:
            ssml: SSML v1.5 文字
            silence_scale: 0.8 ~ 1.2，微調標點符號停頓時間
            is_customized_poly_list_used: 是否使用網頁設定的自訂多音字字典

        Returns:
            Dict: {"synthesis_id": ..., "synthesis_path": ..., "srt_path": ...}
        """
        # 字數檢查：扣除 <speak>/<voice> tag 後不可超過 2000 字元
        countable = re.sub(r"</?speak[^>]*>|</?voice[^>]*>", "", ssml)
        if len(countable) > MAX_TEXT_LENGTH:
            raise AtenAPIError(
                f"文字長度 {len(countable)} 超過單次合成上限 {MAX_TEXT_LENGTH} 字元"
                "（<phoneme>/<prosody>/<break> 等標籤長度也計入）",
                code=42207,
            )

        payload: Dict[str, Any] = {"ssml": ssml}
        if silence_scale is not None and abs(silence_scale - 1.0) > 1e-6:
            payload["silence_scale"] = silence_scale
        if is_customized_poly_list_used is not None:
            payload["is_customized_poly_list_used"] = is_customized_poly_list_used

        url = f"{self.base_url}/api/v1/syntheses/api_token"
        resp = self.session.post(url, json=payload, timeout=60)
        self._raise_for_error(resp, "送出合成任務失敗")
        return resp.json()

    # ------------------------------------------------------------------
    # 六、Get Synthesize Status
    # ------------------------------------------------------------------
    def get_status(self, synthesis_id: str) -> Dict[str, Any]:
        """查詢合成任務狀態（Waiting / Proccessing / Success / Error）"""
        url = f"{self.base_url}/api/v1/syntheses/{synthesis_id}/api_token"
        resp = self.session.get(url, timeout=30)
        self._raise_for_error(resp, "查詢合成狀態失敗")
        return resp.json()

    def wait_for_synthesis(
        self,
        synthesis_id: str,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """
        輪詢直到合成完成

        Args:
            synthesis_id: 合成任務 ID
            poll_interval: 輪詢間隔秒數（注意 API rate limit 120/min）
            timeout: 最長等待秒數

        Returns:
            Dict: 最終狀態回應（含 synthesis_path）
        """
        start = time.time()
        while True:
            status_data = self.get_status(synthesis_id)
            status = status_data.get("status", "")

            if status == "Success":
                return status_data
            if status == "Error":
                code = status_data.get("code") or status_data.get("error_code")
                raise AtenAPIError(f"合成失敗 (synthesis_id={synthesis_id})", code=code)

            if time.time() - start > timeout:
                raise AtenAPIError(
                    f"合成逾時（{timeout}s），最後狀態: {status} (synthesis_id={synthesis_id})"
                )

            print(f"⏳ 合成狀態: {status or '未知'}，{poll_interval}s 後重試...")
            time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # 七、Get Audio File
    # ------------------------------------------------------------------
    def download_audio(self, synthesis_path: str, output_path: str, retries: int = 5) -> str:
        """
        下載合成音檔（WAV）

        Args:
            synthesis_path: 狀態 API 回傳的音檔 URL（可能為完整 URL 或相對路徑）
            output_path: 儲存路徑
            retries: 404（尚未合成完畢）時的重試次數
        """
        if synthesis_path.startswith("http"):
            url = synthesis_path
        else:
            url = f"{self.base_url}/{synthesis_path.lstrip('/')}"

        for attempt in range(retries):
            resp = self.session.get(url, timeout=120)
            if resp.status_code == 200:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return output_path
            if resp.status_code == 404 and attempt < retries - 1:
                # 音檔尚未就緒，稍候重試
                print(f"⏳ 音檔尚未就緒 (404)，重試 {attempt + 1}/{retries}...")
                time.sleep(1.0)
                continue
            self._raise_for_error(resp, "下載音檔失敗")

        raise AtenAPIError("下載音檔失敗：重試次數用盡")

    # ------------------------------------------------------------------
    # 完整合成 pipeline
    # ------------------------------------------------------------------
    def synthesize_to_file(
        self,
        ssml: str,
        output_filename: str = "aten_speech",
        silence_scale: Optional[float] = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
        output_dir: Optional[str] = None,
    ) -> str:
        """
        送出 SSML → 輪詢 → 下載 WAV，回傳檔案路徑

        Args:
            output_dir: 儲存目錄。未指定時存到 ComfyUI output/；
                        節點內部會傳入 temp 目錄，避免與下游 SaveAudio 重複保存。
        """
        print(f"📤 送出合成任務（{len(ssml)} 字元 SSML）...")
        result = self.synthesize_ssml(ssml, silence_scale=silence_scale)
        synthesis_id = result.get("synthesis_id")
        if not synthesis_id:
            raise AtenAPIError(f"API 未回傳 synthesis_id: {result}")

        print(f"🆔 synthesis_id: {synthesis_id}")
        status_data = self.wait_for_synthesis(
            synthesis_id, poll_interval=poll_interval, timeout=timeout
        )

        synthesis_path = status_data.get("synthesis_path") or result.get("synthesis_path")
        if not synthesis_path:
            raise AtenAPIError("找不到 synthesis_path，無法下載音檔")

        if output_dir is None:
            output_dir = folder_paths.get_output_directory()
        os.makedirs(output_dir, exist_ok=True)
        output_path = get_unique_filename(output_dir, output_filename, "wav")

        print("⬇️ 下載音檔...")
        return self.download_audio(synthesis_path, output_path)

    # ------------------------------------------------------------------
    @staticmethod
    def _raise_for_error(resp: requests.Response, message: str):
        """依附件一的 http status / error code 拋出友善錯誤"""
        if resp.status_code == 200:
            return

        code = None
        detail = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                code = body.get("code") or body.get("error_code")
                detail = body.get("message") or body.get("detail") or ""
        except Exception:
            detail = (resp.text or "")[:200]

        hint = HTTP_STATUS_HINTS.get(resp.status_code, "")
        parts = [message, f"HTTP {resp.status_code}"]
        if hint:
            parts.append(hint)
        if detail:
            parts.append(str(detail))
        raise AtenAPIError("，".join(parts), code=code)
