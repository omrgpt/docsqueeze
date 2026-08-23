"""python -m docsqueeze entrypoint."""

import sys

from .core import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
