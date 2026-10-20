"""
opencaster.api — Let other programs control the wands and hear about casts.

The server (server.py) runs inside OpenCaster (GUI or headless) on
http://127.0.0.1:8765/api.  client.py is a dependency-free Python client;
`python -m opencaster.api --help` is a command-line front end.  Any language
can use the API directly: it is plain HTTP + JSON, with Server-Sent Events
for the event stream.
"""
