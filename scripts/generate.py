#!/usr/bin/env python
"""Generate thumbnail images locally, without touching the live game.

Runs the same generation pipeline as a scheduled run - prompt building, model
resolution, retries, moderation - but writes to a scratch directory by default,
so nothing reaches Roblox unless you explicitly ask for it.

    # what can be used as a seed
    scripts/generate.py --list-sources

    # three variations bred from a tracked creative, into generated/
    scripts/generate.py --source thumb-001 --count 3

    # a prompt of your own, on a specific model
    scripts/generate.py --prompt "A stone lighthouse at dusk" --model gemini-3.1-flash-image

    # put one into the real queue, so the next run uploads and activates it
    scripts/generate.py --source thumb-001 --queue

Requires AI_IMAGE_API_KEY in .env (see .env.example).
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import queue as queue_mod                                  # noqa: E402
from src.config import REPO_ROOT, load_config                       # noqa: E402
from src.history import load_thumbnails                             # noqa: E402
from src.image_generator import (GenerationError, generate_image,   # noqa: E402
                                 list_image_models)
from src.imaging import detect_format                               # noqa: E402
from src.models import ThumbnailRecord                              # noqa: E402
from src.prompt_builder import build_prompt                         # noqa: E402

DEFAULT_OUT = REPO_ROOT / "generated"

log = logging.getLogger("generate")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate thumbnail images locally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Output goes to generated/ unless --queue or --out is given.")
    seed = p.add_mutually_exclusive_group()
    seed.add_argument("--source", metavar="KEY",
                      help="seed from a tracked creative's description, e.g. thumb-001")
    seed.add_argument("--prompt", help="use this prompt verbatim")
    seed.add_argument("--describe", metavar="TEXT",
                      help="build the standard prompt around your own description")
    p.add_argument("--count", type=int, default=1, help="how many images (default 1)")
    p.add_argument("--model", help="override the configured image model")
    p.add_argument("--out", type=Path, help=f"output directory (default {DEFAULT_OUT.name}/)")
    p.add_argument("--queue", action="store_true",
                   help="write into thumbnails/queue/ so the next run uploads it LIVE")
    p.add_argument("--list-sources", action="store_true",
                   help="list creatives usable as a seed, then exit")
    p.add_argument("--list-models", action="store_true",
                   help="list image-capable models for your key, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="print the prompt that would be sent, generate nothing")
    return p.parse_args(argv)


def list_sources(records):
    usable = [r for r in records if r.description.strip()]
    if not usable:
        print("No creative has a description yet; use --prompt or --describe.")
        return
    width = max(len(r.thumbnail_key) for r in usable)
    print(f"{len(usable)} creative(s) usable as a seed:\n")
    for r in sorted(usable, key=lambda r: r.thumbnail_key):
        flag = "active  " if r.status == "active" else "inactive"
        print(f"  {r.thumbnail_key:<{width}}  {flag}  {r.description[:88]}")


def list_models(cfg):
    models = list_image_models(cfg.ai_image_api_key)
    image_models = [m for m in models
                    if any(h in m["name"].lower() for h in ("imagen", "image"))]
    print(f"{len(image_models)} image-capable model(s) for this key:\n")
    for m in sorted(image_models, key=lambda m: m["name"]):
        mark = "  <- configured" if m["name"] == cfg.image_model else ""
        print(f"  {m['name']:<40} via {m['kind']}{mark}")


def resolve_prompt(args, records):
    """Return (prompt, source_description, source_key)."""
    if args.prompt:
        return args.prompt, "", ""
    if args.describe:
        record = ThumbnailRecord(thumbnail_key="", description=args.describe)
        return build_prompt(record), args.describe, ""
    if args.source:
        match = next((r for r in records if r.thumbnail_key == args.source), None)
        if match is None:
            raise SystemExit(f"No creative named {args.source!r}. "
                             f"Try --list-sources.")
        if not match.description.strip():
            raise SystemExit(f"{args.source} has no description to seed from. "
                             f"Use --describe or --prompt.")
        return build_prompt(match), match.description, match.thumbnail_key
    raise SystemExit("Choose a seed: --source, --prompt or --describe "
                     "(--list-sources shows what is available).")


def next_stem(out_dir: Path, prefix: str) -> str:
    """A non-colliding name, so repeated runs never overwrite earlier images."""
    existing = {p.stem for p in out_dir.glob(f"{prefix}-*")}
    n = 1
    while f"{prefix}-{n:03d}" in existing:
        n += 1
    return f"{prefix}-{n:03d}"


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()

    if args.list_models:
        list_models(cfg)
        return 0

    records = load_thumbnails()
    if args.list_sources:
        list_sources(records)
        return 0

    if args.model:
        cfg.image_model = args.model
    prompt, source_description, source_key = resolve_prompt(args, records)

    if args.dry_run:
        print(f"model : {cfg.image_model}")
        print(f"source: {source_key or '(none)'}")
        print(f"count : {args.count}")
        print(f"\n{prompt}")
        return 0

    if not cfg.ai_image_api_key:
        raise SystemExit("AI_IMAGE_API_KEY is not set; add it to .env")

    if args.queue:
        out_dir = queue_mod.QUEUE_DIR
        prefix = "candidate"
        log.warning("Writing to the live queue: the next run will upload and "
                    "activate these on your game")
    else:
        out_dir = args.out or DEFAULT_OUT
        prefix = "local"
    out_dir.mkdir(parents=True, exist_ok=True)

    written, failed = [], 0
    for i in range(1, args.count + 1):
        try:
            image, model_used = generate_image(cfg, prompt)
        except GenerationError as exc:
            failed += 1
            log.error("%d/%d failed: %s", i, args.count, exc)
            continue

        stem = next_stem(out_dir, prefix)
        filename = stem + detect_format(image)[0]
        (out_dir / filename).write_bytes(image)
        (out_dir / f"{stem}.json").write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "prompt": prompt,
            "source_description": source_description,
            "source_thumbnail_id": source_key,
            "provider": cfg.image_provider,
            "model": model_used,
            "filename": filename,
            "status": "queued" if args.queue else "local",
        }, indent=2) + "\n")
        written.append(out_dir / filename)
        log.info("%d/%d %s (%s, %.0f KB)", i, args.count, filename,
                 model_used, len(image) / 1024)

    if written:
        print(f"\n{len(written)} image(s) in {out_dir}:")
        for path in written:
            print(f"  {path}")
        if not args.queue:
            print("\nNot queued: nothing will be uploaded. "
                  "Re-run with --queue to put one in front of players.")
    return 1 if failed and not written else 0


if __name__ == "__main__":
    sys.exit(main())
