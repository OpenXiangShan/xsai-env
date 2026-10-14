#!/usr/bin/env python3
"""Client for the warmd length-framed stdout protocol."""
import argparse
import json
import os
import socket
import struct
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sock", default="/run/torchd.sock")
    parser.add_argument("--code")
    parser.add_argument("--cwd")
    parser.add_argument("argv", nargs="*")
    args = parser.parse_args()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(args.sock)
    client.sendall((json.dumps({
        "argv": args.argv, "code": args.code,
        "cwd": args.cwd or os.getcwd(),
    }) + "\n").encode())
    while True:
        header = client.recv(4)
        if len(header) != 4:
            raise SystemExit("warmd: connection closed early")
        size = struct.unpack(">I", header)[0]
        if size & 0x80000000:
            raise SystemExit(size & 0xff)
        data = b""
        while len(data) < size:
            chunk = client.recv(size - len(data))
            if not chunk:
                raise SystemExit("warmd: output frame truncated")
            data += chunk
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
