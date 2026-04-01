FROM ccp-base:latest
COPY services/settlement-engine/ /app/services/settlement-engine/
RUN cd /app/services/settlement-engine && uv pip install .
EXPOSE 8006
CMD ["uvicorn", "settlement_engine.main:app", "--host", "0.0.0.0", "--port", "8006"]
