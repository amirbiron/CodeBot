import types


def test_build_pagination_row_basic(monkeypatch):
    # Stub InlineKeyboardButton to capture (text, callback_data)
    class Btn:
        def __init__(self, text, callback_data):
            self.text = text
            self.callback_data = callback_data
    tg = types.ModuleType('telegram')
    tg.InlineKeyboardButton = Btn
    monkeypatch.setitem(__import__('sys').modules, 'telegram', tg)

    from handlers.pagination import build_pagination_row

    # total=23, page_size=10 -> total_pages=3
    row1 = build_pagination_row(page=1, total_items=23, page_size=10, callback_prefix='files_page_')
    assert row1 is not None and len(row1) == 1
    assert row1[0].text.endswith('הבא') and row1[0].callback_data == 'files_page_2'

    row2 = build_pagination_row(page=2, total_items=23, page_size=10, callback_prefix='files_page_')
    assert row2 is not None and len(row2) == 2
    texts2 = [b.text for b in row2]
    cbs2 = [b.callback_data for b in row2]
    assert any('הקודם' in t for t in texts2)
    assert any('הבא' in t for t in texts2)
    assert 'files_page_1' in cbs2 and 'files_page_3' in cbs2

    row3 = build_pagination_row(page=3, total_items=23, page_size=10, callback_prefix='files_page_')
    assert row3 is not None and len(row3) == 1
    assert row3[0].text.endswith('הקודם') and row3[0].callback_data == 'files_page_2'

    # no pagination needed
    assert build_pagination_row(page=1, total_items=5, page_size=10, callback_prefix='x_') is None
    assert build_pagination_row(page=1, total_items=0, page_size=0, callback_prefix='x_') is None

