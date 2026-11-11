"""
inference/cli.py

    python -m inference predict <file> --model <key> --out <dir>
    python -m inference list

`predict` writes mask.png, overlay.png and summary.json into <dir>.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import DISCLAIMER
from .loaders import UnsupportedFormatError
from .pipeline import run_file, save_slice_result
from .postprocess import DEFAULT_MIN_BLOB_PIXELS
from .predictor import DEFAULT_BATCH_SIZE
from .registry import ModelRegistry, RegistryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m inference",
        description=f"Brain-MRI tumor segmentation. {DISCLAIMER}",
    )
    parser.add_argument(
        "--model-store", default=None,
        help="folder with <model_key>/fold_<k>/best_model.pt "
             "(default: $MODEL_STORE_DIR or ./model_store)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("predict", help="predict the tumor mask of one scan file")
    p.add_argument("file", help="PNG, JPEG, TIFF, FigShare .mat, BraTS .h5 or DICOM file")
    p.add_argument("--model", required=True, help="model key (see `list`)")
    p.add_argument("--out", required=True, help="output folder")
    p.add_argument("--min-blob-pixels", type=int, default=DEFAULT_MIN_BLOB_PIXELS,
                   help="remove blobs smaller than this many pixels at model size; 0 disables "
                        f"(default {DEFAULT_MIN_BLOB_PIXELS})")
    p.add_argument("--slice", type=int, default=None,
                   help="slice index to save for multi-slice files "
                        "(default: the slice with the most tumor pixels)")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    sub.add_parser("list", help="list the models found in the model store")
    return parser


def _cmd_list(registry: ModelRegistry) -> int:
    entries = registry.list()
    if not entries:
        print(f"no models found in {registry.model_store}")
        return 1
    for e in entries:
        score = "n/a" if e.best_score is None else f"{e.best_score:.4f}"
        print(f"{e.key}\n    {e.display_label}\n    scan type: {e.scan_type_label}; "
              f"fold {e.fold} of {sorted(e.folds)} (best_score {score}); "
              f"threshold {e.threshold}; preprocessing {e.preprocessing}")
    return 0


def _cmd_predict(registry: ModelRegistry, args: argparse.Namespace) -> int:
    result = run_file(
        args.file, args.model, registry=registry,
        min_blob_pixels=args.min_blob_pixels, batch_size=args.batch_size,
    )
    index = result.default_slice_index() if args.slice is None else args.slice
    if not 0 <= index < result.n_slices:
        print(f"error: --slice {index} is out of range (file has {result.n_slices} slice(s))",
              file=sys.stderr)
        return 2
    chosen = result.slices[index]
    paths = save_slice_result(chosen, args.out)
    print(json.dumps(chosen.summary, indent=2))
    for name in ("mask", "overlay", "summary"):
        print(f"wrote {paths[name]}")
    print(DISCLAIMER)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    registry = ModelRegistry(args.model_store)
    try:
        if args.command == "list":
            return _cmd_list(registry)
        return _cmd_predict(registry, args)
    except (RegistryError, UnsupportedFormatError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
