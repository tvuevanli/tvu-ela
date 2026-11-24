"""Loaded by every Python that tests/run.sh starts (PYTHONPATH): a socket may connect to loopback or a Unix path only.
Any other connect is refused and logged to $ELA_TRIPWIRE/hits with the test that made it, and run.sh fails on a hit:
no test reaches Slack, Jira or any other live system, whatever credentials the site directory holds."""
import os, socket, sys

_log = os.environ.get("ELA_TRIPWIRE")
if _log:
    if sys.argv and os.path.basename(os.path.dirname(os.path.abspath(sys.argv[0] or "."))) == "tests":
        os.environ["ELA_TEST_NAME"] = os.path.basename(sys.argv[0])   # inherited by the children it starts
    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _local(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return True
        host = str(address[0])
        return host in ("localhost", "::1") or host.startswith("127.") or host == "::ffff:127.0.0.1"

    def _refuse(address):
        with open(os.path.join(_log, "hits"), "a") as f:
            f.write(f"{os.environ.get('ELA_TEST_NAME', '?')}: python {os.path.basename(sys.argv[0] or '-')} "
                    f"connect {address[0]}:{address[1]}\n")
        raise ConnectionRefusedError(f"tripwire: tests/run.sh refuses a connection to {address[0]}:{address[1]}")

    def connect(self, address):
        if not _local(self, address):
            _refuse(address)
        return _connect(self, address)

    def connect_ex(self, address):
        if not _local(self, address):
            _refuse(address)
        return _connect_ex(self, address)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
