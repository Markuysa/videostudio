#!/bin/bash
# Ночной режим: план фильма -> все клипы -> сборка -> уведомление -> удаление Pod.
#   bash /workspace/studio/remote/film_night.sh /workspace/film/plans/storm.json            # с удалением Pod
#   bash /workspace/studio/remote/film_night.sh /workspace/film/plans/storm.json --keep-pod # Pod оставить
# Настройки (необязательно), можно задать перед командой:
#   MAX_HOURS=10      жёсткий лимит времени, потом Pod удаляется в любом случае
#   NTFY_TOPIC=xxx    уведомление на телефон через приложение ntfy (тема = любое секретное слово)
#   FILM_QUALITY=high|fast
#   HF_UPLOAD_REPO=user/films  загрузить готовый фильм в приватный датасет Hugging Face (нужен токен с правом Write)

PLAN="$1"; KEEP=no; [ "$2" = "--keep-pod" ] && KEEP=yes
[ -n "$PLAN" ] || { echo "Использование: bash film_night.sh путь/к/плану.json [--keep-pod]"; exit 1; }
PLAN=$(readlink -f "$PLAN")
[ -f "$PLAN" ] || { echo "Нет файла плана: $PLAN"; exit 1; }
STUDIO=/workspace/studio

# 1. Перезапускаем себя в фоне, чтобы можно было закрыть терминал
if [ -z "$FILM_DETACHED" ]; then
  mkdir -p /workspace/film
  LOG="/workspace/film/night_$(date +%m%d_%H%M).log"
  FILM_DETACHED=1 setsid nohup bash "$0" "$@" > "$LOG" 2>&1 < /dev/null &
  echo "Запущено в фоне. Можно закрывать браузер."
  echo "Следить за прогрессом: tail -f $LOG"
  exit 0
fi

# Подтягиваем переменные окружения Pod (в SSH-сессии RunPod их нет)
while IFS= read -r -d '' kv; do k=${kv%%=*}; [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -z "${!k+x}" ] && export "$kv"; done 2>/dev/null < /proc/1/environ || true
pid1env(){ { tr '\0' '\n' < /proc/1/environ; } 2>/dev/null | grep "^$1=" | head -1 | cut -d= -f2-; }
POD_ID="${RUNPOD_POD_ID:-$(pid1env RUNPOD_POD_ID)}"
VOLUME_ID="${RUNPOD_VOLUME_ID:-$(pid1env RUNPOD_VOLUME_ID)}"
API_KEY="${RUNPOD_API_KEY:-$(pid1env RUNPOD_API_KEY)}"
[ -s /workspace/.runpod_api_key ] && API_KEY=$(cat /workspace/.runpod_api_key)
MAX_HOURS="${MAX_HOURS:-10}"
UI=/workspace/ltx-ui
say(){ echo "[$(date +%H:%M:%S)] $*"; }
notify(){ say "$1"; [ -n "$NTFY_TOPIC" ] && curl -s -m 20 -H "Title: LTX фильм" -d "$1" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null; }

shutdown_pod(){
  if [ "$KEEP" = yes ]; then say "Pod оставлен (--keep-pod). Не забудьте удалить его вручную."; return; fi
  if [ -z "$POD_ID" ]; then say "Не знаю ID пода, удалите его вручную."; return; fi
  say "Через ${SHUTDOWN_DELAY:-60} секунд Pod $POD_ID будет остановлен. Отмена: kill $$"
  sleep ${SHUTDOWN_DELAY:-60}; sync
  if [ -n "$VOLUME_ID" ]; then
    say "Network Volume есть, файлы сохранятся. Удаляю Pod."
    runpodctl pod delete "$POD_ID" 2>/dev/null && return
    runpodctl remove pod "$POD_ID" 2>/dev/null && return
    for url in "https://rest.runpod.io/v1/pods/$POD_ID" "https://api.runpod.io/v2/pods/$POD_ID"; do
      code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE -H "Authorization: Bearer $API_KEY" "$url")
      say "DELETE $url -> $code"; [[ "$code" == 2* ]] && return
    done
  else
    say "Network Volume не найден: удалять нельзя, иначе пропадёт фильм. Останавливаю Pod (Stop)."
    runpodctl pod stop "$POD_ID" 2>/dev/null && return
    runpodctl stop pod "$POD_ID" 2>/dev/null && return
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $API_KEY" "https://rest.runpod.io/v1/pods/$POD_ID/stop")
    say "POST stop -> $code"; [[ "$code" == 2* ]] && return
  fi
  notify "НЕ УДАЛОСЬ остановить Pod $POD_ID автоматически. Остановите его вручную в RunPod!"
}

say "План: $PLAN | Pod: ${POD_ID:-?} | Network Volume: ${VOLUME_ID:-нет} | лимит ${MAX_HOURS} ч"
[ -f "$UI/env" ] && source "$UI/env"
if [ -z "$LTX_TEST_CMD" ] && [ ! -x /workspace/LTX-2/.venv/bin/python ]; then
  notify "Студия LTX не установлена: сначала bash /workspace/studio/remote/ltx_studio.sh"; shutdown_pod; exit 1
fi
which ffmpeg >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null; }
fc-list 2>/dev/null | grep -qi dejavu || apt-get install -y -qq fonts-dejavu-core >/dev/null 2>&1 || true
pkill -f "uvicorn app:app" 2>/dev/null   # веб-студию выключаем, чтобы не занимала видеокарту

PY=/workspace/LTX-2/.venv/bin/python; [ -x "$PY" ] || PY=python3
notify "Старт рендера: $(basename "$PLAN")"
timeout "${MAX_HOURS}h" "$PY" "$STUDIO/remote/film.py" "$PLAN"
CODE=$?
SLUG=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('slug') or '')" "$PLAN" 2>/dev/null)
PROJ="${FILM_DIR:-/workspace/film/${SLUG:-$(basename "${PLAN%.*}")}}"
case $CODE in
  0)   notify "Фильм готов: $PROJ/film.mp4" ;;
  2)   notify "Фильм собран, но часть сцен не получилась: $PROJ/film.mp4 (см. report.json)" ;;
  124) notify "Превышен лимит ${MAX_HOURS} ч. Готовые клипы в $PROJ/clips. Повторный запуск продолжит с места остановки." ;;
  *)   notify "Рендер завершился с ошибкой ($CODE). Лог: $PROJ/render.log" ;;
esac
if [ -n "$HF_UPLOAD_REPO" ] && [ -f "$PROJ/film.mp4" ] && [ -x "$UI/venv/bin/hf" ]; then
  export HF_HOME=/workspace/hf-home
  "$UI/venv/bin/hf" upload "$HF_UPLOAD_REPO" "$PROJ/film.mp4" "$(basename "$PROJ")_$(date +%m%d_%H%M).mp4" \
    --repo-type dataset --private && notify "Фильм загружен на Hugging Face: $HF_UPLOAD_REPO" \
    || say "Загрузка на Hugging Face не удалась (нужен токен с правом Write)"
fi
shutdown_pod
