FROM ccp-base:latest
COPY services/price-oracle/ /app/services/price-oracle/
RUN cd /app/services/price-oracle && uv pip install .
EXPOSE 8008
CMD ["uvicorn", "price_oracle.main:app", "--host", "0.0.0.0", "--port", "8008"]
