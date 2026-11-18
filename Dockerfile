FROM python:3.12-alpine
WORKDIR /app
COPY app.py catalog.py connector.py demo.py ./
COPY web ./web
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 WORKBENCH_BIND=0.0.0.0
EXPOSE 8765
CMD ["python", "app.py"]
