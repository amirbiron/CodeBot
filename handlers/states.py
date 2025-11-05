# Shared conversation states

# Keep the same numeric order as before for compatibility
# Extend with new states at the end so existing values stay the same
GET_CODE, GET_FILENAME, GET_NOTE, EDIT_CODE, EDIT_NAME, WAIT_ADD_CODE_MODE, LONG_COLLECT = range(7)

# Community Library submit flow states (appended to preserve existing values)
CL_COLLECT_TITLE, CL_COLLECT_DESCRIPTION, CL_COLLECT_URL, CL_COLLECT_LOGO = range(7, 11)

