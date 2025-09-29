from typing import List, Optional

from telegram import InlineKeyboardButton


def build_pagination_row(
    page: int,
    total_items: int,
    page_size: int,
    callback_prefix: str,
) -> Optional[List[InlineKeyboardButton]]:
    """Return a row of pagination buttons [prev,next] or None if not needed.

    - page: current 1-based page index
    - total_items: total number of items
    - page_size: items per page
    - callback_prefix: for example r``files\_page\_`` → formats as ``{prefix}{page_num}``
    """
    if page_size <= 0:
        return None
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    if total_pages <= 1:
        return None
    row: List[InlineKeyboardButton] = []
    if page > 1:
        row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"{callback_prefix}{page-1}"))
    if page < total_pages:
        row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"{callback_prefix}{page+1}"))
    return row or None

