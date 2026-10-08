FROM python:3.12-slim-bookworm
WORKDIR /demo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py schema.sql ./
USER 65534:65534
CMD ["python", "run.py"]
