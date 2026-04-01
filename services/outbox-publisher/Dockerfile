FROM ccp-base:latest
COPY services/outbox-publisher/ /app/services/outbox-publisher/
RUN cd /app/services/outbox-publisher && uv pip install .
EXPOSE 8002
CMD ["uvicorn", "outbox_publisher.main:app", "--host", "0.0.0.0", "--port", "8002"]
