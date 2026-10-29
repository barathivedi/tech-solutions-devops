import json
import hmac
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request

app = Flask(__name__)

DB_PATH = os.environ.get("TICKET_DB_PATH", "/data/tickets.db")

ALLOWED_STATUSES = {"Open", "In Progress", "Resolved"}
ALLOWED_PRIORITIES = {"Low", "Medium", "High", "Critical"}
ALLOWED_CATEGORIES = {
    "Hardware", "Software", "Network", "Email", "Access", "Other",
    "Performance", "Storage", "Battery", "Display", "Power",
    "Peripheral", "Security"
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database():
    with database() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_key TEXT NOT NULL UNIQUE,
                requester TEXT NOT NULL,
                email TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                description TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                device_id TEXT,
                issue_code TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                recommendation TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_status
            ON tickets(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_created
            ON tickets(created_at)
        """)


def serialize_ticket(row):
    ticket = dict(row)
    ticket["db_id"] = ticket["id"]
    ticket["id"] = ticket.pop("ticket_key")

    try:
        ticket["evidence"] = json.loads(
            ticket.pop("evidence_json") or "{}"
        )
    except (json.JSONDecodeError, TypeError):
        ticket["evidence"] = {}

    return ticket


def error_response(message, status_code):
    return jsonify({"error": message}), status_code


@app.route("/")
def home():
    return jsonify({
        "application": "Tech Solutions Backend",
        "status": "running",
        "message": "Backend API is working"
    })


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/api/info")
def info():
    return jsonify({
        "project": "Tech Solutions IT Support Ticket Management System",
        "frontend": "Nginx",
        "backend": "Python Flask",
        "deployment": "Docker",
        "database": "SQLite",
        "timestamp": utc_now()
    })


@app.route("/api/tickets", methods=["GET"])
def list_tickets():
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    search = request.args.get("search", "").strip()

    if status and status not in ALLOWED_STATUSES:
        return error_response("Invalid status filter.", 400)

    if priority and priority not in ALLOWED_PRIORITIES:
        return error_response("Invalid priority filter.", 400)

    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        return error_response("Limit must be a number.", 400)

    if not 1 <= limit <= 200:
        return error_response("Limit must be between 1 and 200.", 400)

    conditions = []
    values = []

    if status:
        conditions.append("status = ?")
        values.append(status)

    if priority:
        conditions.append("priority = ?")
        values.append(priority)

    if search:
        conditions.append(
            "(ticket_key LIKE ? OR title LIKE ? "
            "OR requester LIKE ? OR email LIKE ? "
            "OR category LIKE ?)"
        )
        term = f"%{search}%"
        values.extend([term, term, term, term, term])

    sql = "SELECT * FROM tickets"

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY id DESC LIMIT ?"
    values.append(limit)

    with database() as conn:
        rows = conn.execute(sql, values).fetchall()

    return jsonify({
        "tickets": [serialize_ticket(row) for row in rows],
        "count": len(rows)
    })


@app.route("/api/tickets/stats", methods=["GET"])
def ticket_stats():
    with database() as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) AS total
            FROM tickets
            GROUP BY status
        """).fetchall()

    counts = {status: 0 for status in ALLOWED_STATUSES}
    for row in rows:
        counts[row["status"]] = row["total"]

    return jsonify({
        "total": sum(counts.values()),
        "open": counts["Open"],
        "in_progress": counts["In Progress"],
        "resolved": counts["Resolved"]
    })


@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response("A JSON request body is required.", 400)

    required = [
        "requester", "email", "title",
        "category", "priority", "description"
    ]

    fields = {}
    for field in required:
        value = data.get(field)

        if not isinstance(value, str) or not value.strip():
            return error_response(
                f"'{field}' is required and must be text.", 400
            )

        fields[field] = value.strip()

    limits = {
        "requester": 100,
        "email": 150,
        "title": 150,
        "description": 2000
    }

    for field, max_length in limits.items():
        if len(fields[field]) > max_length:
            return error_response(
                f"'{field}' exceeds {max_length} characters.", 400
            )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]):
        return error_response("A valid email address is required.", 400)

    if fields["category"] not in ALLOWED_CATEGORIES:
        return error_response("Invalid ticket category.", 400)

    if fields["priority"] not in ALLOWED_PRIORITIES:
        return error_response("Invalid ticket priority.", 400)

    now = utc_now()
    ticket_key = "TS-" + uuid.uuid4().hex[:8].upper()

    with database() as conn:
        cursor = conn.execute("""
            INSERT INTO tickets (
                ticket_key, requester, email, title, category,
                priority, status, description, source,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Open', ?, 'manual', ?, ?)
        """, (
            ticket_key,
            fields["requester"],
            fields["email"],
            fields["title"],
            fields["category"],
            fields["priority"],
            fields["description"],
            now,
            now
        ))

        row = conn.execute(
            "SELECT * FROM tickets WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone()

    return jsonify({
        "message": "Ticket created successfully.",
        "ticket": serialize_ticket(row)
    }), 201


@app.route("/api/tickets/<ticket_key>", methods=["GET"])
def get_ticket(ticket_key):
    with database() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_key = ?",
            (ticket_key,)
        ).fetchone()

    if row is None:
        return error_response("Ticket not found.", 404)

    return jsonify({"ticket": serialize_ticket(row)})


