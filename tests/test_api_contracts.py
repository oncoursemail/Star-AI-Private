"""Inert OpenAPI request compiler: no network, auth, writes, or remote $ref."""
import pytest
from jsonschema import ValidationError

from star.api_contracts import compile_read_contracts, validate_contract_arguments


OPENAPI = {
    "openapi": "3.2.1",
    "info": {"title": "Demo", "version": "1"},
    "paths": {
        "/users/{userId}": {
            "parameters": [
                {"name": "userId", "in": "path", "required": True,
                 "schema": {"type": "string", "minLength": 2, "maxLength": 60}},
            ],
            "get": {
                "operationId": "getUser",
                "parameters": [
                    {"name": "limit", "in": "query", "required": True,
                     "schema": {"type": "integer", "minimum": 1, "maximum": 100}},
                    {"name": "kind", "in": "query",
                     "schema": {"type": "string", "enum": ["all", "basic", "extended"]}},
                    {"name": "X-Do-Something", "in": "header", "required": True,
                     "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "updateUser",
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
            },
        }
    },
}


def one():
    result = compile_read_contracts(OPENAPI)
    assert result["executable"] is False
    assert result["scanned_operations"] == 1
    assert len(result["contracts"]) == 1
    contract = result["contracts"][0]
    assert contract["method"] == "GET"
    assert contract["status"] == "preview_only_no_execution"
    return contract


def test_compile_read_only_schema_preserves_path_and_query_types():
    contract = one()
    schema = contract["input_schema"]
    assert schema["properties"]["path"]["properties"]["userId"]["minLength"] == 2
    assert schema["properties"]["query"]["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["query"]["properties"]["kind"]["enum"] == [
        "all", "basic", "extended",
    ]
    assert "X-Do-Something" not in schema["properties"]["query"]["properties"]
    assert set(schema["required"]) == {"path", "query"}


def test_validator_accepts_only_typed_inputs():
    contract = one()
    arguments = {"path": {"userId": "alice"}, "query": {"limit": 10, "kind": "basic"}}
    assert validate_contract_arguments(contract, arguments) == arguments


@pytest.mark.parametrize("arguments", [
    {"query": {"limit": 3}},
    {"path": {"userId": "a"}, "query": {"limit": 3}},
    {"path": {"userId": "alice"}, "query": {"limit": "10"}},
    {"path": {"userId": "alice"}, "query": {"limit": -1}},
    {"path": {"userId": "alice"}, "query": {"limit": 200}},
    {"path": {"userId": "alice"}, "query": {"limit": 1, "kind": "surprise"}},
    {"path": {"userId": "alice"}, "query": {"limit": 2, "access_token": "secret"}},
    {"path": {"userId": "alice"}, "query": {"limit": 2}, "endpoint": "http://127.0.0.1"},
])
def test_validator_rejects_wrong_or_extra_model_parameters(arguments):
    with pytest.raises(ValidationError):
        validate_contract_arguments(one(), arguments)


def test_request_body_and_write_operation_never_become_read_contracts():
    spec = {
        "openapi": "3.1.0", "info": {"title": "Demo"},
        "paths": {
            "/mutate": {"post": {"operationId": "mutate"}},
            "/weird": {"get": {"requestBody": {"required": True}}},
        },
    }
    result = compile_read_contracts(spec)
    assert not result["contracts"]
    assert result["skipped"] == {"read operation declares a request body": 1}


def test_secret_bearing_required_query_field_is_refused():
    spec = {"paths": {"/data": {"get": {"parameters": [
        {"name": "api_key", "in": "query", "required": True,
         "schema": {"type": "string"}},
    ]}}}}
    result = compile_read_contracts(spec)
    assert not result["contracts"]
    assert any("credential-like" in item for item in result["skipped"])


def test_unresolved_external_schema_ref_is_not_followed():
    spec = {"paths": {"/data": {"get": {"parameters": [
        {"name": "data", "in": "query", "schema": {
            "$ref": "http://127.0.0.1/private-schema.json",
        }},
    ]}}}}
    result = compile_read_contracts(spec)
    assert not result["contracts"]
    assert any("referenced parameter" in item for item in result["skipped"])


def test_forged_contract_cannot_smuggle_remote_refs_into_validator():
    contract = one()
    contract["input_schema"] = {"$ref": "http://127.0.0.1/not-allowed"}
    with pytest.raises(ValueError, match="supported"):
        validate_contract_arguments(contract, {})


def test_path_parameters_must_match_template():
    spec = {"paths": {"/items/{id}": {"get": {"parameters": []}}}}
    assert not compile_read_contracts(spec)["contracts"]


def test_untrusted_complex_types_skip_instead_of_guessing():
    spec = {"paths": {"/items": {"get": {"parameters": [
        {"name": "filter", "in": "query", "schema": {"type": "object", "properties": {"x": {"type": "string"}}}},
    ]}}}}
    result = compile_read_contracts(spec)
    assert not result["contracts"]


def test_result_count_and_request_limit_are_bounded():
    spec = {"paths": {f"/items/{i}": {"get": {"operationId": f"get{i}"}} for i in range(100)}}
    result = compile_read_contracts(spec, max_contracts=3)
    assert len(result["contracts"]) == 3
    with pytest.raises(ValueError):
        compile_read_contracts(spec, max_contracts=10000)
