FROM python:3.12-slim
WORKDIR /app
COPY python_service/requirements.txt /app/python_service/requirements.txt
RUN pip install --no-cache-dir -r /app/python_service/requirements.txt
COPY python_service/gradheat_python /app/python_service/gradheat_python
COPY python_service/gradheat_core /app/python_service/gradheat_core
COPY crawler /app/crawler
COPY tools/research /app/tools/research
COPY config /app/config
ENV PYTHONPATH=/app/python_service PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV GRADHEAT_BIND_HOST=0.0.0.0 GRADHEAT_PYTHON_PORT=18730
EXPOSE 18730
CMD ["python", "-m", "gradheat_python.api"]
