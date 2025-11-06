# Shared conversation states

# Keep the same numeric order as before for compatibility
# Extend with new states at the end so existing values stay the same
GET_CODE, GET_FILENAME, GET_NOTE, EDIT_CODE, EDIT_NAME, WAIT_ADD_CODE_MODE, LONG_COLLECT = range(7)

# Community Library submit flow states (appended to preserve existing values)
CL_COLLECT_TITLE, CL_COLLECT_DESCRIPTION, CL_COLLECT_URL, CL_COLLECT_LOGO = range(7, 11)

# Snippet Library submit flow states (append after community states)
SN_COLLECT_TITLE, SN_COLLECT_DESCRIPTION, SN_COLLECT_CODE, SN_COLLECT_LANGUAGE = range(11, 15)

