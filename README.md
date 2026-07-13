# ComfyUI-ATEN-NM

ATEN AIVoice（宏正自動科技）TTS 語音合成的 ComfyUI 自製節點套件。
支援中文、英文、台語（TL/TB）、客語（HA/HB）語音合成，輸出 ComfyUI `AUDIO` 格式，可直接串接語音對嘴（wav2lip / LatentSync）、影片配音等下游節點。

依 **ATEN AIVoice API 使用說明 v1.2.111** 實作。

## 專案結構

```
ComfyUI-ATEN-NM/
├── __init__.py              # 節點註冊、/aten/voices 路由、.env 載入
├── config/                  # 集中設定
│   ├── settings.py          #   常數、錯誤碼表、語言表、節點分類、.env 載入
│   └── .env.example         #   複製為 config/.env 後填 token
├── modules/                 # 功能模組
│   ├── aten_api.py          #   API 客戶端（合成/輪詢/下載）
│   ├── aten_nodes.py        #   ComfyUI 節點定義
│   └── audio_utils.py       #   WAV → ComfyUI AUDIO 轉換
├── requirements.txt
└── install_requirements.bat
```

節點在 ComfyUI 選單中的分類：

- `audio/ATEN/TTS` — 語音合成節點
- `audio/ATEN/utils` — 聲優查詢等工具節點

## 節點

| 節點 | 說明 |
|------|------|
| 🎙️ **ATEN 語音 / Speech** | 純文字輸入，自動組 SSML（含保留字元 escape）。可選聲優、語言、語速、音調、音量、停頓微調。輸出 `AUDIO` 與組好的 `ssml` 字串 |
| 📜 **ATEN SSML 合成 (進階)** | 直接輸入完整 SSML v1.5，支援 `<phoneme>`（注音/IPA/ARPAbet/臺羅/客語音標）、`<break>`、`<prosody>`、`<lang>`、`<say-as>` |
| 📋 **ATEN 聲優列表 / Get Voices** | 查詢帳號可用聲優（model_id / name / description） |

## 安裝

1. 將本資料夾放入 `ComfyUI/custom_nodes/`
2. 安裝依賴：

   ```bat
   install_requirements.bat
   ```

   或手動：

   ```bat
   ..\..\..\python_embeded\python.exe -m pip install -r requirements.txt
   ```

3. 複製 `config/.env.example` 為 `config/.env`，填入 API Token（放套件根目錄 `.env` 也可以）：

   ```dotenv
   ATEN_API_TOKEN=<your-token>
   # 企業客戶或離線版才需要改：
   # ATEN_API_URL=https://www.aivoice.com.tw/business/enterprise
   ```

4. 重啟 ComfyUI

## 合成流程（套件內部自動處理）

```
POST /api/v1/syntheses/api_token  (SSML v1.5)
        ↓ synthesis_id
輪詢 GET /api/v1/syntheses/{id}/api_token 直到 Success
        ↓ synthesis_path
GET synthesis_path → WAV 存到 ComfyUI output/ → 轉為 AUDIO 輸出
```

## API 限制（來自官方文件）

- Rate limit：**120 次/分鐘**
- 單次合成上限 **2000 字元**（`<phoneme>` 等 SSML 標籤長度也計入；`<speak>`/`<voice>` 除外）
- `<prosody>`：rate 0.8~1.2、pitch -2st~+2st、volume -6dB~+6dB
- `<break>`：最大 5000ms
- SSML 保留字元 `& < > " '` 需 escape（Speech 節點會自動處理）

## 錯誤排查

| 現象 | 原因 |
|------|------|
| API 初始化失敗 | `.env` 未設定 `ATEN_API_TOKEN` |
| HTTP 403 / error 40301 | 沒有該聲優（model）的使用權限 |
| error 42207 | 超過單次合成字數（2000） |
| error 42212 | SSML 格式錯誤（常見：特殊符號未 escape、`\n` 進入 SSML） |
| 合成逾時 | 調高節點的 `timeout` 參數，或確認伺服器狀態 |

完整 error code 對照表見 `aten_api.py` 的 `ERROR_CODES`。

## 相關專案

- 議題追蹤：Redmine「NMRehab 中控系統 › ComfyUI 套件開發 (Custom Nodes)」子專案
- 姊妹套件：`ComfyUI-voai-NM`（VOAI TTS）、`ComfyUI-Veo-NM`、`ComfyUI-replicate-api-NM`
