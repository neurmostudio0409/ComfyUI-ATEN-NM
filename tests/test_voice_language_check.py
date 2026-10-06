"""#1594 續：送出前先擋掉聲優／語言不匹配，並處理 ATEN 未記載的錯誤碼。

## 為什麼要這兩件事

從 NMRehab 系統走端到端時打出這個：

    node_type: AtenSpeechNode
    voice:     客語斯文男聲-俊昇｜男聲｜客英文     ← 客語聲優
    language:  TL (中文轉台語)                   ← 要唸台語
    錯誤:      HTTP 422 {"error_code":42208}

兩個問題同時浮出來：

1. **「台語生成」工作流配到客語聲優** —— ATEN 會拒絕，但回的碼看不出是哪裡配錯。
   規格書 Revision History v1.1.103 明寫「若需要其他語系，**除了 model 要支援外**，…」，
   而 `/models` 本來就回 `languages`，所以本地就能判斷、講清楚。
2. **42208 不在規格書的錯誤碼表裡**（v1.1.108 只列 10 個碼）。查不到說明時要明講，
   免得下一個人以為是我們漏寫對照表。

`/models` 實測只有三種 languages：中英文（19 位）/ 台英文（8 位）/ 客英文（3 位）。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name


@pytest.fixture
def nodes():
    return pytest.importorskip(f'{PKG}.modules.aten_nodes')


@pytest.fixture
def api_mod():
    return pytest.importorskip(f'{PKG}.modules.aten_api')


@pytest.fixture
def settings():
    from importlib import import_module
    return import_module(f'{PKG}.config.settings')


@pytest.fixture
def voices(nodes):
    """照 ATEN 實際回的三種組合建快取。"""
    nodes._build_voice_labels([
        {'model_id': 'Easton_news', 'name': '台語男聲-文雄', 'languages': ['台英文']},
        {'model_id': 'Shawn_hakka', 'name': '客語斯文男聲-俊昇', 'languages': ['客英文']},
        {'model_id': 'Aaron_narrative', 'name': '秀逸男聲-裕祥', 'languages': ['中英文']},
    ])
    return nodes


# ---------------------------------------------------------------------------
# 1. 擋掉不匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('voice,lang', [
    ('Shawn_hakka', 'TL'),      # 客語聲優唸台語 ← 系統實際踩到的
    ('Shawn_hakka', 'TB'),
    ('Easton_news', 'HA'),      # 台語聲優唸客語
    ('Easton_news', 'HB'),
    ('Aaron_narrative', 'TL'),  # 中文聲優唸台語
])
def test_a_mismatched_voice_is_rejected_before_sending(voices, voice, lang):
    msg = voices.check_voice_language(voice, lang)
    assert msg, f'{voice} + {lang} 應該被擋下'
    assert voice in msg and lang in msg, f'訊息要講清楚是哪個聲優、哪個語言：{msg}'


@pytest.mark.parametrize('voice,lang', [
    ('Easton_news', 'TL'),          # 台語聲優唸台語
    ('Easton_news', 'TB'),
    ('Shawn_hakka', 'HA'),          # 客語聲優唸客語
    ('Shawn_hakka', 'HB'),
    ('Aaron_narrative', 'TW'),      # 中文聲優唸中文
])
def test_a_matching_voice_passes(voices, voice, lang):
    assert voices.check_voice_language(voice, lang) is None


@pytest.mark.parametrize('voice', ['Easton_news', 'Shawn_hakka', 'Aaron_narrative'])
def test_english_is_allowed_for_everyone(voices, voice):
    """三種組合都含英文，不該擋。"""
    assert voices.check_voice_language(voice, 'EN') is None


# ---------------------------------------------------------------------------
# 2. 資料不足時不要亂擋
# ---------------------------------------------------------------------------

def test_an_unknown_voice_is_not_blocked(voices):
    """舊工作流可能直接填 model_id，或 ATEN 新增了聲優 —— 不該因為我們沒資料就擋。"""
    assert voices.check_voice_language('SomeNewVoice_2027', 'TL') is None


def test_a_voice_without_language_data_is_not_blocked(nodes):
    """離線後備清單沒有 languages 欄位時，交給 API 自己判斷。"""
    nodes._build_voice_labels([{'model_id': 'NoLangInfo', 'name': '測試'}])
    assert nodes.check_voice_language('NoLangInfo', 'TL') is None


def test_the_check_is_actually_wired_into_the_node():
    """純函式對了但沒接上就沒意義。"""
    src = (ROOT / 'modules' / 'aten_nodes.py').read_text(encoding='utf-8')
    i = src.index('def generate_speech')
    body = src[i:i + 2500]
    assert 'check_voice_language' in body, 'generate_speech 沒有呼叫檢查'
    assert body.index('check_voice_language') < body.index('build_ssml'), '要在組 SSML 之前擋'


# ---------------------------------------------------------------------------
# 3. ATEN 未記載的錯誤碼
# ---------------------------------------------------------------------------

def test_42208_is_in_the_table_with_an_honest_note(settings):
    """2026-10-07 實測：最保守的請求也持續回 42208，而同組 25 分鐘前還成功。"""
    assert 42208 in settings.ERROR_CODES
    note = settings.ERROR_CODES[42208]
    assert '未記載' in note, '要標明這不是規格書上的碼'
    assert '額度' in note, '要指出往哪裡查'


def test_an_undocumented_code_says_so(api_mod):
    """查不到說明時要明講，免得下一個人去翻規格書找不到還以為是我們漏寫。"""
    class R:
        status_code = 422
        text = '{"error_code":49999}'
        headers = {}
        def json(self):
            return {'error_code': 49999}

    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(R(), 'x')
    msg = str(exc.value)
    assert '49999' in msg
    assert '不在 ATEN 規格書' in msg, f'未記載的碼要講明：{msg}'


def test_a_documented_code_does_not_get_that_note(api_mod):
    class R:
        status_code = 422
        text = '{"error_code":42212}'
        headers = {}
        def json(self):
            return {'error_code': 42212}

    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(R(), 'x')
    msg = str(exc.value)
    assert 'ssml 格式錯誤' in msg
    assert '不在 ATEN 規格書' not in msg


def test_42208_is_not_retried(api_mod, monkeypatch):
    """它是持續性的 —— 只有 42210（隊列滿）值得重試。"""
    calls = {'n': 0}

    class FakeResp:
        status_code = 422
        text = '{"error_code":42208}'
        headers = {}
        def json(self):
            return {'error_code': 42208}

    class FakeSession:
        def post(self, *a, **k):
            calls['n'] += 1
            return FakeResp()

    api = api_mod.AtenAPI.__new__(api_mod.AtenAPI)
    api.session = FakeSession()
    api.base_url = 'https://example.test'
    monkeypatch.setattr(api_mod.time, 'sleep', lambda s: None)

    with pytest.raises(api_mod.AtenAPIError):
        api.synthesize_ssml('<speak>x</speak>')
    assert calls['n'] == 1, f'42208 不該重試，實際打了 {calls["n"]} 次'