@app.route("/api/tickets/<ticket_key>", methods=["PATCH"])
def update_ticket(ticket_key):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return error_response("A JSON request body is required.", 400)

    if set(data.keys()) != {"status"}:
        return error_response(
            "Only the status field can be updated.", 400
        )

    status = data["status"]

    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        return error_response("Invalid ticket status.", 400)

    with database() as conn:
        cursor = conn.execute("""
            UPDATE tickets
            SET status = ?, updated_at = ?
            WHERE ticket_key = ?
        """, (status, utc_now(), ticket_key))

        if cursor.rowcount == 0:
            return error_response("Ticket not found.", 404)

        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_key = ?",
            (ticket_key,)
        ).fetchone()

    return jsonify({
        "message": "Ticket status updated.",
        "ticket": serialize_ticket(row)
    })


@app.route("/api/tickets/<ticket_key>", methods=["DELETE"])
def delete_ticket(ticket_key):
    with database() as conn:
        cursor = conn.execute(
            "DELETE FROM tickets WHERE ticket_key = ?",
            (ticket_key,)
        )

    if cursor.rowcount == 0:
        return error_response("Ticket not found.", 404)

    return jsonify({
        "message": "Ticket deleted successfully.",
        "id": ticket_key
    })


initialize_database()



# -------- Automatic laptop health monitoring (development version) --------

