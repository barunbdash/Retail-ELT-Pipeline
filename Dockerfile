FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY sql/ sql/
COPY models/ models/

RUN useradd --create-home --uid 10001 elt && chown -R elt /app
USER elt

# Seed and run by default so `docker run` produces a populated warehouse.
CMD ["sh", "-c", "python -m pipeline.generate_source_data --rows 20000 && python -m pipeline.run run"]
