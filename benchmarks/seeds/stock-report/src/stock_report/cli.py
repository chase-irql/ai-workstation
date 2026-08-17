import argparse
import json
from pathlib import Path

from .formatter import format_inventory
from .models import Item


def load_items(path: Path) -> list[Item]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Item(**row) for row in rows]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(format_inventory(load_items(args.inventory)))
    return 0
