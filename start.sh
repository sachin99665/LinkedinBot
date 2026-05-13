#!/bin/bash
pip install -r requirements.txt -q
python main.py &
exec node --enable-source-maps artifacts/api-server/dist/index.mjs
