"""Preflight do host: oráculo seguro e sem operações de deploy."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import ops_host_preflight as preflight

GIB = 1024**3


def ready_host():
    return {
        "linux": True,
        "arch": "aarch64",
        "non_root": True,
        "memory_available": 5 * GIB,
        "disk_free": 12 * GIB,
        "docker_client": True,
        "docker_server": True,
        "docker_compose": True,
        "listen_ports": {"80": False, "443": False},
        "dns_resolves": True,
        "domain_supplied": True,
    }


def test_ready_technical_prereqs_do_not_fake_production_or_free_plan():
    report = preflight.assess(ready_host())
    assert report["mode"] == "READ_ONLY"
    assert report["deployment_performed"] is False
    assert report["expenses_authorized"] is False
    assert report["production_validated"] is False
    assert report["checks"]["os"]["state"] == "PASS"
    assert report["checks"]["docker_server"]["state"] == "PASS"
    assert report["checks"]["tcp_80"]["state"] == "PASS"
    assert report["checks"]["tcp_443"]["state"] == "PASS"
    assert report["checks"]["dns"]["state"] == "WARN"
    for gate in ("billing", "firewall_tls", "offhost_backup"):
        assert report["checks"][gate]["state"] == "BLOCKED"
    assert report["status"] == "BLOCKED"


@pytest.mark.parametrize("field,value,failed_gate", [
    ("linux", False, "os"),
    ("arch", "mips64", "arch"),
    ("non_root", False, "user"),
    ("memory_available", 800 * 1024**2, "memory"),
    ("memory_available", None, "memory"),
    ("disk_free", 2 * GIB, "disk"),
    ("disk_free", None, "disk"),
    ("docker_client", False, "docker_client"),
    ("docker_server", False, "docker_server"),
    ("docker_compose", False, "docker_compose"),
    ("listen_ports", {"80": True, "443": False}, "tcp_80"),
    ("listen_ports", {"80": False, "443": True}, "tcp_443"),
    ("listen_ports", None, "tcp_80"),
    ("dns_resolves", False, "dns"),
])
def test_missing_requirement_blocks_without_exception(field, value, failed_gate):
    host = ready_host()
    host[field] = value
    report = preflight.assess(host)
    assert report["checks"][failed_gate]["state"] == "BLOCKED"
    assert report["status"] == "BLOCKED"


def test_no_domain_does_not_resolve_or_pretend_dns():
    host = ready_host()
    host["domain_supplied"] = False
    host["dns_resolves"] = None
    report = preflight.assess(host)
    assert report["checks"]["dns"]["state"] == "BLOCKED"


def test_report_never_discloses_hostname_ip_or_provider_credentials():
    report = preflight.assess(ready_host())
    output = json.dumps(report)
    assert "192.168." not in output
    assert "10.0.0." not in output
    assert "hostname" not in output
    assert "password" not in output
    assert "token" not in output
    assert "billing" in output
    assert "não" not in output or "BLOCKED" in output


def test_socket_listener_parser_only_exposes_boolean(monkeypatch):
    def fake_run(args, **kwargs):
        assert args == ["ss", "-ltnH"]
        assert kwargs.get("shell") is False
        return SimpleNamespace(returncode=0, stdout=(
            "LISTEN 0 128 127.0.0.1:5432 0.0.0.0:*\n"
            "LISTEN 0 128 0.0.0.0:80 0.0.0.0:*\n"
            "LISTEN 0 128 [::]:2222 [::]:*\n"
        ))
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert preflight._listen_ports() == {"80": True, "443": False}


def test_ss_missing_is_unknown_not_false_free(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", missing)
    assert preflight._listen_ports() is None
    assert preflight._run(["docker", "--version"]) is False


def test_subprocess_introspection_never_uses_shell(monkeypatch):
    observed = []
    def fake_run(args, **kwargs):
        observed.append((args, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert preflight._run(["docker", "--version"]) is True
    assert observed[0][1]["shell"] is False
    assert observed[0][1]["timeout"] == 7


def test_disposable_cli_outputs_blocked_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "collect_facts", lambda domain=None: ready_host())
    monkeypatch.setattr("sys.argv", ["ops_host_preflight"])
    with pytest.raises(SystemExit) as result:
        preflight.main()
    assert result.value.code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"
    assert report["deployment_performed"] is False


def test_domain_validation_rejects_unsupported_values(monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "ops_host_preflight", "--domain", "https://127.0.0.1:443",
    ])
    with pytest.raises(SystemExit) as result:
        preflight.main()
    assert result.value.code == 2
