from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import DeviceTarget, HealthCheckProfile
from app.modules.health_check.collector import run_health_check_job
from app.modules.initial_setup.generator import NetworkProfile, generate_initial_setup_artifacts
from app.modules.vpe_macro.generator import VpeMacroRequest, generate_vpe_macro_artifacts


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_data_dir() -> Path:
    return Path.home() / "appdata" / "local" / "f5tool"


def cmd_health_check(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    output = Path(args.output)
    job_store = JobStore(data_dir / "jobs.db")
    audit = AuditLogger(data_dir / "audit")

    fixtures = None
    if args.use_fixture:
        import json

        fixture_path = _project_root() / "tests" / "fixtures" / "tmos_lab.json"
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixtures = {"lab-device-01": raw}

    job = run_health_check_job(
        job_store=job_store,
        audit=audit,
        output_root=output,
        site_name=args.site_name,
        period=args.period,
        engineer_notes=args.notes,
        targets=[DeviceTarget(label="lab-device-01", host=args.host or "203.0.113.10")],
        check_profile=HealthCheckProfile(),
        mock_fixtures=fixtures,
        operator=getpass.getuser(),
    )
    print(f"job: {job.job_id} status={job.status.value}")
    print(f"output: {output / job.job_id}")
    return 0 if job.status.value == "completed" else 1


def cmd_initial_setup(args: argparse.Namespace) -> int:
    profile = NetworkProfile(
        hostname=args.hostname,
        mgmt_ip=args.mgmt_ip,
        mgmt_netmask=args.netmask,
        gateway=args.gateway,
        dns_servers=args.dns.split(",") if args.dns else [],
        ntp_servers=args.ntp.split(",") if args.ntp else [],
        vlans=[{"name": "internal", "tag": 100}],
    )
    for path in generate_initial_setup_artifacts(profile, Path(args.output)):
        print(path)
    return 0


def cmd_vpe_macro(args: argparse.Namespace) -> int:
    request = VpeMacroRequest(
        auth_method=args.auth,
        resource_model=args.resource_model,
        mfa_methods=args.mfa.split(",") if args.mfa else [],
        irule_required=args.irule,
        group_mappings={"lab-group-01": "webtop_lab"},
    )
    for path in generate_vpe_macro_artifacts(request, Path(args.output)):
        print(path)
    return 0


def cmd_check_naming(_args: argparse.Namespace) -> int:
    from tools.check_naming import main as naming_main

    return naming_main([str(_project_root())])


def cmd_gui(_args: argparse.Namespace) -> int:
    from app.gui.main import main as gui_main

    return gui_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="f5tool")
    parser.add_argument("--data-dir", default=str(_default_data_dir()))
    sub = parser.add_subparsers(dest="command", required=True)

    hc = sub.add_parser("health-check")
    hc.add_argument("--output", default="output")
    hc.add_argument("--host", default=None)
    hc.add_argument("--site-name", default="lab-site")
    hc.add_argument("--period", default="")
    hc.add_argument("--notes", default="")
    hc.add_argument("--use-fixture", action="store_true")
    hc.set_defaults(func=cmd_health_check)

    init = sub.add_parser("initial-setup")
    init.add_argument("--output", default="output/initial_setup")
    init.add_argument("--hostname", default="lab-bigip-01.example.invalid")
    init.add_argument("--mgmt-ip", default="203.0.113.10")
    init.add_argument("--netmask", default="255.255.255.0")
    init.add_argument("--gateway", default="203.0.113.1")
    init.add_argument("--dns", default="203.0.113.53")
    init.add_argument("--ntp", default="203.0.113.123")
    init.set_defaults(func=cmd_initial_setup)

    vpe = sub.add_parser("vpe-macro")
    vpe.add_argument("--output", default="output/vpe_macro")
    vpe.add_argument("--auth", choices=["ad", "radius", "oauth", "saml"], default="ad")
    vpe.add_argument("--resource-model", choices=["by_group", "by_account"], default="by_group")
    vpe.add_argument("--mfa", default="")
    vpe.add_argument("--irule", action="store_true")
    vpe.set_defaults(func=cmd_vpe_macro)

    sub.add_parser("check-naming").set_defaults(func=cmd_check_naming)

    sub.add_parser("gui", help="launch preview desktop ui").set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
