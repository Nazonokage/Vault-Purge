"""Record server lifecycle and received signals without changing shutdown behavior."""
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys

import uvicorn


class DiagnosticServer(uvicorn.Server):
    def __init__(self, config, diagnostics):
        super().__init__(config)
        self.diagnostics = diagnostics

    def handle_exit(self, sig, frame):
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = str(sig)
        self.diagnostics.warning("Shutdown signal received: %s; pid=%s. Signal sender is not available from Python's signal handler.", name, os.getpid())
        super().handle_exit(sig, frame)


def run_server(app, settings, port):
    path = settings.database.resolve().parent / "diagnostics.log"
    logger = logging.getLogger(f"vault_purge.lifecycle.{os.getpid()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("Server starting; pid=%s parent_pid=%s executable=%s port=%s", os.getpid(), os.getppid(), sys.executable, port)
    try:
        DiagnosticServer(uvicorn.Config(app, host="127.0.0.1", port=port), logger).run()
    except KeyboardInterrupt:
        logger.info("Interrupt reached server entry point")
    except BaseException:
        logger.exception("Server exited with an exception")
        raise
    finally:
        logger.info("Server stopped; pid=%s", os.getpid())
        logger.removeHandler(handler)
        handler.close()