def initialize_monitoring_tables():
    with database() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS health_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                received_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices(device_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_health_device_received
            ON health_reports(device_id, received_at)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_active_device_issue
            ON tickets(device_id, issue_code)
            WHERE device_id IS NOT NULL
              AND issue_code IS NOT NULL
              AND status <> 'Resolved'
        """)


initialize_monitoring_tables()


def recent_device_metrics(conn, device_id, limit, minutes):
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat()

    rows = conn.execute("""
        SELECT metrics_json
        FROM health_reports
        WHERE device_id = ? AND received_at >= ?
        ORDER BY id DESC
        LIMIT ?
    """, (device_id, cutoff, limit)).fetchall()

    return [json.loads(row["metrics_json"]) for row in rows]


def detect_device_issues(conn, device_id, hostname, metrics):
    issues = []

    disk_free = metrics.get("disk_free_percent")
    if disk_free is not None and disk_free <= 10:
        critical = disk_free <= 5
        issues.append({
            "issue_code": "LOW_DISK_SPACE",
            "title": "Critically low disk space" if critical else "Low disk space",
            "category": "Storage",
            "priority": "Critical" if critical else "High",
            "evidence": {"disk_free_percent": disk_free},
            "recommendation": (
                "Review system-drive usage and identify safe cleanup options. "
                "Do not delete user files without IT approval."
            ),
            "description": (
                f"Device {device_id} ({hostname}) reports "
                f"{disk_free}% free system-drive space."
            )
        })

    # Require three recent reports before flagging sustained resource usage.
    recent = recent_device_metrics(conn, device_id, 3, 60)

    cpu_values = [item.get("cpu_percent") for item in recent]
    if (
        len(cpu_values) == 3
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 95
            for value in cpu_values
        )
    ):
        issues.append({
            "issue_code": "SUSTAINED_HIGH_CPU",
            "title": "Sustained high CPU usage",
            "category": "Performance",
            "priority": "High",
            "evidence": {"recent_cpu_percent": cpu_values},
            "recommendation": (
                "Review running processes, recent application failures and "
                "system events. IT should investigate before stopping processes."
            ),
            "description": (
                f"Device {device_id} ({hostname}) reported CPU usage of at "
                f"least 95% for three reports within the last hour."
            )
        })

    memory_values = [item.get("memory_percent") for item in recent]
    if (
        len(memory_values) == 3
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 95
            for value in memory_values
        )
    ):
        issues.append({
            "issue_code": "SUSTAINED_HIGH_MEMORY",
            "title": "Sustained high memory usage",
            "category": "Performance",
            "priority": "High",
            "evidence": {"recent_memory_percent": memory_values},
            "recommendation": (
                "Review memory usage and application/system events. "
                "Do not terminate user applications automatically."
            ),
            "description": (
                f"Device {device_id} ({hostname}) reported memory usage of "
                "at least 95% for three reports within the last hour."
            )
        })

    network_samples = recent_device_metrics(conn, device_id, 2, 30)
    network_values = [item.get("network_connected") for item in network_samples]

    if len(network_values) == 2 and all(value is False for value in network_values):
        issues.append({
            "issue_code": "NETWORK_UNAVAILABLE",
            "title": "Repeated network connectivity failure",
            "category": "Network",
            "priority": "High",
            "evidence": {"recent_network_connected": network_values},
            "recommendation": (
                "Ask IT to review adapter status, Wi-Fi/Ethernet connection, "
                "IP configuration and relevant network events."
            ),
            "description": (
                f"Device {device_id} ({hostname}) reported network connectivity "
                "unavailable in two consecutive reports."
            )
        })

    return issues



# -------- IT approval workflow: development version --------

ACTION_FOR_ISSUE = {
    "LOW_DISK_SPACE": (
        "collect_disk_diagnostics",
        "Collect disk usage and free-space diagnostics. Do not delete files."
    ),
    "SUSTAINED_HIGH_CPU": (
        "collect_process_diagnostics",
        "Collect process and CPU diagnostics. Do not terminate processes."
    ),
    "SUSTAINED_HIGH_MEMORY": (
        "collect_memory_diagnostics",
        "Collect memory and application diagnostics. Do not close applications."
    ),
    "NETWORK_UNAVAILABLE": (
        "collect_network_diagnostics",
        "Collect adapter, IP and connectivity diagnostics. Do not change settings."
    ),
}

ALLOWED_REMOTE_ACTIONS = {
    "collect_disk_diagnostics",
    "collect_process_diagnostics",
    "collect_memory_diagnostics",
    "collect_network_diagnostics",
    "check_windows_update_status",
    "install_approved_updates",
    "restart_device",
}

ALLOWED_ACTION_STATES = {
    "pending_approval",
    "approved_pending_delivery",
    "delivered",
    "rejected",
    "scheduled",
    "completed",
    "failed",
    "cancelled",
}


def initialize_action_tables():
    with database() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS remote_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_key TEXT NOT NULL,
                device_id TEXT NOT NULL,
                issue_code TEXT NOT NULL,
                action_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                requested_by TEXT NOT NULL DEFAULT 'automatic_detection',
                scheduled_for TEXT,
                decision_by TEXT,
                decision_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(ticket_key, action_type)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_remote_actions_status
            ON remote_actions(status, created_at)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS remote_action_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_action_audit_action
            ON remote_action_audit(action_id, created_at)
        """)


initialize_action_tables()


