#!/usr/bin/env python3
"""Видео под готовую речь: LTX Retake (distilled) с замороженной звуковой дорожкой.

Запускается питоном LTX-2. Принимает те же аргументы, что `python -m ltx_pipelines.retake`
(--video-path, --prompt, --start-time, --end-time, пути к весам, --output-path), но
перерисовывает только видео в окне, а звук исходного файла не трогает: модель двигает губы
под уже записанную реплику. В --video-path ожидается «холст» — клип сцены с дорожкой голоса.

Полный A2Vid (`ltx_pipelines.a2vid_two_stage`) требует dev-чекпоинт и distilled-LoRA (~51 ГБ),
а retake работает на distilled-трансформере, который уже лежит на томе. В distilled-режиме retake
не усиливает влияние звука на картинку, и губы почти не двигаются (проверено 2026-10-29: рот
открывается на одном слоге из трёх). Поэтому денойзер берём guided с одним modality guidance
(cfg=1, звук -> видео x3, как `--a2v-guidance-scale` в штатных пайплайнах) на distilled-расписании.
"""
from __future__ import annotations

import inspect
import logging

import torch

from ltx_core.components.guiders import MultiModalGuiderParams
from ltx_pipelines import retake as R


@torch.inference_mode()
def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = R.video_editing_arg_parser(distilled=True)
    parser.description = "LTX lip-sync: regenerate video under a fixed audio track."
    parser.add_argument("--a2v-scale", type=float, default=3.0,
                        help="how strongly the fixed audio drives the video (modality guidance, 1 = off)")
    args = parser.parse_args()
    if args.start_time >= args.end_time:
        raise ValueError("start_time must be less than end_time")
    src = R.get_videostream_metadata(args.video_path)
    if (src.frames - 1) % 8 != 0:
        raise ValueError(f"frame count must be 8k+1, got {src.frames}")
    if src.width % 32 or src.height % 32:
        raise ValueError(f"width and height must be multiples of 32, got {src.width}x{src.height}")

    init = dict(model_paths=args.model_paths, loras=tuple(args.lora) if args.lora else (),
                quantization=args.quantization, distilled=args.a2v_scale == 1.0, compilation_config=args.compile,
                offload_mode=args.offload_mode, prompt_enhancer_gemma_root=args.prompt_enhancer_gemma_root,
                diffvae_optimization=args.diffvae_optimization)
    allowed = inspect.signature(R.RetakePipeline.__init__).parameters
    pipeline = R.RetakePipeline(**{k: v for k, v in init.items() if k in allowed})
    video_guider = MultiModalGuiderParams(cfg_scale=1.0, stg_scale=0.0, modality_scale=args.a2v_scale)
    hdr = R.resolve_hdr_color_space(video_paths=[args.video_path], hdr=args.hdr)
    call = dict(video_path=args.video_path, prompt=args.prompt, start_time=args.start_time, end_time=args.end_time,
                seed=args.seed, enhance_prompt=args.enhance_prompt, enhance_static_cache=args.enhance_static_cache,
                video_guider_params=video_guider, audio_guider_params=MultiModalGuiderParams(),
                sigmas=R.DISTILLED_SIGMAS,
                vae_dtype=R.vae_dtype_for_hdr(hdr, torch.bfloat16), color_space=hdr, tiling_config=R.AUTO_TILING,
                max_batch_size=args.max_batch_size, regenerate_video=True, regenerate_audio=False)
    allowed = inspect.signature(R.RetakePipeline.__call__).parameters
    result = pipeline(**{k: v for k, v in call.items() if k in allowed})
    R.encode_video(video=result.video, fps=int(src.fps), audio=result.audio, output_path=args.output_path,
                   video_chunks_number=R.get_video_chunks_number(result.num_frames, result.tiling_config),
                   color_space=hdr)


if __name__ == "__main__":
    main()
