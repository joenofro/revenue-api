FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create necessary directories and set up environment
RUN mkdir -p /data
ENV BRAIN_DB=/data/aidan_brain.db
ENV CHROMA_PATH=/data/chromadb

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]