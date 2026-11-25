"""Preflight NÃO destrutivo do host, antes de qualquer tentativa de deploy.

Não consulta Oracle/conta de nuvem, não altera configurações e jamais confirma
elegibilidade de custo, identidade do DNS, certificados ou firewall externo.
Não publica hostname, IP, portas de serviços além de 80/443 ou logs do Docker.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from scripts.ops_setup import validate_domain

MIB = 1024 * 1024
GIB = 1024 * MIB
ARCHITECTURES = {"x86_64", "aarch64", "arm64"}


def _run(args: list[str]) -> bool:
    """Somente introspecção sem shell, saída descartada, timeout curto."""
    try:
        completed = subprocess.run(
            args, shell=False, capture_output=True, text=False, timeout=7,
            check=False,
        )
        return completed.returncode == 0
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return False


def _memory_available() -> int | None:
    try:
        with Path("/proc/meminfo").open(encoding="ascii") as data:
            for line in data:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _listen_ports() -> dict[str, bool] | None:
    """Usa ss para detectar portas em LISTEN; nunca retorna sockets/IPs."""
    try:
        proc = subprocess.run(
            ["ss", "-ltnH"], shell=False, capture_output=True, text=True,
            timeout=7, check=False,
        )
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    occupied = {"80": False, "443": False}
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0] != "LISTEN":
            continue
        port = fields[3].rsplit(":", 1)[-1]
        if port in occupied:
            occupied[port] = True
    return occupied


def _dns_resolves(domain: str | None) -> bool | None:
    """Resolução DNS opcional, sem divulgar o resultado nem conferir IP da VPS."""
    if not domain:
        return None
    try:
        validate_domain(domain)
        return bool(socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM))
    except (socket.gaierror, OSError, ValueError):
        return False


def collect_facts(domain: str | None = None) -> dict[str, Any]:
    """Coleta estritamente leitura local, sem acessar dados financeiros."""
    linux = platform.system() == "Linux"
    try:
        free_disk = shutil.disk_usage("/").free
    except OSError:
        free_disk = None
    return {
        "linux": linux,
        "arch": platform.machine().lower(),
        "non_root": (os.geteuid() != 0) if hasattr(os, "geteuid") else False,
        "memory_available": _memory_available() if linux else None,
        "disk_free": free_disk,
        "docker_client": _run(["docker", "--version"]),
        "docker_server": _run(["docker", "info", "--format", "{{.ServerVersion}}"]),
        "docker_compose": _run(["docker", "compose", "version"]),
        "listen_ports": _listen_ports() if linux else None,
        "dns_resolves": _dns_resolves(domain),
        "domain_supplied": bool(domain),
    }


def assess(facts: dict[str, Any]) -> dict[str, Any]:
    """Nenhum campo do relatório é secret ou endpoint. Custo nunca é aprovado aqui."""
    checks = {}

    def add(name: str, state: str, note: str) -> None:
        checks[name] = {"state": state, "note": note}

    add("os", "PASS" if facts.get("linux") else "BLOCKED",
        "Linux comprovado" if facts.get("linux") else "Requer host Linux")
    add("arch", "PASS" if facts.get("arch") in ARCHITECTURES else "BLOCKED",
        "Arquitetura suportada por Docker" if facts.get("arch") in ARCHITECTURES
        else "Arquitetura não qualificada")
    add("user", "PASS" if facts.get("non_root") else "BLOCKED",
        "Execução não root" if facts.get("non_root") else
        "Execute a inspeção como usuário não root, com acesso permitido ao Docker")

    mem = facts.get("memory_available")
    add("memory", "PASS" if isinstance(mem, int) and mem >= GIB else "BLOCKED",
        "Memória disponível >=1 GiB" if isinstance(mem, int) and mem >= GIB
        else "Não comprovados 1 GiB de RAM disponível")
    disk = facts.get("disk_free")
    add("disk", "PASS" if isinstance(disk, int) and disk >= 3 * GIB else "BLOCKED",
        "Disco livre >=3 GiB no filesystem raiz (não garante espaço no Docker)"
        if isinstance(disk, int) and disk >= 3 * GIB else
        "Não comprovados 3 GiB livres no filesystem raiz")

    for key, caption in (
        ("docker_client", "CLI Docker"),
        ("docker_server", "Daemon Docker acessível"),
        ("docker_compose", "Docker Compose"),
    ):
        add(key, "PASS" if facts.get(key) is True else "BLOCKED",
            caption + (" detectado" if facts.get(key) is True else " indisponível"))

    ports = facts.get("listen_ports")
    for port in ("80", "443"):
        free = isinstance(ports, dict) and ports.get(port) is False
        add("tcp_" + port, "PASS" if free else "BLOCKED",
            f"TCP {port} livre para Caddy" if free else
            f"TCP {port} ocupado ou estado desconhecido; não alterar serviços existentes")

    if facts.get("domain_supplied"):
        add("dns", "WARN" if facts.get("dns_resolves") is True else "BLOCKED",
            "DNS resolve, mas ainda exige comparação com IP da VPS e validação externa"
            if facts.get("dns_resolves") is True else "Domínio sem resolução confirmada")
    else:
        add("dns", "BLOCKED", "Subdomínio real ainda não informado; sem consulta DNS")

    # Indisponível ao script: jamais afirmar gratuidade só com hardware local.
    add("billing", "BLOCKED",
        "Plano, quota e eventuais cobranças dependem de prova no console da VPS")
    add("firewall_tls", "BLOCKED",
        "Firewall, acesso 80/443 e certificado HTTPS exigem validação externa")
    add("offhost_backup", "BLOCKED",
        "Cópia off-host e recuperação ainda exigem plano e evidência reais")

    return {
        "mode": "READ_ONLY",
        "status": "BLOCKED" if any(
            item["state"] == "BLOCKED" for item in checks.values()
        ) else "READY_FOR_REVIEW",
        "checks": checks,
        "deployment_performed": False,
        "expenses_authorized": False,
        "production_validated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspeção local somente leitura, sem criar recursos ou executar deploy"
    )
    parser.add_argument("--domain", default=None, help="Subdomínio HTTPS já controlado")
    args = parser.parse_args()
    if args.domain:
        try:
            validate_domain(args.domain)
        except ValueError:
            parser.error("Use um subdomínio DNS real sem esquema ou porta.")
    report = assess(collect_facts(args.domain))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Code 2 significa 'faltam gates externos', não falha de teste do aplicativo.
    raise SystemExit(2 if report["status"] == "BLOCKED" else 0)


if __name__ == "__main__":
    main()
