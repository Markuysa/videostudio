#!/bin/bash
# Имитация LTX-2.5 для тестов: последний аргумент — путь вывода. Рисует testsrc с тоном.
# FAKE_LTX_FAIL_ONCE=<подстрока пути> — первая попытка с таким путём падает с "CUDA error" (проверка откатов).
out="${@: -1}"
marker="/tmp/fake_ltx_failed_$(echo "$out" | md5sum | cut -c1-8)"
if [ -n "$FAKE_LTX_FAIL_ONCE" ] && [[ "$out" == *"$FAKE_LTX_FAIL_ONCE"* ]] && [ ! -f "$marker" ]; then
  touch "$marker"; echo "RuntimeError: CUDA error: CUBLAS_STATUS_INTERNAL_ERROR" >&2; exit 1
fi
frames=121; size="704x1280"; pipeline="distilled"
args=("$@")
for ((i=0;i<${#args[@]};i++)); do
  case "${args[$i]}" in
    --num-frames) frames="${args[$((i+1))]}";;
    --width) w="${args[$((i+1))]}";;
    --height) h="${args[$((i+1))]}";;
  esac
done
[ -n "$w" ] && size="${w}x${h}"
dur=$(python3 -c "print($frames/24)")
ffmpeg -y -loglevel error -f lavfi -i "testsrc2=size=$size:rate=24:duration=$dur" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=$dur" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$out"
