"""Optional managed loopback MCP host; no FastMCP dependency until start."""

import asyncio
import socket
import threading

from PySide6.QtCore import QThread, Signal

from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='qt.mcp')


class SnapshotMcpHost(QThread):
    """Own an HTTP listener and pin one loaded context until shutdown.

    Attributes:
        ready: URL and verified tool metadata, emitted only after a real handshake.
        failed: Startup/runtime failure message; finished still signals thread exit.
        context: Snapshot served for the entire listener lifetime.
    """

    ready = Signal(str, object)
    failed = Signal(str)

    def __init__(self, context, port: int, parent=None) -> None:
        """Retain a loaded context and desired port; zero selects an unused port."""
        super().__init__(parent)
        self.context = context
        self.port = port
        self.stop_requested = threading.Event()
        self.url = ''

    def stop(self) -> None:
        """Request graceful shutdown from the GUI thread without blocking it."""
        self.stop_requested.set()

    def run(self) -> None:
        """Run the server's owned event loop and report handled startup failures."""
        try:
            asyncio.run(self._serve())
        except ImportError:
            self.failed.emit('MCP dependencies are unavailable. Install the mcp extra and restart.')
        except Exception as exc:
            logger.exception('Embedded MCP host failed')
            self.failed.emit(f'{type(exc).__name__}: {exc}')

    async def _serve(self) -> None:
        import uvicorn
        from fastmcp import Client

        from oci_policy_analysis.mcp_server import create_snapshot_server

        server = await create_snapshot_server(self.context)
        app = server.http_app(path='/mcp', transport='streamable-http')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', self.port))
            listener.listen(128)
            listener.setblocking(False)
            self.url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
            config = uvicorn.Config(app, log_config=None, access_log=False, lifespan='on', timeout_graceful_shutdown=5)
            http = uvicorn.Server(config)
            task = asyncio.create_task(http.serve(sockets=[listener]))
            try:
                deadline = asyncio.get_running_loop().time() + 15
                while not http.started:
                    if task.done():
                        await task
                        raise RuntimeError('MCP listener exited before becoming ready')
                    if self.stop_requested.is_set():
                        return
                    if asyncio.get_running_loop().time() > deadline:
                        raise TimeoutError('MCP listener startup timed out')
                    await asyncio.sleep(0.03)
                async with asyncio.timeout(10):
                    async with Client(self.url) as client:
                        tools = await client.list_tools()
                        status = await client.call_tool('snapshot_status')
                        if status.is_error:
                            raise RuntimeError('MCP snapshot check failed')
                if not self.stop_requested.is_set():
                    self.ready.emit(
                        self.url, [{'name': tool.name, 'description': tool.description or ''} for tool in tools]
                    )
                    logger.info('Embedded MCP ready: %s tools=%d', self.url, len(tools))
                while not self.stop_requested.is_set() and not task.done():
                    await asyncio.sleep(0.05)
                if task.done() and not self.stop_requested.is_set():
                    await task
                    raise RuntimeError('MCP listener stopped unexpectedly')
            finally:
                http.should_exit = True
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=8)
                except TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise TimeoutError('MCP listener did not stop within eight seconds') from None
                logger.info('Embedded MCP listener stopped')
