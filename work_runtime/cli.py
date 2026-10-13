import argparse
import json

from .demo import demo_grants, run_demo, run_worker
from .intervention_demo import run_intervention_demo
from .policy import ExpensePolicy, ExpensePolicyV2
from .publishing import PublishingPolicy
from .publishing_demo import publishing_grants, run_demo as run_publish_demo
from .runtime import Runtime

SUPPORTED_EXPENSE_VERSIONS = ("demo-1", "demo-2")


def _expense_registry(spec):
    """Build (default policy, registry) from a strict --policy-versions spec.

    Tokens are exact version strings separated by commas; demo-1 resolves to
    the default object itself, demo-2 to the published stronger version.
    Raises ValueError with the offending token on any malformed input.
    """
    default = ExpensePolicy()
    registry, seen = {}, set()
    for token in spec.split(","):
        if not token:
            raise ValueError("empty policy version in --policy-versions")
        if token in seen:
            raise ValueError("duplicate policy version '%s'" % token)
        seen.add(token)
        if token == default.version:
            registry[token] = default
        elif token == "demo-2":
            registry[token] = ExpensePolicyV2()
        else:
            raise ValueError("unknown policy version '%s'; supported versions: %s"
                             % (token, ", ".join(SUPPORTED_EXPENSE_VERSIONS)))
    return default, registry


def main(argv=None):
    parser = argparse.ArgumentParser(description="Governed Work Runtime — local reference prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run a real crash-and-recovery demonstration")
    demo.add_argument("--directory", help="Parent directory for a fresh demo folder")
    publish = sub.add_parser("publish-demo",
                             help="Run the signed-evidence content publication demonstration")
    publish.add_argument("--directory", help="Parent directory for a fresh demo folder")
    intervention = sub.add_parser(
        "intervention-demo",
        help="Run the ownership-transfer, cancellation and policy-migration demonstration")
    intervention.add_argument("--directory", help="Parent directory for a fresh demo folder")
    inspect = sub.add_parser("inspect", help="Print a persisted work snapshot and event history")
    inspect.add_argument("--db", required=True)
    inspect.add_argument("--work", default="demo")
    inspect.add_argument("--policy", choices=["expense-submit", "content-publish"],
                         default="expense-submit",
                         help="Policy that owns this database (default: expense-submit)")
    inspect.add_argument("--policy-versions", dest="policy_versions", default=None,
                         help="Explicitly load comma-separated expense policy versions "
                              "(demo-1,demo-2) so pinned works can be inspected")
    worker = sub.add_parser("worker", help="Internal demonstration worker")
    worker.add_argument("--runtime", required=True)
    worker.add_argument("--oa", required=True)
    worker.add_argument("--operation", required=True)
    worker.add_argument("--crash-after-effect", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "demo":
        run_demo(args.directory)
    elif args.command == "publish-demo":
        run_publish_demo(args.directory)
    elif args.command == "intervention-demo":
        run_intervention_demo(args.directory)
    elif args.command == "inspect":
        if args.policy == "content-publish":
            if args.policy_versions is not None:
                parser.error("--policy-versions loads expense-family versions only; "
                             "it cannot be combined with --policy content-publish")
            runtime = Runtime(args.db, PublishingPolicy(), publishing_grants())
        elif args.policy_versions is not None:
            try:
                default, registry = _expense_registry(args.policy_versions)
            except ValueError as error:
                parser.error(str(error))
            runtime = Runtime(args.db, default, demo_grants(), policies=registry)
        else:
            runtime = Runtime(args.db, ExpensePolicy(), demo_grants())
        print(json.dumps({"work": runtime.get_work(args.work), "events": runtime.events(args.work)},
                         ensure_ascii=False, indent=2))
    else:
        run_worker(args.runtime, args.oa, args.operation, args.crash_after_effect)
