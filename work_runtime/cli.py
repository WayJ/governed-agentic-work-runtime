import argparse
import json

from .adoption_demo import run_adoption_demo, run_lint_sop
from .compensation_demo import run_compensation_demo
from .demo import demo_grants, run_demo, run_worker
from .intervention_demo import run_intervention_demo
from .policy import ExpensePolicy, ExpensePolicyV2
from .publication import SopPublicationPolicy
from .publication_demo import publication_grants, run_publication_demo
from .publishing import PublishingPolicy
from .publishing_demo import publishing_grants, run_demo as run_publish_demo
from .support import SupportPolicy, support_grants
from .support_demo import run_demo as run_support_demo
from .revocation_demo import run_revocation_demo
from .rotation_demo import run_rotation_demo
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
    adoption = sub.add_parser(
        "adoption-demo",
        help="Run the SOP lint plus file-adapter adoption demonstration")
    adoption.add_argument("--directory", help="Parent directory for a fresh demo folder")
    revocation = sub.add_parser(
        "revocation-demo",
        help="Run the evidence-revocation demonstration (hold, retained "
             "effects, closed-work correction)")
    revocation.add_argument("--directory", help="Parent directory for a fresh demo folder")
    compensation = sub.add_parser(
        "compensation-demo",
        help="Run the expense-compensation demonstration (real crash "
             "withdrawal, retained history, refusal-not-reversal)")
    compensation.add_argument("--directory", help="Parent directory for a fresh demo folder")
    rotation = sub.add_parser(
        "rotation-demo",
        help="Run the signing-key rotation demonstration (dual-key window, "
             "retirement, verbatim cached receipts, preserved history)")
    rotation.add_argument("--directory", help="Parent directory for a fresh demo folder")
    support = sub.add_parser(
        "support-demo",
        help="Run the support-ticket admission and crash-recovery demonstration "
             "(unknown blocks, ticket-reference business key, real crash "
             "recovery)")
    support.add_argument("--directory",
                         help="Parent directory for a fresh demo folder")
    publication = sub.add_parser(
        "publication-demo",
        help="Run the governed SOP rule-card publication demonstration "
             "(lint, signed approval, one immutable hash-named artifact, "
             "doctored-card conflict, loader fail-closed, key rotation)")
    publication.add_argument("--directory",
                             help="Parent directory for a fresh demo folder")
    lint = sub.add_parser("lint-sop",
                          help="Lint a static SOP rule-card JSON file "
                               "(exit 0 clean / 1 diagnostics / 2 file error)")
    lint.add_argument("path", help="Path to the SOP JSON file")
    lint.add_argument("--json", dest="as_json", action="store_true",
                      help="Print the exact static-only JSON result envelope")
    inspect = sub.add_parser("inspect", help="Print a persisted work snapshot and event history")
    inspect.add_argument("--db", required=True)
    inspect.add_argument("--work", default="demo")
    inspect.add_argument("--policy",
                         choices=["expense-submit", "content-publish",
                                  "sop-publish", "support-ticket"],
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
    ui = sub.add_parser("ui",
                        help="Serve the read-only local GUI for an existing store")
    ui.add_argument("--db", required=True, help="Path to an existing runtime database")
    ui.add_argument("--port", type=int, default=0,
                    help="Loopback port (0-65535; default: an ephemeral port)")
    ui_demo = sub.add_parser(
        "ui-demo",
        help="Seed a five-work sample store and serve the read-only local GUI")
    ui_demo.add_argument("--directory", help="Parent directory for a fresh demo folder")
    ui_demo.add_argument("--port", type=int, default=0,
                         help="Loopback port (0-65535; default: an ephemeral port)")
    args = parser.parse_args(argv)
    if args.command == "demo":
        run_demo(args.directory)
    elif args.command == "publish-demo":
        run_publish_demo(args.directory)
    elif args.command == "intervention-demo":
        run_intervention_demo(args.directory)
    elif args.command == "adoption-demo":
        run_adoption_demo(args.directory)
    elif args.command == "revocation-demo":
        run_revocation_demo(args.directory)
    elif args.command == "compensation-demo":
        run_compensation_demo(args.directory)
    elif args.command == "rotation-demo":
        run_rotation_demo(args.directory)
    elif args.command == "publication-demo":
        run_publication_demo(args.directory)
    elif args.command == "support-demo":
        run_support_demo(args.directory)
    elif args.command == "lint-sop":
        raise SystemExit(run_lint_sop(args.path, args.as_json))
    elif args.command == "inspect":
        if args.policy == "sop-publish":
            if args.policy_versions is not None:
                parser.error("--policy-versions loads expense-family versions only; "
                             "it cannot be combined with --policy sop-publish")
            runtime = Runtime(args.db, SopPublicationPolicy(),
                              publication_grants())
        elif args.policy == "content-publish":
            if args.policy_versions is not None:
                parser.error("--policy-versions loads expense-family versions only; "
                             "it cannot be combined with --policy content-publish")
            runtime = Runtime(args.db, PublishingPolicy(), publishing_grants())
        elif args.policy == "support-ticket":
            if args.policy_versions is not None:
                parser.error("--policy-versions loads expense-family versions only; "
                             "it cannot be combined with --policy support-ticket")
            runtime = Runtime(args.db, SupportPolicy(), support_grants())
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
    elif args.command == "ui":
        # Imported here so the read-only UI backend stays optional: every
        # prior command keeps working in installs without it.
        from .ui_demo import serve_ui
        serve_ui(args.db, args.port)
    elif args.command == "ui-demo":
        from .ui_demo import run_ui_demo
        run_ui_demo(args.directory, args.port)
    else:
        run_worker(args.runtime, args.oa, args.operation, args.crash_after_effect)
