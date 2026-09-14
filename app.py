try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass

import argparse
import json
import os
import sys
import threading
import time
import uuid
import psutil

from flask import Flask, jsonify, make_response, request, send_from_directory
from flask_sock import Sock

import crypto_utils
import db
import integrity
import signatures

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 4000))
START_TIME = time.time()

app = Flask(
    __name__,
    static_folder="static",
    static_url_path=""
)

sock = Sock(app)

# WebSocket -> username
clients = {}
# WebSocket -> sender signing keys for current session
client_keys = {}
clients_lock = threading.Lock()

# Persistent user keys cache for REST / WebSocket clients
# username -> {"private_key": private_key, "public_key_pem": public_key_pem}
user_signing_keys = {}
user_keys_lock = threading.Lock()

# Active request tracking for performance monitoring & load metrics
active_requests = 0
active_requests_lock = threading.Lock()

# In-memory cache of decrypted & verified message representations to eliminate redundant ECDSA & Fernet work
_verified_msg_cache = {}
_verified_msg_lock = threading.Lock()

# Short-window feed cache: avoids hammering DB under concurrent /feed bursts.
_feed_cache_lock = threading.Lock()
_feed_cache = {"ts": 0.0, "data": None, "limit": 0}  # cached feed JSON bytes
_FEED_CACHE_TTL = 0.25  # 250ms window


def _invalidate_feed_cache():
    with _feed_cache_lock:
        _feed_cache["ts"] = 0.0


@app.before_request
def track_start():
    global active_requests
    with active_requests_lock:
        active_requests += 1


@app.teardown_request
def track_end(exc=None):
    global active_requests
    with active_requests_lock:
        if active_requests > 0:
            active_requests -= 1


db.init_db()


def get_or_create_user_keys(username: str):
    """Retrieves or creates an ECDSA P-256 keypair for a username."""
    with user_keys_lock:
        if username in user_signing_keys:
            return user_signing_keys[username]

        priv, pub = signatures.generate_keypair()
        pub_pem = signatures.public_key_to_pem(pub)
        user_signing_keys[username] = {
            "private_key": priv,
            "public_key_pem": pub_pem,
        }
        db.upsert_user_pubkey(username, pub_pem)
        return user_signing_keys[username]


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


# -------------------------------------------------------------
# REQUIRED API ROUTE 1: /message
# Accepts "client-name" and "msg" as input and submits a message.
# Supports JSON body, form-encoded data, and query parameters.
# Prevents duplicate insertions via unique message ID.
# -------------------------------------------------------------
@app.route("/message", methods=["POST", "GET"])
def api_message():
    # 1. Parse inputs
    data = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    elif request.form:
        data = request.form.to_dict()

    # Allow query parameters as fallback
    client_name = (
        data.get("client-name")
        or data.get("client_name")
        or request.args.get("client-name")
        or request.args.get("client_name")
        or ""
    ).strip()

    msg_text = (
        data.get("msg")
        or data.get("text")
        or request.args.get("msg")
        or request.args.get("text")
        or ""
    ).strip()

    if not client_name or not msg_text:
        return jsonify({
            "status": "error",
            "error": "Missing required fields: 'client-name' and 'msg'"
        }), 400

    # 2. Extract or generate unique message ID for deduplication
    msg_id = (
        data.get("id")
        or data.get("msg_id")
        or data.get("msg-id")
        or request.headers.get("X-Message-ID")
        or request.headers.get("Idempotency-Key")
    )
    if not msg_id:
        msg_id = str(uuid.uuid4())

    timestamp = int(
        data.get("timestamp")
        or request.args.get("timestamp")
        or (time.time() * 1000)
    )

    # 3. Security: Digital Signature (ECDSA P-256)
    keys = get_or_create_user_keys(client_name)
    msg_str = canonical_message(client_name, msg_text, timestamp)
    signature = signatures.sign_message(keys["private_key"], msg_str)

    # 4. Security: Encryption at Rest (Fernet AES-128)
    ciphertext = crypto_utils.encrypt_text(msg_text)

    # 5. Atomic Storage with SHA-256 Hash Chain & Deduplication
    inserted, record_data = db.save_message_atomic(
        msg_id=msg_id,
        username=client_name,
        ciphertext=ciphertext,
        signature=signature,
        pubkey_jwk=keys["public_key_pem"],
        timestamp=timestamp,
        compute_hash_fn=integrity.compute_record_hash
    )

    # 6. Broadcast to live WebSockets if newly inserted
    if inserted:
        item_cached = {
            "id": msg_id,
            "msg_id": msg_id,
            "client-name": client_name,
            "username": client_name,
            "msg": msg_text,
            "text": msg_text,
            "timestamp": timestamp,
            "tampered": False,
            "signature_valid": True,
        }
        with _verified_msg_lock:
            _verified_msg_cache[msg_id] = item_cached
        _invalidate_feed_cache()  # New message inserted — invalidate feed cache
        broadcast({
            "type": "message",
            "username": client_name,
            "text": msg_text,
            "timestamp": timestamp,
            "signature_valid": True,
            "tampered": False,
            "msg_id": msg_id,
        })
        return jsonify({
            "status": "ok",
            "id": msg_id,
            "msg_id": msg_id,
            "client-name": client_name,
            "msg": msg_text,
            "duplicate": False,
            "timestamp": timestamp,
        }), 200
    else:
        # Duplicate detected and skipped
        return jsonify({
            "status": "ok",
            "id": msg_id,
            "msg_id": msg_id,
            "client-name": client_name,
            "msg": msg_text,
            "duplicate": True,
            "message": "Duplicate message ignored (idempotent)",
            "timestamp": record_data.get("timestamp", timestamp),
        }), 200


