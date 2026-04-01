FROM ccp-base:latest
COPY services/liquidation-engine/ /app/services/liquidation-engine/
RUN cd /app/services/liquidation-engine && uv pip install .
EXPOSE 8007
CMD ["uvicorn", "liquidation_engine.main:app", "--host", "0.0.0.0", "--port", "8007"]
