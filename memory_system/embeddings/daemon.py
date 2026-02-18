#!/usr/bin/env python3
"""Persistent embedding daemon for fast inference.

Keeps the embedding model loaded in memory and accepts requests via Unix socket.
This eliminates cold-start latency (~2s) for repeated embedding operations.

Protocol:
- Request: 4-byte length prefix (big-endian) + JSON list of texts
- Response: 4-byte length prefix (big-endian) + JSON dict {"vectors": [...], "dim": int}

Usage:
    # Start daemon
    python daemon.py --socket ~/.openclaw/embed.sock

    # Stop daemon
    python daemon.py --stop

    # Client example
    echo '["test query"]' | nc -U ~/.openclaw/embed.sock
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import sys
from pathlib import Path
from typing import List, Optional

# Allow importing memory_system as a package
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


DEFAULT_SOCKET = Path("~/.openclaw/embed.sock").expanduser()
PID_FILE = Path("~/.openclaw/embed.pid").expanduser()

# Global embedder (loaded once, reused)
_embedder = None


def load_embedder():
    """Load the embedding model (called once at startup)."""
    global _embedder
    if _embedder is not None:
        return _embedder

    from memory_system.embeddings.factory import get_embedder

    print("Loading embedding model...", file=sys.stderr)
    _embedder = get_embedder(
        "fastembed",
        model="BAAI/bge-small-en-v1.5",
        use_cache=False,  # Daemon handles caching separately
    )
    print(f"Model loaded: {_embedder.model_name} (dim={_embedder.dim})", file=sys.stderr)
    return _embedder


def recv_exactly(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes from socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def send_message(sock: socket.socket, data: bytes) -> None:
    """Send length-prefixed message."""
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_message(sock: socket.socket) -> bytes:
    """Receive length-prefixed message."""
    length_bytes = recv_exactly(sock, 4)
    length = struct.unpack(">I", length_bytes)[0]
    if length > 10_000_000:  # 10MB max
        raise ValueError(f"Message too large: {length}")
    return recv_exactly(sock, length)


def handle_client(client: socket.socket, embedder) -> None:
    """Handle a single client request."""
    try:
        # Try to receive length-prefixed message first
        data = None
        try:
            data = recv_message(client)
        except (ConnectionError, struct.error):
            # Fall back to raw JSON (for simple testing with netcat)
            client.setblocking(False)
            try:
                data = b""
                while True:
                    try:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    except BlockingIOError:
                        break
            finally:
                client.setblocking(True)

        if not data:
            return

        # Parse request
        try:
            texts = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as e:
            error = {"error": f"Invalid JSON: {e}"}
            send_message(client, json.dumps(error).encode())
            return

        if not isinstance(texts, list):
            error = {"error": "Expected JSON list of strings"}
            send_message(client, json.dumps(error).encode())
            return

        # Compute embeddings
        result = embedder.embed_texts(texts)
        response = {
            "vectors": result.vectors,
            "dim": result.dim,
            "model": result.model,
        }

        # Send response
        response_bytes = json.dumps(response).encode("utf-8")
        send_message(client, response_bytes)

    except Exception as e:
        try:
            error = {"error": str(e)}
            send_message(client, json.dumps(error).encode())
        except Exception:
            pass
    finally:
        client.close()


def run_daemon(socket_path: Path) -> None:
    """Run the embedding daemon."""
    # Clean up stale socket
    if socket_path.exists():
        socket_path.unlink()

    # Ensure parent directory exists
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    # Load model before starting server
    embedder = load_embedder()

    # Create Unix socket
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(5)

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Handle SIGTERM gracefully
    def handle_signal(signum, frame):
        print("\nShutting down...", file=sys.stderr)
        server.close()
        socket_path.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print(f"Embedding daemon listening on {socket_path}", file=sys.stderr)

    try:
        while True:
            client, _ = server.accept()
            # Handle synchronously (embedding is CPU-bound anyway)
            handle_client(client, embedder)
    finally:
        server.close()
        socket_path.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)


def stop_daemon() -> bool:
    """Stop a running daemon."""
    if not PID_FILE.exists():
        print("No daemon running (PID file not found)", file=sys.stderr)
        return False

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (PID {pid})", file=sys.stderr)
        PID_FILE.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError) as e:
        print(f"Failed to stop daemon: {e}", file=sys.stderr)
        PID_FILE.unlink(missing_ok=True)
        return False


def embed_via_daemon(
    texts: List[str],
    socket_path: Path = DEFAULT_SOCKET,
    timeout: float = 30.0,
) -> Optional[dict]:
    """Client function to embed texts via the daemon.

    Returns dict with "vectors", "dim", "model" on success, None on failure.
    """
    if not socket_path.exists():
        return None

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(socket_path))

        # Send request
        request = json.dumps(texts).encode("utf-8")
        send_message(client, request)

        # Receive response
        response_bytes = recv_message(client)
        client.close()

        return json.loads(response_bytes.decode("utf-8"))

    except (socket.error, json.JSONDecodeError, ConnectionError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding daemon")
    parser.add_argument(
        "--socket",
        type=Path,
        default=DEFAULT_SOCKET,
        help=f"Unix socket path (default: {DEFAULT_SOCKET})",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop a running daemon",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check if daemon is running",
    )

    args = parser.parse_args()

    if args.status:
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)  # Check if process exists
                print(f"Daemon running (PID {pid})")
                return 0
            except (ValueError, ProcessLookupError):
                print("Daemon not running (stale PID file)")
                return 1
        else:
            print("Daemon not running")
            return 1

    if args.stop:
        return 0 if stop_daemon() else 1

    run_daemon(args.socket)
    return 0


if __name__ == "__main__":
    sys.exit(main())