# -------------------------------------------------------------
# REQUIRED API ROUTE 2: /feed
# Retrieves all messages in chronological order with decrypted
# plaintext and verified signatures / integrity status.
# Uses a short-window cache to handle concurrent read bursts.
# -------------------------------------------------------------
@app.route("/feed", methods=["GET", "POST"])
def api_feed():
    try:
        limit = int(request.args.get("limit", 100000))
    except (TypeError, ValueError):
        limit = 100000

    fmt = request.args.get("format", "").lower()
    is_dict_fmt = fmt in ("dict", "object", "json_obj")

    # Use feed cache for standard requests (limit >= 1000, no special format)
    # This prevents N concurrent requests all rebuilding the same feed.
    if limit >= 1000 and not is_dict_fmt:
        now = time.monotonic()
        with _feed_cache_lock:
            if _feed_cache["data"] is not None and (now - _feed_cache["ts"]) < _FEED_CACHE_TTL:
                resp = make_response(_feed_cache["data"])
                resp.headers["Content-Type"] = "application/json"
                return resp

    rows = db.load_history(limit=limit)
    chain_ok = integrity.verify_chain(rows)

    feed = []
    for row, intact in zip(rows, chain_ok):
        mid = row.get("msg_id") or str(row["id"])
        with _verified_msg_lock:
            cached_item = _verified_msg_cache.get(mid)

        if cached_item is not None and intact:
            feed.append(cached_item)
            continue

        plaintext = crypto_utils.decrypt_text(row["ciphertext"])
        decrypt_ok = plaintext is not None

        sig_valid = False
        if decrypt_ok:
            msg_str = canonical_message(row["username"], plaintext, row["timestamp"])
            sig_valid = signatures.verify_signature(
                row["pubkey_jwk"],
                row["signature"],
                msg_str
            )

        item = {
            "id": mid,
            "msg_id": mid,
            "client-name": row["username"],
            "username": row["username"],
            "msg": plaintext if decrypt_ok else "[unreadable — ciphertext corrupted]",
            "text": plaintext if decrypt_ok else "[unreadable — ciphertext corrupted]",
            "timestamp": row["timestamp"],
            "tampered": not (intact and decrypt_ok),
            "signature_valid": sig_valid,
        }
        with _verified_msg_lock:
            _verified_msg_cache[mid] = item
        feed.append(item)

    if is_dict_fmt:
        return jsonify({
            "status": "ok",
            "count": len(feed),
            "messages": feed,
            "feed": feed,
        })

    # Serialize once and cache for concurrent requests
    feed_bytes = json.dumps(feed, separators=(',', ':')).encode()
    if limit >= 1000:
        with _feed_cache_lock:
            _feed_cache["data"] = feed_bytes
            _feed_cache["ts"] = time.monotonic()
            _feed_cache["limit"] = limit

    resp = make_response(feed_bytes)
    resp.headers["Content-Type"] = "application/json"
    return resp


# -------------------------------------------------------------
# HEALTH & METRICS ROUTES FOR DYNAMIC LOAD BALANCER
# -------------------------------------------------------------
@app.route("/health", methods=["GET"])
def api_health():
    return jsonify({
        "status": "healthy",
        "backend": f"{HOST}:{PORT}",
        "uptime": round(time.time() - START_TIME, 2)
    }), 200


@app.route("/load", methods=["GET"])
def api_load():
    with active_requests_lock:
        in_flight = active_requests

    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent

    return jsonify({
        "status": "healthy",
        "backend_id": f"{HOST}:{PORT}",
        "cpu_percent": cpu,
        "memory_percent": mem,
        "active_requests": in_flight,
        "uptime": round(time.time() - START_TIME, 2),
    }), 200


