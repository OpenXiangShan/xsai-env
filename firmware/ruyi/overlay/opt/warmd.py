#!/usr/bin/env python3
"""torch 预热常驻服务：import 一次，之后每个任务 fork 一个子进程跑。

为什么是 fork 而不是 exec：exec 会把预热好的解释器换掉，白 import。fork 出来的
子进程通过写时复制共享父进程已经 import 好的 torch 页表，子进程只付“真正干活”
的代价。子进程对内存的任何修改都不会回传给父进程或兄弟进程。

协议（每连接一次请求，换行结尾的 JSON）：
    {"cwd": "/", "argv": ["/opt/job.py", "arg1"], "code": null, "env": {...}}
    argv 非空 → 等价于 python3 argv...
    code 非空 → 等价于 python3 -c code
子进程的 stdout/stderr 直接写回同一个 socket（帧格式：4 字节大端长度 + 数据），
最后发一个 4 字节大端退出码。

用法：
    服务端:  python3 warmd.py --sock /run/torchd.sock --preload torch,numpy
    客户端:  python3 warmctl.py --sock /run/torchd.sock -- /opt/job.py a b
"""
import argparse, json, os, runpy, signal, socket, struct, sys, traceback

PRELOADED = []

def _serve_one(conn, argv, code, cwd, env):
    """在 fork 出来的子进程里跑任务，输出经 conn 回传。"""
    pid = os.fork()
    if pid == 0:                                    # ---- child ----
        try:
            os.close(srv_sock.fileno())
        except Exception:
            pass
        try:
            if cwd:
                os.chdir(cwd)
            if env:
                os.environ.update({k: str(v) for k, v in env.items()})

            class _Chan:
                """把未缓冲写折成帧，父进程那边按帧还原成字节流。"""
                def __init__(self, sock):
                    self.sock = sock
                def write(self, b):
                    if isinstance(b, str):
                        b = b.encode()
                    if not b:
                        return 0
                    try:
                        self.sock.sendall(struct.pack(">I", len(b)) + b)
                    except OSError:
                        pass
                    return len(b)
                def flush(self):
                    pass
                def isatty(self):
                    return False
                def writelines(self, lines):
                    for l in lines:
                        self.write(l)
                def fileno(self):
                    return self.sock.fileno()

            chan = _Chan(conn)
            sys.stdout = chan
            sys.stderr = chan
            rc = 0
            try:
                if code is not None:
                    exec(compile(code, "<warmctl -c>", "exec"), {"__name__": "__main__"})
                else:
                    sys.argv = list(argv)
                    runpy.run_path(argv[0], run_name="__main__")
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            except BaseException:
                traceback.print_exc()
                rc = 1
            try:
                # 客户端约定：最高位置 1 的帧表示退出码，其余为数据帧
                conn.sendall(struct.pack(">I", 0x80000000 | (rc & 0xFF)))
            except OSError:
                pass
        finally:
            os._exit(0)
    # ---- parent ----
    conn.close()
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        # 子进程已被 SIGCHLD 处理器回收，属正常路径
        pass


def main():
    global srv_sock
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", default="/run/torchd.sock")
    ap.add_argument("--preload", default="torch,numpy")
    ap.add_argument("--preload-script", default="")
    ap.add_argument("--backlog", type=int, default=8)
    a = ap.parse_args()

    # 先建 socket 再预载：客户端可以提前连上排队，不必等 import torch 完成
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    srv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv_sock.bind(a.sock)
    os.chmod(a.sock, 0o600)
    srv_sock.listen(a.backlog)
    for name in [m for m in a.preload.split(",") if m]:
        __import__(name)
        PRELOADED.append(name)
    if a.preload_script:
        runpy.run_path(a.preload_script, run_name="__preload__")
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)     # 交给内核回收，避免僵尸
    sys.stderr.write(f"warmd ready sock={a.sock} preloaded={PRELOADED}\n")
    sys.stderr.flush()

    while True:
        conn, _ = srv_sock.accept()
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 1 << 22:
                break
        try:
            req = json.loads(buf.decode() or "{}")
        except Exception:
            conn.close()
            continue
        _serve_one(conn, req.get("argv") or [], req.get("code"), req.get("cwd"), req.get("env"))


if __name__ == "__main__":
    main()
