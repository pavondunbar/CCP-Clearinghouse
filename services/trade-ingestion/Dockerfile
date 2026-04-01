FROM ccp-base:latest
COPY services/trade-ingestion/ /app/services/trade-ingestion/
RUN cd /app/services/trade-ingestion && uv pip install .
EXPOSE 8001
CMD ["uvicorn", "trade_ingestion.main:app", "--host", "0.0.0.0", "--port", "8001"]