def broadcast(payload, exclude=None):
    data = json.dumps(payload)
    with clients_lock:
        dead = []
        for ws in list(clients.keys()):
            if ws is exclude:
                continue
            try:
                ws.send(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            clients.pop(ws, None)
            client_keys.pop(ws, None)


def broadcast_user_list():
    with clients_lock:
        users = list(clients.values())
    broadcast({
        "type": "userlist",
        "users": users,
        "count": len(users)
    })


def canonical_message(username: str, text: str, timestamp: int) -> str:
    return f"{username}|{text}|{timestamp}"


def build_history_payload():
    rows = db.load_history()
    chain_ok = integrity.verify_chain(rows)
    history = []

    for row, intact in zip(rows, chain_ok):
        plaintext = crypto_utils.decrypt_text(row["ciphertext"])
        decrypt_ok = plaintext is not None

        sig_valid = False
        if decrypt_ok:
            msg_str = canonical_message(row["username"], plaintext, row["timestamp"])
            sig_valid = signatures.verify_signature(
                row["pubkey_jwk"],
                row["signature"],
                msg_str
            )

        history.append({
            "id": row.get("msg_id") or str(row["id"]),
            "username": row["username"],
            "text": plaintext if decrypt_ok else "[unreadable — ciphertext corrupted]",
            "timestamp": row["timestamp"],
            "tampered": not (intact and decrypt_ok),
            "signature_valid": sig_valid
        })

    return history


@sock.route("/ws")
def ws_handler(ws):
    username = None
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break

            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue

            mtype = msg.get("type")

            if mtype == "join":
                username = (msg.get("username") or "Anonymous").strip()[:24] or "Anonymous"
                keys = get_or_create_user_keys(username)

                with clients_lock:
                    clients[ws] = username
                    client_keys[ws] = keys
                    online_count = len(clients)

                ws.send(json.dumps({
                    "type": "history",
                    "messages": build_history_payload()
                }))

                broadcast({
                    "type": "notice",
                    "text": f"{username} joined the chat",
                    "timestamp": int(time.time() * 1000)
                })
                broadcast_user_list()

            elif mtype == "message":
                if not username:
                    continue

                text = str(msg.get("text", ""))[:2000]
                timestamp = msg.get("timestamp") or int(time.time() * 1000)
                if not text.strip():
                    continue

                msg_id = msg.get("msg_id") or msg.get("id") or str(uuid.uuid4())
                key_data = client_keys.get(ws) or get_or_create_user_keys(username)
                msg_str = canonical_message(username, text, timestamp)
                signature = signatures.sign_message(key_data["private_key"], msg_str)

                ciphertext = crypto_utils.encrypt_text(text)

                inserted, _ = db.save_message_atomic(
                    msg_id=msg_id,
                    username=username,
                    ciphertext=ciphertext,
                    signature=signature,
                    pubkey_jwk=key_data["public_key_pem"],
                    timestamp=timestamp,
                    compute_hash_fn=integrity.compute_record_hash
                )

                if inserted:
                    broadcast({
                        "type": "message",
                        "username": username,
                        "text": text,
                        "timestamp": timestamp,
                        "signature_valid": True,
                        "tampered": False,
                        "msg_id": msg_id,
                    })

            elif mtype == "typing":
                if not username:
                    continue
                broadcast({
                    "type": "typing",
                    "username": username
                }, exclude=ws)

    finally:
        with clients_lock:
            was_present = clients.pop(ws, None)
            client_keys.pop(ws, None)
            online_count = len(clients)

        if was_present:
            broadcast({
                "type": "notice",
                "text": f"{was_present} left the chat",
                "timestamp": int(time.time() * 1000)
            })
            broadcast_user_list()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GRP-CHAT Backend Server")
    parser.add_argument("--port", type=int, default=PORT, help="Port to listen on")
    parser.add_argument("--host", type=str, default=HOST, help="Host to bind to")
    parser.add_argument("--db", type=str, default=None, help="Database path")
    args, unknown = parser.parse_known_args()

    if args.db:
        db.DB_PATH = args.db
        db.init_db()

    PORT = args.port
    HOST = args.host

    print(f"Group chat backend server listening on http://{HOST}:{PORT}")
    print(f"  - Database: {db.DB_PATH}")
    print(f"  - WebSocket: ws://{HOST}:{PORT}/ws")
    print(f"  - API Route: http://{HOST}:{PORT}/message")
    print(f"  - API Route: http://{HOST}:{PORT}/feed")
    print(f"  - Health:    http://{HOST}:{PORT}/health")
    print(f"  - Load:      http://{HOST}:{PORT}/load")

    app.run(host=HOST, port=PORT, threaded=True)