"""统一启动本机 API 与批次生图执行器，避免只启动接口而遗漏队列消费。"""
import argparse
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def wait_ready(api, port):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if api.poll() is not None:
            raise RuntimeError("接口进程启动失败，未启动生图执行器；请查看上方日志")
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(.5)
    raise RuntimeError("接口或数据库/对象存储未就绪，未启动生图执行器")


def run_services(*, port=8000):
    processes = []
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT)
        processes.append(api)
        wait_ready(api, port)
        worker = subprocess.Popen([sys.executable, "-m", "backend.cli", "generation-worker"], cwd=ROOT)
        processes.append(worker)
        print("接口与生图执行器已启动。执行器将处理已确认且未取消的队列任务。按 Ctrl+C 一起关闭。", flush=True)
        while True:
            for name, child in zip(("接口", "生图执行器"), processes):
                code = child.poll()
                if code is not None:
                    print(f"{name}已退出（退出码 {code}），正在关闭配套进程，请检查日志后重新启动。", file=sys.stderr, flush=True)
                    return code or 1
            time.sleep(.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(processes):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="同时启动 API 与生图执行器（会处理已确认队列）")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    from .app.core.config import get_settings
    if not get_settings().database_url:
        parser.error("需要配置 PostgreSQL，确保 API 与执行器共享同一队列；仅接口调试请用 npm run api:http")
    # 已有接口占用端口时拒绝启动，不额外拉起一个会消费任务的执行器。
    try:
        with socket.socket() as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", args.port))
    except (OSError, OverflowError):
        parser.error("端口不可用，请先关闭旧接口进程，或指定其他端口")
    def stop(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        return run_services(port=args.port)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
