#!/bin/bash

ln -s /app/.apt/usr/lib/python3/dist-packages/gi/_gi.cpython-36m-x86_64-linux-gnu.so /app/.apt/usr/lib/python3/dist-packages/gi/_gi.cpython-37m-x86_64-linux-gnu.so
ln -s /app/.apt/usr/lib/python3/dist-packages/gi/_gi_cairo.cpython-36m-x86_64-linux-gnu.so /app/.apt/usr/lib/python3/dist-packages/gi/_gi_cairo.cpython-37m-x86_64-linux-gnu.so
ln -s /app/.apt/usr/lib/python3/dist-packages/cairo/_cairo.cpython-36m-x86_64-linux-gnu.so /app/.apt/usr/lib/python3/dist-packages/cairo/_cairo.cpython-37m-x86_64-linux-gnu.so
poetry config virtualenvs.create false
poetry run python3 -m tle