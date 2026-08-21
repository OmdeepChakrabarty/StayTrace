FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Environment settings
ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/parcels.db \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# Create data directory for persistent SQLite database
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "api/main.py"]
