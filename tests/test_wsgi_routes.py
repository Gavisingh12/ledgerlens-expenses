from io import BytesIO
from pathlib import Path
import unittest
from wsgiref.util import setup_testing_defaults

from app.server import app, make_session


class WsgiRouteTest(unittest.TestCase):
    def call(self, path, method="GET", body=b"", content_type="application/x-www-form-urlencoded", cookie=""):
        env = {}
        setup_testing_defaults(env)
        env.update(
            {
                "PATH_INFO": path,
                "REQUEST_METHOD": method,
                "wsgi.input": BytesIO(body),
                "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": content_type,
            }
        )
        if cookie:
            env["HTTP_COOKIE"] = cookie
        status_headers = []
        response = b"".join(app(env, lambda status, headers: status_headers.append((status, headers))))
        return status_headers[0], response

    def test_protected_dashboard_renders_for_logged_in_user(self):
        cookie = "session=" + make_session(1, "Aisha")
        (status, _), response = self.call("/", cookie=cookie)

        self.assertEqual(status, "200 OK")
        self.assertIn(b"Balance Summary", response)

    def test_import_upload_redirects_to_report(self):
        boundary = "----codexboundary"
        csv_bytes = Path("data/expenses_export.csv").read_bytes()
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="csv_file"; filename="expenses_export.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode("utf-8") + csv_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        cookie = "session=" + make_session(1, "Aisha")

        (status, headers), _ = self.call(
            "/import",
            method="POST",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            cookie=cookie,
        )

        self.assertEqual(status, "303 See Other")
        self.assertTrue(any(key == "Location" and value.startswith("/imports/") for key, value in headers))


if __name__ == "__main__":
    unittest.main()
