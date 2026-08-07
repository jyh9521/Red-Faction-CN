#!/usr/bin/env python3
"""Finalize an ImageGen signage candidate using the original HD TGA container.

The generated candidate is expected on a flat green chroma-key stage.  This
tool removes the stage with Codex's installed helper, fits the localized asset
inside the original non-transparent bounds without changing its aspect ratio,
and writes pixels through rf_cn/tools/tga.py so the original 18-byte header,
bit depth, descriptor, dimensions, and origin convention are retained.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GAME = ROOT.parent
sys.path.insert(0, str(HERE))

import tga  # noqa: E402


def green_stage_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    mask = Image.new("1", rgb.size)
    src = rgb.load()
    dst = mask.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            red, green, blue = src[x, y]
            dst[x, y] = (
                green > 150
                and green > red * 1.45
                and green > blue * 1.45
            )
    bbox = mask.getbbox()
    border = []
    edge = min(4, rgb.width, rgb.height)
    for y in range(rgb.height):
        for x in range(rgb.width):
            if x < edge or x >= rgb.width - edge or y < edge or y >= rgb.height - edge:
                border.append(bool(dst[x, y]))
    border_ratio = sum(border) / len(border) if border else 0.0
    if bbox is None or border_ratio < 0.25:
        raise ValueError("candidate does not contain a detectable green stage")
    return bbox


def threshold_bbox(alpha: Image.Image, threshold: int = 4):
    return alpha.point(lambda value: 255 if value >= threshold else 0).getbbox()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="TGA filename under signage_hd")
    parser.add_argument("candidate", type=Path, help="ImageGen PNG candidate")
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=GAME / "tmp" / "signage_hd_final",
    )
    args = parser.parse_args()

    original_path = ROOT / "work" / "signage_hd_orig" / args.name
    target_path = ROOT / "signage_hd" / args.name
    if not original_path.is_file():
        raise FileNotFoundError(original_path)
    if not args.candidate.is_file():
        raise FileNotFoundError(args.candidate)

    args.preview_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.name).stem
    staged_path = args.preview_dir / f"{stem}.green.png"
    cutout_path = args.preview_dir / f"{stem}.cutout.png"
    preview_path = args.preview_dir / f"{stem}.png"

    original = tga.read(original_path)
    original_rgba = original.image.convert("RGBA")
    if original.bpp == 32:
        original_alpha = original_rgba.getchannel("A")
        target_bbox = threshold_bbox(original_alpha)
        visible = sum(1 for value in original_alpha.get_flattened_data() if value >= 4)
        alpha_coverage = visible / (original_rgba.width * original_rgba.height)
    else:
        original_alpha = Image.new("L", original_rgba.size, 255)
        target_bbox = (0, 0, original_rgba.width, original_rgba.height)
        alpha_coverage = 1.0
    if target_bbox is None:
        target_bbox = (0, 0, original_rgba.width, original_rgba.height)

    with Image.open(args.candidate) as candidate_image:
        candidate_rgb = candidate_image.convert("RGB")
        try:
            stage_bbox = green_stage_bbox(candidate_rgb)
        except ValueError:
            stage_bbox = None

    if stage_bbox is None:
        if alpha_coverage < 0.90:
            raise ValueError(
                "candidate has no green stage but original is a transparent decal"
            )
        panel = candidate_rgb.resize(original_rgba.size, Image.Resampling.LANCZOS)
        canvas = panel.convert("RGBA")
        canvas.putalpha(original_alpha)
    else:
        candidate_rgb.crop(stage_bbox).save(staged_path)

        codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        helper = (
            codex_root
            / "skills"
            / ".system"
            / "imagegen"
            / "scripts"
            / "remove_chroma_key.py"
        )
        subprocess.run(
            [
                sys.executable,
                str(helper),
                "--input",
                str(staged_path),
                "--out",
                str(cutout_path),
                "--auto-key",
                "border",
                "--soft-matte",
                "--transparent-threshold",
                "12",
                "--opaque-threshold",
                "220",
                "--despill",
                "--force",
            ],
            check=True,
        )

        with Image.open(cutout_path) as cutout:
            cutout = cutout.convert("RGBA")
            source_bbox = threshold_bbox(cutout.getchannel("A"))
            if source_bbox is None:
                raise ValueError("chroma-key removal produced no visible content")
            content = cutout.crop(source_bbox)

        target_width = target_bbox[2] - target_bbox[0]
        target_height = target_bbox[3] - target_bbox[1]
        scale = min(target_width / content.width, target_height / content.height)
        fitted_size = (
            max(1, round(content.width * scale)),
            max(1, round(content.height * scale)),
        )
        content = (
            content.convert("RGBa")
            .resize(fitted_size, Image.Resampling.LANCZOS)
            .convert("RGBA")
        )
        position = (
            target_bbox[0] + (target_width - fitted_size[0]) // 2,
            target_bbox[1] + (target_height - fitted_size[1]) // 2,
        )
        canvas = Image.new("RGBA", original_rgba.size, (0, 0, 0, 0))
        canvas.alpha_composite(content, position)

    pixels = list(canvas.get_flattened_data())
    canvas.putdata(
        [
            (0, 0, 0, 0) if alpha == 0 else (red, green, blue, alpha)
            for red, green, blue, alpha in pixels
        ]
    )
    canvas.save(preview_path)

    original.image = canvas
    tga.write(target_path, original)
    check = tga.read(target_path)
    if check.image.size != original_rgba.size:
        raise AssertionError(f"size changed: {original_rgba.size} -> {check.image.size}")
    if check.bpp != original.bpp or check.header != original.header:
        raise AssertionError("TGA header or bit depth changed")

    alpha_text = "none"
    if check.bpp == 32:
        alpha_text = str(check.image.getchannel("A").getextrema())
    print(
        f"OK {args.name}: size={check.image.size} bpp={check.bpp} "
        f"desc=0x{check.header[17]:02x} alpha={alpha_text} "
        f"preview={preview_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
