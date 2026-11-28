"""עוזר לטסט: שרת שמטפטף תשובה, בתהליך משלו, בלי gevent — כמו ספק של מודל שפה, שהוא תמיד תהליך אחר.

ארגומנטים: ``http`` או ``tls``, ולשני — נתיבי התעודה והמפתח. מדפיס את הפורט בשורה הראשונה, ואז לכל חיבור, ב-
thread משלו: קורא את הבקשה, שולח כותרות של תשובה ארוכה, ואחריהן בית אחד כל ``DRIP_SECONDS``, עד שהלקוח סוגר.

**השרת יוצא כשה-stdin שלו נסגר**, כלומר כשהתהליך שהריץ אותו מת. בלי זה, פרוב שנהרג בתקרת הזמן של הטסט (כך הוא
נכשל כשאין תקרה בחילוץ) היה משאיר את השרתים רצים, יתומים, אחרי סוף הריצה — וזה קרה בבדיקת המוטציה.

**למה תהליך נפרד:** שרת TLS של gevent (``StreamServer`` עם ``certfile``) באותו תהליך כמו הלקוח קטע את החיבור
השני ברצף אחרי 0.41 שניות, ב-``Broken pipe``, בלי קשר לסדר או לנתיב של ה-SSLContext. מאותו לקוח מול השרת הזה,
בתהליך נפרד, שלוש קריאות רצופות נקטעו כל אחת בתקרה, בדיוק (28.11.2026). זה היה ארטיפקט של שרת הבדיקה, ולא
של הלקוח — וכאן הוא לא קיים.
"""

from __future__ import annotations

import os
import socket
import ssl
import sys
import threading
import time

DRIP_SECONDS = 0.2


def _serve(conn: socket.socket, context: "ssl.SSLContext | None") -> None:
    try:
        if context is not None:
            conn = context.wrap_socket(conn, server_side=True)
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000000\r\n\r\n")
        while True:
            conn.sendall(b" ")
            time.sleep(DRIP_SECONDS)
    except OSError:
        # הלקוח סגר את החיבור כשהתקרה שלו נגמרה — זה הסוף הצפוי של כל חיבור כאן.
        return
    finally:
        conn.close()


def _exit_with_the_parent() -> None:
    sys.stdin.read()  # חוזר רק ב-EOF: התהליך שהריץ אותנו סגר את הצינור, או מת
    os._exit(0)


def main(argv: list[str]) -> None:
    threading.Thread(target=_exit_with_the_parent, daemon=True).start()
    context = None
    if argv[0] == "tls":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(argv[1], argv[2])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    print(listener.getsockname()[1], flush=True)
    while True:
        conn, _address = listener.accept()
        threading.Thread(target=_serve, args=(conn, context), daemon=True).start()


if __name__ == "__main__":
    main(sys.argv[1:])
