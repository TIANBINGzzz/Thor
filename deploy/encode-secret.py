"""Encode a local JSON configuration for a Flow private variable; never print secrets."""

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("write_env", Path(__file__).with_name("write-env.py"))
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local *.secret.json file; never commit it")
    parser.add_argument("output", type=Path, help="New *.secret.b64 file; copy its contents to Flow")
    args = parser.parse_args()
    try:
        environment = writer.parse_bundle(args.input.read_text(encoding="utf-8-sig"))
        encoded = base64.b64encode(json.dumps(environment, ensure_ascii=False).encode("utf-8"))
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    except OSError:
        parser.exit(1, "Cannot read input or create output; choose an existing directory and a new output file.\n")
    print("Encoded configuration written. Copy the file content into CCSDK_DEPLOY_ENV_B64 with private mode enabled.")


if __name__ == "__main__":
    main()
