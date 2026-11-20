"""Run from the project root: python -m browzine_mock [serve|reset|export-openapi]."""

import argparse
import json
from pathlib import Path

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="PolyGate BrowZine mock API")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "reset", "export-openapi"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--yes", action="store_true", help="Confirm restoring the database to its seed data")
    parser.add_argument("--output", type=Path, default=Path("openapi.live.json"),
                        help="Where export-openapi writes (never the reviewed openapi.json by default)")
    args = parser.parse_args()
    if args.command == "reset" and not args.yes:
        parser.error("Reset deletes every change made to the mock data. Add --yes to confirm.")
    application = create_app()
    if args.command == "reset":
        application.state.store.reset()
        print(f"Seed data restored: {application.state.store.db_path}")
    elif args.command == "export-openapi":
        args.output.write_text(json.dumps(application.openapi(), indent=2), encoding="utf-8")
        print(f"OpenAPI specification: {args.output.resolve()}")
    else:
        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535")
        import uvicorn
        print(f"Interactive API documentation: http://{args.host}:{args.port}/docs")
        uvicorn.run(application, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
