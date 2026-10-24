#!/usr/bin/env python3
"""SaneQueue live comparison QA. READ-ONLY: GETs to local UI and AMI QueueStatus only.

No Asterisk dialplan changes, no AMI write commands, no caller/channel identifiers,
no stored passwords. Python 3.11+ standard library only.
"""
from __future__ import annotations

import collections
import datetime as dt
import getpass
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.request

APP_ORIGIN = "http://127.0.0.1:18882"
TARGET_QUEUE = "8001"
REPORT = Path(__file__).resolve().with_name("qa_readonly_result.json")
DEVICE_STATES = {
    "0": "unknown", "1": "ready", "2": "in_use", "3": "busy",
    "4": "invalid", "5": "unavailable", "6": "ringing",
    "7": "ring_in_use", "8": "on_hold", "10": "in_call",
}


def choose(prompt, default):
    value = input(f"{prompt} [{default}]: ").strip()
    return value or str(default)


def safe_target(host, port, queue):
    ip = ipaddress.ip_address(host)
    allowed_nets = (
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    if ip.version != 4 or not any(ip in network for network in allowed_nets):
        raise ValueError("Only loopback or an RFC1918 private IPv4 is allowed")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid AMI port")
    if not queue or len(queue) > 32 or not all(ch.isascii() and (ch.isalnum() or ch in '_-') for ch in queue):
        raise ValueError("Invalid queue identifier")


def read_packet(sock, buf):
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            raise EOFError("AMI disconnected")
        buf += chunk
        if len(buf) > 4_000_000:
            raise RuntimeError("AMI response exceeds size limit")
    raw, buf = buf.split(b"\r\n\r\n", 1)
    result = {}
    for line in raw.decode("utf-8", "replace").split("\r\n"):
        if ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value
    return result, buf


def query_ami(host, port, user, password, queue):
    """Send only Login, QueueStatus and Logoff. Summarize, never print raw IDs."""
    with socket.create_connection((host, port), timeout=6) as s:
        s.settimeout(8)
        greeting = bytearray()
        while b"\r\n" not in greeting:
            greeting += s.recv(2048)
            if len(greeting) > 2048:
                raise RuntimeError("AMI banner invalid")
        banner, _, buf = bytes(greeting).partition(b"\r\n")
        if not banner.startswith(b"Asterisk Call Manager"):
            raise RuntimeError("Not an AMI endpoint")
        def send(fields):
            for value in fields.values():
                if "\r" in str(value) or "\n" in str(value):
                    raise ValueError("Invalid AMI field")
            s.sendall(("".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n").encode("utf-8"))
        try:
            send({"Action": "Login", "Username": user, "Secret": password,
                  "Events": "on", "ActionID": "sqaudit-login"})
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                packet, buf = read_packet(s, buf)
                if packet.get("ActionID") == "sqaudit-login" or "Response" in packet:
                    if packet.get("Response") != "Success":
                        raise PermissionError("AMI login rejected")
                    break
            else:
                raise TimeoutError("AMI login timeout")
            send({"Action": "QueueStatus", "Queue": queue, "ActionID": "sqaudit-queue"})
            found = False
            statuses = collections.Counter()
            memberships = 0
            paused = 0
            entries = 0
            queue_waiting = None
            completed = None
            abandoned = None
            complete = False
            deadline = time.monotonic() + 9
            while time.monotonic() < deadline:
                packet, buf = read_packet(s, buf)
                if packet.get("ActionID") not in ("sqaudit-queue", None):
                    continue
                if packet.get("Response") == "Error":
                    raise PermissionError("QueueStatus rejected")
                event = packet.get("Event")
                if event == "QueueStatusComplete":
                    complete = True
                    break
                if packet.get("Queue") not in (queue, None):
                    continue
                if event == "QueueParams":
                    found = True
                    queue_waiting = int(packet.get("Calls") or 0)
                    completed = int(packet.get("Completed") or 0)
                    abandoned = int(packet.get("Abandoned") or 0)
                elif event == "QueueMember":
                    memberships += 1
                    statuses[str(packet.get("Status", "0"))] += 1
                    paused += int(str(packet.get("Paused", "0")) == "1")
                elif event == "QueueEntry":
                    entries += 1
            if not complete:
                raise TimeoutError("QueueStatus incomplete")
            return {
                "connected": True,
                "queue_found": found,
                "queue_members": memberships,
                "state_codes": dict(statuses),
                "state_labels": {DEVICE_STATES.get(k, f"unknown_{k}"): v for k, v in statuses.items()},
                "paused_members": paused,
                "waiting_from_params": queue_waiting,
                "waiting_entries": entries,
                "completed_since_reset": completed,
                "abandoned_since_reset": abandoned,
                "snapshot_complete": True,
            }
        finally:
            try:
                send({"Action": "Logoff", "ActionID": "sqaudit-logout"})
            except (OSError, ValueError):
                pass


def get_local_json(path):
    req = urllib.request.Request(APP_ORIGIN + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("Local API returned non-200 status")
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise RuntimeError("Local API not JSON")
        if int(response.headers.get("Content-Length", "0") or 0) > 3_000_000:
            raise RuntimeError("Local API response too large")
        return json.loads(response.read(3_000_001))


def panel_summary(queue):
    response = get_local_json("/api/operations")
    q = response.get("queues", {}).get(queue)
    if not isinstance(q, dict):
        return {"api_ok": True, "source": response.get("data_source", "unknown"),
                "queue_found": False, "queue_members": 0, "state_codes": {},
                "waiting": None, "waiting_entries": None}
    members = q.get("members", {}) or {}
    counter = collections.Counter(str(m.get("Status", "0")) for m in members.values())
    return {"api_ok": True, "source": response.get("data_source", "unknown"),
            "queue_found": True, "queue_members": len(members),
            "state_codes": dict(counter), "paused_members": sum(str(m.get("Paused")) in ("1", "true", "True") for m in members.values()),
            "waiting": int(q.get("Calls", 0) or 0), "waiting_entries": len(q.get("entries", {}) or {}),
            "completed_since_reset": int(q.get("Completed", 0) or 0),
            "abandoned_since_reset": int(q.get("Abandoned", 0) or 0)}


def classify(exc):
    if isinstance(exc, PermissionError):
        return "authentication_or_AMI_permission"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "network_timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return "network_or_local_server_unavailable"
    if isinstance(exc, ValueError):
        return "unexpected_response_format"
    return "unexpected_error"


def compare(ami, panel):
    return {
        "both_queues_found": ami.get("queue_found") and panel.get("queue_found"),
        "members_match": ami.get("queue_members") == panel.get("queue_members"),
        "device_status_codes_match": ami.get("state_codes") == panel.get("state_codes"),
        "waiting_count_match": ami.get("waiting_from_params") == panel.get("waiting"),
        "waiting_entries_match": ami.get("waiting_entries") == panel.get("waiting_entries"),
        "completed_match": ami.get("completed_since_reset") == panel.get("completed_since_reset"),
        "abandoned_match": ami.get("abandoned_since_reset") == panel.get("abandoned_since_reset"),
        "panel_live_source": panel.get("source") == "ami-live",
    }


def main():
    print("SaneQueue Live QA — read-only Asterisk and web app comparison")
    print("Allowed AMI actions: Login, QueueStatus, Logoff. No control actions.")
    print("No caller data, channel identifiers or passwords will be written to disk.\n")
    host = choose("AMI host (local tunnel preferred)", "127.0.0.1")
    port = int(choose("AMI port", 15038 if host == "127.0.0.1" else 5038))
    user = choose("AMI username", "sq")
    queue = choose("Queue", TARGET_QUEUE)
    safe_target(host, port, queue)
    if host != "127.0.0.1":
        print("WARNING: Direct AMI TCP lacks encryption. Use SSH forwarding if possible.")
    password = getpass.getpass("AMI password (hidden, NEVER saved): ")
    if not password:
        print("Password missing"); return 1
    try:
        build = get_local_json("/__sanequeue__/build")
        gate = get_local_json("/api/ami/control-status")
    except Exception as exc:
        print("Cannot reach local SaneQueue at " + APP_ORIGIN + ": " + classify(exc))
        return 2
    report = {
        "test": "SaneQueue read-only AMI vs local dashboard",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "app_build": str(build.get("version", "unknown")),
        "app_mode": str(build.get("mode", "unknown")),
        "queue": queue,
        "test_samples": [],
        "controls_armed_at_start": bool(gate.get("enabled")),
        "controls_remaining_seconds_at_start": gate.get("remaining_seconds", 0),
        "privacy": "No AMI password, call ID, caller number, channel name or raw AMI packet is included",
    }
    for idx in range(3):
        item = {"index": idx + 1, "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            # Two reads are not atomically synchronized; transient mismatches can occur.
            item["panel"] = panel_summary(queue)
        except Exception as exc:
            item["panel_error"] = classify(exc)
        try:
            item["ami"] = query_ami(host, port, user, password, queue)
        except Exception as exc:
            item["ami_error"] = classify(exc)
        if item.get("ami") and item.get("panel"):
            item["comparison"] = compare(item["ami"], item["panel"])
        report["test_samples"].append(item)
        if idx < 2:
            time.sleep(3)
    report["generated_at_utc_end"] = dt.datetime.now(dt.timezone.utc).isoformat()
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(REPORT, 0o600)
    except OSError:
        pass
    print("\nSaved sanitized diagnostic:", REPORT.name)
    for sample in report["test_samples"]:
        comparison = sample.get("comparison", {})
        if comparison:
            bad = [key for key, value in comparison.items() if not value]
            print(f"Sample {sample['index']}: " + ("all checks matched" if not bad else "mismatch: " + ", ".join(bad)))
        else:
            print(f"Sample {sample['index']}: {sample.get('ami_error', '')} {sample.get('panel_error', '')}")
    if report["controls_armed_at_start"]:
        print("WARNING: test controls were armed. Disarm in the web UI until the read comparison is clean.")
    print("Upload ONLY qa_readonly_result.json to the conversation, after reviewing it locally.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print("Input cancelled or invalid.")
        sys.exit(2)
