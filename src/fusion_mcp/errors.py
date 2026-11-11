"""Error types the tools raise."""

from mcp.server.mcpserver.exceptions import ToolError


class FusionToolError(ToolError):
    """A tool-level failure, carrying the BIP fault message when one is present.

    Subclassing the MCP SDK's ToolError means this message reaches the agent (after
    the SDK's "Error executing tool query_fusion:" prefix); any other exception is
    reported as a bare "Error executing tool" with the details kept on the server.
    """


class FusionUnreachable(FusionToolError):
    """Fusion could not be reached (network, DNS, TLS or timeout); says nothing about the password."""


class SessionExpired(FusionToolError):
    """BI Publisher rejected the session token (expired or logged out)."""
