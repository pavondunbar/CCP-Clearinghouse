FROM ccp-base:latest
COPY services/reconciliation-engine/ /app/services/reconciliation-engine/
RUN cd /app/services/reconciliation-engine && uv pip install .
EXPOSE 8080
CMD ["uvicorn", "reconciliation_engine.main:app", "--host", "0.0.0.0", "--port", "8080"]
