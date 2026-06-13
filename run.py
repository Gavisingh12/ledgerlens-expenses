from app.server import app, init_db, make_server, os


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving on http://127.0.0.1:{port}")
    make_server("0.0.0.0", port, app).serve_forever()
