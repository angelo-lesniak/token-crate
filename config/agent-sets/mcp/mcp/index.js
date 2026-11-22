// pi's own MCP client, loaded as a package. The shared settings switch the
// built-in copy off (`-builtin:mcp`), so a session runs MCP when this set is
// selected, or when a trusted project turns the built-in back on in its
// .pi/settings.json; pi's public factory is the same code, with the same
// project-trust gate on `.pi/mcp.json`.
import { createMcpExtension } from "@earendil-works/pi-coding-agent";

export default createMcpExtension();
