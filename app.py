import json
import threading
import time
from flask import Flask, send_from_directory
from flask_sock import Sock

HOST = "0.0.0.0"
PORT = 4000

app = Flask(__name__, static_folder="static", static_url_path="")
sock = Sock(app)

clients = {}
clients_lock = threading.Lock()


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


def broadcast_user_list():
    with clients_lock:
        users = list(clients.values())

    broadcast({
        "type": "userlist",
        "users": users,
        "count": len(users)
    })


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

                with clients_lock:
                    clients[ws] = username
                    online_count = len(clients)

                print(f"[join] {username} joined ({online_count} online)")

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

                if not text.strip():
                    continue

                print(f"[message] {username}: {text}")

                broadcast({
                    "type": "message",
                    "username": username,
                    "text": text,
                    "timestamp": int(time.time() * 1000)
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
