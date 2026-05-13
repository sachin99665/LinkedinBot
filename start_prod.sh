#!/bin/bash
pip install -r requirements.txt -q
python main.py &
npx --yes serve artifacts/bot-status/dist/public -l $PORT -s
