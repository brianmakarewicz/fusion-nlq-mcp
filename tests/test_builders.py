import pytest

from fusion_mcp.builders import build_data_model_xml, prepare_sql
from fusion_mcp.errors import FusionToolError


def test_one_trailing_semicolon_is_removed():
    assert prepare_sql("SELECT 1 FROM dual;") == "SELECT 1 FROM dual"


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM dual; DELETE FROM x",
    "SELECT 1 FROM dual;;",
    "SELECT ';' FROM dual",
])
def test_semicolons_inside_the_sql_are_refused(sql):
    with pytest.raises(FusionToolError, match="semicolon"):
        prepare_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM ap_invoices_all FOR UPDATE",
    "select * from x for  update nowait",
    "SELECT * FROM x\nFOR\nUPDATE OF y",
    "SELECT * FROM x FOR/**/UPDATE",
    "SELECT * FROM x FOR -- note\nUPDATE",
    "SELECT '--' AS a FROM x FOR UPDATE",
])
def test_for_update_is_refused(sql):
    with pytest.raises(FusionToolError, match="FOR UPDATE"):
        prepare_sql(sql)


def test_column_names_containing_for_update_are_allowed():
    assert prepare_sql("SELECT for_update_flag FROM x")


def test_for_update_inside_quoted_text_is_allowed():
    assert prepare_sql("SELECT 'for update' AS label FROM dual")


@pytest.mark.parametrize("sql", [
    "DELETE FROM x",
    "BEGIN NULL; END",
    "UPDATE x SET y = 1",
    "",
])
def test_only_queries_are_allowed(sql):
    with pytest.raises(FusionToolError):
        prepare_sql(sql)


@pytest.mark.parametrize("sql", [
    "WITH t AS (SELECT 1 a FROM dual) SELECT a FROM t",
    "-- comment\nSELECT 1 FROM dual",
    "/* comment */ SELECT 1 FROM dual",
    "SELECT * FROM (SELECT 1 a FROM dual) UNION ALL SELECT 2 FROM dual",
])
def test_ctes_subqueries_and_comments_are_allowed(sql):
    assert prepare_sql(sql)


def test_cdata_terminator_is_refused():
    with pytest.raises(FusionToolError, match=r"\]\]>"):
        prepare_sql("SELECT ']]>' FROM dual")


def test_data_model_wraps_the_query_in_a_ref_cursor():
    xdm = build_data_model_xml("SELECT 1 AS n FROM dual;")
    assert "OPEN :xdo_cursor FOR SELECT 1 AS n FROM dual\n; END;" in xdm
