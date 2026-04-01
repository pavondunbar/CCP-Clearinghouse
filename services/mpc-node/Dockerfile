FROM ccp-base:latest
COPY services/mpc-node/ /app/services/mpc-node/
RUN cd /app/services/mpc-node && uv pip install .
EXPOSE 8020
CMD ["uvicorn", "mpc_node.main:app", "--host", "0.0.0.0", "--port", "8020"]
