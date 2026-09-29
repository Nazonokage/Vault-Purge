"""Offline image, video, and audio review tools."""
import sys

__version__ = "1.2.0"


def patch_asyncio_windows_proactor() -> None:
    if sys.platform == "win32":
        import asyncio.proactor_events
        import socket

        _orig_call_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost

        def _patched_call_connection_lost(self, exc):
            try:
                self._protocol.connection_lost(exc)
            finally:
                if hasattr(self, "_sock") and self._sock is not None:
                    if hasattr(self._sock, "shutdown") and self._sock.fileno() != -1:
                        try:
                            self._sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None
                server = getattr(self, "_server", None)
                if server is not None:
                    server._detach()
                    self._server = None

        asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost


patch_asyncio_windows_proactor()

