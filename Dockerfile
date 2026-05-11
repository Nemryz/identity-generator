FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The clipboard flag does not work inside a container.
# Use --json and mount a volume to retrieve output files.
ENTRYPOINT ["python", "-X", "utf8", "main.py"]
