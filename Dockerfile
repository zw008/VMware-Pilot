FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml README.md ./
COPY vmware_pilot/ vmware_pilot/
COPY examples/ examples/

# Install dependencies
RUN uv pip install --system --no-cache .

# State directory (mount at runtime to persist workflows).
# Pilot has no config file — this holds workflows.db and custom workflow YAML.
RUN mkdir -p /root/.vmware/workflows

# MCP server uses stdio transport — no port needed
CMD ["python", "-m", "vmware_pilot.mcp_server"]
