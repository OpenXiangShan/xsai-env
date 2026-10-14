#!/usr/bin/env python3
"""Small fork-per-request torch warm daemon, adapted from the proven recipe."""
import argparse
import json
import os
import runpy
import signal
import socket
import struct
import sys
import traceback


def serve(conn, argv, code, cwd, env, server):
    pid = os.fork()
    if pid == 0:
        try:
            server.close()
            if cwd:
                os.chdir(cwd)
            os.environ.update({k: str(v) for k, v in (env or {}).items()})

            class Channel:
                def write(self, value):
                    data = value.encode() if isinstance(value, str) else value
                    if data:
                        conn.sendall(struct.pack(">I", len(data)) + data)
                    return len(data)

                def flush(self):
                    pass

                def isatty(self):
                    return False

                def fileno(self):
                    return conn.fileno()

            sys.stdout = Channel()
            sys.stderr = sys.stdout
            try:
                if code is not None:
                    exec(compile(code, "<warmctl>", "exec"), {"__name__": "__main__"})
                else:
                    sys.argv = list(argv)
                    runpy.run_path(argv[0], run_name="__main__")
                rc = 0
            except SystemExit as exc:
                rc = exc.code if isinstance(exc.code, int) else 0
            except BaseException:
                traceback.print_exc()
                rc = 1
            conn.sendall(struct.pack(">I", 0x80000000 | (rc & 0xff)))
        except OSError:
            pass
        finally:
            os._exit(0)
    conn.close()
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sock", default="/run/torchd.sock")
    parser.add_argument("--preload", default="torch,numpy")
    parser.add_argument("--preload-script", default="")
    args = parser.parse_args()
    if os.path.exists(args.sock):
        os.unlink(args.sock)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(args.sock)
    os.chmod(args.sock, 0o600)
    server.listen(8)
    for module in filter(None, args.preload.split(",")):
        __import__(module)
    if args.preload_script:
        runpy.run_path(args.preload_script, run_name="__preload__")
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    sys.stderr.write("warmd ready sock=%s preloaded=%s\n" % (args.sock, args.preload))
    while True:
        conn, _ = server.accept()
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        try:
            request = json.loads(data.decode() or "{}")
            serve(conn, request.get("argv") or [], request.get("code"),
                  request.get("cwd"), request.get("env"), server)
        except (ValueError, OSError):
            conn.close()


if __name__ == "__main__":
    main()
