import argparse
import json

from .demo import demo_grants, run_demo, run_worker
from .policy import ExpensePolicy
from .runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description="Governed Work Runtime — local reference prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run a real crash-and-recovery demonstration")
    demo.add_argument("--directory", help="Parent directory for a fresh demo folder")
    inspect = sub.add_parser("inspect", help="Print a persisted work snapshot and event history")
    inspect.add_argument("--db", required=True)
    inspect.add_argument("--work", default="demo")
    worker = sub.add_parser("worker", help="Internal demonstration worker")
    worker.add_argument("--runtime", required=True)
    worker.add_argument("--oa", required=True)
    worker.add_argument("--operation", required=True)
    worker.add_argument("--crash-after-effect", action="store_true")
    args = parser.parse_args()
    if args.command == "demo":
        run_demo(args.directory)
    elif args.command == "inspect":
        runtime = Runtime(args.db, ExpensePolicy(), demo_grants())
        print(json.dumps({"work": runtime.get_work(args.work), "events": runtime.events(args.work)},
                         ensure_ascii=False, indent=2))
    else:
        run_worker(args.runtime, args.oa, args.operation, args.crash_after_effect)
