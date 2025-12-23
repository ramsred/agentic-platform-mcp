FROM python:3.11-slim

# Why:
# - slim = smaller attack surface
# - python 3.11 = matches rest of stack

WORKDIR /app

# Copy requirements first (layer caching best practice)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src ./src

# Default command
CMD ["python", "-m", "src.host.multi_mcp_host"]