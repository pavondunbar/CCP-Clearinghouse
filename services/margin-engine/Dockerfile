FROM ccp-base:latest
COPY services/margin-engine/ /app/services/margin-engine/
RUN cd /app/services/margin-engine && uv pip install .
EXPOSE 8004
CMD ["uvicorn", "margin_engine.main:app", "--host", "0.0.0.0", "--port", "8004"]
