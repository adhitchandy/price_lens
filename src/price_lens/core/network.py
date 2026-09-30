"""Detect a lost internet connection and wait for it to come back.

A storefront is only treated as "offline" when BOTH are true:
* the browser errors look like network errors (Firefox "about:neterror", DNS failures, ...), and
* a quick connectivity probe to the storefront fails.
That keeps company networks with proxies (where raw probes may fail while the browser works)
from ever pausing a healthy run.
"""
from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable, Iterable

NETWORK_ERROR = re.compile(
    r"neterror|dnsnotfound|connectionfailure|nettimeout|netreset|netoffline|"
    r"reached error page|proxyconnectfailure|err_internet_disconnected|err_name_not_resolved|"
    r"err_network_changed|err_connection_timed_out|name or service not known|"
    r"getaddrinfo failed|temporary failure in name resolution|network is unreachable|"
    r"no route to host|connection (?:was )?reset|nodename nor servname",
    re.IGNORECASE,
)
WAIT_SECONDS = 15 * 60
POLL_SECONDS = 30
_sleep = time.sleep  # patched in tests


def is_network_error(text: str | None) -> bool:
    return bool(text) and bool(NETWORK_ERROR.search(str(text)))


def mostly_network_errors(errors: Iterable[str]) -> bool:
    errors = [e for e in errors if e]
    return bool(errors) and sum(is_network_error(e) for e in errors) * 2 >= len(errors)


def probe(hosts: Iterable[str], timeout: float = 4.0) -> bool:
    """True if any host resolves and accepts a TCP connection on 443."""
    for host in hosts:
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def storefront_hosts(domain: str) -> list[str]:
    return [f"www.{domain}", domain]


def wait_for_connection(domain: str, log: Callable[[str], None], *,
                        max_wait: int = WAIT_SECONDS, poll: int = POLL_SECONDS,
                        check: Callable[[list[str]], bool] | None = None) -> bool:
    """Poll until the storefront is reachable again. ``log`` is called every poll, so a user
    cancel (raised from the log callback) stops the wait. Returns False after ``max_wait``."""
    check = check or (lambda h: probe(h))  # resolved at call time
    hosts = storefront_hosts(domain)
    waited = 0
    while waited < max_wait:
        _sleep(poll)
        waited += poll
        if check(hosts):
            return True
        log(f"   … still offline after {waited // 60} min {waited % 60:02d} s "
            f"(waiting up to {max_wait // 60} min)")
    return False
