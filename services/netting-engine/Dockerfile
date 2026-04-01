FROM ccp-base:latest
COPY services/netting-engine/ /app/services/netting-engine/
RUN cd /app/services/netting-engine && uv pip install .
EXPOSE 8003
CMD ["uvicorn", "netting_engine.main:app", "--host", "0.0.0.0", "--port", "8003"]
