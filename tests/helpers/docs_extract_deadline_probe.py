"""עוזר לטסט: תקרת הזמן של "חלץ" מול שרת שמטפטף תשובה, בתהליך ש-gevent החליף בו את הרשת.

⚠️ הקובץ עושה ``monkey.patch_all()`` בזמן ייבוא, ולכן הוא יושב ב-``tests/helpers`` ולא תחת ``tests/``:
אסור שיתגלה או ייובא לתוך תהליך ה-pytest, שבו ה-patching כבוי (``CODEBOT_DISABLE_GEVENT_PATCH``).

**התהליך מדמה את ה-worker של הוובאפ:** gunicorn עם ``worker_class=gevent`` קורא ``monkey.patch_all()`` לפני
שהוא טוען את האפליקציה (``gunicorn/workers/ggevent.py``, ``GeventWorker.init_process``), וכך גם כאן — לפני כל
ייבוא אחר.

**השרת מטפטף** (``tests/helpers/docs_extract_drip_server.py``, בתהליך משלו — ההסבר שם): הוא שולח כותרות של
תשובה ארוכה, ואחריהן בית אחד כל ``DRIP_SECONDS`` שלו, בלי סוף. כל קריאה מהרשת מקבלת משהו לפני התקרה של ה-SDK,
ולכן רק תקרה על הקריאה כולה עוצרת אותה. ``sdk_ceiling_alone`` מראה את זה: אותה קריאה, בלי ``gevent.Timeout``,
עדיין רצה אחרי ``CONTROL_WAIT_SECONDS``.

הפלט: שורת JSON אחת.
"""

from __future__ import annotations

# חייב להיות ראשון, לפני כל ייבוא אחר.
from gevent import monkey

monkey.patch_all()

import datetime  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/probe")
os.environ.setdefault("BOT_TOKEN", "0:probe")

import gevent  # noqa: E402

#: התקרה של החילוץ בפרוב. בפרודקשן היא ``EXTRACT_DEADLINE_SECONDS`` של השירות. השרת מטפטף בית כל 0.2 שניות
#: (``DRIP_SECONDS`` שלו) — הרבה מתחת לתקרה של ה-SDK, שהשירות קובע לגודל של התקרה הזו.
DEADLINE_SECONDS = 1.0
#: כמה זמן הביקורת מחכה לקריאה בלי ``gevent.Timeout`` לפני שהיא קובעת שהקריאה לא נעצרה.
CONTROL_WAIT_SECONDS = 3.0
DRIP_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs_extract_drip_server.py")


def _start_drip_server(*args: str) -> tuple[subprocess.Popen, int]:
    # ``-B`` בקריאה: הסביבה נבנית כאן מ-``os.environ``, אבל כך אין תלות בכך שמישהו העביר ``PYTHONDONTWRITEBYTECODE``.
    # ``stdin`` צינור שנשאר פתוח כל עוד הפרוב חי: השרת יוצא כשהוא נסגר (``docs_extract_drip_server.py``).
    server = subprocess.Popen([sys.executable, "-B", DRIP_SERVER, *args], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    return server, int(server.stdout.readline())


def _write_certificate(folder: str) -> tuple[str, str]:
    """תעודה עצמית ל-127.0.0.1, כדי שהלקוח יאמת את השרת המקומי כמו כל שרת אחר."""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
    with open(cert_path, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return cert_path, key_path


def main(folder: str) -> dict:
    cert_path, key_path = _write_certificate(folder)
    # שני המסלולים שבהם httpx2 בונה את ה-SSLContext: עם ``SSL_CERT_FILE`` — ``ssl.create_default_context``; בלעדיו,
    # כמו בפרודקשן — ``truststore.SSLContext``, ש-OpenSSL שבתוכו מאמת מול ``SSL_CERT_FILE`` (``httpx2/_config.py``).
    os.environ["SSL_CERT_FILE"] = cert_path
    os.environ.pop("SSL_CERT_DIR", None)

    plain, plain_port = _start_drip_server("http")
    secure, secure_port = _start_drip_server("tls", cert_path, key_path)

    import httpx2
    import openai

    from services import docs_extract_service as svc
    from services.docs_search_service import DocsSearchError
    from services.llm_endpoint_settings import LlmEndpoint

    svc.EXTRACT_DEADLINE_SECONDS = DEADLINE_SECONDS
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]

    beats: list[float] = []

    def heart():
        while True:
            beats.append(time.monotonic())
            gevent.sleep(0.05)

    heart_greenlet = gevent.spawn(heart)

    def through_truststore(endpoint):
        # כמו ``_openai_client``, עם ``trust_env=False``: httpx2 מדלג על ``SSL_CERT_FILE`` ובונה ``truststore.SSLContext``.
        return openai.OpenAI(api_key=endpoint.api_key, base_url=endpoint.base_url, timeout=DEADLINE_SECONDS,
                             max_retries=0, http_client=httpx2.Client(trust_env=False, timeout=DEADLINE_SECONDS))

    def measure(base_url, factory):
        endpoint = LlmEndpoint("probe-key", base_url, "probe-model")
        started = time.monotonic()
        first_beat = len(beats)
        code = None
        try:
            svc._call_model(endpoint, messages, factory)
        except DocsSearchError as exc:
            code = exc.code
        elapsed = time.monotonic() - started
        window = [started] + beats[first_beat:] + [time.monotonic()]
        gaps = [later - earlier for earlier, later in zip(window, window[1:])]
        return {"code": code, "elapsed": round(elapsed, 3), "max_gap": round(max(gaps), 3)}

    result = {
        "patched": monkey.is_module_patched("socket") and monkey.is_module_patched("ssl"),
        "deadline_enforceable": svc.deadline_enforceable(),
        "deadline": DEADLINE_SECONDS,
        "http": measure(f"http://127.0.0.1:{plain_port}/v1/", svc._openai_client),
        "https": measure(f"https://127.0.0.1:{secure_port}/v1/", svc._openai_client),
        "https_truststore": measure(f"https://127.0.0.1:{secure_port}/v1/", through_truststore),
    }

    # הביקורת: אותה קריאה בלי ``gevent.Timeout``, עם התקרה של ה-SDK בלבד.
    client = svc._openai_client(LlmEndpoint("probe-key", f"http://127.0.0.1:{plain_port}/v1/", "probe-model"))
    control = gevent.spawn(client.chat.completions.create, model="probe-model", messages=messages)
    gevent.sleep(CONTROL_WAIT_SECONDS)
    result["sdk_ceiling_alone"] = {"waited": CONTROL_WAIT_SECONDS, "still_running": not control.dead}
    control.kill()
    heart_greenlet.kill()
    for server in (plain, secure):
        server.kill()
        server.wait()
    return result


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1])))
