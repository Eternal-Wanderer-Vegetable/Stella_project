from capability.input_parser import merge_schemas, parse_input


def test_parse_input_extracts_declared_city_and_date():
    schema = {
        "properties": {
            "city": {"type": "string", "regex": r"查(?P<city>[\u4e00-\u9fff]{2,8})天气"},
            "date": {"type": "string", "regex": r"(?P<date>明天|今天|后天)"},
        },
        "required": ["city", "date"],
    }
    result = parse_input("帮我查东京天气，明天的", schema)
    assert result.complete
    assert result.values == {"city": "东京", "date": "明天"}


def test_parse_input_fails_closed_on_ambiguous_value():
    result = parse_input(
        "查东京和大阪天气",
        {
            "properties": {"city": {"regex": r"(?P<city>东京|大阪)"}},
            "required": ["city"],
        },
    )
    assert result.complete is False
    assert result.ambiguous == ("city",)


def test_merge_schemas_preserves_capability_parser_and_tool_required_fields():
    merged = merge_schemas(
        {"properties": {"city": {"regex": r"(?P<city>东京)"}}, "required": []},
        {"properties": {"date": {"type": "string"}}, "required": ["date"]},
    )
    assert set(merged["properties"]) == {"city", "date"}
    assert merged["required"] == ["date"]
