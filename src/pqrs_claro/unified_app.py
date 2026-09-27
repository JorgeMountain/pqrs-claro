"""Interfaz del recorrido y API local en un único proceso y puerto."""

import argparse
from dataclasses import replace

from .app import create_app
from .config import Settings


def create_unified_app(settings=None, **dependencies):
    return create_app(settings, interface="recorrido", **dependencies)


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    settings = replace(
        Settings.load(), port=args.port,
        initial_review_enabled=True, initial_classification_provider="openai",
    )
    uvicorn.run(create_unified_app(settings), host="127.0.0.1", port=args.port,
                access_log=False)


if __name__ == "__main__":
    main()