def ensure_action_proposal(conn, ticket_key, device_id, issue_code, now):
    mapped = ACTION_FOR_ISSUE.get(issue_code)
    if mapped is None:
        return

    action_type, summary = mapped

    existing = conn.execute("""
        SELECT id FROM remote_actions
        WHERE ticket_key = ? AND action_type = ?
    """, (ticket_key, action_type)).fetchone()

    if existing:
        return

    cursor = conn.execute("""
        INSERT INTO remote_actions (
            ticket_key, device_id, issue_code, action_type,
            summary, status, requested_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending_approval',
                'automatic_detection', ?, ?)
    """, (
        ticket_key, device_id, issue_code, action_type,
        summary, now, now
    ))

    conn.execute("""
        INSERT INTO remote_action_audit (
            action_id, event, actor, note, created_at
        )
        VALUES (?, 'approval_requested', 'system',
                'Proposed after automatic issue detection.', ?)
    """, (cursor.lastrowid, now))


def it_auth_error():
    expected_token = os.environ.get("IT_API_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    supplied_token = ""

    if authorization.lower().startswith("bearer "):
        supplied_token = authorization[7:].strip()

    if not expected_token:
        return error_response(
            "IT approval authentication is not configured.", 503
        )

    if not supplied_token or not hmac.compare_digest(
        supplied_token, expected_token
    ):
        return error_response("Valid IT authentication is required.", 401)

    return None


@app.route("/api/it/actions", methods=["GET"])
def list_it_actions():
    auth_error = it_auth_error()
    if auth_error:
        return auth_error

    status = request.args.get("status", "pending_approval")

    if status != "all" and status not in ALLOWED_ACTION_STATES:
        return error_response("Invalid action status filter.", 400)

    with database() as conn:
        if status == "all":
            rows = conn.execute("""
                SELECT * FROM remote_actions
                ORDER BY id DESC LIMIT 200
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM remote_actions
                WHERE status = ?
                ORDER BY id DESC LIMIT 200
            """, (status,)).fetchall()

    return jsonify({
        "actions": [dict(row) for row in rows],
        "count": len(rows)
    })


@app.route("/api/it/actions/<int:action_id>/decision", methods=["POST"])
def decide_it_action(action_id):
    auth_error = it_auth_error()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("A JSON request body is required.", 400)

    allowed_fields = {
        "decision", "technician_id", "note", "scheduled_for"
    }
    if set(data) - allowed_fields:
        return error_response("Unsupported decision fields.", 400)

    decision = data.get("decision")
    technician_id = data.get("technician_id")
    note = data.get("note", "")

    if decision not in {"approve", "reject", "schedule"}:
        return error_response(
            "Decision must be approve, reject or schedule.", 400
        )

    if (
        not isinstance(technician_id, str)
        or not technician_id.strip()
        or len(technician_id) > 100
    ):
        return error_response("A valid technician_id is required.", 400)

    if not isinstance(note, str) or len(note) > 1000:
        return error_response("The note must be text under 1000 characters.", 400)

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    scheduled_for = None

    if decision == "approve":
        new_status = "approved_pending_delivery"

    elif decision == "reject":
        new_status = "rejected"

    else:
        raw_schedule = data.get("scheduled_for")
        if not isinstance(raw_schedule, str):
            return error_response(
                "scheduled_for must be an ISO-8601 timestamp with timezone.",
                400
            )

        try:
            scheduled_dt = datetime.fromisoformat(
                raw_schedule.replace("Z", "+00:00")
            )
        except ValueError:
            return error_response("Invalid scheduled_for timestamp.", 400)

        if scheduled_dt.tzinfo is None:
            return error_response(
                "scheduled_for must include a timezone.", 400
            )

        if scheduled_dt.astimezone(timezone.utc) <= now_dt:
            return error_response(
                "scheduled_for must be in the future.", 400
            )

        scheduled_for = scheduled_dt.astimezone(timezone.utc).isoformat()
        new_status = "scheduled"

    with database() as conn:
        action = conn.execute("""
            SELECT * FROM remote_actions WHERE id = ?
        """, (action_id,)).fetchone()

        if action is None:
            return error_response("Action request not found.", 404)

        if action["status"] != "pending_approval":
            return error_response(
                "Only pending approval requests can be decided.", 409
            )

        conn.execute("""
            UPDATE remote_actions
            SET status = ?, scheduled_for = ?, decision_by = ?,
                decision_note = ?, updated_at = ?
            WHERE id = ?
        """, (
            new_status, scheduled_for, technician_id.strip(),
            note.strip(), now, action_id
        ))

        conn.execute("""
            INSERT INTO remote_action_audit (
                action_id, event, actor, note, created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            action_id, decision, technician_id.strip(), note.strip(), now
        ))

        updated = conn.execute("""
            SELECT * FROM remote_actions WHERE id = ?
        """, (action_id,)).fetchone()

    if decision == "approve":
        message = (
            "Approval recorded. The action has NOT been executed; "
            "secure agent enrollment and task delivery are not implemented yet."
        )
    elif decision == "reject":
        message = "Action rejected. No remote operation was executed."
    else:
        message = (
            "Action scheduled. No remote operation will execute in this version."
        )

    return jsonify({
        "message": message,
        "action": dict(updated)
    })


@app.route("/api/it/actions/<int:action_id>/audit", methods=["GET"])
def get_it_action_audit(action_id):
    auth_error = it_auth_error()
    if auth_error:
        return auth_error

    with database() as conn:
        action = conn.execute(
            "SELECT id FROM remote_actions WHERE id = ?", (action_id,)
        ).fetchone()

        if action is None:
            return error_response("Action request not found.", 404)

        rows = conn.execute("""
            SELECT event, actor, note, created_at
            FROM remote_action_audit
            WHERE action_id = ?
            ORDER BY id ASC
        """, (action_id,)).fetchall()

    return jsonify({
        "action_id": action_id,
        "audit": [dict(row) for row in rows]
    })



@app.route("/api/agent/health", methods=["POST"])
def receive_health_report():
    expected_token = os.environ.get("AGENT_API_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    supplied_token = ""

    if authorization.lower().startswith("bearer "):
        supplied_token = authorization[7:].strip()

    if not expected_token:
        return error_response("Health-report authentication is not configured.", 503)

    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        return error_response("Valid agent authentication is required.", 401)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)

    device_id = payload.get("device_id")
    hostname = payload.get("hostname", device_id)
    metrics = payload.get("metrics")

    if (
        not isinstance(device_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", device_id)
    ):
        return error_response("A valid device_id is required.", 400)

    if not isinstance(hostname, str) or not hostname.strip() or len(hostname) > 100:
        return error_response("A valid hostname is required.", 400)

    if not isinstance(metrics, dict) or not metrics:
        return error_response("A non-empty metrics object is required.", 400)

    allowed_metrics = {
        "cpu_percent", "memory_percent",
        "disk_free_percent", "network_connected"
    }

    unknown_metrics = set(metrics) - allowed_metrics
    if unknown_metrics:
        return error_response(
            "Unsupported metrics: " + ", ".join(sorted(unknown_metrics)), 400
        )

    if not set(metrics).intersection(allowed_metrics):
        return error_response("No supported health measurements supplied.", 400)

    for key in ("cpu_percent", "memory_percent", "disk_free_percent"):
        if key in metrics:
            value = metrics[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 100
            ):
                return error_response(f"{key} must be a number from 0 to 100.", 400)

    if (
        "network_connected" in metrics
        and not isinstance(metrics["network_connected"], bool)
    ):
        return error_response("network_connected must be true or false.", 400)

    device_id = device_id.strip()
    hostname = hostname.strip()
    received_at = utc_now()

    with database() as conn:
        conn.execute("""
            INSERT INTO devices (device_id, hostname, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                hostname = excluded.hostname,
                last_seen = excluded.last_seen
        """, (device_id, hostname, received_at, received_at))

        conn.execute("""
            INSERT INTO health_reports (device_id, received_at, metrics_json)
            VALUES (?, ?, ?)
        """, (
            device_id,
            received_at,
            json.dumps(metrics, separators=(",", ":"), sort_keys=True)
        ))

        issues = detect_device_issues(conn, device_id, hostname, metrics)
        tickets_created = []
        tickets_already_open = []
        tickets_updated = []

        priority_rank = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}

        for issue in issues:
            existing = conn.execute("""
                SELECT ticket_key, priority
                FROM tickets
                WHERE device_id = ? AND issue_code = ?
                  AND status <> 'Resolved'
                LIMIT 1
            """, (device_id, issue["issue_code"])).fetchone()

            if existing:
                ticket_key = existing["ticket_key"]

                if priority_rank[issue["priority"]] > priority_rank.get(existing["priority"], 0):
                    conn.execute("""
                        UPDATE tickets
                        SET priority = ?, title = ?, description = ?,
                            evidence_json = ?, recommendation = ?, updated_at = ?
                        WHERE ticket_key = ?
                    """, (
                        issue["priority"],
                        issue["title"] + " on " + hostname,
                        issue["description"],
                        json.dumps(issue["evidence"], sort_keys=True),
                        issue["recommendation"],
                        received_at,
                        ticket_key
                    ))
                    tickets_updated.append(ticket_key)
                else:
                    tickets_already_open.append(ticket_key)

                ensure_action_proposal(
                    conn, ticket_key, device_id,
                    issue["issue_code"], received_at
                )
                continue

            ticket_key = "TS-" + uuid.uuid4().hex[:8].upper()
            conn.execute("""
                INSERT INTO tickets (
                    ticket_key, requester, email, title, category, priority,
                    status, description, source, device_id, issue_code,
                    evidence_json, recommendation, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Open', ?, 'automatic', ?, ?, ?, ?, ?, ?)
            """, (
                ticket_key,
                "Laptop Monitoring Agent",
                "monitoring@tech-solutions.local",
                issue["title"] + " on " + hostname,
                issue["category"],
                issue["priority"],
                issue["description"],
                device_id,
                issue["issue_code"],
                json.dumps(issue["evidence"], sort_keys=True),
                issue["recommendation"],
                received_at,
                received_at
            ))
            tickets_created.append(ticket_key)
            ensure_action_proposal(
                conn, ticket_key, device_id,
                issue["issue_code"], received_at
            )

    return jsonify({
        "message": "Health report accepted.",
        "device_id": device_id,
        "received_at": received_at,
        "issues_detected": [
            {
                "issue_code": issue["issue_code"],
                "priority": issue["priority"]
            }
            for issue in issues
        ],
        "tickets_created": tickets_created,
        "tickets_already_open": tickets_already_open,
        "tickets_updated": tickets_updated
    }), 201


@app.route("/api/devices", methods=["GET"])
def list_monitored_devices():
    auth_error = it_auth_error()
    if auth_error:
        return auth_error

    with database() as conn:
        rows = conn.execute("""
            SELECT d.device_id, d.hostname, d.first_seen, d.last_seen,
                   (SELECT COUNT(*) FROM health_reports h
                    WHERE h.device_id = d.device_id) AS report_count
            FROM devices d
            ORDER BY d.last_seen DESC
            LIMIT 200
        """).fetchall()

    return jsonify({
        "devices": [dict(row) for row in rows],
        "count": len(rows)
    })



# -------- Controlled agent task delivery: development version --------

# This version delivers task descriptors only. The Windows agent and its
# safe execution engine have not been implemented yet.
AGENT_DELIVERABLE_ACTIONS = {
    "collect_disk_diagnostics",
    "collect_process_diagnostics",
    "collect_memory_diagnostics",
    "collect_network_diagnostics",
}


def agent_task_auth_error():
    expected_token = os.environ.get("AGENT_API_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    supplied_token = ""

    if authorization.lower().startswith("bearer "):
        supplied_token = authorization[7:].strip()

    if not expected_token:
        return error_response(
            "Agent authentication is not configured.", 503
        )

    if not supplied_token or not hmac.compare_digest(
        supplied_token, expected_token
    ):
        return error_response(
            "Valid agent authentication is required.", 401
        )

    return None


@app.route("/api/agent/tasks/claim", methods=["POST"])
def claim_agent_task():
    auth_error = agent_task_auth_error()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"device_id"}:
        return error_response(
            "Provide only the device_id field in a JSON body.", 400
        )

    device_id = payload.get("device_id")
    if (
        not isinstance(device_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", device_id)
    ):
        return error_response("A valid device_id is required.", 400)

    now = utc_now()
    allowed = tuple(sorted(AGENT_DELIVERABLE_ACTIONS))
    placeholders = ",".join("?" for _ in allowed)

    with database() as conn:
        # Serialize task claims so concurrent polls cannot claim the same
        # pending item at the same time.
        conn.execute("BEGIN IMMEDIATE")

        action = conn.execute(f"""
            SELECT * FROM remote_actions
            WHERE device_id = ?
              AND (
                  status = 'approved_pending_delivery'
                  OR (
                      status = 'scheduled'
                      AND scheduled_for IS NOT NULL
                      AND scheduled_for <= ?
                  )
              )
              AND action_type IN ({placeholders})
            ORDER BY id ASC
            LIMIT 1
        """, (device_id, now, *allowed)).fetchone()

        if action is None:
            return jsonify({
                "tasks": [],
                "message": "No approved diagnostic tasks are available."
            })

        update = conn.execute("""
            UPDATE remote_actions
            SET status = 'delivered', updated_at = ?
            WHERE id = ? AND status = ?
        """, (now, action["id"], action["status"]))

        if update.rowcount != 1:
            return error_response(
                "Task state changed; poll again.", 409
            )

        conn.execute("""
            INSERT INTO remote_action_audit (
                action_id, event, actor, note, created_at
            )
            VALUES (?, 'task_delivered', ?, ?, ?)
        """, (
            action["id"],
            device_id,
            "Approved predefined diagnostic task offered to the agent.",
            now
        ))

        # Return only the approved task descriptor, never an executable
        # command or user-supplied script.
        task = {
            "task_id": action["id"],
            "ticket_key": action["ticket_key"],
            "device_id": action["device_id"],
            "action_type": action["action_type"],
            "summary": action["summary"],
            "status": "delivered",
            "execution_mode": "descriptor_only",
            "message": (
                "No operation is executed by this API. "
                "A controlled Windows agent is still required."
            )
        }

    return jsonify({"tasks": [task]})


@app.route("/api/agent/tasks/<int:action_id>/result", methods=["POST"])
def report_agent_task_result(action_id):
    auth_error = agent_task_auth_error()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("A JSON request body is required.", 400)

    if set(payload) - {"device_id", "result", "note"}:
        return error_response("Unsupported result fields.", 400)

    device_id = payload.get("device_id")
    result = payload.get("result")
    note = payload.get("note", "")

    if (
        not isinstance(device_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", device_id)
    ):
        return error_response("A valid device_id is required.", 400)

    if result not in {"completed", "failed"}:
        return error_response(
            "result must be completed or failed.", 400
        )

    if not isinstance(note, str) or len(note) > 1000:
        return error_response(
            "note must be text no longer than 1000 characters.", 400
        )

    now = utc_now()

    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")

        action = conn.execute("""
            SELECT * FROM remote_actions WHERE id = ?
        """, (action_id,)).fetchone()

        if action is None:
            return error_response("Task not found.", 404)

        if action["device_id"] != device_id:
            return error_response(
                "This task is not assigned to that device.", 403
            )

        if action["action_type"] not in AGENT_DELIVERABLE_ACTIONS:
            return error_response(
                "This action type cannot be delivered by this version.", 403
            )

        if action["status"] != "delivered":
            return error_response(
                "Only delivered tasks can report a result.", 409
            )

        conn.execute("""
            UPDATE remote_actions
            SET status = ?, decision_note = ?, updated_at = ?
            WHERE id = ?
        """, (result, note.strip(), now, action_id))

        conn.execute("""
            INSERT INTO remote_action_audit (
                action_id, event, actor, note, created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            action_id,
            "task_result_" + result,
            device_id,
            note.strip(),
            now
        ))

    return jsonify({
        "message": "Task result recorded.",
        "task_id": action_id,
        "device_id": device_id,
        "status": result,
        "note": (
            "This endpoint records a reported result; it does not execute "
            "or independently verify a diagnostic operation."
        )
    })



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
