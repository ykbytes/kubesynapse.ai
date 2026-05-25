"""Entry point for `python -m agentctl` and the installed console script."""

from agentctl.app import app
from agentctl.commands import register_all


def main() -> None:
    register_all(app)
    app()


if __name__ == "__main__":
    main()
