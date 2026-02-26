#!/usr/bin/env bash
# Run the SEC KG chatbot. Access from Windows: http://192.168.1.39:8501
cd "$(dirname "$0")/../.."
streamlit run python/chatbot/app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true \
  "$@"
