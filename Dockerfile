FROM pytorch/pytorch:2.10.0-cuda12.6-cudnn9-runtime

WORKDIR /app

# Install system dependencies (libgl1 for opencv)
RUN apt-get update && apt-get install -y gcc curl libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --locked --no-dev

# Copy application code
COPY . .

# Create LHS directory
#RUN mkdir -p /app/LHS

EXPOSE 9000 9001

CMD ["uv", "run", "bot.py"]
