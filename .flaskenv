# Flask environment variables — read automatically by `flask run` when python-dotenv is installed.
# FLASK_RUN_PORT is kept in sync with server.port in config.yml.
# Running `testbook-web` from the CLI will update this file automatically.
FLASK_APP=testbook.web:app
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=5005

