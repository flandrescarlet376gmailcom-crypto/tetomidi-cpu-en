"""
HTTP client the tetomidi app uses to talk to the transcription server.
Has no GUI code, so it can be tested on its own.
"""
import base64
import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ApiError(Exception):
    pass


def _ssl_context():
    """Use certifi's CA bundle so HTTPS works inside the packaged .exe."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()


class ApiClient:
    def __init__(self, server, token, timeout=30):
        self.base = server.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _open(self, method, path, body=None, headers=None, timeout=None):
        h = {"Authorization": f"Bearer {self.token}"}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=_SSL) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", str(e))
            except Exception:
                msg = str(e)
            raise ApiError(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            raise ApiError(f"Cannot reach server: {e.reason}")
        except OSError as e:
            raise ApiError(f"Connection problem: {e}")

    def health(self):
        return json.loads(self._open("GET", "/api/health").decode("utf-8"))

    def submit_file(self, path):
        with open(path, "rb") as f:
            data = f.read()
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Filename": urllib.parse.quote(os.path.basename(path)),
        }
        body = self._open("POST", "/api/jobs", body=data, headers=headers, timeout=600)
        return json.loads(body.decode("utf-8"))["id"]

    def submit_link(self, url):
        body = json.dumps({"url": url}).encode("utf-8")
        out = self._open("POST", "/api/links", body=body,
                         headers={"Content-Type": "application/json"})
        return json.loads(out.decode("utf-8"))["id"]

    def status(self, job_id):
        return json.loads(self._open("GET", f"/api/jobs/{job_id}").decode("utf-8"))

    def download_midi(self, job_id, dst_path):
        data = self._open("GET", f"/api/jobs/{job_id}/midi", timeout=300)
        with open(dst_path, "wb") as f:
            f.write(data)
        return dst_path

    def cancel(self, job_id):
        return json.loads(self._open("DELETE", f"/api/jobs/{job_id}").decode("utf-8"))


class BridgeClient:
    """
    Talks to an existing transcription endpoint that accepts a file or a link
    and returns the MIDI. Keeps the same interface as ApiClient so the UI
    does not need to change:
        POST {base}{file_path}   multipart/form-data, field "file"
        POST {base}{link_path}   JSON {"url": "..."}
    The response may be the MIDI bytes directly, or JSON containing
    "midi_url" (fetched next), or "midi_base64".
    """

    def __init__(self, base, file_path="/transcribe", link_path="/transcribe-url",
                 token="", timeout=7200):
        self.base = base.rstrip("/")
        self.file_path = file_path
        self.link_path = link_path
        self.token = token
        self.timeout = timeout
        self.jobs = {}
        self.lock = threading.Lock()

    def health(self):
        return {"ok": True}

    def _headers(self, content_type):
        h = {"Content-Type": content_type}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method, url, body=None, headers=None):
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                return r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", ""), r.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise ApiError(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise ApiError(f"Cannot reach server: {e.reason}")
        except OSError as e:
            raise ApiError(f"Connection problem: {e}")

    def _send_file(self, path, filename, data):
        boundary = uuid.uuid4().hex
        safe = filename.replace('"', "_")
        head = (f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="file"; filename="{safe}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = self._headers(f"multipart/form-data; boundary={boundary}")
        return self._request("POST", self.base + path, head + data + tail, headers)

    def _send_link(self, path, url):
        body = json.dumps({"url": url}).encode("utf-8")
        return self._request("POST", self.base + path, body, self._headers("application/json"))

    def _extract_midi(self, ctype, disp, data, fallback_name):
        """Return (midi_bytes, file_name) from whatever the endpoint sent back."""
        looks_json = "json" in ctype or data.lstrip()[:1] == b"{"
        if looks_json:
            obj = json.loads(data.decode("utf-8"))
            if obj.get("midi_url"):
                _, _, midi = self._request("GET", obj["midi_url"], headers=self._headers("*/*"))
            elif obj.get("midi_base64"):
                midi = base64.b64decode(obj["midi_base64"])
            else:
                raise ApiError("Unexpected JSON response, keys: " + ", ".join(obj.keys()))
        else:
            midi = data
        if midi[:4] != b"MThd":
            raise ApiError("Response is not a MIDI file. First bytes: " + repr(midi[:60]))
        m = re.search(r'filename="?([^";]+)"?', disp or "")
        name = os.path.basename(m.group(1)) if m else fallback_name
        if not name.lower().endswith(".mid"):
            name = os.path.splitext(name)[0] + ".mid"
        return midi, name

    def _run(self, jid, fn, fallback_name):
        try:
            ctype, disp, raw = fn()
            midi, name = self._extract_midi(ctype, disp, raw, fallback_name)
            state = {"state": "done", "midi": midi, "name": name, "error": ""}
        except Exception as e:
            state = {"state": "error", "midi": None, "name": "", "error": str(e)}
        with self.lock:
            if self.jobs.get(jid, {}).get("state") != "cancelled":
                self.jobs[jid].update(state)

    def submit_file(self, path):
        with open(path, "rb") as f:
            data = f.read()
        name = os.path.basename(path)
        jid = uuid.uuid4().hex
        with self.lock:
            self.jobs[jid] = {"state": "running", "midi": None, "name": "", "error": ""}
        threading.Thread(target=self._run,
                         args=(jid, lambda: self._send_file(self.file_path, name, data),
                               os.path.splitext(name)[0] + ".mid"),
                         daemon=True).start()
        return jid

    def submit_link(self, url):
        jid = uuid.uuid4().hex
        with self.lock:
            self.jobs[jid] = {"state": "running", "midi": None, "name": "", "error": ""}
        threading.Thread(target=self._run,
                         args=(jid, lambda: self._send_link(self.link_path, url), "link.mid"),
                         daemon=True).start()
        return jid

    def status(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
        if j is None:
            raise ApiError("unknown job")
        return {"id": jid, "state": j["state"], "progress": None,
                "name": j["name"], "error": j["error"], "position": 0}

    def download_midi(self, jid, dst_path):
        with self.lock:
            midi = self.jobs.get(jid, {}).get("midi")
        if not midi:
            raise ApiError("MIDI is not ready")
        with open(dst_path, "wb") as f:
            f.write(midi)
        return dst_path

    def cancel(self, jid):
        # The remote request cannot be aborted from here, so its result is ignored.
        with self.lock:
            if jid in self.jobs:
                self.jobs[jid]["state"] = "cancelled"
        return {"id": jid, "state": "cancelled"}
