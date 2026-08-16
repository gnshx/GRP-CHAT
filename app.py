import json
import threading
import time
from flask import Flask, send_from_directory
from flask_sock import Sock

import db
import crypto_utils
import signatures
import integrity

HOST = "0.0.0.0"
PORT = 4000

app = Flask(__name__, static_folder="static", static_url_path="")
sock = Sock(app)

# ws -> username
clients = {}
# ws -> pubkey_jwk (dict) registered at join time for THIS session
client_keys = {}
clients_lock = threading.Lock()

db.init_db()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


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
    """Must match static/crypto.js canonicalMessage() exactly, or every
    signature check fails."""
    return f"{username}|{text}|{timestamp}"


def build_history_payload():
    """Loads stored messages, decrypts them, walks the hash chain, and
    re-verifies each signature — so a client that just joined can see which
    (if any) past messages were tampered with."""
    rows = db.load_history()
    chain_ok = integrity.verify_chain(rows)

    history = []
    for row, intact in zip(rows, chain_ok):
        plaintext = crypto_utils.decrypt_text(row["ciphertext"])
        decrypt_ok = plaintext is not None

        sig_valid = False
        if decrypt_ok:
            pubkey_jwk = json.loads(row["pubkey_jwk"])
            msg_str = canonical_message(row["username"], plaintext, row["timestamp"])
            sig_valid = signatures.verify_signature(pubkey_jwk, row["signature"], msg_str)

        history.append({
            "username": row["username"],
            "text": plaintext if decrypt_ok else "[unreadable — ciphertext corrupted]",
            "timestamp": row["timestamp"],
            "tampered": not (intact and decrypt_ok),
            "signature_valid": sig_valid
        })

    return history


@sock.route("/ws")
def ws_handler(ws):
    print("[connect] new socket opened")

    username = None

    try:
        while True:
            raw = ws.receive()

            if raw is None:
                break

            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                print("[warn] received invalid JSON")
                continue

            mtype = msg.get("type")

            if mtype == "join":
                username = (
                    msg.get("username") or "Anonymous"
                ).strip()[:24] or "Anonymous"

                pubkey_jwk = msg.get("pubkey")
                if not pubkey_jwk:
                    ws.send(json.dumps({
                        "type": "error",
                        "text": "Missing signing public key — cannot join."
                    }))
                    continue

                with clients_lock:
                    clients[ws] = username
                    client_keys[ws] = pubkey_jwk
                    online_count = len(clients)

                db.upsert_user_pubkey(username, json.dumps(pubkey_jwk))

                print(f"[join] {username} joined ({online_count} online)")

                # Send this client (and only this client) the chat history.
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
                signature = msg.get("signature")

                if not text.strip() or not signature:
                    continue

                pubkey_jwk = client_keys.get(ws)
                msg_str = canonical_message(username, text, timestamp)

                if not pubkey_jwk or not signatures.verify_signature(pubkey_jwk, signature, msg_str):
                    print(f"[warn] bad signature from {username}, message dropped")
                    ws.send(json.dumps({
                        "type": "error",
                        "text": "Signature verification failed — message was not sent."
                    }))
                    continue

                # Encrypt for storage (requirement #3) and extend the hash
                # chain (requirement #4) before persisting (requirement #1).
                ciphertext = crypto_utils.encrypt_text(text)
                prev_hash = db.get_last_hash()
                record_hash = integrity.compute_record_hash(
                    prev_hash, username, ciphertext, signature, timestamp
                )

                db.save_message(
                    username, ciphertext, signature,
                    json.dumps(pubkey_jwk), timestamp, prev_hash, record_hash
                )

                print(f"[message] {username}: {text}")

                broadcast({
                    "type": "message",
                    "username": username,
                    "text": text,
                    "timestamp": timestamp,
                    "signature_valid": True,
                    "tampered": False
                })

            elif mtype == "typing":
                if not username:
                    continue

                broadcast(
                    {
                        "type": "typing",
                        "username": username
                    },
                    exclude=ws
                )

            else:
                print(f"[warn] unknown message type: {mtype}")

    finally:
        with clients_lock:
            was_present = clients.pop(ws, None)
            client_keys.pop(ws, None)
            online_count = len(clients)

        if was_present:
            print(f"[leave] {was_present} left ({online_count} online)")

            broadcast({
                "type": "notice",
                "text": f"{was_present} left the chat",
                "timestamp": int(time.time() * 1000)
            })

            broadcast_user_list()
        else:
            print("[leave] socket closed before joining")


if __name__ == "__main__":
    print(f"Group chat server listening on http://{HOST}:{PORT}")
    print(f"WebSocket endpoint: ws://{HOST}:{PORT}/ws")

    app.run(
        host=HOST,
        port=PORT,
        threaded=True
    )