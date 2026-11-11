"""BIP artifact builders.

Turns one SELECT into the data model (.xdm) XML Oracle BIP expects. The query is
opened as a ref cursor inside a short PL/SQL block, so BI Publisher reads the
column names from the cursor and no column list is needed.
"""

from __future__ import annotations

import re

from .errors import FusionToolError

_LEADING = re.compile(r"^\s*(?:/\*.*?\*/\s*|--[^\n]*\n\s*)*", re.S)
_FOR_UPDATE = re.compile(r"\bFOR\s+UPDATE\b", re.I)
# Comments and quoted text, blanked out before looking for FOR UPDATE: Oracle reads a
# comment between FOR and UPDATE as a space, and quoted text is only data.
_COMMENTS_AND_STRINGS = re.compile(r"/\*.*?\*/|--[^\n]*|'(?:[^']|'')*'", re.S)


def prepare_sql(sql: str) -> str:
    """Return the SQL ready to embed, or raise if it is not a single query.

    The query is placed after OPEN ... FOR inside a PL/SQL block. Anything after a
    semicolon would run as an extra PL/SQL statement, so semicolons are refused
    everywhere except one trailing semicolon, which is removed.
    """
    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    if not s:
        raise FusionToolError("sql is empty")
    if ";" in s:
        raise FusionToolError(
            "The SQL contains a semicolon. Send exactly one SELECT statement; if you need "
            "a literal semicolon in a string, use CHR(59)")
    if "]]>" in s:
        # BI Publisher rejects this sequence in a data model's SQL however it is escaped.
        raise FusionToolError("The SQL contains ']]>', which BI Publisher cannot accept; "
                              "write it as ']]' || '>' instead")
    if _FOR_UPDATE.search(_COMMENTS_AND_STRINGS.sub(" ", s)):
        # SELECT ... FOR UPDATE locks the rows it reads, so it is not a harmless query.
        raise FusionToolError("FOR UPDATE is not allowed: it locks the rows it reads")
    first = _LEADING.sub("", s)[:6].upper()
    if not (first.startswith("SELECT") or first.startswith("WITH")):
        raise FusionToolError("Only queries are allowed: the SQL must start with SELECT or WITH")
    return s


def build_data_model_xml(sql: str) -> str:
    """Build a BIP data model (.xdm) that returns the rows of one query.

    Output is <ROWSET><ROW><COLUMN_NAME>value</COLUMN_NAME>...</ROW></ROWSET>, with
    tags taken from the query's column names or aliases.
    """
    q = prepare_sql(sql)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<dataModel xmlns="http://xmlns.oracle.com/oxp/xmlp" version="2.0" '
        'defaultDataSourceRef="ApplicationDB_FSCM">'
        '<dataProperties><property name="include_parameters" value="false"/>'
        '<property name="include_null_Element" value="true"/>'
        '<property name="include_rowsettag" value="false"/>'
        '<property name="xml_tag_case" value="upper"/></dataProperties>'
        '<dataSets><dataSet name="Q" type="simple">'
        '<sql dataSourceRef="ApplicationDB_FSCM" nsQuery="true" sp="true" xmlRowTagName="ROW">'
        '<![CDATA[DECLARE type refcursor is REF CURSOR; xdo_cursor refcursor; '
        f'BEGIN OPEN :xdo_cursor FOR {q}\n; END;]]>'
        '</sql></dataSet></dataSets>'
        '<output rootName="DATA_DS" uniqueRowName="false"><nodeList name="Q"/></output>'
        '</dataModel>'
    )
