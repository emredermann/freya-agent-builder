"""Cancel any stuck or running simulations in the workspace."""
from __future__ import annotations

import pathlib
import sys

KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

import freya


def main():
    print("Checking active simulations in Freya workspace...")
    cancelled = freya.cancel_running_simulations()
    if cancelled:
        print(f"Successfully cancelled {len(cancelled)} stuck simulation(s): {cancelled}")
    else:
        print("No stuck or running simulations found. Workspace is clear!")


if __name__ == "__main__":
    main()
