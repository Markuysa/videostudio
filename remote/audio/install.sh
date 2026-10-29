#!/bin/bash
# Звуковая студия на Pod: голоса (Qwen3-TTS), фоли (HunyuanVideo-Foley), музыка (ACE-Step 1.5).
# Нужно ~70 ГБ на томе (окружения ~44 ГБ, веса ~25 ГБ). Ставится сама при первом фильме со звуковой студией.
# Каждая модель живёт в своём окружении на сетевом томе, повторный запуск только проверяет установку.
#   bash /workspace/studio/remote/audio/install.sh [tts] [foley] [music]   # без аргументов — всё
set -e
while IFS= read -r -d '' kv; do k=${kv%%=*}; [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -z "${!k+x}" ] && export "$kv"; done 2>/dev/null < /proc/1/environ || true
export UV_PYTHON_INSTALL_DIR=/workspace/uv-python HF_HOME=/workspace/hf-home
# кэш пакетов — на локальном диске пода: на томе он за одну установку вырастает до 15 ГБ и упирается в квоту
export UV_CACHE_DIR=/root/.cache/uv UV_LINK_MODE=copy
export HF_HUB_ENABLE_HF_TRANSFER=1 PATH="$HOME/.local/bin:$PATH"
AUDIO=/workspace/audio; MODELS=/workspace/models/audio; HF=/workspace/ltx-ui/venv/bin/hf
TORCH_INDEX=https://download.pytorch.org/whl/cu128
say(){ echo -e "\n\033[1;36m==> $*\033[0m"; }
fail(){ echo -e "\n\033[1;31mОШИБКА: $*\033[0m"; exit 1; }
WANT="${*:-tts foley music}"
want(){ [[ " $WANT " == *" $1 "* ]]; }

command -v uv >/dev/null || pip install -q -U uv 2>/dev/null || pip install -q -U uv --break-system-packages 2>/dev/null \
  || curl -LsSf https://astral.sh/uv/install.sh | sh
command -v uv >/dev/null || fail "не удалось установить uv"
[ -x "$HF" ] || fail "сначала установите студию LTX: bash /workspace/studio/remote/ltx_studio.sh"
mkdir -p "$AUDIO" "$MODELS" "$HF_HOME"

if want tts; then
  say "Голоса: Qwen3-TTS (VoiceDesign + Base, ~9 ГБ)"
  if [ ! -f "$AUDIO/tts/.ok" ]; then
    [ -x "$AUDIO/tts/venv/bin/python" ] || uv venv --python 3.12 "$AUDIO/tts/venv"
    uv pip install --python "$AUDIO/tts/venv/bin/python" torch torchaudio --index-url "$TORCH_INDEX"
    uv pip install --python "$AUDIO/tts/venv/bin/python" qwen-tts soundfile
    touch "$AUDIO/tts/.ok"
  fi
  for m in Qwen3-TTS-12Hz-1.7B-VoiceDesign Qwen3-TTS-12Hz-1.7B-Base; do
    "$HF" download "Qwen/$m" --local-dir "$MODELS/$m" >/dev/null || fail "не скачалась модель $m"
  done
  "$AUDIO/tts/venv/bin/python" -c "import torch, qwen_tts; assert torch.cuda.is_available(); print('qwen-tts OK')"
fi

if want foley; then
  say "Фоли: HunyuanVideo-Foley XXL (~15 ГБ)"
  REPO="$AUDIO/foley/HunyuanVideo-Foley"
  [ -d "$REPO/.git" ] || git clone -q https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley "$REPO"
  if [ ! -f "$AUDIO/foley/.ok" ]; then
    [ -x "$AUDIO/foley/venv/bin/python" ] || uv venv --python 3.11 "$AUDIO/foley/venv"
    P="$AUDIO/foley/venv/bin/python"
    uv pip install --python "$P" torch torchvision torchaudio --index-url "$TORCH_INDEX"
    # requirements.txt без gradio и инструментов разработки
    grep -vE "^(gradio|black|isort|flake8|mypy|pre-commit|torch|torchvision|torchaudio)" "$REPO/requirements.txt" \
      | grep -vE "^\s*(#|$)" > "$AUDIO/foley/requirements.txt"
    uv pip install --python "$P" -r "$AUDIO/foley/requirements.txt"
    touch "$AUDIO/foley/.ok"
  fi
  "$HF" download tencent/HunyuanVideo-Foley hunyuanvideo_foley.pth synchformer_state_dict.pth vae_128d_48k.pth \
    config.yaml --local-dir "$MODELS/HunyuanVideo-Foley" >/dev/null || fail "не скачались веса HunyuanVideo-Foley"
  "$HF" download google/siglip2-base-patch16-512 >/dev/null && "$HF" download laion/larger_clap_general >/dev/null \
    || fail "не скачались энкодеры SigLIP2/CLAP"
  (cd "$REPO" && "$AUDIO/foley/venv/bin/python" -c "import torch, hunyuanvideo_foley.utils.model_utils; assert torch.cuda.is_available(); print('foley OK')")
fi

if want music; then
  say "Музыка: ACE-Step 1.5 (~10 ГБ)"
  REPO="$AUDIO/music/ACE-Step-1.5"
  [ -d "$REPO/.git" ] || git clone -q https://github.com/ace-step/ACE-Step-1.5 "$REPO"
  if [ ! -f "$AUDIO/music/.ok" ]; then
    (cd "$REPO" && uv sync --no-dev)
    touch "$AUDIO/music/.ok"
  fi
  (cd "$REPO" && .venv/bin/python -c "import torch, acestep.inference; assert torch.cuda.is_available(); print('ace-step OK')")
fi

say "Звуковая студия готова"
