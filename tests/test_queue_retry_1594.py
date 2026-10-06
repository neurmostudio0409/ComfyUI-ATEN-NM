"""#1594：42210（隊列已滿）要退避重試；任何失敗都不得回 None 給下游。

## 現場

GPU 機日誌：

    ❌ ATEN API 錯誤: 送出合成任務失敗，HTTP 422
    TypeError: 'NoneType' object is not subscriptable
      ComfyUI/comfy_api/latest/_ui.py:286 in save_audio
        for batch_number, waveform in enumerate(audio["waveform"].cpu()):

兩個問題疊在一起：

1. **422 的真因沒被講出來** —— 把日誌那段 SSML 原封不動打 API 是 **200**，
   四組對照（純文字 / 只有 lang / 只有 prosody / 原樣）全部 200；
   併發送 10 次才中 2 次，body 是 ``{"error_code":42210}``
   ＝「目前在隊列內或合成中的任務已達到上限」。
   單發不會踩到，**排程一次產多段旁白並發打才會**。

2. **失敗時回 ``(None,)``** —— 節點宣告 ``RETURN_TYPES = ("AUDIO", …)``，
   回 None 讓下游 SaveAudio 死在 TypeError，真正原因只剩 terminal 的 print。

ATEN 的錯誤 body 只有 ``error_code``、**沒有 message**，而原本的
``_raise_for_error`` 只在 ``resp.json()`` 丟例外時才退回 ``resp.text``
—— 所以碼有抓到、訊息卻整個消失。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name


@pytest.fixture
def api_mod():
    return pytest.importorskip(f'{PKG}.modules.aten_api')


class FakeResp:
    """最小的 requests.Response 替身。"""

    def __init__(self, status, body=None, text=None, headers=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else '')
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body


# ---------------------------------------------------------------------------
# 1. 錯誤訊息要講得出原因
# ---------------------------------------------------------------------------

def test_the_error_code_survives_even_without_a_message(api_mod):
    """ATEN 的 422 只回 {"error_code":42210} —— 沒有 message 欄位。"""
    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(FakeResp(422, {'error_code': 42210}), '送出合成任務失敗')
    msg = str(exc.value)
    assert '42210' in msg
    assert '隊列' in msg, f'應該帶上對照表的說明，實際：{msg}'
    assert exc.value.code == 42210


def test_a_string_error_code_is_still_looked_up(api_mod):
    """ERROR_CODES 是 int 鍵；回字串就查不到說明 —— 要先轉。"""
    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(FakeResp(422, {'error_code': '42212'}), 'x')
    assert 'ssml' in str(exc.value).lower()
    assert exc.value.code == 42212


def test_a_non_dict_body_is_not_silently_dropped(api_mod):
    """body 不是 dict 時，原本 except 不觸發、detail 留空 → 線索整個消失。"""
    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(FakeResp(422, ['nope'], text='["nope"]'), 'x')
    assert 'nope' in str(exc.value)


def test_a_non_json_body_is_not_silently_dropped(api_mod):
    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(FakeResp(500, None, text='<html>boom</html>'), 'x')
    assert 'boom' in str(exc.value)


# ---------------------------------------------------------------------------
# 2. 只有 42210 該重試
# ---------------------------------------------------------------------------

def test_the_queue_full_code_is_configured(api_mod):
    from importlib import import_module
    st = import_module(f'{PKG}.config.settings')
    assert st.QUEUE_FULL_CODE == 42210
    assert len(st.QUEUE_FULL_RETRY_DELAYS_S) >= 3, '至少要撐過幾輪排隊'
    assert st.ERROR_CODES[42210]


def test_queue_full_is_retried_then_succeeds(api_mod, monkeypatch):
    """前兩次 42210、第三次成功 → 不應該讓使用者看到失敗。"""
    calls = {'n': 0}

    class FakeSession:
        def post(self, url, json=None, timeout=None):
            calls['n'] += 1
            if calls['n'] <= 2:
                return FakeResp(422, {'error_code': 42210})
            return FakeResp(200, {'synthesis_id': 'ok', 'synthesis_path': 'u'})

    api = api_mod.AtenAPI.__new__(api_mod.AtenAPI)
    api.session = FakeSession()
    api.base_url = 'https://example.test'
    monkeypatch.setattr(api_mod.time, 'sleep', lambda s: None)

    out = api.synthesize_ssml('<speak>x</speak>')
    assert out['synthesis_id'] == 'ok'
    assert calls['n'] == 3, '應該重試到成功'


def test_queue_full_eventually_gives_up(api_mod, monkeypatch):
    """一直滿就不能無限等 —— 用完次數要拋出來讓上層知道。"""
    class FakeSession:
        def post(self, *a, **k):
            return FakeResp(422, {'error_code': 42210})

    api = api_mod.AtenAPI.__new__(api_mod.AtenAPI)
    api.session = FakeSession()
    api.base_url = 'https://example.test'
    monkeypatch.setattr(api_mod.time, 'sleep', lambda s: None)

    with pytest.raises(api_mod.AtenAPIError) as exc:
        api.synthesize_ssml('<speak>x</speak>')
    assert exc.value.code == 42210


@pytest.mark.parametrize('code', [42203, 42207, 42212])
def test_other_422_codes_are_not_retried(api_mod, monkeypatch, code):
    """缺 token / 超字數 / ssml 格式錯 —— 重試幾次都一樣，立刻拋。"""
    calls = {'n': 0}

    class FakeSession:
        def post(self, *a, **k):
            calls['n'] += 1
            return FakeResp(422, {'error_code': code})

    api = api_mod.AtenAPI.__new__(api_mod.AtenAPI)
    api.session = FakeSession()
    api.base_url = 'https://example.test'
    monkeypatch.setattr(api_mod.time, 'sleep', lambda s: None)

    with pytest.raises(api_mod.AtenAPIError):
        api.synthesize_ssml('<speak>x</speak>')
    assert calls['n'] == 1, f'{code} 不該重試，實際打了 {calls["n"]} 次'


# ---------------------------------------------------------------------------
# 3. 失敗不得回 None（崩潰的直接原因）
# ---------------------------------------------------------------------------

def test_no_failure_path_returns_none():
    """節點宣告輸出 AUDIO，回 (None,…) 會讓下游 SaveAudio 死在 TypeError。

    ComfyUI 沒做錯 —— `save_audio` 有權假設 AUDIO 輸入是 AUDIO dict。
    """
    src = (ROOT / 'modules' / 'aten_nodes.py').read_text(encoding='utf-8')
    assert 'return (None' not in src, '還有失敗路徑回 None'


def test_the_nodes_still_declare_audio_outputs():
    """上面那條的前提：輸出型別真的是 AUDIO（不是改成可選才躲掉的）。"""
    src = (ROOT / 'modules' / 'aten_nodes.py').read_text(encoding='utf-8')
    assert 'RETURN_TYPES = ("AUDIO", "STRING")' in src
    assert 'RETURN_TYPES = ("AUDIO",)' in src


def test_the_token_value_is_never_printed():
    """錯誤訊息現在會帶上 response body —— 不能順手把 token 的值也印出去。

    注意：說明文字裡提到變數名（「在 config/.env 中設定 ATEN_API_TOKEN」）
    不是洩漏；要擋的是把**值**插進輸出。
    """
    for name in ('modules/aten_api.py', 'modules/aten_nodes.py'):
        src = (ROOT / name).read_text(encoding='utf-8')
        for n, line in enumerate(src.splitlines(), 1):
            if 'print(' not in line:
                continue
            for leak in ('self.api_token', 'get_api_token()', '{api_token'):
                assert leak not in line, f'{name}:{n} 把 token 的值印出來了：{line.strip()}'


def test_the_error_message_does_not_echo_auth_headers(api_mod):
    """body 退回 resp.text 時，不應把請求標頭一起帶出來。"""
    with pytest.raises(api_mod.AtenAPIError) as exc:
        api_mod.AtenAPI._raise_for_error(FakeResp(422, {'error_code': 42210}), 'x')
    assert 'Authorization' not in str(exc.value)
