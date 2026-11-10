# Playwright image ships Chromium + system deps matching playwright==1.49.1
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --break-system-packages -r pyproject.toml
COPY . .
ENV PYTHONUNBUFFERED=1 HEADLESS=1
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
