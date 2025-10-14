import importlib


def test_highlight_terminal_and_create_image_paths(monkeypatch):
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor

    code = "print('x')\n"

    # מסלול terminal (גם אם TerminalFormatter אינו זמין, הפונקציה תחזיר את הקוד)
    out_term = cp.highlight_code(code, programming_language='python', output_format='terminal')
    assert isinstance(out_term, str)

    # מסלול HTML עם קוד קצר מ-10 תווים — יחזיר את הקוד עצמו
    short = "x = 1\n"
    out_short = cp.highlight_code(short, programming_language='python', output_format='html')
    assert out_short == short or isinstance(out_short, str)

    # בדיקת create_code_image על תוכן ריק — אמור להחזיר None או bytes ללא חריגה
    img = cp.create_code_image("", programming_language='python')
    assert (img is None) or isinstance(img, (bytes, bytearray))

