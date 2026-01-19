# Gap Foundry Backend Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create outputs directory
RUN mkdir -p outputs/reports outputs/runs

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "gap_foundry.api:app", "--host", "0.0.0.0", "--port", "8000"]
