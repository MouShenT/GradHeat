import argparse
from pathlib import Path

import uvicorn

from gradheat_workbench.app import create_app


def main():
    parser = argparse.ArgumentParser(description="启动仅监听本机的GradHeat择校工作台")
    parser.add_argument("--port", type=int, default=18727)
    parser.add_argument("--snapshot", type=Path, help="固定使用指定的comparison.json快照目录")
    parser.add_argument("--session-db", type=Path, help="使用指定的本地比较记录库")
    args = parser.parse_args()
    print(f"GradHeat 工作台 http://127.0.0.1:{args.port} （Ctrl+C停止）", flush=True)
    uvicorn.run(create_app(snapshot=args.snapshot, session_db=args.session_db), host="127.0.0.1",
                port=args.port, access_log=False)


if __name__ == "__main__":
    main()
