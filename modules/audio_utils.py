"""
音訊工具：載入 WAV 並轉為 ComfyUI AUDIO 格式
"""

def load_audio_as_comfyui_format(audio_path: str):
    """
    載入音訊並轉換為 ComfyUI AUDIO 格式 [batch, channels, samples]

    Returns:
        tuple: (audio_dict, error_message)
    """
    try:
        # torch/soundfile 延遲載入：CI 或非 ComfyUI 環境不需安裝
        import torch
        import soundfile as sf
        waveform, sample_rate = sf.read(audio_path)

        waveform_tensor = torch.from_numpy(waveform).float()

        # 確保形狀為 [batch, channels, samples]
        if len(waveform_tensor.shape) == 1:
            # 單聲道: [samples] -> [1, 1, samples]
            waveform_tensor = waveform_tensor.unsqueeze(0).unsqueeze(0)
        elif len(waveform_tensor.shape) == 2:
            if waveform_tensor.shape[0] > waveform_tensor.shape[1]:
                # [samples, channels] -> [1, channels, samples]
                waveform_tensor = waveform_tensor.transpose(0, 1).unsqueeze(0)
            else:
                # [channels, samples] -> [1, channels, samples]
                waveform_tensor = waveform_tensor.unsqueeze(0)

        audio_dict = {
            "waveform": waveform_tensor,
            "sample_rate": sample_rate,
        }

        print(f"✅ 音訊已載入：取樣率 {sample_rate}Hz，形狀 {tuple(waveform_tensor.shape)}")
        return audio_dict, None

    except Exception as e:
        error_msg = f"載入音訊時發生錯誤: {e}"
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
        return None, error_msg
