from __future__ import annotations

import argparse
import json
from pathlib import Path

from .characters import build_character_cards
from .io import read_text
from .models import to_dict
from .pipeline import run_pipeline
from .segmenter import segment_novel


def cmd_run(args: argparse.Namespace) -> None:
    payload = run_pipeline(args.novel, args.characters, args.out, max_shots=args.max_shots, use_llm=args.use_llm)
    print(f"已生成 {len(payload['shots'])} 张候选分镜，输出目录：{Path(args.out).resolve()}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("ficframe.api:app", host=args.host, port=args.port, reload=args.reload)


def cmd_segment(args: argparse.Namespace) -> None:
    cards = build_character_cards(read_text(args.characters)) if args.characters else []
    scenes = segment_novel(read_text(args.novel), cards)
    print(json.dumps(to_dict(scenes), ensure_ascii=False, indent=2))


def cmd_characters(args: argparse.Namespace) -> None:
    cards = build_character_cards(read_text(args.characters))
    print(json.dumps(to_dict(cards), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ficframe", description="小说配图工具集")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑完整流水线")
    run.add_argument("--novel", required=True, help="小说 Markdown 文件")
    run.add_argument("--characters", required=True, help="人物设定 Markdown 文件")
    run.add_argument("--out", default="outputs/run", help="输出目录")
    run.add_argument("--max-shots", type=int, default=8, help="最多生成多少张分镜")
    run.add_argument("--use-llm", action="store_true", help="调用 LLM 增强场景分析和 prompt")
    run.set_defaults(func=cmd_run)

    segment = sub.add_parser("segment", help="只分析小说场景")
    segment.add_argument("--novel", required=True, help="小说 Markdown 文件")
    segment.add_argument("--characters", help="人物设定 Markdown 文件，可选")
    segment.set_defaults(func=cmd_segment)

    chars = sub.add_parser("characters", help="只抽取角色卡")
    chars.add_argument("--characters", required=True, help="人物设定 Markdown 文件")
    chars.set_defaults(func=cmd_characters)

    serve = sub.add_parser("serve", help="启动 Web 前端和 API")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址")
    serve.add_argument("--port", type=int, default=8787, help="监听端口")
    serve.add_argument("--reload", action="store_true", help="开发模式自动重载")
    serve.set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
