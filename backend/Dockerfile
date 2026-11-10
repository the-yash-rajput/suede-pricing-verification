# Playwright image ships Chromium + system deps matching playwright==1.49.1
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --break-system-packages -r pyproject.toml
COPY . .
ENV PYTHONUNBUFFERED=1 HEADLESS=1
EXPOSE 8000
# Virtual screen :99 for brands with config.headed=true (bot walls). Xvfb ships in the image.
# ponytail: plain Xvfb, not xvfb-run: xvfb-run hangs as PID 1 (waits on a SIGUSR1 that never arrives).
ENV DISPLAY=:99
CMD ["sh", "-c", "Xvfb :99 -screen 0 1366x900x24 -nolisten tcp & exec uvicorn api:app --host 0.0.0.0 --port 8000"]
