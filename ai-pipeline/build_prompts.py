# -*- coding: utf-8 -*-
"""build_prompts.py — 把分镜蓝图展开成「可复制粘贴的批量 prompt 包」。

AI 视频流程里最费时间的不是点生成，而是反复拼 prompt、对不上镜号、生成完不知道哪个文件是哪一镜。
这个脚本把 shot_blueprint.json 变成：

    ai-pipeline/prompts/queue.csv          表格，可直接导进批处理工具
    ai-pipeline/prompts/S01.txt ...        每镜一个文件，含图/视频 prompt 与负面提示
    ai-pipeline/prompts/rename_map.txt     生成文件 → 目标命名 的映射，出片后照着重命名

用法::

    python3 ai-pipeline/build_prompts.py
"""
from __future__ import annotations

import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.join(HERE, "shot_blueprint.json")
OUT = os.path.join(HERE, "prompts")


def main():
    with open(BP, encoding="utf-8") as f:
        bp = json.load(f)
    os.makedirs(OUT, exist_ok=True)

    queue_path = os.path.join(OUT, "queue.csv")
    fields = ["shot_id", "order", "duration", "keyframe_prompt", "video_prompt",
              "negative_prompt", "seed", "expect_filename"]
    with open(queue_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, s in enumerate(bp["shots"], 1):
            w.writerow({
                "shot_id": s["shot_id"], "order": i, "duration": s["duration"],
                "keyframe_prompt": s["keyframe_image_prompt"],
                "video_prompt": s["image_to_video_prompt"],
                "negative_prompt": s["negative_prompt"], "seed": s["seed"],
                "expect_filename": f"{s['shot_id']}_{s['shot_name']}_v1.mp4",
            })

    for s in bp["shots"]:
        p = os.path.join(OUT, f"{s['shot_id']}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# {s['shot_id']} {s['shot_name']}  {s['shot_size']}  "
                    f"{s['t_start']}s-{s['t_end']}s  {s['camera_move']}\n")
            f.write(f"# 画面：{s['scene_desc']}\n\n")
            f.write("## 关键帧（文生图 / 图生图）\n")
            f.write(s["keyframe_image_prompt"] + "\n\n")
            f.write("## 图生视频（镜头运动）\n")
            f.write(s["image_to_video_prompt"] + "\n\n")
            f.write("## 负面提示（通用）\n")
            f.write(s["negative_prompt"] + "\n\n")
            f.write(f"## 种子 seed = {s['seed']}（便于复现同一镜；换镜请改 seed）\n")

    with open(os.path.join(OUT, "rename_map.txt"), "w", encoding="utf-8") as f:
        f.write("# 生成后按此表重命名，再用剪辑软件按 01..0N 顺序导入即可自动排好时间线\n")
        for i, s in enumerate(bp["shots"], 1):
            f.write(f"任意文件名_{i:02d}.mp4  ->  {i:02d}_{s['shot_id']}_{s['shot_name']}.mp4\n")

    print(f"[ok] {queue_path}")
    print(f"[ok] {len(bp['shots'])} 个 prompt 文件 → {OUT}")
    print("[ok] rename_map.txt")


if __name__ == "__main__":
    main()
