import argparse

import uvicorn

from .web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="dubber", description="Dubber, interfaz web")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    # Solo 127.0.0.1: la app lanza procesos y escribe archivos en tu equipo.
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
