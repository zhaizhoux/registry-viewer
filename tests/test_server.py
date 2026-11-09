import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from regview.server import create_server
from tests.fake import FakeRegistry, sample_tree

TOKEN = "unit-test-token-123"


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = create_server(
            port=0, token=TOKEN, registry=FakeRegistry(sample_tree()),
            home=cls.temp.name, quiet=True,
        )
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def call(self, path, token=True, method="GET", body=None, host=None, origin=None):
        headers = {}
        if token:
            headers["X-Regview-Token"] = TOKEN
        if host:
            headers["Host"] = host
        if origin:
            headers["Origin"] = origin
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def jcall(self, path, **kwargs):
        status, raw, headers = self.call(path, **kwargs)
        return status, json.loads(raw.decode("utf-8")), headers

    # ---------- 静态资源与安全边界 ----------

    def test_index_requires_token(self):
        self.assertEqual(self.call("/", token=False)[0], 403)

    def test_index_with_query_token(self):
        status, raw, _ = self.call("/?token=" + TOKEN, token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"regview", raw)

    def test_static_assets(self):
        for name in ("/app.js", "/style.css", "/favicon.svg"):
            status, raw, _ = self.call(name, token=False)
            self.assertEqual(status, 200, name)
            self.assertGreater(len(raw), 50, name)

    def test_wrong_host_rejected(self):
        status, _, _ = self.call("/?token=" + TOKEN, token=False, host="attacker.example")
        self.assertEqual(status, 403)

    def test_cross_origin_rejected(self):
        status, _, _ = self.call("/api/health", origin="https://attacker.example")
        self.assertEqual(status, 403)

    def test_api_requires_token(self):
        self.assertEqual(self.call("/api/health", token=False)[0], 403)

    def test_unknown_path(self):
        self.assertEqual(self.call("/nope")[0], 404)
        self.assertEqual(self.call("/api/nope")[0], 404)

    # ---------- API ----------

    def test_health_and_roots(self):
        status, data, _ = self.jcall("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["readonly"])
        self.assertIn("reg", data["formats"])
        status, data, _ = self.jcall("/api/roots")
        self.assertEqual(len(data["roots"]), 5)
        self.assertEqual(data["default"], "HKEY_CURRENT_USER")

    def test_node_and_children(self):
        status, data, _ = self.jcall("/api/node?path=" +
                                     urllib.parse.quote("HKCU\\Software\\Acme"))
        self.assertEqual(status, 200)
        self.assertEqual(len(data["values"]), 6)
        self.assertIsNone(data["error"])
        self.assertEqual(data["parent"], "HKEY_CURRENT_USER\\Software")

        status, data, _ = self.jcall("/api/children?path=" + urllib.parse.quote("HKCU\\Software"))
        self.assertEqual(data["children"], ["Acme", "Missing"])

    def test_node_error_and_bad_path(self):
        status, data, _ = self.jcall("/api/node?path=" +
                                     urllib.parse.quote("HKCU\\Software\\Missing"))
        self.assertEqual(status, 200)
        self.assertIn("拒绝访问", data["error"]["message"])
        self.assertEqual(self.call("/api/node?path=NOPE")[0], 400)

    def test_value_detail(self):
        status, data, _ = self.jcall("/api/value?path=" +
                                     urllib.parse.quote("HKCU\\Software\\Acme") +
                                     "&name=Blob")
        self.assertEqual(data["type"], "REG_BINARY")
        self.assertIn("00000010", data["hex"])
        self.assertEqual(self.jcall("/api/value?path=" +
                                    urllib.parse.quote("HKCU\\Software\\Acme") +
                                    "&name=NotThere")[0], 404)

    def test_search(self):
        status, data, _ = self.jcall("/api/search?q=Acme&root=HKCU&scope=keys")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(self.call("/api/search?q=&root=HKCU")[0], 400)

    def test_export_reg(self):
        status, raw, headers = self.call("/api/export?path=" +
                                         urllib.parse.quote("HKCU\\Software") + "&format=reg")
        self.assertEqual(status, 200)
        self.assertIn("Windows Registry Editor Version 5.00", raw.decode("utf-16"))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))

    def test_export_json_and_csv(self):
        status, raw, _ = self.call("/api/export?path=HKCU&format=json")
        self.assertEqual(json.loads(raw.decode("utf-8"))["readonly"], True)
        status, raw, _ = self.call("/api/export?path=HKCU&format=csv")
        self.assertIn(b"key_path,value_name", raw)

    def test_invalid_export_format(self):
        self.assertEqual(self.call("/api/export?path=HKCU&format=xml")[0], 400)

    def test_bookmarks_crud(self):
        status, data, _ = self.jcall("/api/bookmarks", method="POST",
                                     body={"path": "HKCU\\Software\\Acme"})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["bookmarks"]), 1)
        status, data, _ = self.jcall("/api/bookmarks")
        self.assertEqual(data["bookmarks"][0]["name"], "Acme")
        status, data, _ = self.jcall("/api/bookmarks", method="DELETE",
                                     body={"path": "HKEY_CURRENT_USER\\Software\\Acme"})
        self.assertEqual(len(data["bookmarks"]), 0)

    def test_view_parameter_is_accepted(self):
        status, data, _ = self.jcall("/api/node?path=HKCU&view=64")
        self.assertEqual(status, 200)
        self.assertEqual(data["path"], "HKEY_CURRENT_USER")


if __name__ == "__main__":
    unittest.main()
